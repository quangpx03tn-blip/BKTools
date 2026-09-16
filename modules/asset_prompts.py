import json
import os
import re
from . import ai_client


# Lấy theo model đang cấu hình trong ai_client (biến SHOPAIKEY_MODEL),
# để đổi model một chỗ là toàn hệ thống đổi theo — tránh tình trạng
# key chỉ bán Claude nhưng handler vẫn gọi gemini-2.5-flash.
DEFAULT_MODEL = ai_client.SHOPAIKEY_MODEL
ASSET_PROMPTS_MAX_OUTPUT_TOKENS = 8192

# Số asset mỗi lần gọi AI. Bản cũ gửi TẤT CẢ asset trong 1 lần gọi, nên danh
# sách dài là AI trả thiếu (hoặc output bị cắt) => sót asset.
ASSETS_PER_BATCH = 10

# Số lần gọi lại riêng cho các asset còn thiếu
MAX_RETRY_ROUNDS = 2


class AssetPromptsHandler:
    """
    Tool 3 — Asset Prompt Generator
    - Đọc prompt bên ngoài do người dùng dán: char_style / bg_style / scene_style.
    - Đọc danh sách CHARACTERS + BACKGROUNDS từ Tool 2 hoặc người dùng nhập tay.
    - Với mỗi nhân vật: tạo prompt reference sheet đồng nhất, đủ chi tiết để dùng G-Labs/Midjourney.
    - Với mỗi bối cảnh: tạo prompt môi trường trống (không người), chi tiết không gian/ánh sáng/mood.
    - Không tự điền style mặc định; chỉ dùng đúng prompt người dùng đưa.

    ĐẢM BẢO KHÔNG SÓT ASSET (điểm khác biệt so với bản cũ):
    Bản cũ gửi toàn bộ asset trong MỘT lần gọi và chỉ kiểm tra "có đủ 2 tiêu đề
    section hay không". AI trả về 5/15 nhân vật vẫn được coi là thành công =>
    người dùng mất prompt của 10 nhân vật mà không hề được báo.

    Bản này:
    1. Chia lô nhỏ (10 asset/lần) để AI không bị quá tải và output không bị cắt.
    2. Sau mỗi lô, ĐỐI CHIẾU TỪNG ID: asset nào chưa có prompt thì gọi lại
       riêng cho đúng những asset đó (tối đa 2 vòng).
    3. Asset nào vẫn thiếu sau khi thử lại thì dựng bằng fallback cục bộ —
       tuyệt đối không để trống dòng nào.
    4. Trả về thống kê (tổng/thiếu/đã bù) để lớp trên biết chuyện gì đã xảy ra.
    """

    _ID_RE = re.compile(r"(CHARACTERS?|BACKGROUNDS?)\s*(\d{1,3})", re.IGNORECASE)

    def __init__(self, api_key=None, default_model=DEFAULT_MODEL):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        if not self.api_key:
            raise ValueError("Chưa cấu hình API Key!")
        self.default_model = default_model

    # ------------------------------------------------------------------
    # Tiện ích
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_items(items):
        cleaned = []
        for raw in items or []:
            line = str(raw).strip()
            if not line:
                continue
            cleaned.append(line)
        return cleaned

    @classmethod
    def _norm_id(cls, raw, kind):
        """'characters 1' / 'CHARACTER 01' -> 'CHARACTERS 001'."""
        m = cls._ID_RE.match((raw or "").strip())
        if not m:
            return None
        return f"{kind} {int(m.group(2)):03d}"

    @classmethod
    def _extract_id(cls, line, kind):
        """Lấy ID từ một dòng prompt AI trả về, ví dụ '[CHARACTERS 003] ...'."""
        m = cls._ID_RE.search(line or "")
        if not m:
            return None
        prefix = m.group(1).upper()
        if not prefix.startswith(kind[:-1]):
            return None
        return f"{kind} {int(m.group(2)):03d}"

    @classmethod
    def _index_items(cls, items, kind):
        """
        Chuẩn hóa danh sách đầu vào thành [(id, mô tả gốc)].
        Asset không có ID rõ ràng vẫn được cấp ID tuần tự để không bị bỏ sót.
        """
        indexed = []
        used = set()
        auto = 1
        for raw in items:
            text = str(raw).strip()
            aid = cls._norm_id(text, kind)
            if aid is None or aid in used:
                while f"{kind} {auto:03d}" in used:
                    auto += 1
                aid = f"{kind} {auto:03d}"
            used.add(aid)
            indexed.append((aid, text))
        return indexed

    @classmethod
    def _parse_prompt_lines(cls, raw_text, kind, wanted_ids):
        """
        Bóc các dòng prompt AI trả về thành {id: dòng prompt}.
        Chỉ giữ ID thực sự nằm trong danh sách yêu cầu (chống AI bịa thêm).
        """
        found = {}
        for line in (raw_text or "").splitlines():
            line = line.strip()
            if not line or line.startswith("[CHARACTER PROMPTS]") or line.startswith("[BACKGROUND PROMPTS]"):
                continue
            aid = cls._extract_id(line, kind)
            if aid and aid in wanted_ids and aid not in found:
                # Chỉ nhận dòng có nội dung thật sự sau ID
                body = re.sub(r"^\[?\s*(?:CHARACTERS?|BACKGROUNDS?)\s*\d{1,3}\s*\]?\s*[:\-]?\s*", "", line)
                if len(body.split()) >= 5:
                    found[aid] = f"[{aid}] {body.strip()}"
        return found

    # ------------------------------------------------------------------
    # Fallback cho từng asset (không bao giờ để trống)
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_character(aid, desc, char_style, scene_style):
        return (
            f"[{aid}] {char_style}, {scene_style + ', ' if scene_style else ''}subject: {desc}, "
            f"production character reference sheet, consistent identity, full-body front view, side view, 3/4 view, "
            f"six expression close-ups, clear facial features, detailed costume, accurate props, "
            f"no text, no words, no letters, no watermark, no logo --ar 16:9"
        )

    @staticmethod
    def _fallback_background(aid, desc, bg_style, scene_style):
        return (
            f"[{aid}] {bg_style}, location: {desc}, {scene_style + ', ' if scene_style else ''}"
            f"empty environment reference sheet, detailed architecture, depth, atmosphere, cinematic lighting, "
            f"wide establishing view, no characters, no people, "
            f"no text, no words, no letters --ar 16:9"
        )

    def _fallback_for(self, kind, aid, desc, char_style, bg_style, scene_style):
        if kind == "CHARACTERS":
            return self._fallback_character(aid, desc, char_style, scene_style)
        return self._fallback_background(aid, desc, bg_style, scene_style)

    # ------------------------------------------------------------------
    # Prompt gửi cho AI
    # ------------------------------------------------------------------

    @staticmethod
    def _build_batch_prompt(kind, batch, style_text, scene_style):
        is_char = kind == "CHARACTERS"
        assets_json = json.dumps(
            [{"id": aid, "description": desc} for aid, desc in batch],
            ensure_ascii=False, indent=1
        )
        id_list = ", ".join(aid for aid, _ in batch)

        if is_char:
            role_block = """
[WHAT TO PRODUCE FOR EACH CHARACTER]
A single-line English image prompt for a production character reference sheet:
- consistent identity across angles: face, hair, outfit, accessories, proportions, colour identity
- full-body front view, side view, 3/4 view, plus expression close-ups
- age, role, social status, costume era and material, distinguishing props
- neutral background so the character reads clearly
"""
            style_label = "CHARACTER STYLE"
        else:
            role_block = """
[WHAT TO PRODUCE FOR EACH BACKGROUND]
A single-line English image prompt for an empty environment reference sheet:
- absolutely no people, no characters, no silhouettes
- architecture, materials, depth layers, foreground/background props
- light source, time of day, weather, era and mood
- wide establishing view of the space
"""
            style_label = "BACKGROUND STYLE"

        return f"""
[SYSTEM ROLE]
You are a professional AI prompt engineer for G-Labs / Midjourney production asset reference sheets.

[CRITICAL — COMPLETENESS IS THE MOST IMPORTANT RULE]
You are given exactly {len(batch)} assets. You MUST output exactly {len(batch)} prompt lines — one for every single id, with no omissions, no merging, and no summarising.
Required ids, all of which must appear exactly once:
{id_list}
Before you finish, count your output lines and confirm the count is {len(batch)}. If any id is missing, add it.

[USER-PROVIDED MASTER STYLE — USE THIS EXACT AESTHETIC]
{style_label}:
{style_text}

SCENE STYLE / OVERALL VISUAL DNA:
{scene_style if scene_style else "(no extra scene style provided)"}

[CRITICAL STYLE RULE]
Use ONLY the master style text above. Do not add another default style, do not replace it, do not change its aesthetic.
{role_block}
[HOW TO BUILD EACH PROMPT]
1. Read the asset description carefully and understand what it actually depicts.
2. Enrich vague descriptions with sensible, consistent detail so the image is immediately recognisable.
3. Apply the SCENE STYLE as shared visual DNA when provided, but never let it override the master style above.
4. Write every prompt in English, optimised for image generation models.
5. End every prompt with: no text, no words, no letters, no watermark, no logo --ar 16:9

[OUTPUT RULES — STRICT]
- Raw text only. No markdown fences, no commentary, no blank lines between prompts.
- Exactly one line per asset, in the same order as given.
- Each line starts with the id in square brackets, then the prompt.

[OUTPUT FORMAT]
[{batch[0][0]}] <single-line English image prompt>

[ASSETS TO PROCESS — ALL {len(batch)} MUST APPEAR IN YOUR OUTPUT]
{assets_json}
"""

    # ------------------------------------------------------------------
    # Sinh prompt cho một nhóm (CHARACTERS hoặc BACKGROUNDS)
    # ------------------------------------------------------------------

    def _generate_group(self, kind, indexed, style_text, scene_style):
        """
        Trả về ({id: dòng prompt}, danh sách id phải dùng fallback).
        Chia lô + đối chiếu từng ID + gọi lại riêng phần còn thiếu.
        """
        results = {}
        if not indexed:
            return results, []

        def call_ai(batch):
            raw = ai_client.generate_content(
                api_key=self.api_key,
                prompt=self._build_batch_prompt(kind, batch, style_text, scene_style),
                system_prompt=(
                    "Generate raw production image prompts only. You must return exactly one "
                    "line for every asset id given — never omit any asset."
                ),
                shop_model=self.default_model,
                gemini_model=self.default_model,
                temperature=0.45,
                max_output_tokens=ASSET_PROMPTS_MAX_OUTPUT_TOKENS,
                timeout=300,
            )
            raw = (raw or "").strip()
            if "```" in raw:
                raw = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("```")).strip()
            return raw

        # Vòng 1: chia lô
        for start in range(0, len(indexed), ASSETS_PER_BATCH):
            batch = indexed[start:start + ASSETS_PER_BATCH]
            batch_no = start // ASSETS_PER_BATCH + 1
            wanted = {aid for aid, _ in batch}
            try:
                found = self._parse_prompt_lines(call_ai(batch), kind, wanted)
                results.update(found)
                if len(found) < len(batch):
                    print(f"[!] {kind} lô {batch_no}: AI trả {len(found)}/{len(batch)}, sẽ gọi lại phần thiếu")
            except Exception as e:
                print(f"[!] {kind} lô {batch_no} lỗi: {e}")

        # Vòng 2-3: gọi lại RIÊNG cho những asset còn thiếu
        for attempt in range(MAX_RETRY_ROUNDS):
            missing = [(aid, desc) for aid, desc in indexed if aid not in results]
            if not missing:
                break
            print(f"[i] {kind}: thử lại lần {attempt + 1} cho {len(missing)} asset còn thiếu")
            for start in range(0, len(missing), ASSETS_PER_BATCH):
                batch = missing[start:start + ASSETS_PER_BATCH]
                wanted = {aid for aid, _ in batch}
                try:
                    results.update(self._parse_prompt_lines(call_ai(batch), kind, wanted))
                except Exception as e:
                    print(f"[!] {kind} retry lỗi: {e}")

        still_missing = [aid for aid, _ in indexed if aid not in results]
        return results, still_missing

    # ------------------------------------------------------------------
    # Điểm vào chính
    # ------------------------------------------------------------------

    def generate_asset_prompts(self, char_style: str, bg_style: str, scene_style: str,
                               characters: list, backgrounds: list) -> dict:
        scene_style = (scene_style or "").strip()
        characters = self._clean_items(characters)
        backgrounds = self._clean_items(backgrounds)

        if not characters and not backgrounds:
            raise ValueError("Chưa có Characters hoặc Backgrounds để tạo prompt.")

        char_style = (char_style or "").strip()
        bg_style = (bg_style or "").strip()

        if characters and not char_style:
            raise ValueError("Vui lòng nhập hoặc dán Character Style trước khi Generate All Prompts.")
        if backgrounds and not bg_style:
            raise ValueError("Vui lòng nhập hoặc dán Background Style trước khi Generate All Prompts.")

        char_indexed = self._index_items(characters, "CHARACTERS")
        bg_indexed = self._index_items(backgrounds, "BACKGROUNDS")

        char_map, char_missing = self._generate_group("CHARACTERS", char_indexed, char_style, scene_style)
        bg_map, bg_missing = self._generate_group("BACKGROUNDS", bg_indexed, bg_style, scene_style)

        # Bù fallback cho asset vẫn thiếu — KHÔNG BAO GIỜ để trống dòng nào
        for aid, desc in char_indexed:
            if aid not in char_map:
                char_map[aid] = self._fallback_character(aid, desc, char_style, scene_style)
        for aid, desc in bg_indexed:
            if aid not in bg_map:
                bg_map[aid] = self._fallback_background(aid, desc, bg_style, scene_style)

        # Dựng output theo ĐÚNG thứ tự đầu vào
        lines = ["[CHARACTER PROMPTS]"]
        lines += [char_map[aid] for aid, _ in char_indexed]
        lines += ["", "[BACKGROUND PROMPTS]"]
        lines += [bg_map[aid] for aid, _ in bg_indexed]

        total = len(char_indexed) + len(bg_indexed)
        fallback_count = len(char_missing) + len(bg_missing)
        if fallback_count:
            print(f"[!] Tool 3: {fallback_count}/{total} asset phải dùng fallback")

        return {
            "status": "success",
            "full_text": "\n".join(lines).strip(),
            "stats": {
                "total": total,
                "characters": len(char_indexed),
                "backgrounds": len(bg_indexed),
                "from_ai": total - fallback_count,
                "from_fallback": fallback_count,
                "fallback_ids": char_missing + bg_missing,
            },
        }
