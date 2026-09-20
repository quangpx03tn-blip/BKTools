"""
modules/thumbnail_handler.py

Hai luồng tạo tiêu đề thumbnail tối ưu CTR:
1. Từ tiêu đề video -> 5 tiêu đề ngắn, thu hút click
2. Từ tóm tắt kịch bản -> tóm tắt cốt lõi -> 5 tiêu đề thumbnail

Sau đó xây dựng prompt AI tạo ảnh (Midjourney / DALL-E / G-Labs).
"""

import json
import os
import re
from . import ai_client


# Lấy theo model đang cấu hình trong ai_client (biến SHOPAIKEY_MODEL),
# để đổi model một chỗ là toàn hệ thống đổi theo — tránh tình trạng
# key chỉ bán Claude nhưng handler vẫn gọi gemini-2.5-flash.
# Tác vụ ngắn, có khuôn mẫu (mô tả 30-60 từ, tách scene, gán asset) ->
# dùng model NHANH. Nếu key không bán model này, ai_client tự chuyển
# sang model dự phòng nên không bao giờ lỗi model_not_found.
DEFAULT_MODEL = ai_client.MODEL_FAST
TITLES_MAX_OUTPUT_TOKENS = 2048

LANG_NAMES = {
    "vi": "tiếng Việt",
    "en": "tiếng Anh",
    "de": "tiếng Đức",
    "pt": "tiếng Bồ Đào Nha",
    "es": "tiếng Tây Ban Nha",
    "ko": "tiếng Hàn",
    "ja": "tiếng Nhật",
    "zh": "tiếng Trung",
    "fr": "tiếng Pháp",
    "th": "tiếng Thái",
}


def generate_thumbnail_titles(video_title, script_summary, api_key, output_lang="vi", model=""):
    """
    Sinh 5 tiêu đề thumbnail tối ưu CTR.

    Path 1: video_title có nội dung -> biến thể ngắn từ tiêu đề.
    Path 2: chỉ có script_summary -> tóm tắt rồi sinh tiêu đề.
    """
    api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("Chưa cấu hình API Key!")

    video_title = (video_title or "").strip()
    script_summary = (script_summary or "").strip()
    lang_name = LANG_NAMES.get(output_lang, "tiếng Việt")

    if not video_title and not script_summary:
        raise ValueError("Hãy nhập Tiêu đề Video hoặc Tóm tắt kịch bản.")

    use_model = (model or "").strip() or DEFAULT_MODEL

    if video_title:
        source_block = f"""NGUỒN: TIÊU ĐỀ VIDEO
{video_title}
"""
        task = "Từ tiêu đề video trên, tạo 5 tiêu đề thumbnail ngắn gọn, tối ưu CTR."
    else:
        source_block = f"""NGUỒN: TÓM TẮT KỊCH BẢN
{script_summary[:4000]}
"""
        task = "Đọc tóm tắt kịch bản, nắm nội dung cốt lõi, rồi tạo 5 tiêu đề thumbnail ngắn gọn, tối ưu CTR."

    prompt = f"""
[SYSTEM ROLE]
Bạn là chuyên gia tối ưu CTR YouTube thumbnail.
Toàn bộ đầu ra PHẢI bằng {lang_name}.

[NHIỆM VỤ]
{task}

{source_block}

[YÊU CẦU]
- Mỗi tiêu đề dài 6–10 từ, súc tích, tạo tò mò
- Dùng từ mạnh: Sự thật / Bí mật / Động trời / Vạch trần / Sốc (hoặc tương đương theo ngôn ngữ đầu ra)
- Đa dạng góc: câu hỏi, khẳng định, kịch tính
- Không clickbait sai sự thật

[ĐỊNH DẠNG]
Chỉ trả JSON thuần:
{{
  "titles": ["tiêu đề 1", "tiêu đề 2", "tiêu đề 3", "tiêu đề 4", "tiêu đề 5"]
}}
"""

    raw = ai_client.generate_content(
        api_key=api_key,
        prompt=prompt,
        gemini_model=use_model,
        shop_model=use_model,
        json_mode=True,
        temperature=0.8,
        max_output_tokens=TITLES_MAX_OUTPUT_TOKENS,
        # Mặc định của ai_client chỉ 60s — Claude sinh nội dung dài thường vượt ngưỡng này.
        timeout=180,
    )

    data = json.loads(raw)
    titles = data.get("titles") or []
    if not isinstance(titles, list) or len(titles) == 0:
        raise RuntimeError("AI không trả về danh sách tiêu đề hợp lệ.")

    titles = [str(t).strip() for t in titles if str(t).strip()]
    while len(titles) < 5:
        titles.append(f"Tiêu đề {len(titles) + 1}")
    return {"titles": titles[:5]}


def analyze_thumbnail_structure(video_title, selected_title, api_key, output_lang="vi", model=""):
    """Phân tích HÌNH ẢNH & VỊ TRÍ / VĂN BẢN & FONTS / MÀU SẮC & CẢM XÚC."""
    api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("Chưa cấu hình API Key!")

    video_title = (video_title or "").strip()
    selected_title = (selected_title or "").strip()
    lang_name = LANG_NAMES.get(output_lang, "tiếng Việt")

    if not selected_title and not video_title:
        raise ValueError("Cần tiêu đề để phân tích cấu trúc thumbnail.")

    use_model = (model or "").strip() or DEFAULT_MODEL

    prompt = f"""
[SYSTEM ROLE]
Bạn là chuyên gia thiết kế thumbnail YouTube.
Toàn bộ đầu ra PHẢI bằng {lang_name}.

[ĐẦU VÀO]
Tiêu đề video: {video_title or "(không có)"}
Tiêu đề thumbnail đã chọn: {selected_title or "(không có)"}

[NHIỆM VỤ]
Phân tích cấu trúc thumbnail tối ưu CTR.

[ĐỊNH DẠNG]
Chỉ trả JSON thuần:
{{
  "image_position": "vị trí nhân vật/hình ảnh chính, ngắn gọn",
  "text_fonts": "chữ hiển thị trên thumbnail, IN HOA, tối đa 5-7 từ",
  "color_emotion": "bảng màu + cảm xúc, ngắn gọn"
}}
"""

    raw = ai_client.generate_content(
        api_key=api_key,
        prompt=prompt,
        gemini_model=use_model,
        shop_model=use_model,
        json_mode=True,
        temperature=0.6,
        max_output_tokens=1024,
        # Mặc định của ai_client chỉ 60s — Claude sinh nội dung dài thường vượt ngưỡng này.
        timeout=180,
    )
    data = json.loads(raw)
    return {
        "image_position": str(data.get("image_position") or "").strip(),
        "text_fonts": str(data.get("text_fonts") or "").strip(),
        "color_emotion": str(data.get("color_emotion") or "").strip(),
    }


def build_thumbnail_prompt(
    video_title,
    selected_topic,
    script_summary,
    style,
    subtitle,
    custom_prompt,
    image_position,
    text_style,
    color_emotion,
    output_lang="vi",
):
    """Ghép prompt AI tạo ảnh thumbnail (không gọi AI — deterministic)."""
    topic = (selected_topic or "").strip() or "Video thumbnail concept"
    focus = (script_summary or "").strip() or "High-impact visual composition"
    style = (style or "").strip() or "Hand-drawn 2D Historical Explainer Cartoon Style"
    lang_name = LANG_NAMES.get(output_lang, "vi")

    parts = [
        f"YouTube thumbnail, {style}",
        f"depicting {focus}",
        f'featuring bold thematic concept about "{topic}"',
    ]

    if (video_title or "").strip():
        parts.append(f'video title context: "{video_title.strip()}"')
    if (subtitle or "").strip():
        parts.append(f'text overlay: "{subtitle.strip()}"')

    structure = []
    if (image_position or "").strip():
        structure.append(f"composition: {image_position.strip()}")
    if (text_style or "").strip():
        structure.append(f"text treatment: {text_style.strip()}")
    if (color_emotion or "").strip():
        structure.append(f"color palette and mood: {color_emotion.strip()}")
    if structure:
        parts.append(", ".join(structure))

    parts.append("dramatic composition, high contrast, clean negative space for text")
    if (custom_prompt or "").strip():
        parts.append(custom_prompt.strip())
    parts.append("16:9 --ar 16:9")
    parts.append(f"[Lang: {lang_name}]")

    return {"prompt": ", ".join(parts)}


def build_thumbnail_prompt_ai(
    api_key,
    selected_title,
    video_title="",
    script_summary="",
    subtitle="",
    custom_prompt="",
    image_position="",
    text_style="",
    color_emotion="",
    image_base64="",
    char_style="",
    bg_style="",
    scene_style="",
    visual="",
    profile_name="",
    output_lang="vi",
    model="",
):
    """
    Tạo prompt Midjourney/DALL-E bằng AI:
    - Phân tích ảnh tham chiếu (nếu có) bằng vision
    - Kết hợp Active Profile style (char_style / bg_style / scene_style / visual)
    - Kết hợp tiêu đề thumbnail đã chọn
    """
    api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("Chưa cấu hình API Key!")

    selected_title = (selected_title or "").strip()
    if not selected_title and not (video_title or "").strip():
        raise ValueError("Cần tiêu đề thumbnail để tạo prompt ảnh.")

    use_model = (model or "").strip() or DEFAULT_MODEL

    lang_name = LANG_NAMES.get(output_lang, "tiếng Việt")

    profile_block = ""
    if any([(char_style or "").strip(), (bg_style or "").strip(),
            (scene_style or "").strip(), (visual or "").strip()]):
        profile_block = f"""
[ACTIVE PROFILE STYLE — BẮT BUỘC TUÂN THỦ]
Channel: {profile_name or "(unknown)"}
Visual DNA: {(visual or "").strip() or "(không có)"}
Character Style: {(char_style or "").strip() or "(không có)"}
Background Style: {(bg_style or "").strip() or "(không có)"}
Scene Style: {(scene_style or "").strip() or "(không có)"}
"""
    else:
        profile_block = """
[ACTIVE PROFILE STYLE]
Chưa có Active Profile — dùng phong cách YouTube thumbnail cinematic phổ biến, high contrast, CTR-oriented.
"""

    # 3 cấu trúc là BẮT BUỘC — thiếu thì không ghép được prompt đúng ý đồ
    _img_pos = (image_position or "").strip()
    _txt_sty = (text_style or "").strip()
    _col_emo = (color_emotion or "").strip()
    _missing = []
    if not _img_pos:
        _missing.append("Vị trí / Composition")
    if not _txt_sty:
        _missing.append("Text overlay")
    if not _col_emo:
        _missing.append("Màu sắc & Cảm xúc")
    if _missing:
        raise ValueError(
            "Thiếu cấu trúc thumbnail: " + ", ".join(_missing) +
            ". Hãy bấm 'Phân tích cấu trúc' trước khi ghép prompt."
        )

    structure_block = f"""
[CẤU TRÚC THUMBNAIL ĐÃ PHÂN TÍCH — BẮT BUỘC TÁI HIỆN ĐẦY ĐỦ CẢ 3 YẾU TỐ]
Hình ảnh & vị trí: {_img_pos}
Văn bản & fonts: {_txt_sty}
Màu sắc & cảm xúc: {_col_emo}
"""

    # --- ẢNH THAM CHIẾU ---
    # Giờ cả ShopAIKey và Gemini gốc đều đọc được ảnh.
    has_image = bool((image_base64 or "").strip())

    if has_image:
        image_instruction = """
[ẢNH THAM CHIẾU — BẮT BUỘC PHÂN TÍCH TRƯỚC KHI VIẾT PROMPT]
Ảnh đính kèm là reference composition thật. BẮT BUỘC nhìn kỹ ảnh và rút ra:
- Bố cục: subject nằm trái/phải/giữa, tỉ lệ chiếm khung, rule of thirds, negative space ở đâu
- Ánh sáng: hướng sáng, rim light, độ tương phản, vùng sáng/tối
- Bảng màu chủ đạo: 2-3 màu chính và màu nhấn
- Pose / gesture / biểu cảm / object placement đáng học
- Cách chữ được đặt trong ảnh mẫu (nếu có): vị trí, kích thước tương đối, tương phản nền

SAU ĐÓ tái tạo ý tưởng theo ACTIVE PROFILE STYLE — KHÔNG copy nguyên ảnh,
chỉ lấy composition DNA và chuyển sang visual DNA của channel.
Trong "composition_note" PHẢI nêu rõ bạn đã học được gì cụ thể TỪ ẢNH NÀY
(nêu đích danh bố cục/màu/ánh sáng quan sát được, không nói chung chung).
"""
    else:
        image_instruction = """
[ẢNH THAM CHIẾU]
Không có ảnh upload. Tự thiết kế composition tối ưu CTR dựa trên tiêu đề + profile style.
"""

    prompt = f"""
[SYSTEM ROLE]
Bạn là chuyên gia thiết kế YouTube thumbnail + viết prompt Midjourney / DALL-E / G-Labs.
Prompt ảnh cuối cùng PHẢI bằng tiếng Anh (chuẩn image-gen).
Phần giải thích ngắn (nếu có trong JSON) bằng {lang_name}.

[ĐẦU VÀO]
Tiêu đề thumbnail đã chọn: {selected_title or "(không có)"}
Tiêu đề video gốc: {(video_title or "").strip() or "(không có)"}
Tóm tắt kịch bản: {(script_summary or "").strip()[:1500] or "(không có)"}
Text overlay trên thumbnail: {(subtitle or "").strip() or selected_title or "(không có)"}
Yêu cầu bổ sung từ user: {(custom_prompt or "").strip() or "(không có)"}

{profile_block}
{structure_block}
{image_instruction}

[NHIỆM VỤ]
Viết 1 prompt ảnh thumbnail YouTube hoàn chỉnh, sẵn sàng paste vào Midjourney/DALL-E.
Prompt PHẢI tổng hợp ĐỦ 3 nguồn: (a) cấu trúc thumbnail đã phân tích ở trên,
(b) ảnh tham chiếu (nếu có), (c) Active Profile style.

[QUY TẮC]
1. Bám sát ACTIVE PROFILE STYLE (char/bg/scene/visual) nếu có.
2. Composition CTR: focal object 40-55%, negative space dành cho dòng chữ tiêu đề, high contrast.
3. BẮT BUỘC render dòng chữ tiêu đề NGAY TRONG ẢNH — đây là yêu cầu quan trọng nhất:
   - Dùng chính xác chuỗi ký tự này, không dịch, không đổi chữ, không viết tắt:
     "{(subtitle or "").strip() or selected_title}"
   - Trong prompt phải ghi rõ theo mẫu:
     with bold large text overlay reading exactly "<chuỗi trên>" placed in the negative space
   - Mô tả kiểu chữ / font / màu chữ / viền chữ theo đúng mục "Văn bản & fonts" ở trên.
   - Chữ phải to, dễ đọc ở kích thước nhỏ, tương phản mạnh với nền, không bị vật thể che khuất.
4. Prompt tiếng Anh, 1 đoạn liền, 80–140 từ, kết thúc bằng: --ar 16:9
5. Nếu profile có nhân vật signature (vd. faceless strategist), đưa vào đúng mô tả char_style.
6. Không dùng countryball trừ khi profile yêu cầu.

[ĐỊNH DẠNG]
Chỉ trả JSON thuần:
{{
  "prompt": "full English image prompt, MUST contain the exact quoted title text, ending with --ar 16:9",
  "composition_note": "ghi chú ngắn về bố cục bằng {lang_name}"
}}
"""

    if has_image:
        # Có ảnh -> gọi vision (hỗ trợ cả ShopAIKey lẫn Gemini gốc)
        raw = ai_client.generate_content_with_image(
            api_key=api_key,
            prompt=prompt,
            image_base64=image_base64,
            json_mode=True,
            temperature=0.7,
            max_output_tokens=2048,
            gemini_model=use_model,
            shop_model=use_model,
            # Mặc định của ai_client chỉ 60s — Claude sinh nội dung dài thường vượt ngưỡng này.
            timeout=180,
        )
    else:
        # Không có ảnh -> chỉ dùng text
        raw = ai_client.generate_content(
            api_key=api_key,
            prompt=prompt,
            json_mode=True,
            temperature=0.7,
            max_output_tokens=2048,
            gemini_model=use_model,
            shop_model=use_model,
            # Mặc định của ai_client chỉ 60s — Claude sinh nội dung dài thường vượt ngưỡng này.
            timeout=180,
        )

    data = json.loads(ai_client.clean_json_text(raw))
    final_prompt = str(data.get("prompt") or "").strip()
    if not final_prompt:
        raise RuntimeError("AI không trả về prompt ảnh hợp lệ.")

    # --- ÉP DÒNG TIÊU ĐỀ CỨNG TRONG ẢNH ---
    # Dù prompt hướng dẫn đã yêu cầu, model vẫn có thể bỏ sót chữ.
    # Ở đây kiểm tra lại và tự chèn nếu thiếu, để ảnh sinh ra LUÔN có tiêu đề.
    overlay_text = (subtitle or "").strip() or selected_title or (video_title or "").strip()
    if overlay_text:
        # Bỏ --ar tạm để chèn mệnh đề text vào đúng phần mô tả
        ar_suffix = ""
        m_ar = re.search(r"\s--ar\s+\S+\s*$", final_prompt)
        if m_ar:
            ar_suffix = m_ar.group(0).rstrip()
            final_prompt = final_prompt[:m_ar.start()].rstrip(", ")

        if overlay_text.lower() not in final_prompt.lower():
            final_prompt = (
                final_prompt.rstrip(". ,") +
                f', with bold large text overlay reading exactly "{overlay_text}" '
                "placed in the negative space, high-contrast readable typography, "
                "text fully visible and not obstructed"
            )

        final_prompt = final_prompt.rstrip(", ") + (ar_suffix or "")

    if "--ar" not in final_prompt:
        final_prompt = final_prompt.rstrip(", ") + " --ar 16:9"

    return {
        "prompt": final_prompt,
        "composition_note": str(data.get("composition_note") or "").strip(),
        "used_image": has_image,
        "used_profile": bool(profile_name or char_style or bg_style or scene_style),
        "overlay_text": overlay_text,
        "structure_used": {
            "image_position": _img_pos,
            "text_style": _txt_sty,
            "color_emotion": _col_emo,
        },
    }
