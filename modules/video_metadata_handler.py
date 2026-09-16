import json
import os
import re
from . import ai_client


# Lấy theo model đang cấu hình trong ai_client (biến SHOPAIKEY_MODEL),
# để đổi model một chỗ là toàn hệ thống đổi theo — tránh tình trạng
# key chỉ bán Claude nhưng handler vẫn gọi gemini-2.5-flash.
DEFAULT_MODEL = ai_client.SHOPAIKEY_MODEL
METADATA_MAX_OUTPUT_TOKENS = 8192

TONE_GUIDES = {
    "phat-phap": "Giọng văn nhẹ nhàng, sâu lắng, gần gũi như đang tâm sự với một người bạn. Tuyệt đối không giáo điều, không phán xét, không dùng giọng dạy đời.",
    "doi-thuong": "Giọng văn chân thật, gần gũi, như đang kể lại một câu chuyện đời thường cho bạn bè nghe. Tự nhiên, không màu mè.",
    "lich-su": "Giọng văn cuốn hút, giàu chi tiết, gợi không khí hào hùng hoặc bí ẩn của lịch sử, nhưng vẫn chính xác và tôn trọng sự thật.",
    "truyen-cam-hung": "Giọng văn tích cực, mạnh mẽ, tạo động lực, nhưng không sáo rỗng hay hô khẩu hiệu.",
    "khac": "Giọng văn trung tính, rõ ràng, chuyên nghiệp, phù hợp với nội dung phổ thông."
}


def _fallback_metadata(subject, summary, keyword, cta):
    short_subject = (subject or summary or "Nội dung video").strip()[:60] or "Nội dung video"
    kw = (keyword or short_subject.split(",")[0].strip()).strip()[:30]
    cta_line = (cta or "Để lại cảm nghĩ của bạn ở phần bình luận và theo dõi kênh để không bỏ lỡ nội dung tiếp theo.").strip()

    titles = [
        short_subject[:100],
        f"{short_subject[:70]} — góc nhìn mới"[:100],
        f"{short_subject[:40]} | Đừng bỏ lỡ"[:100]
    ]
    description = (
        f"{summary[:220].strip() or short_subject.strip()}.\n"
        f"📌 Từ khóa: {kw}\n"
        f"{cta_line}"
    )
    tags = " ".join([
        "#Video",
        f"#{re.sub(r'[^\\wÀ-ỹ_]', '', kw.split()[0] or 'NoiDung')[:18]}",
        "#YouTube",
        "#KiếnThức",
        "#KhámPhá"
    ])

    return {
        "titles": titles,
        "description": description,
        "tags": tags,
        "tip": "Thêm một từ khóa dài chính xác trong 3 giây đầu mô tả để tăng khả năng đề xuất."
    }


def generate_metadata(subject, summary, keyword, cta, tone, api_key, output_language="Vietnamese"):
    api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("Chưa cấu hình API Key!")

    subject = (subject or "").strip()
    summary = (summary or "").strip()
    keyword = (keyword or "").strip()
    cta = (cta or "").strip()
    tone_guide = TONE_GUIDES.get(tone, TONE_GUIDES["khac"])
    output_language = (output_language or "Vietnamese").strip()

    if not subject and not summary:
        raise ValueError("Hãy nhập ít nhất Chủ đề hoặc Tóm tắt nội dung.")

    lang_instruction = {
        "Vietnamese": "tiếng Việt",
        "English": "tiếng Anh",
        "Chinese": "tiếng Trung (Simplified)",
        "Korean": "tiếng Hàn",
        "Thai": "tiếng Thái",
        "Indonesian": "tiếng Indonesia",
        "Spanish": "tiếng Tây Ban Nha",
        "French": "tiếng Pháp",
        "German": "tiếng Đức",
        "Japanese": "tiếng Nhật"
    }.get(output_language, "tiếng Việt")

    prompt = f"""
[SYSTEM ROLE]
Bạn là chuyên gia SEO YouTube {lang_instruction}, hiểu sâu thuật toán đề xuất và tâm lý người xem.
Nhiệm vụ: đọc kỹ CHỦ ĐỀ VÀ TÓM TẮT KỊCH BẢN (thường là tiêu đề kịch bản người dùng copy thủ công), sau đó tạo metadata hoàn chỉnh, sát nội dung thật — tuyệt đối không dùng công thức chung chung.
Toàn bộ đầu ra PHẢI bằng {lang_instruction}.

[THÔNG TIN ĐẦU VÀO]
CHỦ ĐỀ / TÊN NHÂN VẬT CHÍNH (tiêu đề kịch bản người dùng dán vào):
{subject or "(không có, hãy dựa vào tóm tắt)"}

TÓM TẮT / KỊCH BẢN GỐC (người dùng dán thủ công):
{summary[:4000] or "(không có, hãy dựa vào chủ đề)"}

TỪ KHÓA CHÍNH (PRIMARY KEYWORD):
{keyword or "(để trống — hãy tự đề xuất 2-3 từ khóa SEO phù hợp nhất)"}

KÊNH / CALL-TO-ACTION MẶC ĐỊNH:
{cta or "(để trống — hãy tự viết câu kêu gọi nhẹ nhàng phù hợp giọng văn, không bịa tên kênh cụ thể)"}

TÔNG GIỌNG YÊU CẦU:
{tone_guide}

[YÊU CẦU OUTPUT]
1. TIÊU ĐỀ YOUTUBE: tạo đúng 3 phương án, mỗi tiêu đề dưới 100 ký tự, hấp dẫn, đúng trọng tâm nội dung, mỗi phương án khai thác một góc nhìn khác.
2. MÔ TẢ (DESCRIPTION): 3-5 câu bằng đúng giọng văn yêu cầu, sau đó xuống dòng "📌 Từ khóa: ...", rồi câu call-to-action. Dùng \\n để xuống dòng.
3. TAGS: 4-8 hashtag liên quan sát chủ đề, cách nhau bởi khoảng trắng.
4. TIP: 1 câu SEO Coach dưới 25 từ giúp người dùng cải thiện SEO.

[ĐỊNH DẠNG — CHỈ TRẢ VỀ JSON THUẦN, KHÔNG MARKDOWN, KHÔNG GIẢI THÍCH THÊM]
{{
  "titles": ["tiêu đề 1", "tiêu đề 2", "tiêu đề 3"],
  "description": "3-5 câu mô tả...\\n📌 Từ khóa: ...\\n<call-to-action>",
  "tags": "#tag1 #tag2 #tag3",
  "tip": "Gợi ý SEO Coach..."
}}
"""

    try:
        raw_text = ai_client.generate_content(
            api_key=api_key,
            prompt=prompt,
            system_prompt="Bạn là chuyên gia SEO YouTube tiếng Việt. Chỉ trả về JSON thuần, không markdown.",
            shop_model=DEFAULT_MODEL,
            gemini_model=DEFAULT_MODEL,
            json_mode=True,
            temperature=0.55,
            max_output_tokens=METADATA_MAX_OUTPUT_TOKENS,
            timeout=300
        )

        text = ai_client.clean_json_text(raw_text)
        data = json.loads(text)

        titles = data.get("titles") or ([data.get("title")] if data.get("title") else [])
        titles = [str(x).strip() for x in titles if str(x).strip()][:3]
        if not titles:
            titles = [subject[:100] if subject else summary[:100]]

        return {
            "titles": titles,
            "description": (data.get("description") or "").strip(),
            "tags": (data.get("tags") or "").strip(),
            "tip": (data.get("tip") or "").strip()
        }

    except Exception as e:
        print(f"[!] Lỗi generate metadata, dùng fallback cục bộ: {e}")
        return _fallback_metadata(subject, summary, keyword, cta)
