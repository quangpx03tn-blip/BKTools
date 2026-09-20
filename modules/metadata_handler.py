import json
import os
from . import ai_client


# Lấy theo model đang cấu hình trong ai_client (biến SHOPAIKEY_MODEL),
# để đổi model một chỗ là toàn hệ thống đổi theo — tránh tình trạng
# key chỉ bán Claude nhưng handler vẫn gọi gemini-2.5-flash.
# Tác vụ ngắn, có khuôn mẫu (mô tả 30-60 từ, tách scene, gán asset) ->
# dùng model NHANH. Nếu key không bán model này, ai_client tự chuyển
# sang model dự phòng nên không bao giờ lỗi model_not_found.
DEFAULT_MODEL = ai_client.MODEL_FAST
METADATA_MAX_OUTPUT_TOKENS = 4096


class VideoMetadataHandler:
    """
    Tool 6 — Video Metadata & SEO Optimizer
    - Nhận tiêu đề kịch bản (script title) từ người dùng copy từ Tool 1.
    - Tạo bộ metadata hoàn chỉnh: mô tả video, keywords, tags, CTA, hashtags.
    - Tối ưu cho YouTube/TikTok/Instagram với từ khóa SEO thông minh.
    - Không tự điền mặc định; dùng đúng nội dung người dùng cung cấp.
    """

    def __init__(self, api_key=None, default_model=DEFAULT_MODEL):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        if not self.api_key:
            raise ValueError("Chưa cấu hình API Key!")
        self.default_model = default_model

    @staticmethod
    def _generate_fallback_metadata(title, channel_desc="", video_topic=""):
        """Fallback metadata nếu AI không phản hồi"""
        keywords = []
        if title:
            words = title.split()[:5]
            keywords.extend(words)
        if video_topic:
            keywords.append(video_topic)

        description = f"Tiêu đề: {title}\n"
        if channel_desc:
            description += f"Kênh: {channel_desc}\n"
        description += "\nXem video đầy đủ để hiểu rõ chi tiết."

        tags = ", ".join(keywords[:10]) if keywords else "video, content"
        hashtags = " ".join([f"#{w.replace(' ', '')}" for w in keywords[:8]]) if keywords else "#video #content"

        cta = "Đăng ký kênh để xem thêm nội dung!"

        return {
            "description": description,
            "keywords": tags,
            "hashtags": hashtags,
            "cta": cta,
            "short_title": title[:60] if title else "",
            "long_title": title[:100] if title else ""
        }

    def generate_metadata(self, script_title: str, channel_desc: str = "", video_topic: str = "") -> dict:
        """
        Tạo metadata từ tiêu đề kịch bản.

        Args:
            script_title: Tiêu đề kịch bản (bắt buộc)
            channel_desc: Mô tả kênh (tùy chọn)
            video_topic: Chủ đề video (tùy chọn)

        Returns:
            Dict chứa: description, keywords, hashtags, cta, short_title, long_title
        """
        script_title = (script_title or "").strip()
        channel_desc = (channel_desc or "").strip()
        video_topic = (video_topic or "").strip()

        if not script_title:
            raise ValueError("Vui lòng nhập hoặc dán tiêu đề kịch bản trước khi tạo Metadata.")

        prompt = f"""
[SYSTEM ROLE]
You are a professional video SEO expert and content strategist for YouTube, TikTok, and Instagram.

[TASK]
Generate a complete, optimized metadata package for a video based on the script title provided by the user.

[USER-PROVIDED INFORMATION]
SCRIPT TITLE: {script_title}
CHANNEL DESCRIPTION: {channel_desc if channel_desc else "(not provided)"}
VIDEO TOPIC: {video_topic if video_topic else "(not provided)"}

[GENERATE - EACH SECTION IN EXACT FORMAT]

1. SHORT TITLE (For YouTube Shorts, Instagram Reels — max 60 chars):
[EXACT SHORT TITLE HERE]

2. LONG TITLE (For YouTube full video — max 100 chars, SEO-optimized):
[EXACT LONG TITLE HERE]

3. VIDEO DESCRIPTION (2-4 sentences, natural, engaging, with 2-3 keywords):
[EXACT DESCRIPTION HERE]

4. KEYWORDS (10 comma-separated keywords for SEO, most relevant first):
[KEYWORD1, KEYWORD2, KEYWORD3, ...]

5. HASHTAGS (8-10 hashtags for Instagram/TikTok, trending-aware):
#HASHTAG1 #HASHTAG2 #HASHTAG3 ...

6. CALL-TO-ACTION (1 sentence, clear, action-oriented):
[EXACT CTA HERE]

[CONSTRAINTS]
- Keep all text in Vietnamese unless the original title is in English.
- Make keywords specific to the content, not generic.
- Hashtags must be trending or contextually relevant.
- CTA should encourage subscription, sharing, or engagement.
- Do not add markdown or extra formatting.
- Return raw text only.
"""

        try:
            raw_text = ai_client.generate_content(
                api_key=self.api_key,
                prompt=prompt,
                system_prompt="Generate only the raw metadata sections in the exact format requested. No markdown, no extra text.",
                shop_model=self.default_model,
                gemini_model=self.default_model,
                temperature=0.65,
                max_output_tokens=METADATA_MAX_OUTPUT_TOKENS,
                timeout=300
            )

            raw_text = (raw_text or "").strip()
            if "```" in raw_text:
                raw_text = "\n".join(line for line in raw_text.splitlines() if not line.strip().startswith("```"))
                raw_text = raw_text.strip()

            # Parse sections
            result = self._parse_metadata_response(raw_text)

            # Fallback nếu parse không tìm được sections
            if not result.get("description") or not result.get("keywords"):
                result = self._generate_fallback_metadata(script_title, channel_desc, video_topic)

            return {
                "status": "success",
                "data": result
            }

        except Exception as e:
            print(f"[!] Lỗi khi gen metadata: {e}")
            raise e

    @staticmethod
    def _parse_metadata_response(raw_text):
        """Parse phản hồi từ AI thành các section metadata"""
        lines = raw_text.split('\n')
        result = {
            "short_title": "",
            "long_title": "",
            "description": "",
            "keywords": "",
            "hashtags": "",
            "cta": ""
        }

        current_section = None
        section_content = []

        for line in lines:
            line = line.strip()

            if "SHORT TITLE" in line.upper() and "[" in line:
                current_section = "short_title"
                section_content = []
            elif "LONG TITLE" in line.upper() and "[" in line:
                current_section = "long_title"
                section_content = []
            elif "VIDEO DESCRIPTION" in line.upper() and "[" in line:
                current_section = "description"
                section_content = []
            elif "KEYWORDS" in line.upper() and "[" in line:
                current_section = "keywords"
                section_content = []
            elif "HASHTAGS" in line.upper() and "#" in line:
                current_section = "hashtags"
                section_content = []
            elif "CALL-TO-ACTION" in line.upper() and "[" in line:
                current_section = "cta"
                section_content = []
            elif line and current_section and not line.startswith("["):
                section_content.append(line)
            elif line.startswith("[EXACT") or line.startswith("[") and line.endswith("]"):
                # End of section marker
                if current_section and section_content:
                    result[current_section] = " ".join(section_content).strip()
                current_section = None
                section_content = []

        # Collect last section
        if current_section and section_content:
            result[current_section] = " ".join(section_content).strip()

        # Clean up brackets
        for key in result:
            result[key] = result[key].replace("[", "").replace("]", "").strip()

        return result
