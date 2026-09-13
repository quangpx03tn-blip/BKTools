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


def process_topics(ngach_kenh, so_topics, ngon_ngu, focus, yeu_cau_bo_sung="", style_guide="", dna="", topic_bank=""):
    api_key = _load_api_key_from_env_file()

    if not api_key:
        raise ValueError("Chưa cấu hình API Key!")

    prompt = f"""
    Bạn là một chuyên gia sáng tạo nội dung YouTube hàng đầu. Hãy dựa vào thông tin dưới đây để tạo ra chính xác {so_topics} chủ đề (topics) video cực kỳ thu hút.

    --- QUY TẮC BẮT BUỘC VỀ NGÔN NGỮ ---
    - Ngôn ngữ đầu ra (Output Language): BẮT BUỘC TOÀN BỘ nội dung tiêu đề (title_main, titles_list), góc độ (angle_doc_bao), câu mở đầu (hook_sentence) và tags phải được viết hoàn toàn bằng: {ngon_ngu}. 
    - Tuyệt đối không được pha trộn ngôn ngữ khác (trừ khi là tên riêng hoặc từ khóa kỹ thuật). Toàn bộ kết quả trả về phải bằng chính xác ngôn ngữ này.

    --- THÔNG TIN CẤU HÌNH ---
    - Ngách kênh: {ngach_kenh}
    - Số lượng topics yêu cầu: {so_topics}
    - Ngôn ngữ đầu ra: {ngon_ngu}
    - Tiêu chí ưu tiên (Focus): {focus}
    - Yêu cầu bổ sung: {yeu_cau_bo_sung if yeu_cau_bo_sung else 'Không có'}

    --- TÀI LIỆU GỐC ---
    [STYLE GUIDE]: {style_guide}
    [DNA KÊNH]: {dna}
    [TOPIC BANK]: {topic_bank}

    --- YÊU CẦU ĐỊNH DẠNG ---
    Trả về ĐÚNG MỘT đối tượng JSON thuần túy (không kèm markdown như ```json) có cấu trúc:
    {{
      "topics": [
        {{
          "id": "01",
          "title_main": "Tiêu đề chính hook cực mạnh (Bằng ngôn ngữ {ngon_ngu})",
          "ctr_badge": "HIGH",
          "easy_badge": "EASY",
          "titles_list": [
            {{"title": "Tiêu đề lựa chọn 1 (Bằng ngôn ngữ {ngon_ngu})", "formula": "Formula A — Mở Tầng"}},
            {{"title": "Tiêu đề lựa chọn 2 (Bằng ngôn ngữ {ngon_ngu})", "formula": "Formula B — Khoảnh Khắc Vỡ Lẽ"}},
            {{"title": "Tiêu đề lựa chọn 3 (Bằng ngôn ngữ {ngon_ngu})", "formula": "Formula D — Một Sang Tính Ra"}}
          ],
          "angle_doc_bao": "Phân tích góc độ độc đáo bằng ngôn ngữ {ngon_ngu}...",
          "hook_sentence": "Câu mở đầu video cực cuốn bằng ngôn ngữ {ngon_ngu}...",
          "tags": ["tag1", "tag2"]
        }}
      ]
    }}
    """

    try:
        raw_text = ai_client.generate_content(
            api_key=api_key,
            prompt=prompt,
            system_prompt="You are a helpful assistant designed to output JSON.",
            json_mode=True,
            temperature=0.7
        )

        # Loại bỏ các ký tự markdown (```json ... ```) nếu AI lỡ trả kèm theo
        raw_text = ai_client.clean_json_text(raw_text)

        parsed_data = json.loads(raw_text)

        if isinstance(parsed_data, dict) and "topics" in parsed_data:
            return parsed_data["topics"]
        elif isinstance(parsed_data, list):
            return parsed_data
        return []

    except Exception as e:
        print(f"❌ Lỗi tạo topics: {str(e)}")
        raise e