"""
modules/get_prompt_video_handler.py

Tool 2 — Get-Prompt Video (biến prompt ảnh tĩnh thành prompt video).

Đầu vào là chính kết quả của Get-Prompt Image (ô "G-Labs Image Prompts"),
cộng với Scene List (VO, nhân vật, bối cảnh, camera).

Nhiệm vụ: ĐỌC và HIỂU từng prompt ảnh, đối chiếu với nội dung VO của scene
đó, rồi viết prompt video tương ứng — mô tả chuyển động của nhân vật, của
vật thể, của máy quay và diễn biến trong khung hình.

Nguyên tắc thiết kế (khác hẳn kiểu sinh ngẫu nhiên):
    - KHÔNG random, KHÔNG dùng bảng chuyển động mặc định gán bừa.
    - Mỗi scene phải được phân tích riêng: prompt ảnh nói gì, VO nói gì,
      thì chuyển động phải phục vụ đúng nội dung đó.
    - Chuyển động phải bắt đầu TỪ đúng khung hình mà prompt ảnh đã tạo ra
      (image-to-video), không đổi bố cục, không đổi nhân vật, không đổi bối cảnh.
    - Giữ nguyên ID scene để khớp file ảnh 001.jpg, 002.jpg...
"""

import json
import re

from . import ai_client


# Lấy theo model đang cấu hình trong ai_client (biến SHOPAIKEY_MODEL),
# để đổi model một chỗ là toàn hệ thống đổi theo — tránh tình trạng
# key chỉ bán Claude nhưng handler vẫn gọi gemini-2.5-flash.
DEFAULT_MODEL = ai_client.SHOPAIKEY_MODEL

# Số scene xử lý mỗi lượt gọi AI. Để nhỏ vì mỗi scene cần AI đọc kỹ cả
# prompt ảnh lẫn VO; lô quá lớn khiến model đọc lướt và trả về chung chung.
BATCH_SIZE = 6

MAX_OUTPUT_TOKENS = 8192

# Cụm ép cuối mỗi prompt: giữ nguyên khung hình gốc, không sinh chữ trong video
NO_TEXT_GUARD = "no text, no letters, no captions, no watermark, no subtitles"
CONSISTENCY_GUARD = (
    "preserve the exact composition, character design, outfit, color palette "
    "and lighting of the source image"
)


class GetPromptVideoHandler:
    """
    Chuyển danh sách prompt ảnh + VO thành danh sách prompt video.

    Cách dùng:
        handler = GetPromptVideoHandler(api_key="...")
        result = handler.process_get_prompt_video(
            scenes_data=[{"id": "001", "vo": "...", "character": "...",
                          "background": "...", "camera": "..."}],
            image_prompts_text="[001] ...\n[002] ...",
            motion_style="cinematic subtle motion",
        )
    """

    def __init__(self, api_key=None, default_model=DEFAULT_MODEL):
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise ValueError("Chưa cấu hình API Key!")
        self.default_model = default_model

    # ──────────────────────────────────────────────────────────
    #  PHẦN 1 — ĐỌC LẠI KẾT QUẢ GET-PROMPT IMAGE
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _norm_id(raw) -> str:
        """Chuẩn hóa ID scene về dạng chuỗi số 3 chữ số: 1 -> 001."""
        s = str(raw or "").strip()
        m = re.search(r"\d+", s)
        if not m:
            return s
        return m.group(0).zfill(3)

    @classmethod
    def parse_image_prompts(cls, image_prompts_text: str) -> dict:
        """
        Tách ô "G-Labs Image Prompts" thành map {scene_id: prompt ảnh}.

        Get-Prompt Image xuất mỗi scene một dòng theo dạng:
            [001] scene style, medium shot, CHARACTERS 001, at ... --ar 16:9

        Hàm này chấp nhận cả dạng không có ngoặc vuông ("001. ..." hoặc
        "001: ...") để không vỡ nếu người dùng sửa tay.
        """
        text = (image_prompts_text or "").strip()
        if not text:
            return {}

        result = {}
        current_id = None
        buffer = []

        def flush():
            if current_id and buffer:
                body = " ".join(buffer).strip()
                if body:
                    result[current_id] = body

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            # [001] ...  |  001. ...  |  001: ...  |  001 - ...
            m = re.match(r"^\[?\s*(\d{1,4})\s*[\]\.\:\-–]\s*(.*)$", line)
            if m:
                flush()
                current_id = cls._norm_id(m.group(1))
                buffer = [m.group(2).strip()] if m.group(2).strip() else []
            elif current_id:
                # Dòng nối tiếp của prompt phía trên (prompt bị wrap)
                buffer.append(line)

        flush()
        return result

    @staticmethod
    def _strip_tech_params(prompt: str) -> str:
        """
        Bỏ các tham số kỹ thuật của image-gen khỏi prompt ảnh trước khi đưa
        cho AI đọc: --ar, --no, --v... Giữ lại phần mô tả nội dung để AI
        tập trung hiểu cảnh, không bị nhiễu bởi cú pháp Midjourney.
        """
        text = (prompt or "").strip()
        text = re.sub(r"--\w+(?:\s+[^\s-][^\s]*)*", " ", text)
        text = re.sub(r"\b(no text|no letters|no captions|no watermark|no subtitles)\b,?", " ", text, flags=re.I)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip(" ,")

    # ──────────────────────────────────────────────────────────
    #  PHẦN 2 — PROMPT GỬI AI CHO TỪNG LÔ
    # ──────────────────────────────────────────────────────────

    def _batch_prompt(self, batch: list, motion_style: str, vo_lang: str) -> str:
        """
        Dựng prompt yêu cầu AI đọc từng scene và viết prompt video tương ứng.

        batch: list các dict đã ghép sẵn
            {"id", "vo", "character", "background", "camera", "image_prompt"}
        """
        blocks = []
        for sc in batch:
            blocks.append(
                f"""--- SCENE {sc['id']} ---
PROMPT ẢNH ĐÃ TẠO (khung hình đầu tiên của video):
{sc['image_prompt'] or "(chưa có prompt ảnh cho scene này)"}

NỘI DUNG VO (lời thuyết minh đang nói khi cảnh này chiếu):
{sc['vo'] or "(không có)"}

NHÂN VẬT: {sc['character'] or "(không có)"}
BỐI CẢNH: {sc['background'] or "(không có)"}
GÓC MÁY ĐÃ CHỌN: {sc['camera'] or "medium shot"}"""
            )

        scenes_block = "\n\n".join(blocks)
        ids_list = ", ".join(sc["id"] for sc in batch)

        return f"""
[VAI TRÒ]
Bạn là chuyên gia viết prompt image-to-video cho Veo / Runway / Kling.
Nhiệm vụ: biến MỘT ẢNH TĨNH đã có thành MỘT ĐOẠN VIDEO 5-8 giây.

[NGUYÊN TẮC BẮT BUỘC — ĐỌC KỸ]
1. TUYỆT ĐỐI KHÔNG sinh chuyển động ngẫu nhiên hay dùng mẫu có sẵn.
   Với mỗi scene, bạn PHẢI đọc prompt ảnh và VO của CHÍNH scene đó,
   hiểu trong cảnh có ai, đang ở đâu, đang làm gì, VO đang nói về điều gì,
   rồi mới quyết định chuyển động phù hợp với nội dung ấy.
2. Chuyển động phải BẮT ĐẦU TỪ đúng khung hình mà prompt ảnh đã tạo.
   KHÔNG đổi bố cục, KHÔNG đổi thiết kế nhân vật, KHÔNG đổi trang phục,
   KHÔNG đổi bối cảnh, KHÔNG đổi bảng màu, KHÔNG thêm nhân vật mới.
3. Chuyển động phải phục vụ nội dung VO. Ví dụ nguyên tắc suy luận:
   - VO nêu bối cảnh tổng quan  -> máy đẩy vào chậm hoặc bay ngang mở không gian
   - VO nêu con số / dữ kiện    -> máy gần như tĩnh, chỉ vật thể trọng tâm động nhẹ
   - VO nói về hành động cụ thể -> nhân vật thực hiện đúng hành động đó
   - VO đặt câu hỏi / bỏ lửng   -> máy lùi ra chậm, nhân vật ngưng lại, tạo khoảng lặng
   - VO nói về biến động / xung đột -> chuyển động dứt khoát hơn, có lực
   Đây là NGUYÊN TẮC suy luận, không phải bảng tra cứu để gán máy móc.
4. Mỗi scene chỉ 1-2 chuyển động chính. Nhồi nhiều chuyển động làm video rối
   và mô hình sinh video sẽ bóp méo hình.
5. Nêu rõ TỐC ĐỘ chuyển động (slow / steady / brisk) và HƯỚNG nếu có.
6. Không mô tả chữ, phụ đề, watermark xuất hiện trong video.
7. Prompt video viết bằng TIẾNG ANH, 1 đoạn liền, 40-90 từ.
   Phần "reason" viết bằng tiếng Việt.

[DỮ LIỆU CÁC SCENE]
{scenes_block}

[YÊU CẦU ĐẦU RA]
Trả về JSON thuần, không kèm markdown. Đúng {len(batch)} phần tử,
đúng các ID sau: {ids_list}

{{
  "scenes": [
    {{
      "id": "001",
      "video_prompt": "English image-to-video prompt: what moves, how fast, camera behaviour",
      "subject_motion": "chuyển động của nhân vật/vật thể, tiếng Việt, ngắn",
      "camera_motion": "chuyển động máy quay, tiếng Việt, ngắn",
      "duration": 6,
      "reason": "vì sao chọn chuyển động này cho ĐÚNG scene này, dẫn lại chi tiết từ prompt ảnh và VO"
    }}
  ]
}}
""".strip()

    # ──────────────────────────────────────────────────────────
    #  PHẦN 3 — GỌI AI THEO LÔ
    # ──────────────────────────────────────────────────────────

    def _analyze_batch(self, batch: list, motion_style: str, vo_lang: str) -> dict:
        """Gọi AI cho 1 lô scene, trả map {scene_id: dict kết quả}."""
        prompt = self._batch_prompt(batch, motion_style, vo_lang)

        raw = ai_client.generate_content(
            api_key=self.api_key,
            prompt=prompt,
            gemini_model=self.default_model,
            shop_model=self.default_model,
            json_mode=True,
            temperature=0.55,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            # Mặc định của ai_client là 60s — quá ngắn cho một lô nhiều scene,
            # request bị cắt giữa chừng khiến cả lô rơi về fallback.
            timeout=240,
        )

        data = json.loads(ai_client.clean_json_text(raw))
        out = {}
        for item in (data.get("scenes") or []):
            if not isinstance(item, dict):
                continue
            sid = self._norm_id(item.get("id"))
            if not sid:
                continue
            out[sid] = {
                "video_prompt": str(item.get("video_prompt") or "").strip(),
                "subject_motion": str(item.get("subject_motion") or "").strip(),
                "camera_motion": str(item.get("camera_motion") or "").strip(),
                "duration": item.get("duration") or 6,
                "reason": str(item.get("reason") or "").strip(),
            }
        return out

    # ──────────────────────────────────────────────────────────
    #  PHẦN 4 — FALLBACK KHÔNG NGẪU NHIÊN
    # ──────────────────────────────────────────────────────────

    def _fallback_motion(self, scene: dict) -> dict:
        """
        Khi AI không trả về scene nào đó, vẫn phải cho ra chuyển động CÓ CĂN CỨ
        — suy ra từ góc máy đã chọn và độ dài VO, tuyệt đối không random.

        Góc máy quyết định chuyển động hợp lý: cảnh rộng thì đẩy/kéo chậm để
        khoe không gian, cận cảnh thì máy gần như tĩnh để giữ nét biểu cảm.
        """
        camera = (scene.get("camera") or "").lower()
        vo = (scene.get("vo") or "").strip()
        vo_len = len(vo)

        if any(k in camera for k in ("extreme wide", "ews", "establishing", "drone", "aerial")):
            cam = "very slow push in"
            subj = "ambient environmental movement: drifting clouds, moving light, subtle atmospheric haze"
            why = "Cảnh thiết lập rộng — đẩy máy chậm để mở dần không gian."
        elif any(k in camera for k in ("wide", "ws", "full shot")):
            cam = "slow pan following the subject"
            subj = "subject shifts weight and turns slightly, background elements move gently"
            why = "Cảnh rộng — pan chậm theo chủ thể để giữ mạch quan sát."
        elif any(k in camera for k in ("extreme close", "ecu", "macro", "detail")):
            cam = "locked off, no camera movement"
            subj = "minimal detail motion only: slight tremor, light glinting across the surface"
            why = "Cực cận — máy tĩnh để chi tiết không bị nhòe."
        elif any(k in camera for k in ("close", "cu", "cận")):
            cam = "almost static with a barely perceptible drift in"
            subj = "subtle facial and breathing motion, small head tilt, eyes shifting focus"
            why = "Cận cảnh — giữ máy gần như tĩnh để nổi biểu cảm."
        else:
            cam = "gentle slow drift in"
            subj = "natural idle motion of the subject, small gestures consistent with the scene"
            why = "Trung cảnh — đẩy nhẹ tạo cảm giác sống mà không phá bố cục."

        # Thời lượng suy từ độ dài VO (~15 ký tự/giây đọc), kẹp trong 4-8s
        est = 6 if not vo_len else max(4, min(8, round(vo_len / 15)))

        base = self._strip_tech_params(scene.get("image_prompt") or "")
        head = base if base else (scene.get("background") or "the scene")

        video_prompt = (
            f"{head}. Animate this still image: {subj}. Camera: {cam}. "
            f"{CONSISTENCY_GUARD}, smooth natural motion, consistent lighting, "
            f"{NO_TEXT_GUARD}"
        )

        return {
            "video_prompt": video_prompt,
            "subject_motion": subj,
            "camera_motion": cam,
            "duration": est,
            "reason": why + " (Suy từ góc máy — AI không trả kết quả cho scene này.)",
            "fallback": True,
        }

    # ──────────────────────────────────────────────────────────
    #  PHẦN 5 — HÀM CHÍNH
    # ──────────────────────────────────────────────────────────

    def process_get_prompt_video(self, scenes_data: list,
                                 image_prompts_text: str,
                                 motion_style: str = "",
                                 vo_lang: str = "Vietnamese") -> dict:
        """
        scenes_data: list scene từ Scene List
            [{"id","vo","character","background","camera"}, ...]
        image_prompts_text: nội dung ô "G-Labs Image Prompts" (kết quả Tool 2)
        motion_style: định hướng chuyển động chung (tùy chọn)

        Trả về:
            {"veos_prompts": "chuỗi nhiều dòng, mỗi scene 1 prompt",
             "video_scenes": [{id, camera_motion, subject_motion,
                               duration, reason, video_prompt}, ...],
             "matched": số scene tìm được prompt ảnh,
             "total": tổng scene,
             "fallback_count": số scene phải dùng fallback}
        """
        if not scenes_data:
            return {"veos_prompts": "", "video_scenes": [],
                    "matched": 0, "total": 0, "fallback_count": 0}

        image_map = self.parse_image_prompts(image_prompts_text)
        if not image_map:
            raise ValueError(
                "Chưa có kết quả Get-Prompt Image. Hãy bấm 'Get-Prompt - image' "
                "để tạo prompt ảnh trước, vì prompt video được viết dựa trên chính "
                "nội dung của từng prompt ảnh."
            )

        # Ghép scene với prompt ảnh tương ứng theo ID
        enriched = []
        matched = 0
        for sc in scenes_data:
            sid = self._norm_id(sc.get("id"))
            img = image_map.get(sid, "")
            if img:
                matched += 1
            enriched.append({
                "id": sid,
                "vo": (sc.get("vo") or sc.get("text") or "").strip(),
                "character": (sc.get("character") or "").strip(),
                "background": (sc.get("background") or "").strip(),
                "camera": (sc.get("camera") or "").strip() or "medium shot",
                "image_prompt": self._strip_tech_params(img),
            })

        if not matched:
            raise ValueError(
                "Không khớp được ID scene nào với prompt ảnh. Kiểm tra lại ô "
                "G-Labs Image Prompts — mỗi dòng cần bắt đầu bằng [001], [002]..."
            )

        # Gọi AI theo lô
        results = {}
        for i in range(0, len(enriched), BATCH_SIZE):
            batch = enriched[i:i + BATCH_SIZE]
            try:
                results.update(self._analyze_batch(batch, motion_style, vo_lang))
            except Exception:
                # Lô lỗi thì để fallback lo, không làm sập cả tiến trình
                continue

        # Ghép kết quả cuối
        lines = []
        video_scenes = []
        fallback_count = 0

        for sc in enriched:
            item = results.get(sc["id"])
            if not item or not item.get("video_prompt"):
                item = self._fallback_motion(sc)
                fallback_count += 1

            prompt_body = item["video_prompt"].strip()

            # Ép hai lớp bảo vệ nếu AI bỏ sót
            low = prompt_body.lower()
            if "no text" not in low:
                prompt_body = prompt_body.rstrip(". ,") + f", {NO_TEXT_GUARD}"
            if "composition" not in low and "source image" not in low:
                prompt_body = prompt_body.rstrip(". ,") + f", {CONSISTENCY_GUARD}"

            dur = item.get("duration") or 6
            try:
                dur = max(4, min(8, int(float(dur))))
            except (TypeError, ValueError):
                dur = 6

            final = f"[{sc['id']}] {prompt_body} --duration {dur}s --ar 16:9"
            lines.append(final)

            video_scenes.append({
                "id": sc["id"],
                "camera_motion": item.get("camera_motion", ""),
                "subject_motion": item.get("subject_motion", ""),
                "duration": dur,
                "reason": item.get("reason", ""),
                "video_prompt": final,
                "fallback": bool(item.get("fallback")),
            })

        return {
            "veos_prompts": "\n\n".join(lines),
            "video_scenes": video_scenes,
            "matched": matched,
            "total": len(enriched),
            "fallback_count": fallback_count,
        }
