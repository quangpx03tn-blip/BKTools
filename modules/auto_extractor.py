import os
import json
from modules import ai_client


def _load_api_key_from_env_file():
    """Đọc GEMINI_API_KEY từ file .env nếu có, fallback sang biến môi trường."""
    api_key = ""
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('GEMINI_API_KEY='):
                    api_key = line.strip().split('=', 1)[1]
                    break
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")
    return api_key


def extract_from_files(style_guide="", dna="", topic_bank="", api_key=""):
    """
    Sử dụng AI (ShopAIKey "sk-" hoặc Gemini gốc) để phân tích 3 file cốt lõi
    (Style Guide, DNA Kênh, Topic Bank) và tự động trích xuất các thông số
    cấu hình profile kênh.
    """
    api_key = (api_key or "").strip() or _load_api_key_from_env_file()

    if not api_key:
        raise ValueError("Chưa cấu hình API Key! Vui lòng nhập API Key ở sidebar.")

    prompt = f"""
    Bạn là một chuyên gia phân tích hệ thống dữ liệu YouTube. Hãy đọc và phân tích kỹ nội dung từ 3 tài liệu cốt lõi của kênh dưới đây để trích xuất ra các thông số cấu hình chuẩn xác dưới dạng JSON.

    --- TÀI LIỆU KÊNH ---
    [STYLE GUIDE]:
    {style_guide}

    [DNA KÊNH]:
    {dna}

    [TOPIC BANK]:
    {topic_bank}

    --- YÊU CẦU ĐỊNH DẠNG JSON TRẢ VỀ ---
    Trả về ĐÚNG MỘT đối tượng JSON thuần túy (không kèm mã markdown ```json) với các trường sau:
    - ten_kenh: Tên kênh trích xuất được (nếu không có, đặt tên mặc định ngắn gọn).
    - ngach: Ngách chủ đề chính của kênh.
    - visual: Phong cách hình ảnh (Visual style).
    - ngon_ngu: Ngôn ngữ chính.
    - pov: Góc nhìn (POV style).
    - cuc_truc: Cấu trúc kịch bản.
    - so_phan: Số phần tiêu chuẩn (dạng số hoặc chuỗi).
    - target_phut: Thời lượng phút mục tiêu (dạng số).
    - char_style: Prompt mô tả character style.
    - bg_style: Prompt mô tả background style.
    - scene_style: Prompt mô tả scene style / aesthetic (~40 từ).
    - style_ref: Prompt tham chiếu visual style reference sheet.
    """

    try:
        raw_text = ai_client.generate_content(
            api_key=api_key,
            prompt=prompt,
            system_prompt="You are a helpful assistant designed to output JSON.",
            json_mode=True,
            temperature=0.3
        )

        raw_text = ai_client.clean_json_text(raw_text)
        return json.loads(raw_text)

    except Exception as e:
        print(f"Lỗi Auto Extract: {str(e)}")
        raise e
