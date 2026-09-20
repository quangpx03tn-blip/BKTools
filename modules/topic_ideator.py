import os
import json
from modules import ai_client


def _load_api_key_from_env_file():
    """
    Đọc GEMINI_API_KEY từ file .env nếu có, fallback sang biến môi trường.

    Chỉ dùng làm PHƯƠNG ÁN DỰ PHÒNG khi giao diện không gửi key lên.
    Trên server (Railway) không có file .env, và mỗi người dùng nhập key
    riêng ở sidebar — nên key từ giao diện phải được ưu tiên.
    """
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


def _build_prompt(ngach_kenh, so_topics, ngon_ngu, focus, yeu_cau_bo_sung,
                  style_guide, dna, topic_bank, goc_rieng=""):
    """Dựng prompt cho MỘT lô topics. Tách riêng để gọi song song nhiều lô."""
    goc_block = ""
    if goc_rieng:
        goc_block = f"""
    --- GÓC NHÌN RIÊNG CHO LÔ NÀY (để không trùng với lô khác) ---
    {goc_rieng}
    """

    return f"""
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
{goc_block}
    --- TÀI LIỆU GỐC ---
    [STYLE GUIDE]: {style_guide}
    [DNA KÊNH]: {dna}
    [TOPIC BANK]: {topic_bank}

    --- GIỚI HẠN ĐỘ DÀI (BẮT BUỘC — để trả kết quả nhanh) ---
    - angle_doc_bao: TỐI ĐA 2 câu. Không phân tích dài dòng.
    - hook_sentence: TỐI ĐA 1 câu.
    - tags: đúng 5 tag, mỗi tag 1-3 từ.
    - Không viết lời dẫn, không giải thích thêm ngoài JSON.

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


# Mỗi lô tối đa ngần này topic. Thời gian gọi AI tỷ lệ thuận với số chữ
# phải sinh, nên lô nhỏ = mỗi lời gọi nhanh hơn hẳn.
TOPICS_PER_BATCH = 5

# Các góc nhìn khác nhau cho từng lô, để topic giữa các lô không trùng nhau.
BATCH_ANGLES = [
    "Khai thác góc CON SỐ và DỮ LIỆU gây sốc: thống kê, so sánh, thứ hạng.",
    "Khai thác góc CON NGƯỜI và CÂU CHUYỆN: nhân vật, bi kịch, nghịch lý cá nhân.",
    "Khai thác góc BÍ MẬT và VẠCH TRẦN: điều bị giấu, hậu trường, sự thật ít biết.",
    "Khai thác góc TƯƠNG LAI và HỆ QUẢ: điều sắp xảy ra, rủi ro, cơ hội.",
]


def process_topics(ngach_kenh, so_topics, ngon_ngu, focus, yeu_cau_bo_sung="",
                   style_guide="", dna="", topic_bank="", api_key=""):
    # Ưu tiên key người dùng nhập ở sidebar; chỉ rơi về .env khi không có.
    # Trước đây module này CHỈ đọc .env nên trên web luôn dùng key cũ/rỗng,
    # gây lỗi 401 dù các tool khác vẫn chạy bình thường.
    api_key = (api_key or "").strip() or _load_api_key_from_env_file()

    if not api_key:
        raise ValueError("Chưa cấu hình API Key!")

    try:
        total = max(1, int(so_topics))
    except (TypeError, ValueError):
        total = 5

    # Chia thành các lô nhỏ rồi gọi SONG SONG. 10 topic trước đây là một lời
    # gọi ~100s; nay thành 2 lô chạy cùng lúc nên tổng chỉ còn ~45s.
    batches = []
    remaining = total
    i = 0
    while remaining > 0:
        n = min(TOPICS_PER_BATCH, remaining)
        batches.append((n, BATCH_ANGLES[i % len(BATCH_ANGLES)]))
        remaining -= n
        i += 1

    def run_batch(args):
        n, goc = args
        prompt = _build_prompt(ngach_kenh, n, ngon_ngu, focus, yeu_cau_bo_sung,
                               style_guide, dna, topic_bank, goc)
        raw_text = ai_client.generate_content(
            api_key=api_key,
            prompt=prompt,
            # Cấm mở đầu bằng lời dẫn: mỗi câu thừa là thêm thời gian chờ,
            # và model hay dẫn dắt trước khi vào JSON.
            system_prompt=(
                "You output raw JSON only. No preamble, no explanation, "
                "no markdown fences. Start your reply with { immediately."
            ),
            json_mode=True,
            temperature=0.7,
            # Mặc định của ai_client chỉ 60s — Claude sinh nội dung dài thường vượt ngưỡng này.
            timeout=180,
        )
        raw_text = ai_client.clean_json_text(raw_text)
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict) and "topics" in parsed:
            return parsed["topics"]
        if isinstance(parsed, list):
            return parsed
        return []

    if len(batches) == 1:
        all_topics = run_batch(batches[0])
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(batches)) as ex:
            results = list(ex.map(run_batch, batches))
        all_topics = [t for part in results for t in part]

    # Đánh số lại liên tục vì mỗi lô tự đánh từ 01
    for idx, t in enumerate(all_topics, 1):
        if isinstance(t, dict):
            t["id"] = f"{idx:02d}"

    if not all_topics:
        raise RuntimeError("AI không trả về topic nào hợp lệ.")

    return all_topics[:total]