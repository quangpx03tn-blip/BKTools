import os
import json
import re
from modules import ai_client


# Lấy theo model đang cấu hình trong ai_client (biến SHOPAIKEY_MODEL),
# để đổi model một chỗ là toàn hệ thống đổi theo — tránh tình trạng
# key chỉ bán Claude nhưng handler vẫn gọi gemini-2.5-flash.
DEFAULT_MODEL = ai_client.SHOPAIKEY_MODEL
ASSIGN_MAX_OUTPUT_TOKENS = 8192

# Số scene mỗi lần gọi AI. Nhỏ để JSON không bao giờ bị cắt giữa chừng.
# Bản cũ gọi 1 lần cho TOÀN BỘ scene và bắt AI sinh lại cả glabs_prompts
# (có nhúng nguyên văn VO) => video dài là tràn 8192 token => JSON đứt =>
# rơi xuống fallback => gán theo vòng xoay = "random". Đây là lỗi gốc.
SCENES_PER_BATCH = 12


class AssetAssigner:
    """
    Gán CHARACTERS / BACKGROUNDS / camera từ kết quả Pre-scan vào từng scene VO.

    NGUYÊN TẮC (theo yêu cầu người dùng):
    - Mỗi scene chỉ 1 BACKGROUNDS phù hợp nhất với VO. Chỉ ghép 2 khi VO mô tả
      rõ hai nơi liên kết trong cùng một shot (và AI phải nêu lý do).
    - Nhân vật KHÔNG được tự động thêm cho "đa dạng". Chỉ gán người thực sự
      được VO nhắc tới hoặc đang hành động trong khoảnh khắc đó.
    - Phải đọc MÔ TẢ của CHARACTERS/BACKGROUNDS để khớp nghĩa với VO, không
      suy đoán từ số thứ tự ID.
    - Tuyệt đối không gán theo index scene hay vòng xoay mù.
    """

    # Camera hợp lệ (dùng để kiểm tra giá trị AI trả về)
    VALID_CAMERAS = {
        "close-up", "medium shot", "wide shot",
        "over-the-shoulder shot", "low angle shot",
    }

    def __init__(self, api_key=None):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        if not self.api_key:
            raise ValueError("Chưa cấu hình API Key!")

    @staticmethod
    def _clean_json_text(text):
        text = (text or "").strip()
        if "```" in text:
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        return text

    @staticmethod
    def _parse_assets(text, prefix):
        pattern = re.compile(rf"^\s*[-•*]?\s*{prefix}\s*(\d{{1,3}})\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)
        assets = []
        for line in (text or "").splitlines():
            match = pattern.match(line.strip())
            if match:
                num = int(match.group(1))
                assets.append({
                    "id": f"{prefix.upper()} {num:03d}",
                    "description": match.group(2).strip()
                })
        return assets

    # ------------------------------------------------------------------
    # Chấm điểm khớp VO <-> asset (chỉ dùng cho nhánh fallback)
    # ------------------------------------------------------------------

    @staticmethod
    def _tokens(text):
        """
        Tách token cho cả chữ Latin lẫn CJK.

        Tiếng Hàn/Nhật/Trung viết dính, tách theo từ sẽ ra cụm dài như
        "인공지능" và gần như không bao giờ khớp với mô tả asset. Vì vậy bổ sung
        n-gram 2-3 ký tự cho phần CJK để bắt được khớp một phần
        ("인공지능" ~ "인공", "공지", "지능"...).
        """
        text = (text or "").lower()
        tokens = set(re.findall(r"[\wÀ-ỹ]+", text))

        for chunk in re.findall(r"[가-힣ぁ-ゔァ-ヴー一-龥]{2,}", text):
            tokens.add(chunk)
            for size in (2, 3):
                for i in range(len(chunk) - size + 1):
                    tokens.add(chunk[i:i + size])
        return tokens

    # Từ khóa tăng điểm — bao phủ cả đề tài lịch sử lẫn hiện đại/công nghệ,
    # và cả 3 ngôn ngữ Việt / Anh / Hàn (bản cũ gần như chỉ có Việt-Anh nên
    # VO tiếng Hàn luôn ra điểm 0).
    _ROLE_BOOSTS = [
        ("king", ["king", "왕", "임금", "군주", "vua"]),
        ("queen", ["queen", "왕비", "여왕", "hoàng hậu"]),
        ("official", ["official", "minister", "quan", "triều đình", "대신", "관료", "장관"]),
        ("soldier", ["soldier", "warrior", "quân", "binh", "병사", "군인"]),
        ("worker", ["worker", "laborer", "công nhân", "lao động", "노동자", "일꾼", "직장인"]),
        ("mother", ["mother", "mẹ", "어머니", "엄마"]),
        ("child", ["child", "boy", "girl", "đứa trẻ", "아이", "어린", "학생"]),
        ("expert", ["expert", "researcher", "scientist", "engineer", "analyst",
                    "chuyên gia", "nhà nghiên cứu", "kỹ sư",
                    "전문가", "연구원", "과학자", "엔지니어", "개발자", "분석"]),
        ("executive", ["ceo", "executive", "founder", "leader", "giám đốc", "lãnh đạo",
                       "경영자", "대표", "리더", "기업가"]),
        ("citizen", ["citizen", "public", "people", "crowd", "người dân", "công chúng",
                     "시민", "국민", "대중", "사람들"]),
        ("politician", ["government", "president", "policy", "chính phủ", "tổng thống",
                        "정부", "대통령", "정책", "국가"]),
    ]
    _PLACE_BOOSTS = [
        ("palace", ["palace", "royal court", "triều đình", "궁궐", "왕궁"]),
        ("village", ["village", "làng", "마을"]),
        ("market", ["market", "chợ", "시장"]),
        ("prison", ["prison", "cell", "ngục", "감옥"]),
        ("battlefield", ["battlefield", "war", "chiến trường", "전쟁", "전장"]),
        ("room", ["room", "chamber", "phòng", "방", "실내"]),
        ("road", ["road", "street", "đường", "길", "거리"]),
        ("office", ["office", "desk", "meeting", "văn phòng", "cuộc họp",
                    "사무실", "회의", "책상", "기업"]),
        ("lab", ["lab", "laboratory", "server", "data center", "phòng thí nghiệm",
                 "연구소", "실험실", "서버", "데이터"]),
        ("city", ["city", "urban", "skyline", "thành phố", "đô thị", "도시", "빌딩"]),
        ("factory", ["factory", "plant", "industrial", "nhà máy", "công nghiệp",
                     "공장", "산업", "생산"]),
        ("home", ["home", "house", "living room", "nhà", "gia đình", "집", "가정", "거실"]),
    ]

    def _score_asset_for_vo(self, asset, vo_text):
        desc = (asset.get("description", "") or "").lower()
        vo = (vo_text or "").lower()

        asset_tokens = self._tokens(desc)
        vo_tokens = self._tokens(vo)
        # Token quá ngắn gây nhiễu; chỉ tính token >= 2 ký tự
        overlap = len([t for t in (asset_tokens & vo_tokens) if len(t) >= 2])

        boost = 0
        for _, words in self._ROLE_BOOSTS + self._PLACE_BOOSTS:
            if any(w in desc for w in words) and any(w in vo for w in words):
                boost += 3

        # Tín hiệu mạnh nhất: tên riêng (Google, 구글, LLM...) xuất hiện ở CẢ HAI.
        # Viết hoa Latin >= 2 ký tự, hoặc cụm CJK >= 2 ký tự.
        proper = set(re.findall(r"\b[A-Z][A-Za-z]{1,}\b", asset.get("description", "") or ""))
        for name in proper:
            if len(name) >= 2 and name.lower() in vo:
                boost += 5

        return overlap + boost

    # ------------------------------------------------------------------
    # Suy luận camera & chuyển cảnh cho nhánh fallback (KHÔNG theo index)
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_camera(vo_text):
        """
        Suy camera từ ĐẶC ĐIỂM NỘI DUNG của VO.
        Bản cũ dùng cameras[min(idx, 4)] — gán theo số thứ tự dòng, nên mọi
        video đều ra đúng một chuỗi medium→close-up→wide→OTS→low angle→low
        angle→... Đó chính là "random" mà người dùng nhìn thấy.
        """
        vo = (vo_text or "").strip()
        low = vo.lower()

        crowd = ["crowd", "people", "everyone", "society", "nation", "world", "public",
                 "đám đông", "mọi người", "xã hội", "quốc gia", "thế giới", "người dân",
                 "사람들", "대중", "사회", "국가", "세계", "시민", "국민", "전 세계"]
        place = ["city", "factory", "building", "landscape", "street", "office",
                 "thành phố", "nhà máy", "tòa nhà", "đường phố", "văn phòng",
                 "도시", "공장", "건물", "거리", "사무실", "풍경"]
        power = ["power", "dominate", "threat", "authority", "giant", "control",
                 "quyền lực", "thống trị", "đe dọa", "khổng lồ", "kiểm soát",
                 "권력", "지배", "위협", "거대", "통제", "강대국"]
        emotion = ["fear", "anxiety", "hope", "realize", "shock", "worry", "secret",
                   "lo lắng", "sợ hãi", "hy vọng", "nhận ra", "bí mật", "bất an",
                   "불안", "두려움", "희망", "깨닫", "충격", "비밀", "걱정"]

        if any(w in low for w in power):
            return "low angle shot"
        if any(w in low for w in crowd) or any(w in low for w in place):
            return "wide shot"
        if any(w in low for w in emotion):
            return "close-up"
        # Câu hỏi tu từ -> hướng vào nội tâm/đối thoại với khán giả
        if vo.endswith("?") or "?" in vo:
            return "close-up"
        if len(vo) <= 40:
            return "close-up"
        return "medium shot"

    @staticmethod
    def _has_location_shift(vo_text):
        """
        VO có mô tả rõ hai NƠI CHỐN liên kết trong cùng một shot hay không.
        Chỉ khi True mới được phép ghép 2 background.

        CHỈ nhận tín hiệu KHÔNG GIAN thật sự. Cố ý loại các liên từ chỉ thời
        gian/logic ("đồng thời", "동시에", "meanwhile", "at the same time",
        "giữa", "between") vì chúng hay xuất hiện trong câu tương phản ý niệm
        ("vừa tạo cơ hội, đồng thời đe dọa việc làm") chứ không hề đổi địa điểm
        — đây là nguồn ghép 2 bối cảnh sai.
        """
        low = (vo_text or "").lower()
        signals = [
            "from inside", "outside the", "beyond the", "across the",
            "through the window", "in the distance", "on the other side",
            "từ trong", "bên ngoài", "phía xa", "qua cửa sổ", "đằng xa", "phía bên kia",
            "밖으로", "안에서", "너머", "창밖", "멀리", "건너편",
        ]
        return any(s in low for s in signals)

    # ------------------------------------------------------------------
    # Fallback: KHÔNG random, kế thừa scene trước khi thiếu tín hiệu
    # ------------------------------------------------------------------

    def _fallback_scene(self, scene, characters, backgrounds, prev_character, prev_background):
        """Gán cho MỘT scene khi AI không trả lời được cho scene đó."""
        vo_text = scene.get("vo", "")

        scored_chars = sorted(
            ((self._score_asset_for_vo(a, vo_text), a["id"]) for a in characters),
            key=lambda item: item[0], reverse=True
        )
        scored_bgs = sorted(
            ((self._score_asset_for_vo(a, vo_text), a["id"]) for a in backgrounds),
            key=lambda item: item[0], reverse=True
        )

        # NHÂN VẬT: chỉ lấy 1 người khớp nhất. Không tự động ghép nhiều người.
        # Không có tín hiệu -> kế thừa scene trước để giữ liên tục mạch cảnh
        # (bản cũ xoay vòng char_cycle_idx = random).
        if scored_chars and scored_chars[0][0] > 0:
            character = scored_chars[0][1]
        elif prev_character:
            character = prev_character
        elif characters:
            character = characters[0]["id"]
        else:
            character = "CHARACTERS 001"

        # BỐI CẢNH: mặc định đúng 1. Chỉ ghép 2 khi VO nói rõ hai nơi liên kết.
        if scored_bgs and scored_bgs[0][0] > 0:
            background = scored_bgs[0][1]
            if self._has_location_shift(vo_text) and len(scored_bgs) > 1 and scored_bgs[1][0] > 0:
                background = f"{scored_bgs[0][1]}; {scored_bgs[1][1]}"
        elif prev_background:
            background = prev_background
        elif backgrounds:
            background = backgrounds[0]["id"]
        else:
            background = "BACKGROUNDS 001"

        return {
            "id": scene.get("id", ""),
            "character": character,
            "background": background,
            "camera": self._infer_camera(vo_text),
            "reason": "fallback: suy từ từ khóa VO và giữ liên tục với scene trước",
        }

    # ------------------------------------------------------------------
    # Prompt cho AI
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(batch, characters, backgrounds, scene_style, vo_lang, context_note):
        scenes_payload = [
            {"id": sc.get("id", ""), "vo": sc.get("vo", "")}
            for sc in batch
        ]

        return f"""
[SYSTEM ROLE]
You are a video production director assigning production assets to narration scenes.
You must understand what each Voice-Over actually says, then pick the assets that genuinely match its meaning.

[VOICE-OVER LANGUAGE]
{vo_lang}

[PROJECT VISUAL STYLE]
{scene_style}

[AVAILABLE CHARACTERS — THE ONLY CHARACTERS THAT EXIST]
{json.dumps(characters, ensure_ascii=False, indent=1)}

[AVAILABLE BACKGROUNDS — THE ONLY LOCATIONS THAT EXIST]
{json.dumps(backgrounds, ensure_ascii=False, indent=1)}

[CONTINUITY FROM PREVIOUS SCENES]
{context_note}

[HOW TO DECIDE — READ THE DESCRIPTIONS, NOT THE ID NUMBERS]
1. Read each Voice-Over and determine its concrete meaning: who is being talked about or acting, what is happening, and where it most plausibly takes place.
2. Then read the DESCRIPTION text of every CHARACTER and BACKGROUND above. Match by MEANING between the description and the voice-over. Never infer anything from the ID number itself. ID order is meaningless.
3. Never assign an asset because of the scene's position in the list. Position carries no information.

[BACKGROUND RULES — STRICT]
1. Assign EXACTLY ONE background id per scene. This is the default and applies to almost every scene.
2. Pick the single location whose description best fits what the voice-over describes.
3. ONLY assign two ids (separated by "; ") when the voice-over explicitly describes two linked places within one single shot — for example looking from inside out to another place, or one continuous shot spanning a transition. If you do this, your reason MUST state which two places the voice-over names.
4. Keep continuity: if consecutive scenes stay in the same implied place, keep the same background. Change it only when the voice-over genuinely moves to a different place or topic.
5. Do use the full range of available backgrounds across the video where the voice-over justifies it — but only ever because the meaning matches, never for variety alone.

[CHARACTER RULES — STRICT]
1. Assign only characters the voice-over ACTUALLY refers to or that are visibly acting in that moment.
2. NEVER add an extra character for variety, balance, or to fill the frame. An unjustified extra character is an error.
3. Most scenes should have exactly ONE character. Assign several (separated by "; ") only when the voice-over genuinely puts them in the same moment — dialogue, confrontation, comparison of two groups, a crowd reacting, a family scene.
4. If the voice-over is pure narration with no visible person, reuse the most contextually relevant character from the previous scenes instead of inventing presence.
5. Use only ids listed above. Never invent a new id, name, or description.

[CAMERA RULES]
Choose exactly one of: close-up, medium shot, wide shot, over-the-shoulder shot, low angle shot.
- close-up: inner emotion, realization, fear, secrecy, personal stakes
- medium shot: one person explaining or acting, dialogue
- wide shot: environment, crowds, cities, scale, systemic change
- over-the-shoulder shot: confrontation, observing something
- low angle shot: power, authority, threat, dominance
Never pick a camera based on the scene's position in the list.

[REASON FIELD]
For every scene give a short reason (max 20 words) naming the concrete words or idea in the voice-over that justify your choice. If you assigned two backgrounds, the reason must name both places.
Write the reason in {vo_lang} so the user can read it.

[GOOD EXAMPLE]
VO: "Google's AI experts are closely assessing each nation's AI readiness."
-> character: the AI expert character; background: the office/analysis location; camera: medium shot
   reason: "VO names Google AI experts assessing data, so expert in analysis workspace"

[BAD EXAMPLE — NEVER DO THIS]
-> character: "CHARACTERS 001; CHARACTERS 002; CHARACTERS 003" when the VO only mentions experts
   reason: "for variety"  (rejected: extra characters not mentioned in the VO)

[OUTPUT FORMAT — STRICT RAW JSON ONLY]
Return every scene exactly once, in the same id order. No markdown, no commentary.
{{
  "assigned_scenes": [
    {{"id": "001", "character": "CHARACTERS 002", "background": "BACKGROUNDS 001", "camera": "medium shot", "reason": "..."}},
    {{"id": "002", "character": "CHARACTERS 001; CHARACTERS 003", "background": "BACKGROUNDS 002", "camera": "wide shot", "reason": "..."}}
  ]
}}

[SCENES TO ASSIGN]
{json.dumps(scenes_payload, ensure_ascii=False, indent=1)}
"""

    # ------------------------------------------------------------------
    # Chuẩn hóa kết quả AI
    # ------------------------------------------------------------------

    def _normalize_batch(self, parsed_data, batch, allowed_chars, allowed_bgs,
                         characters, backgrounds, prev_character, prev_background):
        """
        Kiểm tra & làm sạch kết quả AI cho một lô.
        Scene nào AI trả sai/thiếu thì CHỈ scene đó dùng fallback.
        """
        assigned = parsed_data.get("assigned_scenes", []) if isinstance(parsed_data, dict) else []
        by_id = {str(item.get("id", "")).strip(): item for item in assigned if isinstance(item, dict)}

        results = []
        for idx, scene in enumerate(batch):
            s_id = str(scene.get("id", "")).strip()
            item = by_id.get(s_id)
            if item is None and idx < len(assigned) and isinstance(assigned[idx], dict):
                item = assigned[idx]
            item = item or {}

            raw_character = str(item.get("character") or "")
            raw_background = str(item.get("background") or "")
            camera = str(item.get("camera") or "").strip().lower()
            reason = str(item.get("reason") or "").strip()

            # Chỉ giữ ID có thật trong Pre-scan (chống AI bịa ID)
            char_ids = [m.group(0).upper() for m in re.finditer(r"CHARACTERS\s*\d{1,3}", raw_character, re.IGNORECASE)]
            bg_ids = [m.group(0).upper() for m in re.finditer(r"BACKGROUNDS\s*\d{1,3}", raw_background, re.IGNORECASE)]
            char_ids = [c for c in dict.fromkeys(char_ids) if not allowed_chars or c in allowed_chars]
            bg_ids = [b for b in dict.fromkeys(bg_ids) if not allowed_bgs or b in allowed_bgs]

            # AI trả rỗng/toàn ID bịa -> fallback riêng scene này
            if not char_ids or not bg_ids:
                results.append(self._fallback_scene(scene, characters, backgrounds,
                                                    prev_character, prev_background))
                prev_character = results[-1]["character"]
                prev_background = results[-1]["background"]
                continue

            # BỐI CẢNH: ép về 1. Chỉ cho 2 khi AI nêu được lý do VÀ VO thật sự
            # có tín hiệu hai nơi liên kết trong cùng một shot.
            if len(bg_ids) > 1:
                if reason and self._has_location_shift(scene.get("vo", "")):
                    bg_ids = bg_ids[:2]
                else:
                    bg_ids = bg_ids[:1]

            if camera not in self.VALID_CAMERAS:
                camera = self._infer_camera(scene.get("vo", ""))

            entry = {
                "id": s_id,
                "character": "; ".join(char_ids),
                "background": "; ".join(bg_ids),
                "camera": camera,
                "reason": reason,
            }
            results.append(entry)
            prev_character = entry["character"]
            prev_background = entry["background"]

        return results, prev_character, prev_background

    # ------------------------------------------------------------------
    # Đọc scene_style của dự án
    # ------------------------------------------------------------------

    def _load_scene_style(self, styles, project_name):
        scene_style = styles.get("scene_style", "2D cartoon illustration")

        try:
            clean_proj_name = os.path.basename(str(project_name)).strip()
            if clean_proj_name.endswith('.json'):
                clean_proj_name = clean_proj_name[:-5]

            target_json = os.path.join(".", "projects", f"{clean_proj_name}.json")

            if not os.path.exists(target_json):
                proj_dir = os.path.join(".", "projects")
                if os.path.exists(proj_dir):
                    for f_name in os.listdir(proj_dir):
                        if clean_proj_name.lower() in f_name.lower() and f_name.endswith('.json'):
                            target_json = os.path.join(proj_dir, f_name)
                            break

            if os.path.exists(target_json):
                with open(target_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                extracted_style = data.get("scene_style", data.get("scene_prompt", data.get("aesthetic", "")))
                if extracted_style and len(extracted_style.strip()) > 5:
                    scene_style = extracted_style.strip()
            else:
                print(f"=== [ASSIGN] Không tìm thấy file JSON cho dự án: {clean_proj_name} ===")
        except Exception as e:
            print(f"=== [ASSIGN] Lỗi khi đọc file JSON: {e} ===")

        return scene_style

    # ------------------------------------------------------------------
    # Điểm vào chính
    # ------------------------------------------------------------------

    def process_assignment(self, scenes_data: list, assets_text: str, styles: dict,
                           vo_lang: str = "Tiếng Việt", project_name: str = "Default_Project") -> dict:
        """
        Gán nhân vật/bối cảnh từ kết quả Pre-scan vào từng VO theo nghĩa cảnh.
        Không random, không bịa asset mới; chỉ dùng CHARACTERS/BACKGROUNDS đã có.
        """
        styles = styles or {}
        scenes_data = scenes_data or []
        scene_style = self._load_scene_style(styles, project_name)

        characters = self._parse_assets(assets_text, "CHARACTERS")
        backgrounds = self._parse_assets(assets_text, "BACKGROUNDS")

        allowed_chars = {a["id"] for a in characters}
        allowed_bgs = {a["id"] for a in backgrounds}

        # Nhãn giao diện ("Tiếng Hàn") -> tên chuẩn ("Korean") để chỉ thị ngôn
        # ngữ trong prompt có hiệu lực thật sự.
        lang_name = ai_client.resolve_lang(vo_lang)

        all_assigned = []
        prev_character = ""
        prev_background = ""

        for start in range(0, len(scenes_data), SCENES_PER_BATCH):
            batch = scenes_data[start:start + SCENES_PER_BATCH]
            batch_no = start // SCENES_PER_BATCH + 1

            if prev_character or prev_background:
                context_note = (
                    f"Previous scene used character(s): {prev_character or 'none'}; "
                    f"background: {prev_background or 'none'}. "
                    "Keep continuity unless the voice-over clearly moves elsewhere."
                )
            else:
                context_note = "This is the first batch; there is no previous scene."

            try:
                result_text = ai_client.generate_content(
                    api_key=self.api_key,
                    prompt=self._build_prompt(batch, characters, backgrounds,
                                              scene_style, lang_name, context_note),
                    system_prompt=(
                        "Return only valid JSON. Assign assets only from the provided Pre-scan ids, "
                        "matching the meaning of each voice-over against the asset descriptions. "
                        "Exactly one background per scene unless the voice-over names two linked places."
                    ),
                    json_mode=True,
                    temperature=0.2,
                    max_output_tokens=ASSIGN_MAX_OUTPUT_TOKENS,
                    timeout=300
                )
                parsed = json.loads(self._clean_json_text(result_text))
                batch_result, prev_character, prev_background = self._normalize_batch(
                    parsed, batch, allowed_chars, allowed_bgs,
                    characters, backgrounds, prev_character, prev_background
                )
            except Exception as e:
                print(f"[!] Assign lô {batch_no} lỗi, dùng fallback cho lô này: {e}")
                batch_result = []
                for scene in batch:
                    entry = self._fallback_scene(scene, characters, backgrounds,
                                                 prev_character, prev_background)
                    batch_result.append(entry)
                    prev_character = entry["character"]
                    prev_background = entry["background"]

            all_assigned.extend(batch_result)

        # Server tự dựng glabs_prompts (AI không cần sinh -> không tràn token)
        vo_by_id = {str(sc.get("id", "")).strip(): sc.get("vo", "") for sc in scenes_data}
        # Nhãn "context" để bằng tiếng Anh: đây là prompt KỸ THUẬT gửi cho AI
        # ảnh (không phải chữ người dùng đọc), và prompt ảnh luôn dùng tiếng Anh.
        prompt_lines = [
            f"[{item['id']}] {item['camera']}, {scene_style}, {item['character']}, "
            f"at {item['background']}, "
            f"context: \"{vo_by_id.get(item['id'], '')}\", "
            f"professional lighting --ar 16:9"
            for item in all_assigned
        ]

        return {
            "assigned_scenes": all_assigned,
            "glabs_prompts": "\n".join(prompt_lines),
        }
