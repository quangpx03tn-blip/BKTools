import os
import glob
import time
from google import genai
from google.genai import types
from . import ai_client
from .direct_script_writer import DirectScriptWriter, DEFAULT_MODEL


class ResearchScriptWriter:
    def __init__(self, api_key=None, default_model=DEFAULT_MODEL):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        self.client = genai.Client(api_key=self.api_key) if (self.api_key and not self.api_key.startswith("sk-")) else None
        self.default_model = default_model

    def read_project_markdowns(self, project_dir):
        result = {
            "style_guide": "",
            "dna": "",
            "topic_bank": "",
            "other": "",
            "extracted_headers": []
        }

        if not project_dir or not os.path.exists(project_dir):
            return result

        md_files = glob.glob(os.path.join(project_dir, "*.md"))
        for file_path in md_files:
            file_name = os.path.basename(file_path)
            lower_name = file_name.lower()
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    file_text = "".join(lines)
                    block = f"\n\n--- [FILE: {file_name}] ---\n{file_text[:3000]}"
                    if "style" in lower_name:
                        result["style_guide"] += block
                    elif "dna" in lower_name:
                        result["dna"] += block
                    elif "topic" in lower_name or "bank" in lower_name:
                        result["topic_bank"] += block
                    else:
                        result["other"] += block
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith("#"):
                            result["extracted_headers"].append({
                                "file": file_name,
                                "header": stripped
                            })
            except Exception as e:
                print(f"[!] Lỗi khi đọc file {file_name}: {e}")
        return result

    def _generate_research(self, prompt):
        max_retries = 3
        delay = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                if self.api_key.startswith("sk-"):
                    return ai_client.generate_content(
                        api_key=self.api_key,
                        prompt=prompt,
                        shop_model=self.default_model,
                        temperature=0.7,
                        max_output_tokens=8192,
                        timeout=300
                    )

                if not self.client:
                    raise ValueError("Chưa cấu hình API Key hợp lệ!")

                response = self.client.models.generate_content(
                    model=self.default_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=8192,
                        tools=[types.Tool(google_search=types.GoogleSearch())]
                    )
                )
                return response.text
            except Exception as e:
                last_error = e
                error_str = str(e)
                if ("429" in error_str or "RESOURCE_EXHAUSTED" in error_str
                        or "503" in error_str or "UNAVAILABLE" in error_str):
                    if attempt < max_retries - 1:
                        print(f"[!] Gặp lỗi quá tải (429/503), đang thử lại lần {attempt + 1} sau {delay} giây...")
                        time.sleep(delay)
                        delay *= 2
                        continue
                    if self.client:
                        try:
                            response = self.client.models.generate_content(
                                model=self.default_model,
                                contents=prompt,
                                config=types.GenerateContentConfig(
                                    temperature=0.7,
                                    max_output_tokens=8192
                                )
                            )
                            return response.text
                        except Exception as e2:
                            last_error = e2
                raise last_error

        raise RuntimeError(f"Không thể nhận phản hồi từ API sau nhiều lần thử. Lỗi cuối: {last_error}")

    def execute_api_research_and_write(self, topic, project_dir, profile_id=None, options=None):
        if not self.api_key:
            raise ValueError("Chưa cấu hình API Key hợp lệ!")

        options = options or {}
        language = options.get("ngon_ngu", "Tiếng Việt")
        structure = options.get("cau_truc", "Levels — Escalation (POV)")
        sections = options.get("so_phan", "12")
        target_minutes = options.get("target_phut", 15)
        pov_style = options.get("pov_style", "Ngôi thứ 2 (Bạn)")
        context = options.get("context", "")
        md_data = self.read_project_markdowns(project_dir)

        research_prompt = f"""
Bạn là chuyên gia research nội dung YouTube. Hãy nghiên cứu và phân tích sâu chủ đề sau để làm nguồn dữ liệu viết kịch bản voice-over dài.

CHỦ ĐỀ GỐC: "{topic}"

[THÔNG SỐ KỊCH BẢN SẼ VIẾT SAU RESEARCH]
- Ngôn ngữ output bắt buộc: {language}
- Cấu trúc bắt buộc: {structure}
- Số phần bắt buộc: {sections}
- Thời lượng mục tiêu: {target_minutes} phút
- POV style bắt buộc: {pov_style}
- Context bổ sung: {context if context else "Không có"}

[STYLE GUIDE NỘI BỘ KÊNH]
{md_data["style_guide"] if md_data["style_guide"] else "Không có Style Guide riêng."}

[DNA KÊNH]
{md_data["dna"] if md_data["dna"] else "Không có DNA kênh riêng."}

[TOPIC BANK THAM KHẢO]
{md_data["topic_bank"] if md_data["topic_bank"] else "Không có Topic Bank tham khảo."}

Yêu cầu research:
1. Phân tích ý nghĩa thật sự của tiêu đề và góc nhìn độc đáo nhất.
2. Thu thập các sự kiện, bối cảnh, chi tiết, ví dụ, nhân vật, mâu thuẫn và diễn biến quan trọng liên quan trực tiếp.
3. Chỉ giữ thông tin có thể chuyển hóa thành lời kể voice-over hấp dẫn.
4. Sắp xếp dữ liệu theo đúng hướng cấu trúc {structure} và {sections} phần.
5. Trả về báo cáo research chi tiết, có đủ chất liệu để viết script {target_minutes} phút.
"""

        research_text = self._generate_research(research_prompt)

        writer_options = dict(options)
        writer_options["research_data"] = research_text
        writer = DirectScriptWriter(api_key=self.api_key)
        result = writer.execute_direct_write(
            topic=topic,
            project_dir=project_dir,
            profile_id=profile_id,
            options=writer_options
        )
        result["research_summary"] = research_text
        return result
