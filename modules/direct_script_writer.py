import os
import glob
import json
import re
import time
from . import ai_client
from . import profile_manager

# Tốc độ đọc voice-over trung bình (~155 từ/phút), khớp với công thức hiển thị trên giao diện
WORDS_PER_MINUTE = 155
# Lấy theo model đang cấu hình trong ai_client (biến SHOPAIKEY_MODEL),
# để đổi model một chỗ là toàn hệ thống đổi theo — tránh tình trạng
# key chỉ bán Claude nhưng handler vẫn gọi gemini-2.5-flash.
DEFAULT_MODEL = ai_client.SHOPAIKEY_MODEL
SECTION_MAX_OUTPUT_TOKENS = 8192


class DirectScriptWriter:
    def __init__(self, api_key=None):
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()

    def read_project_files(self, project_dir):
        result = {
            "style_guide": "",
            "dna": "",
            "topic_bank": "",
            "other": "",
            "file_list": []
        }

        if not project_dir or not os.path.exists(project_dir):
            return result

        all_files = glob.glob(os.path.join(project_dir, "*.*"))

        for file_path in all_files:
            file_name = os.path.basename(file_path)
            result["file_list"].append(file_name)
            lower_name = file_name.lower()

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    file_text = f.read()
            except Exception as e:
                print(f"[!] Lỗi khi đọc file {file_name}: {e}")
                continue

            block = f"\n\n==================== [FILE: {file_name}] ====================\n{file_text}"

            if "style" in lower_name:
                result["style_guide"] += block
            elif "dna" in lower_name:
                result["dna"] += block
            elif "topic" in lower_name or "bank" in lower_name:
                result["topic_bank"] += block
            else:
                result["other"] += block

        return result

    # ------------------------------------------------------------------
    # CÁC HÀM TIỆN ÍCH CHO LOGIC VIẾT DÀI THEO TỪNG PHẦN
    # ------------------------------------------------------------------

    @staticmethod
    def _count_words(text):
        return len((text or "").split())

    @staticmethod
    def _parse_minutes(target_minutes):
        try:
            minutes = float(str(target_minutes).replace(",", "."))
            if minutes <= 0:
                minutes = 10
        except (TypeError, ValueError):
            minutes = 10
        return minutes

    @staticmethod
    def _parse_section_count(sections):
        match = re.search(r"\d+", str(sections or ""))
        if not match:
            return None
        n = int(match.group(0))
        return n if 1 <= n <= 20 else None

    def _generate_once(self, prompt, temperature=0.7, max_output_tokens=SECTION_MAX_OUTPUT_TOKENS):
        """Gọi AI 1 lần (tự nhận diện sk- / Gemini), có retry khi quá tải 429/503."""
        max_retries = 3
        delay = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                return ai_client.generate_content(
                    api_key=self.api_key,
                    prompt=prompt,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    timeout=300
                )
            except Exception as e:
                last_error = e
                error_str = str(e)
                if ("429" in error_str or "RESOURCE_EXHAUSTED" in error_str
                        or "503" in error_str or "UNAVAILABLE" in error_str):
                    if attempt < max_retries - 1:
                        print(f"[!] Quá tải (429/503), thử lại lần {attempt + 1} sau {delay}s...")
                        time.sleep(delay)
                        delay *= 2
                        continue
                raise e

        raise RuntimeError(f"Không nhận được phản hồi từ AI. Lỗi cuối: {last_error}")

    def _build_context_block(self, topic, project_data, profile_data, source_material_section,
                             language, structure, pov_style, context):
        return f"""
CHỦ ĐỀ VIDEO: {topic}

{source_material_section}

--- [STYLE GUIDE — BẮT BUỘC TUÂN THỦ VĂN PHONG, GIỌNG ĐIỆU, CÁCH HÀNH VĂN] ---
{project_data["style_guide"] if project_data["style_guide"] else "Không có Style Guide riêng, hãy dùng văn phong chuyên nghiệp, tự nhiên, phù hợp YouTube."}

--- [DNA KÊNH — BẮT BUỘC GIỮ ĐÚNG BẢN SẮC, GIÁ TRỊ CỐT LÕI VÀ CÁ TÍNH CỦA KÊNH] ---
{project_data["dna"] if project_data["dna"] else "Không có DNA kênh riêng, hãy giữ giọng điệu trung lập, đáng tin cậy."}

--- [TOPIC BANK — CHỈ THAM KHẢO PHONG CÁCH, TUYỆT ĐỐI KHÔNG SAO CHÉP NỘI DUNG CŨ] ---
{project_data["topic_bank"] if project_data["topic_bank"] else "Không có Topic Bank tham khảo."}

--- [TÀI LIỆU BỔ SUNG KHÁC (nếu có)] ---
{project_data["other"] if project_data["other"] else "Không có tài liệu bổ sung."}

PROFILE / STYLE KÊNH (dữ liệu cấu hình): {json.dumps(profile_data, ensure_ascii=False)}

[THÔNG SỐ BẮT BUỘC ÁP DỤNG CHO MỌI ĐOẠN VIẾT]
- NGÔN NGỮ OUTPUT: "{language}" — toàn bộ lời kịch bản phải bằng đúng ngôn ngữ này, không pha ngôn ngữ khác.
- CẤU TRÚC: "{structure}".
- POV STYLE: "{pov_style}" — giữ đúng ngôi kể/góc nhìn này nhất quán từ đầu đến cuối.
- CONTEXT BỔ SUNG: {context if context else "Không có"}
"""

    def _build_outline(self, context_block, n_sections, total_words):
        """Bước 1: xin AI một dàn ý ngắn gọn để các phần sau bám sát, tránh lặp ý."""
        prompt = f"""
{context_block}

Nhiệm vụ: Lập DÀN Ý cho kịch bản voice-over {n_sections} phần (tổng khoảng {total_words} từ).
Với mỗi phần, ghi đúng 1 dòng theo mẫu:
PHẦN {1}: <tên phần> — <trọng tâm 1 câu + 2-3 ý chính sẽ triển khai>
...đến PHẦN {n_sections}.
Chỉ trả về dàn ý, không viết kịch bản, không thêm lời thừa.
"""
        try:
            return self._generate_once(prompt, temperature=0.5, max_output_tokens=2048)
        except Exception as e:
            print(f"[!] Không tạo được dàn ý, sẽ viết không dàn ý: {e}")
            return ""

    @staticmethod
    def _outline_for_section(outline, index):
        if not outline:
            return ""
        lines = [ln.strip() for ln in outline.splitlines() if ln.strip()]
        for ln in lines:
            if re.match(rf"^(PHẦN|PART)\s*{index}\b", ln, re.IGNORECASE):
                return ln
        return ""

    def _write_one_section(self, context_block, outline, index, n_sections,
                           per_section_words, previous_tail, next_heading):
        """Viết đúng 1 phần; nếu thiếu từ thì gọi AI viết tiếp cho đủ."""
        min_words = int(per_section_words * 0.9)
        section_focus = self._outline_for_section(outline, index)

        continuity = ""
        if previous_tail:
            continuity += f"\n[KẾT THÚC CỦA PHẦN TRƯỚC — để tiếp mạch, KHÔNG lặp lại]:\n...{previous_tail}\n"
        if next_heading:
            continuity += f"\n[PHẦN KẾ TIẾP SẼ LÀ: {next_heading} — hãy khép phần này gọn để nhường chỗ, không viết lấn sang phần sau.]\n"

        prompt = f"""
{context_block}

[DÀN Ý TOÀN BÀI — để biết vị trí của phần đang viết]:
{outline if outline else "(không có dàn ý)"}

Nhiệm vụ: CHỈ VIẾT DUY NHẤT PHẦN {index}/{n_sections} của kịch bản voice-over.
{f'- Bám sát trọng tâm dàn ý cho phần này: {section_focus}' if section_focus else '- Tự chọn trọng tâm hợp lý cho vị trí phần này.'}
{continuity}
[YÊU CẦU ĐỘ DÀI — BẮT BUỘC]
- Phần này phải có TỐI THIỂU {min_words} từ (mục tiêu ~{per_section_words} từ). Thiếu từ là thất bại.
- Triển khai sâu: phân tích, ví dụ cụ thể, chi tiết gợi hình, nhịp cảm xúc — tuyệt đối không tóm tắt hay viết lướt.

[ĐỊNH DẠNG]
- Bắt đầu bằng heading đánh số phần (dùng ngôn ngữ output, vd "PHẦN {index}:" / "PART {index}:" / "제{index}장:").
- Chỉ trả về nội dung phần này, không mở đầu/kết thúc cả bài, không ghi chú ngoài lề.
"""
        text = self._generate_once(prompt)

        # Nếu AI vẫn viết thiếu, gọi bổ sung tối đa 2 lần cho chính phần đó
        for _ in range(2):
            current_words = self._count_words(text)
            if current_words >= min_words:
                break
            extend_prompt = f"""
{context_block}

Phần {index}/{n_sections} hiện mới có {current_words} từ, trong khi YÊU CẦU TỐI THIỂU là {min_words} từ.
Hãy VIẾT TIẾP ngay sau đoạn cuối dưới đây (không lặp lại nguyên văn, không viết lại heading):
...{text[-600:]}

Viết thêm tối thiểu {min_words - current_words} từ, đào sâu thêm phân tích, ví dụ, chi tiết và cảm xúc cho CHÍNH phần {index} này.
Chỉ trả về phần viết thêm.
"""
            extra = self._generate_once(extend_prompt)
            text = f"{text}\n{extra}"

        return text.strip()

    def _write_single_pass(self, context_block, total_words, sections_label):
        """Chế độ Auto: viết cả bài trong 1 lần, thiếu thì gọi viết tiếp."""
        prompt = f"""
{context_block}

Nhiệm vụ: VIẾT TRỌN VẸN kịch bản voice-over trong MỘT lần trả lời.
- Chia thành các phần rõ ràng có heading đánh số (số phần do bạn chọn hợp lý, ứng với "{sections_label}").
- TỔNG SỐ TỪ TỐI THIỂU: {int(total_words * 0.9)} từ (mục tiêu ~{total_words} từ). Thiếu từ là thất bại.
- Hook mở đầu gây tò mò mạnh; thân bài phân tích sâu; kết thúc đọng lại giá trị.

Chỉ trả về kịch bản thuần text, không ghi chú ngoài lề.
"""
        text = self._generate_once(prompt)

        for _ in range(2):
            current_words = self._count_words(text)
            if current_words >= int(total_words * 0.9):
                break
            extend_prompt = f"""
{context_block}

Kịch bản hiện mới có {current_words} từ, yêu cầu tối thiểu {int(total_words * 0.9)} từ.
Hãy VIẾT TIẾP ngay sau đoạn cuối (không lặp lại nguyên văn):
...{text[-600:]}

Tiếp tục mạch kịch bản (thêm phần/phân tích mới, KHÔNG kết thúc sớm) cho đến khi đủ độ dài. Chỉ trả về phần viết thêm.
"""
            extra = self._generate_once(extend_prompt)
            text = f"{text}\n{extra}"

        return text.strip()

    def execute_direct_write(self, topic, project_dir, profile_id=None, options=None):
        if not self.api_key:
            raise ValueError("Chưa cấu hình API Key hợp lệ!")

        options = options or {}
        language = options.get("ngon_ngu", "Tiếng Việt")
        structure = options.get("cau_truc", "Levels — Escalation (POV)")
        sections = options.get("so_phan", "12")
        target_minutes = options.get("target_phut", 10)
        pov_style = options.get("pov_style", "Ngôi thứ 3 (Khách quan / Quan sát)")
        context = options.get("context", "")
        research_result_text = (options.get("research_data") or "").strip()

        minutes = self._parse_minutes(target_minutes)
        total_words = int(minutes * WORDS_PER_MINUTE)
        n_sections = self._parse_section_count(sections)

        project_data = self.read_project_files(project_dir)

        profile_data = {}
        if profile_id:
            try:
                profiles = profile_manager.load_profiles()
                profile_data = next((p for p in profiles if str(p.get("id")) == str(profile_id)), {})
            except Exception:
                profile_data = {}

        if research_result_text:
            source_material_section = f"""
--- [KẾT QUẢ RESEARCH CHUYÊN SÂU - DÙNG LÀM NGUỒN DỮ LIỆU CỐT LÕI ĐỂ VIẾT] ---
{research_result_text}
"""
        else:
            source_material_section = f"""
--- [THÔNG TIN CHỦ ĐỀ GỐC (Viết trực tiếp do không có dữ liệu Research trước đó)] ---
Chủ đề: {topic}
"""

        context_block = self._build_context_block(
            topic, project_data, profile_data, source_material_section,
            language, structure, pov_style, context
        )

        if n_sections and n_sections >= 2:
            outline = self._build_outline(context_block, n_sections, total_words)
            per_section_words = max(300, int(total_words / n_sections))
            outline_lines = [ln.strip() for ln in (outline or "").splitlines() if ln.strip()]

            written_sections = []
            previous_tail = ""
            for i in range(1, n_sections + 1):
                next_heading = self._outline_for_section(outline, i + 1) if i < n_sections else ""
                section_text = self._write_one_section(
                    context_block, outline, i, n_sections,
                    per_section_words, previous_tail, next_heading
                )
                written_sections.append(section_text)
                previous_tail = section_text[-500:]
                # Nhắc tiến độ lên console server để dễ theo dõi
                print(f"[DIRECT WRITE] Phần {i}/{n_sections}: {self._count_words(section_text)} từ")

            script_text = "\n\n".join(written_sections)
        else:
            outline = ""
            script_text = self._write_single_pass(context_block, total_words, sections)

        actual_words = self._count_words(script_text)
        actual_minutes = round(actual_words / WORDS_PER_MINUTE, 1)

        script_text += (
            f"\n\n[KIỂM TRA CÀI ĐẶT] Ngôn ngữ: {language} | Cấu trúc: {structure} | "
            f"Số phần: {sections} | Thời lượng mục tiêu: {minutes:g} phút (~{total_words} từ) | "
            f"POV: {pov_style}\n"
            f"[THỐNG KÊ] Thực viết: {actual_words} từ (~{actual_minutes:g} phút đọc ở {WORDS_PER_MINUTE} từ/phút)"
        )

        return {
            "status": "success",
            "model_used": DEFAULT_MODEL,
            "topic": topic,
            "word_count": actual_words,
            "estimated_minutes": actual_minutes,
            "api_response_script": script_text
        }
