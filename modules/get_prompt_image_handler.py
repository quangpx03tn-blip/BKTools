import os
import json
import re

from . import ai_client


class GetPromptImageHandler:
    """
    Module cho tab "GET-PROMPT IMAGE":
    - Đầu vào: scene_style (ô Scene Style) + scenes_data (scene đã có VO, nhân
      vật, bối cảnh, camera từ Scene List) + assets_text (kết quả Pre-scan, chứa
      mô tả của từng CHARACTERS/BACKGROUNDS ID).
    - Đầu ra: mỗi scene 1 dòng prompt ảnh hoàn chỉnh, TÊN NHÂN VẬT / BỐI CẢNH /
      CAMERA giữ NGUYÊN VĂN y hệt Scene List (code tự ghép, không qua AI).

    ĐỂ PROMPT BÁM SÁT VOICE-OVER (khác biệt so với bản cũ):
    1. Có bước phân tích CHỦ ĐỀ toàn bộ VO trước: rút ra subject / era / motif
       vocabulary (vật thể đặc trưng của chủ đề). Mọi scene đều phải cắm ít nhất
       1 motif => không còn mô tả chung chung dùng được cho mọi video.
    2. AI được cấp MÔ TẢ THẬT của nhân vật & bối cảnh (dịch sang tiếng Anh ở
       bước phân tích chủ đề), không chỉ ID trần "CHARACTERS 001" — nhờ vậy hành
       động/tư thế nó viết ra khớp đúng con người và đúng địa điểm của scene.
    3. AI bị buộc mô tả SỰ VIỆC CỤ THỂ mà VO đang nói (chủ thể, hành động, ánh
       mắt, vật thể chủ đề, chiều sâu), kèm ví dụ tốt/xấu ngay trong prompt.
    4. Gọi AI theo LÔ (batch) nhỏ. Bản cũ gọi 1 lần cho toàn bộ scene và bị cắt
       ở 8192 token khi video dài => JSON lỗi => TẤT CẢ scene rơi về mô tả
       fallback cố định. Đây là nguyên nhân chính khiến prompt mất chủ đề.

    ĐẢM BẢO "TUYỆT ĐỐI KHÔNG CÓ CHỮ TRONG ẢNH" — 3 lớp bảo vệ:
    1. Prompt hệ thống cấm AI mô tả bất kỳ chữ/ký tự đọc được nào.
    2. Bộ lọc regex thay thế theo từng cụm (giữ đúng ngữ pháp câu).
    3. Luôn chèn cứng NO_TEXT_GUARD + tham số --no vào cuối MỌI prompt.
    Toàn bộ chữ tiếng Việt của asset được dịch sang tiếng Anh trước khi vào
    prompt, kể cả ở nhánh fallback — không nhúng văn bản tiếng Việt vào prompt.
    """

    # Cụm từ chèn cứng ở CUỐI MỌI prompt để đảm bảo ảnh không chứa chữ
    NO_TEXT_GUARD = "no text, no words, no letters, no captions, no subtitles, no signage, no watermark, no logo"
    NO_TEXT_PARAM = "--no text, words, letters, caption, subtitle, signage, watermark, logo"

    # Số scene mỗi lần gọi AI. Nhỏ để JSON không bao giờ bị cắt giữa dòng.
    SCENES_PER_BATCH = 12
    MAX_OUTPUT_TOKENS = 8192

    # Lớp bảo vệ 2: thay thế theo từng cụm để câu vẫn đúng ngữ pháp.
    # Lưu ý thứ tự & lookbehind (?<!non-): tránh "readable" -> "non-legible"
    # rồi "legible" khớp lại lần nữa thành "non-non-legible".
    # Các mẫu "saying/reading X" phải nuốt luôn phần nội dung phía sau.
    # Phần đuôi theo sau "saying/reading": hoặc chuỗi trong ngoặc kép, hoặc tối
    # đa 4 token VIẾT HOA, hoặc dừng ngay. Có biên rõ ràng để KHÔNG nuốt phần
    # còn lại của câu (lỗi cũ: "banner reading "X" behind him" mất luôn "behind
    # him").
    # Lõi: chuỗi trong ngoặc kép, hoặc tối đa 4 token VIẾT HOA / SỐ ("1984").
    _TEXT_BODY = (
        r'(?:'
        r'["“”‘’][^"“”‘’]*["“”‘’]'
        r'|(?:[A-Z0-9][A-Z0-9\-]{1,}[ ]*){1,4}'
        r')'
    )
    # Dùng sau một danh từ đã rõ là chữ (sign/text/label...): phần nội dung có
    # thể có hoặc không, vì bản thân danh từ đã đủ nguy hiểm.
    _TEXT_SUFFIX_OPT = r'(?:\s*' + _TEXT_BODY + r')?'
    # Dùng cho luật quét vét không có danh từ đứng trước: BẮT BUỘC phải có nội
    # dung chữ thì mới thay, nếu không "a man reading a book" sẽ bị phá.
    _TEXT_SUFFIX_REQ = r'\s*' + _TEXT_BODY

    # Lớp bảo vệ 2: thay thế theo từng cụm để câu vẫn đúng ngữ pháp.
    _RISKY_REPLACEMENTS = [
        # 1) Trước hết nuốt các mẫu "<danh từ> saying/reading <NỘI DUNG>" — phải
        #    chạy TRƯỚC các luật thay danh từ, nếu không "written text" bị đổi
        #    trước và phần "saying HELLO WORLD" sẽ sót lại nguyên nội dung chữ.
        (re.compile(r"\b(?:written|engraved|printed|carved)?\s*texts?\s+(?:saying|reading|that reads?|which reads?)" + _TEXT_SUFFIX_OPT, re.IGNORECASE), "blank surface"),
        (re.compile(r"\b(?:sign|signage|billboard|banner|placard|poster)s?\s+(?:saying|reading|that reads?|which reads?)" + _TEXT_SUFFIX_OPT, re.IGNORECASE), "blank panel"),
        (re.compile(r"\bwords?\s+(?:saying|reading|that reads?|which reads?)" + _TEXT_SUFFIX_OPT, re.IGNORECASE), "blank marking"),
        (re.compile(r"\bletters?\s+(?:saying|reading|that reads?|which reads?)" + _TEXT_SUFFIX_OPT, re.IGNORECASE), "blank marking"),
        (re.compile(r"\b(?:labels?|captions?|headlines?|titles?|inscriptions?)\s+(?:saying|reading|that reads?|which reads?)" + _TEXT_SUFFIX_OPT, re.IGNORECASE), "blank marking"),
        # 2) Quét vét nội dung chữ còn sót sau "saying/reading" khi không có danh
        #    từ đứng trước. BẮT BUỘC có nội dung chữ (ngoặc kép hoặc token VIẾT
        #    HOA/SỐ) mới thay, nên "a man reading a book" không bị phá.
        (re.compile(r"\b(?:saying|reading|that reads?|which reads?)" + _TEXT_SUFFIX_REQ), "blank surface"),
        # 3) Sau đó mới thay các danh từ/tính từ nguy hiểm.
        (re.compile(r"\bwritten text\b", re.IGNORECASE), "abstract etched pattern"),
        (re.compile(r"\bengraved text\b", re.IGNORECASE), "engraved abstract pattern"),
        # (?<!non-) chặn "readable"->"non-legible" rồi "legible" khớp lại lần nữa
        # tạo ra "non-non-legible".
        (re.compile(r"(?<!non-)\b(?:readable|legible)\b", re.IGNORECASE), "non-legible"),
        (re.compile(r"\binscriptions?\b", re.IGNORECASE), "worn carved pattern"),
        (re.compile(r"\binscribed\b", re.IGNORECASE), "faintly patterned"),
        (re.compile(r"\btitle cards?\b", re.IGNORECASE), "opening tableau"),
        (re.compile(r"\bsubtitles?\b", re.IGNORECASE), "text-free frame"),
        (re.compile(r"\bcaptions?\b", re.IGNORECASE), "text-free frame"),
    ]

    # Dòng "- CHARACTERS 001: Tên (mô tả)" trong kết quả Pre-scan
    _ASSET_LINE = re.compile(
        r"^\s*[-•*]?\s*((?:CHARACTERS?|BACKGROUNDS?)\s*\d{1,3})\s*[:：]\s*(.+?)\s*$",
        re.IGNORECASE,
    )

    _ASSET_ID = re.compile(r"(?:CHARACTERS?|BACKGROUNDS?)\s*\d{1,3}", re.IGNORECASE)

    # Cụm sáo rỗng: nếu AI trả về mô tả chỉ gồm những cụm này thì coi là hỏng
    _GENERIC_MARKERS = (
        "cinematic tableau",
        "narrative moment",
        "atmospheric depth",
        "captures the moment",
        "visually striking scene",
    )

    def __init__(self, api_key=None, default_model=None):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        if not self.api_key:
            raise ValueError("Chưa cấu hình API Key!")
        # Theo model đang cấu hình trong ai_client, để đổi một chỗ là toàn
        # hệ thống đổi theo (key chỉ bán Claude thì không gọi nhầm Gemini).
        # Tác vụ ngắn, có khuôn mẫu (mô tả 30-60 từ) -> dùng model NHANH.
        # Nếu key không bán model này, ai_client tự chuyển sang model dự
        # phòng nên không bao giờ lỗi model_not_found.
        self.default_model = default_model or ai_client.MODEL_FAST

    # ------------------------------------------------------------------
    # Tiện ích
    # ------------------------------------------------------------------

    @staticmethod
    def _norm_id(raw: str) -> str:
        """Chuẩn hóa 'characters  1' / 'CHARACTER 01' -> 'CHARACTERS 001'."""
        m = re.match(r"\s*(CHARACTERS?|BACKGROUNDS?)\s*(\d{1,3})", raw or "", re.IGNORECASE)
        if not m:
            return (raw or "").strip().upper()
        kind = "CHARACTERS" if m.group(1).upper().startswith("CHARACTER") else "BACKGROUNDS"
        return f"{kind} {int(m.group(2)):03d}"

    @classmethod
    def _parse_asset_descriptions(cls, assets_text: str) -> dict:
        """Giải kết quả Pre-scan thành {"CHARACTERS 001": "Vị quan bảo thủ (...)"}."""
        asset_map = {}
        for line in (assets_text or "").splitlines():
            m = cls._ASSET_LINE.match(line)
            if m:
                asset_map[cls._norm_id(m.group(1))] = m.group(2).strip()
        return asset_map

    @classmethod
    def _ids_used_in_scenes(cls, scenes_data: list) -> list:
        """Các ID thực sự xuất hiện trong Scene List, giữ nguyên thứ tự."""
        used = []
        for sc in scenes_data:
            for field in ("character", "background"):
                for m in cls._ASSET_ID.finditer(sc.get(field) or ""):
                    aid = cls._norm_id(m.group(0))
                    if aid not in used:
                        used.append(aid)
        return used

    @classmethod
    def _describe_ids(cls, raw_field: str, visuals: dict, asset_map: dict) -> str:
        """
        "CHARACTERS 001; CHARACTERS 003" -> "CHARACTERS 001 = <mô tả tiếng Anh>;
        CHARACTERS 003 = <mô tả>" để nhét vào prompt AI làm ngữ cảnh thật.
        Ưu tiên bản dịch tiếng Anh (visuals); chỉ dùng bản gốc nếu chưa dịch được.
        """
        raw_field = (raw_field or "").strip()
        if not raw_field:
            return ""
        ids = [cls._norm_id(m.group(0)) for m in cls._ASSET_ID.finditer(raw_field)]
        if not ids:
            return raw_field
        parts = []
        for aid in dict.fromkeys(ids):
            desc = visuals.get(aid) or asset_map.get(aid)
            parts.append(f"{aid} = {desc}" if desc else aid)
        return "; ".join(parts)

    @classmethod
    def _plain_descriptions(cls, raw_field: str, visuals: dict) -> str:
        """
        Như _describe_ids nhưng CHỈ trả phần mô tả, không kèm "ID =".
        Dùng cho nhánh fallback: prompt cuối đã có sẵn ID do code ghép riêng,
        nên ở đây chỉ cần mô tả thuần để câu đọc trôi chảy.
        """
        raw_field = (raw_field or "").strip()
        if not raw_field or not visuals:
            return ""
        ids = [cls._norm_id(m.group(0)) for m in cls._ASSET_ID.finditer(raw_field)]
        descs = [visuals[aid] for aid in dict.fromkeys(ids) if visuals.get(aid)]
        return "; ".join(descs)

    def _sanitize_description(self, text: str) -> str:
        """Lớp bảo vệ 2: khử cụm từ có nguy cơ khiến ảnh sinh ra bị dính chữ."""
        if not text:
            return ""
        out = str(text)
        for pattern, replacement in self._RISKY_REPLACEMENTS:
            out = pattern.sub(replacement, out)
        # AI đôi khi vẫn nhắc lại ID dù bị cấm -> bỏ đi vì code đã ghép riêng
        out = self._ASSET_ID.sub("", out)
        out = re.sub(r"\s{2,}", " ", out)
        out = re.sub(r"\s+([,.;])", r"\1", out)
        out = re.sub(r"(,\s*){2,}", ", ", out)
        return out.strip(" ,;.")

    @classmethod
    def _is_generic(cls, text: str) -> bool:
        """Mô tả quá ngắn hoặc toàn cụm sáo rỗng => coi như AI trả lời hỏng."""
        t = (text or "").strip().lower()
        if len(t.split()) < 8:
            return True
        return any(marker in t for marker in cls._GENERIC_MARKERS)

    # ------------------------------------------------------------------
    # Bước 1: hiểu CHỦ ĐỀ toàn bộ kịch bản
    # ------------------------------------------------------------------

    def _analyze_topic(self, scenes_data: list, asset_map: dict) -> dict:
        """
        Đọc toàn bộ VO một lần để rút ra chủ đề + bộ motif hình ảnh đặc trưng.
        Đây là thứ giữ cho mọi scene bám đúng chủ đề (AI, lịch sử, kinh tế...)
        thay vì trôi thành mô tả chung chung.

        Đồng thời dịch mô tả nhân vật/bối cảnh sang tiếng Anh (asset_visuals) để
        prompt cuối không chứa văn bản tiếng Việt — vốn là nguồn gây dính chữ.
        """
        joined = " ".join((sc.get("vo") or "").strip() for sc in scenes_data)
        sample = joined[:6000]

        used_ids = self._ids_used_in_scenes(scenes_data)
        asset_lines = "\n".join(
            f"- {aid}: {asset_map.get(aid, '(no description available)')}" for aid in used_ids
        ) or "(none)"

        prompt = f"""
[ROLE]
You are a visual development director analyzing a narration script before storyboarding.

[FULL NARRATION — ALL SCENES COMBINED]
{sample}

[CAST AND LOCATIONS APPEARING IN THIS SCRIPT]
{asset_lines}

[TASK]
Identify what this video is actually about, build the visual vocabulary the whole storyboard must stay inside, and translate the cast/location notes into English visual descriptors.

[RULES]
1. subject: one concrete English sentence naming the real topic of this script (e.g. "the disruption of human labor and daily life by artificial intelligence", not "a story about change").
2. era_setting: the concrete time period and world implied (e.g. "near-future present day, worn urban infrastructure retrofitted with AI hardware").
3. motifs: 8-14 CONCRETE, DRAWABLE objects, technologies, environments or visual symbols that belong to THIS topic specifically. Nouns with optional qualifier, no adjective-only entries, no readable text objects.
   - For an AI topic: glowing processor modules, server racks, camera lenses, robotic arms, cable bundles, holographic interface glow, automated kiosks, drones...
   - For a historical topic: period architecture, period clothing, ceremonial props, era-specific tools...
   - Never output generic filler like "light", "mood", "atmosphere", "emotion".
4. mood: 3-6 words describing the emotional tone.
5. asset_visuals: for EVERY id listed in CAST AND LOCATIONS above, give one concise ENGLISH visual descriptor (max 20 words) built from its description — age, role, clothing, expression, props for characters; architecture, era, lighting, weather, props for locations. Keep the identity recognisable. This text goes into an English image prompt, so write it in English only.
6. Output STRICTLY raw JSON, no markdown.

[OUTPUT SHAPE]
{{"subject": "...", "era_setting": "...", "motifs": ["...", "..."], "mood": "...",
 "asset_visuals": {{"CHARACTERS 001": "elderly woman, silver bun, cream knit cardigan, anxious gaze", "BACKGROUNDS 001": "old transit platform at dusk, metal canopy, misty crowd"}}}}
"""

        try:
            raw = ai_client.generate_content(
                api_key=self.api_key,
                prompt=prompt,
                system_prompt="Return only valid JSON describing the script's concrete visual topic and English asset descriptors.",
                gemini_model=self.default_model,
                shop_model=self.default_model,
                json_mode=True,
                temperature=0.3,
                max_output_tokens=3000,
                timeout=180,
            )
            data = json.loads(ai_client.clean_json_text(raw))
            motifs = [str(m).strip() for m in (data.get("motifs") or []) if str(m).strip()]

            visuals = {}
            for key, value in (data.get("asset_visuals") or {}).items():
                text = self._sanitize_description(value)
                if text:
                    visuals[self._norm_id(key)] = text

            return {
                "subject": str(data.get("subject") or "").strip(),
                "era_setting": str(data.get("era_setting") or "").strip(),
                "motifs": motifs,
                "mood": str(data.get("mood") or "").strip(),
                "asset_visuals": visuals,
            }
        except Exception as e:
            # Sai key / hết credit -> báo ngay, đừng để prompt rơi về mô tả
            # chung chung mà người dùng tưởng là AI viết.
            if ai_client.is_fatal_error(e):
                raise RuntimeError(f"Không gọi được AI: {e}")
            print(f"[!] Không phân tích được chủ đề kịch bản: {e}")
            return {"subject": "", "era_setting": "", "motifs": [], "mood": "", "asset_visuals": {}}

    # ------------------------------------------------------------------
    # Bước 2: sinh mô tả hình ảnh cho từng scene (theo lô)
    # ------------------------------------------------------------------

    def _batch_prompt(self, batch: list, scene_style: str, topic: dict,
                      visuals: dict, asset_map: dict) -> str:
        simplified = []
        for sc in batch:
            simplified.append({
                "id": sc.get("id", ""),
                "voice_over": sc.get("vo", ""),
                "character_in_shot": self._describe_ids(sc.get("character", ""), visuals, asset_map),
                "location_of_shot": self._describe_ids(sc.get("background", ""), visuals, asset_map),
                "camera": sc.get("camera", ""),
            })

        motif_line = ", ".join(topic.get("motifs") or []) or "(not detected — infer from the voice-over itself)"

        return f"""
[SYSTEM ROLE]
You are a storyboard artist writing image-generation descriptions. Each description must let a viewer recognise THE EXACT CONTENT OF THE VOICE-OVER just by looking at the picture.

[SCRIPT SUBJECT — EVERY SCENE MUST STAY INSIDE THIS WORLD]
Subject: {topic.get('subject') or '(infer from the voice-over)'}
Era / setting: {topic.get('era_setting') or '(infer from the voice-over)'}
Overall mood: {topic.get('mood') or '(infer from the voice-over)'}

[TOPIC MOTIF VOCABULARY — DRAW FROM THIS]
{motif_line}

[LOCKED SCENE STYLE — THE VISUAL DNA]
{scene_style}

[YOUR TASK]
For every scene below, write ONE English visual description of what the frame literally shows.

[HOW TO WRITE IT — FOLLOW IN ORDER]
1. READ THE VOICE-OVER FIRST. Decide the single most important literal fact, event or claim it states. The picture must depict THAT, not a vague mood around it.
2. VISUALISE THE ABSTRACT. The narration is often conceptual ("we stand in the middle of the most radical technological transformation in human history"). Never answer with abstract words. Convert the idea into a concrete staged situation: who is present, what they are doing with their body, what topic-specific objects surround them, what contrast carries the meaning (old vs new, human vs machine, crowd vs individual, calm vs pressure).
3. USE THE CHARACTER AND LOCATION DESCRIPTIONS GIVEN for each scene. They tell you who is really in the shot and where it really happens. Stage the action so it fits that person and that place. Do NOT repeat their ID codes — the system inserts those separately.
4. ANCHOR THE TOPIC. Every description must contain at least one concrete object or environment detail from the MOTIF VOCABULARY (or an equally specific object clearly belonging to the subject). A description that would fit any video on any topic is a FAILURE.
5. RESPECT THE CAMERA value for framing: close-up = face and hands fill the frame; medium shot = upper body plus immediate surroundings; wide shot = full environment and scale; over-the-shoulder = foreground silhouette framing a subject; low angle = looming dominance.
6. MATCH THE SCENE STYLE for medium, palette, lighting, texture and rendering.
7. Include in each description: the subject's posture and gaze, the specific action or gesture, the topic objects around them, the lighting, and the foreground/background depth.

[STRICT RULES]
1. NEVER write any ID such as "CHARACTERS 001" or "BACKGROUNDS 002".
2. NO TEXT IN IMAGE: even if the voice-over mentions books, screens, signs, documents, tablets, labels or newspapers, never describe readable, legible or written text. Show them as blank, glowing, or abstractly patterned surfaces.
3. No captions, subtitles, typography, lettering, logos, watermarks or UI text.
4. Write in ENGLISH only. 30 to 60 words per scene, one flowing line, no line breaks, no bullet points.
5. Each scene's description must differ from the others — vary the staging, the objects and the composition scene to scene.
6. Output STRICTLY a raw JSON object mapping scene id to description, nothing else.

[GOOD EXAMPLE]
Voice-over: "In the age of artificial intelligence, we stand in the middle of the most radical technological transformation in human history."
Description: "weary commuters stand motionless with lowered heads and slack shoulders while a glowing processor module and tangled cable bundles dominate the rusted machinery above them, pale green interface light washing their faces, cold overcast dusk, dense foreground crowd against deep industrial background"

[BAD EXAMPLE — NEVER DO THIS]
"a solemn cinematic tableau capturing the narrative moment with soft dramatic lighting and atmospheric depth"
(rejected: no subject, no action, no topic object, would fit any video)

[OUTPUT SHAPE]
{{"001": "<30-60 word description>", "002": "<30-60 word description>"}}

[SCENES]
{json.dumps(simplified, ensure_ascii=False, indent=1)}
"""

    def _build_scene_descriptions(self, scenes_data: list, scene_style: str,
                                  topic: dict, visuals: dict, asset_map: dict) -> dict:
        """
        Gọi AI theo lô nhỏ. Một lô hỏng chỉ ảnh hưởng lô đó, các lô khác vẫn giữ
        mô tả bám chủ đề (bản cũ hỏng 1 lần là mất sạch toàn bộ scene).

        Các lô chạy SONG SONG: với Claude mỗi lô mất 40-60s, chạy tuần tự thì
        24 scene (2 lô) mất ~2 phút. Chạy đồng thời tổng chỉ còn bằng một lô.
        """
        batches = []
        for start in range(0, len(scenes_data), self.SCENES_PER_BATCH):
            batch = scenes_data[start:start + self.SCENES_PER_BATCH]
            batch_no = start // self.SCENES_PER_BATCH + 1
            batches.append((batch_no, batch))

        def run_one(item):
            batch_no, batch = item
            try:
                raw = ai_client.generate_content(
                    api_key=self.api_key,
                    prompt=self._batch_prompt(batch, scene_style, topic, visuals, asset_map),
                    system_prompt=(
                        "Return only valid JSON. Every description must depict the literal content "
                        "of its voice-over using concrete topic-specific objects. Never include "
                        "readable text in the image. Write in English only."
                    ),
                    gemini_model=self.default_model,
                    shop_model=self.default_model,
                    json_mode=True,
                    temperature=0.6,
                    max_output_tokens=self.MAX_OUTPUT_TOKENS,
                    timeout=300,
                )
                parsed = json.loads(ai_client.clean_json_text(raw))
                if not isinstance(parsed, dict):
                    raise ValueError("JSON trả về không phải object id -> description")
                return parsed
            except Exception as e:
                if ai_client.is_fatal_error(e):
                    raise RuntimeError(f"Không gọi được AI: {e}")
                print(f"[!] Lô {batch_no} lỗi khi tạo mô tả hình ảnh: {e}")
                return {}

        if len(batches) == 1:
            results = [run_one(batches[0])]
        else:
            from concurrent.futures import ThreadPoolExecutor
            # Giới hạn 4 luồng để không chạm rate limit của nhà cung cấp key.
            with ThreadPoolExecutor(max_workers=min(4, len(batches))) as ex:
                results = list(ex.map(run_one, batches))

        descriptions = {}
        for parsed in results:
            for key, value in parsed.items():
                cleaned = self._sanitize_description(value)
                if cleaned and not self._is_generic(cleaned):
                    descriptions[str(key).strip()] = cleaned
                else:
                    print(f"[!] mô tả scene {key} bị loại (chung chung/rỗng)")

        return descriptions

    # ------------------------------------------------------------------
    # Fallback bám chủ đề (thay cho 1 câu cố định của bản cũ)
    # ------------------------------------------------------------------

    def _fallback_description(self, scene: dict, topic: dict, visuals: dict,
                              asset_map: dict, index: int) -> str:
        """
        Khi AI hỏng, vẫn dựng mô tả từ dữ liệu thật: mô tả nhân vật + bối cảnh
        (bản tiếng Anh từ asset_visuals) + motif của chủ đề, xoay vòng motif để
        các scene khác nhau. Tuyệt đối không nhúng văn bản tiếng Việt vào prompt.
        """
        visuals = visuals or {}
        parts = []

        # Chỉ lấy mô tả tiếng Anh thuần (không kèm "ID =") vì prompt cuối đã có
        # sẵn ID do code ghép riêng. Nếu chưa dịch được sang tiếng Anh thì bỏ
        # qua, tuyệt đối không nhúng mô tả tiếng Việt vào prompt ảnh.
        char_desc = self._plain_descriptions(scene.get("character", ""), visuals)
        if char_desc:
            parts.append(f"featuring {char_desc}")

        bg_desc = self._plain_descriptions(scene.get("background", ""), visuals)
        if bg_desc:
            parts.append(f"set in {bg_desc}")

        motifs = topic.get("motifs") or []
        if motifs:
            picked = [motifs[index % len(motifs)]]
            if len(motifs) > 1:
                picked.append(motifs[(index + 1) % len(motifs)])
            parts.append("with " + " and ".join(picked) + " visible in frame")

        if topic.get("era_setting"):
            parts.append(topic["era_setting"])
        if topic.get("mood"):
            parts.append(f"{topic['mood']} tone")

        parts.append("expressive posture and clear gaze direction, layered foreground and background depth")

        return self._sanitize_description(", ".join(p for p in parts if p))

    # ------------------------------------------------------------------
    # Điểm vào chính
    # ------------------------------------------------------------------

    def process_get_prompt_image(self, scenes_data: list, scene_style: str,
                                 assets_text: str = "") -> dict:
        """
        scenes_data: list dict, mỗi dict tối thiểu gồm:
            {"id": "001", "vo": "...", "character": "CHARACTERS 001; CHARACTERS 003",
             "background": "BACKGROUNDS 002", "camera": "medium shot"}
        scene_style: chuỗi style lấy từ ô "Scene Style" trên giao diện.
        assets_text: kết quả Pre-scan (tab Assets) — cung cấp mô tả thật cho
            từng ID. Bỏ trống vẫn chạy nhưng prompt sẽ kém bám sát hơn.

        Trả về:
            {"glabs_prompts": "toàn bộ prompt, mỗi dòng 1 scene",
             "assigned_scenes": [{"id":..., "character":..., "background":...,
                                  "camera":..., "final_prompt":...}, ...]}
        """
        if not scenes_data:
            return {"glabs_prompts": "", "assigned_scenes": []}

        scene_style = (scene_style or "").strip()
        if not scene_style:
            raise ValueError("Vui lòng nhập hoặc dán Scene Style prompt bên ngoài trước khi tạo Get-Prompt Image.")

        # Bước 0: giải mô tả thật của nhân vật/bối cảnh từ kết quả Pre-scan
        asset_map = self._parse_asset_descriptions(assets_text)

        # Bước 1: hiểu chủ đề + dịch asset sang tiếng Anh để mọi scene bám đúng
        # thế giới của kịch bản và prompt không chứa văn bản tiếng Việt
        topic = self._analyze_topic(scenes_data, asset_map)
        visuals = topic.get("asset_visuals") or {}

        # Bước 2: AI viết mô tả hành động cụ thể cho từng scene (theo lô)
        descriptions = self._build_scene_descriptions(
            scenes_data, scene_style, topic, visuals, asset_map
        )

        # Bước 3: code tự ghép cứng camera + nhân vật + bối cảnh (giữ y hệt Scene List)
        prompts_lines = []
        assigned_scenes = []

        for index, sc in enumerate(scenes_data):
            s_id = str(sc.get("id", "")).strip()
            character = (sc.get("character") or "").strip()
            background = (sc.get("background") or "").strip()
            camera = (sc.get("camera") or "").strip() or "medium shot"

            desc = (descriptions.get(s_id) or "").strip()
            if not desc:
                desc = self._fallback_description(sc, topic, visuals, asset_map, index)
            desc = self._sanitize_description(desc)

            segments = [scene_style, camera]
            if character:
                segments.append(character)
            if background:
                segments.append(f"at {background}")
            segments.append(desc)
            # Lớp bảo vệ 3: luôn chèn cứng cụm không-chữ vào cuối mọi prompt
            segments.append(self.NO_TEXT_GUARD)

            final_prompt = f"[{s_id}] " + ", ".join(s for s in segments if s) + f" {self.NO_TEXT_PARAM} --ar 16:9"

            prompts_lines.append(final_prompt)
            assigned_scenes.append({
                "id": s_id,
                "character": character,
                "background": background,
                "camera": camera,
                "final_prompt": final_prompt,
            })

        return {
            "glabs_prompts": "\n".join(prompts_lines),
            "assigned_scenes": assigned_scenes,
        }
