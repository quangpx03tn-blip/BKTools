"""
modules/camera_handler.py

Tool 4 — Camera & Shot Designer.

Nhận nội dung .srt (hoặc danh sách scene đã tách sẵn từ Tool 2), phân tích
ngữ cảnh từng câu thoại rồi thiết kế:
    - Cỡ cảnh (shot size): EWS / WS / MS / CU / ECU
    - Chuyển động máy (camera movement)
    - Chuyển cảnh (transition) sang shot kế tiếp
    - Ghi chú ánh sáng / VFX
    - Lý do chọn góc (giải thích cho người dựng)

Khác với bản cũ (chuỗi if/else khớp từ khóa tiếng Việt cứng), module này gọi
AI qua ai_client.generate_content(,
            # Mặc định của ai_client chỉ 60s — Claude sinh nội dung dài thường vượt ngưỡng này.
            timeout=180,
        ) nên chạy đúng với MỌI ngôn ngữ và mọi
chủ đề kênh. Khi không có API key hoặc AI lỗi, tự rơi về bộ luật heuristic
(không phụ thuộc ngôn ngữ) để người dùng vẫn có bảng làm việc.
"""

import json
import os
import re

from . import ai_client


# Lấy theo model đang cấu hình trong ai_client (biến SHOPAIKEY_MODEL),
# để đổi model một chỗ là toàn hệ thống đổi theo — tránh tình trạng
# key chỉ bán Claude nhưng handler vẫn gọi gemini-2.5-flash.
DEFAULT_MODEL = ai_client.SHOPAIKEY_MODEL
CAMERA_MAX_OUTPUT_TOKENS = 8192

# Ngưỡng mặc định: một cú máy dài quá ngần này giây thì nên tách.
DEFAULT_MAX_SHOT_SECONDS = 6.0

# --- BẢNG THUẬT NGỮ CHUẨN (đồng bộ với dropdown ở giao diện) ---

SHOT_SIZES = ["EWS", "WS", "MS", "CU", "ECU"]

SHOT_SIZE_LABELS = {
    "EWS": "Extreme Wide Shot",
    "WS": "Wide Shot",
    "MS": "Medium Shot",
    "CU": "Close-up",
    "ECU": "Extreme Close-up",
}

CAMERA_MOVEMENTS = [
    "Static",
    "Slow Push In",
    "Slow Pull Out",
    "Pan Left",
    "Pan Right",
    "Tilt Up",
    "Tilt Down",
    "Tracking",
    "Handheld",
    "Rack Focus",
    "Drone Establish",
    "Crane Down",
]

TRANSITIONS = ["Smooth Cut", "Hard Cut", "Fade", "Match Cut", "Whip Pan", "Dissolve"]

# Nhịp dựng theo thể loại: (giây/shot mục tiêu, mô tả cho prompt)
PACING_PRESETS = {
    "documentary": (6.0, "điềm đạm, để hình thở, ưu tiên shot rộng và tĩnh"),
    "tech_report": (4.0, "nhịp nhanh, nhiều cắt, xen kẽ cận cảnh số liệu với toàn cảnh"),
    "drama": (5.0, "theo cảm xúc, dùng cận cảnh nội tâm và chuyển động chậm"),
    "explainer": (5.0, "cân bằng, rõ ràng, ưu tiên trung cảnh dễ theo dõi"),
}

# Ống kính gợi ý theo cỡ cảnh (dùng cho fallback và khi AI bỏ trống)
LENS_BY_SIZE = {
    "EWS": "24mm – Rộng",
    "WS": "24mm – Rộng",
    "MS": "35mm – Tự nhiên",
    "CU": "85mm – Nén hậu cảnh",
    "ECU": "85mm – Nén hậu cảnh",
}

DOF_BY_SIZE = {
    "EWS": "Sâu (f/8)",
    "WS": "Sâu (f/8)",
    "MS": "Vừa (f/4)",
    "CU": "Nông (f/1.8)",
    "ECU": "Nông (f/1.8)",
}


# ══════════════════════════════════════════════════════════════
#  PHẦN 1 — PARSE FILE .SRT
# ══════════════════════════════════════════════════════════════

_TIMECODE_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _tc_to_seconds(h, m, s, ms):
    """Đổi các thành phần timecode sang tổng số giây (float)."""
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def seconds_to_tc(total_seconds: float) -> str:
    """Đổi số giây sang timecode chuẩn .srt: HH:MM:SS,mmm"""
    if total_seconds < 0:
        total_seconds = 0.0
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = int(total_seconds % 60)
    millis = int(round((total_seconds - int(total_seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_srt(raw_srt: str) -> list:
    """
    Tách nội dung .srt thành danh sách block.

    Trả về list các dict:
        {no, start, end, dur, tc, tc_end, text}
    với start/end/dur tính bằng giây (float).

    Bỏ qua block không có timecode hoặc không có thoại. Không phụ thuộc
    ngôn ngữ nên chạy được với SRT tiếng Hàn/Nhật/Trung/Việt/Anh.
    """
    raw_srt = (raw_srt or "").replace("﻿", "").strip()
    if not raw_srt:
        return []

    blocks = re.split(r"\r?\n\s*\r?\n", raw_srt)
    result = []

    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n")]
        timecode_line = None
        text_lines = []

        for line in lines:
            if not line:
                continue
            if "-->" in line and _TIMECODE_RE.search(line):
                timecode_line = line
                continue
            # Dòng chỉ chứa số thứ tự thì bỏ (chỉ khi chưa gặp timecode)
            if timecode_line is None and re.fullmatch(r"\d+", line):
                continue
            text_lines.append(line)

        if not timecode_line or not text_lines:
            continue

        m = _TIMECODE_RE.search(timecode_line)
        start = _tc_to_seconds(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _tc_to_seconds(m.group(5), m.group(6), m.group(7), m.group(8))
        if end < start:
            end = start

        result.append({
            "no": len(result) + 1,
            "start": round(start, 3),
            "end": round(end, 3),
            "dur": round(end - start, 2),
            "tc": seconds_to_tc(start),
            "tc_end": seconds_to_tc(end),
            "text": " ".join(text_lines).strip(),
        })

    return result


def scenes_to_blocks(scenes: list) -> list:
    """
    Chuyển danh sách scene từ Tool 2 (Scene Breakdown) sang cùng định dạng
    với parse_srt, để phần phân tích phía sau dùng chung một đường.

    Mỗi scene có thể mang: timecode ("00:00:01,000 --> 00:00:05,000" hoặc
    chỉ mốc bắt đầu), text/vo, character, background.
    """
    blocks = []
    cursor = 0.0

    for idx, sc in enumerate(scenes or []):
        if not isinstance(sc, dict):
            continue
        text = (sc.get("text") or sc.get("vo") or sc.get("content") or "").strip()
        if not text:
            continue

        tc_raw = (sc.get("timecode") or sc.get("tc") or "").strip()
        start = end = None
        m = _TIMECODE_RE.search(tc_raw)
        if m:
            start = _tc_to_seconds(m.group(1), m.group(2), m.group(3), m.group(4))
            end = _tc_to_seconds(m.group(5), m.group(6), m.group(7), m.group(8))
        else:
            single = re.search(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})", tc_raw)
            if single:
                start = _tc_to_seconds(single.group(1), single.group(2),
                                       single.group(3), single.group(4))

        if start is None:
            # Không có timecode: ước lượng theo độ dài thoại (~15 ký tự/giây đọc)
            start = cursor
            end = start + max(2.0, len(text) / 15.0)
        if end is None or end <= start:
            end = start + max(2.0, len(text) / 15.0)

        cursor = end
        blocks.append({
            "no": len(blocks) + 1,
            "start": round(start, 3),
            "end": round(end, 3),
            "dur": round(end - start, 2),
            "tc": seconds_to_tc(start),
            "tc_end": seconds_to_tc(end),
            "text": text,
            "character": sc.get("character", ""),
            "background": sc.get("background", ""),
            "scene_id": sc.get("id") or sc.get("scene_id") or (idx + 1),
        })

    return blocks


# ══════════════════════════════════════════════════════════════
#  PHẦN 2 — HEURISTIC FALLBACK (không phụ thuộc ngôn ngữ)
# ══════════════════════════════════════════════════════════════

def _heuristic_shot(block: dict, prev_size: str, index: int, total: int) -> dict:
    """
    Quyết định góc máy khi không có AI, dựa vào ĐẶC ĐIỂM CẤU TRÚC của câu
    (độ dài, có số liệu, có dấu hỏi, vị trí trong bài) thay vì từ khóa của
    một ngôn ngữ cụ thể — nên vẫn đúng với SRT tiếng Hàn, Nhật, Anh...
    """
    text = block.get("text", "")
    dur = block.get("dur", 0)
    char_count = len(text)
    has_number = bool(re.search(r"\d", text))
    is_question = text.rstrip().endswith(("?", "？"))
    is_short = char_count < 25

    # Mở bài / kết bài luôn ưu tiên shot rộng để thiết lập hoặc khép không gian
    if index == 0:
        size, movement, reason = "EWS", "Slow Push In", \
            "Câu mở đầu — cần shot thiết lập rộng để dựng bối cảnh cho toàn bài."
    elif index == total - 1:
        size, movement, reason = "WS", "Slow Pull Out", \
            "Câu kết — pull out mở rộng không gian tạo cảm giác khép lại."
    elif has_number and is_short:
        size, movement, reason = "ECU", "Static", \
            "Câu ngắn chứa số liệu — cực cận giúp người xem đọc kịp con số."
    elif has_number:
        size, movement, reason = "CU", "Static", \
            "Câu chứa số liệu cụ thể — cận cảnh nhấn mạnh dữ kiện."
    elif is_question:
        size, movement, reason = "MS", "Slow Push In", \
            "Câu hỏi hướng tới người xem — trung cảnh đẩy nhẹ tạo tương tác."
    elif is_short:
        size, movement, reason = "CU", "Static", \
            "Câu chốt ngắn, mạnh — cận cảnh tăng sức nặng."
    elif char_count > 70:
        size, movement, reason = "WS", "Slow Pan Right", \
            "Câu dài mang nhiều thông tin — shot rộng kèm pan chậm giữ nhịp đọc."
    else:
        size, movement, reason = "MS", "Static", \
            "Câu tường thuật trung tính — trung cảnh là lựa chọn an toàn."

    # Chống lặp cỡ cảnh liền kề: đẩy lên/xuống 1 bậc trên thang EWS→ECU
    if size == prev_size:
        i = SHOT_SIZES.index(size)
        size = SHOT_SIZES[i + 1] if i < len(SHOT_SIZES) - 1 else SHOT_SIZES[i - 1]
        reason += f" (Đổi cỡ cảnh để tránh trùng {prev_size} liền trước.)"

    transition = "Hard Cut" if dur < 3.0 else "Smooth Cut"

    return {
        "size": size,
        "movement": movement,
        "transition": transition,
        "reason": reason,
        "confidence": 60,
    }


def build_fallback_shots(blocks: list, max_shot_seconds: float = DEFAULT_MAX_SHOT_SECONDS) -> list:
    """Dựng toàn bộ shot list bằng heuristic (khi không gọi được AI)."""
    shots = []
    prev_size = ""
    total = len(blocks)

    for i, b in enumerate(blocks):
        decision = _heuristic_shot(b, prev_size, i, total)
        prev_size = decision["size"]
        shots.append(_compose_shot(b, decision, max_shot_seconds))

    return shots


# ══════════════════════════════════════════════════════════════
#  PHẦN 3 — CHUẨN HÓA & GHÉP KẾT QUẢ
# ══════════════════════════════════════════════════════════════

def _normalize_size(value: str) -> str:
    """Ép mọi biến thể tên cỡ cảnh về đúng 1 trong 5 mã chuẩn."""
    v = (value or "").strip().upper()
    if v in SHOT_SIZES:
        return v
    # Cho phép AI trả tên đầy đủ hoặc tiếng Việt
    if "EXTREME" in v and "WIDE" in v:
        return "EWS"
    if "EXTREME" in v and "CLOSE" in v:
        return "ECU"
    if "WIDE" in v or "TOÀN" in v or "ESTABLISH" in v:
        return "WS"
    if "MEDIUM" in v or "TRUNG" in v:
        return "MS"
    if "CLOSE" in v or "CẬN" in v:
        return "CU"
    return "MS"


def _normalize_choice(value: str, allowed: list, default: str) -> str:
    """Khớp giá trị AI trả về với danh sách cho phép (không phân biệt hoa thường)."""
    v = (value or "").strip()
    if not v:
        return default
    for item in allowed:
        if item.lower() == v.lower():
            return item
    # Khớp lỏng: chứa nhau
    for item in allowed:
        if item.lower() in v.lower() or v.lower() in item.lower():
            return item
    return v if len(v) <= 40 else default


def _compose_shot(block: dict, decision: dict, max_shot_seconds: float) -> dict:
    """Ghép 1 block SRT + quyết định góc máy thành 1 dòng shot hoàn chỉnh."""
    size = _normalize_size(decision.get("size"))
    dur = block.get("dur", 0)

    return {
        "no": block.get("no"),
        "tc": block.get("tc", ""),
        "tc_end": block.get("tc_end", ""),
        "start": block.get("start", 0),
        "end": block.get("end", 0),
        "dur": dur,
        "text": block.get("text", ""),
        "size": size,
        "size_label": SHOT_SIZE_LABELS.get(size, size),
        "movement": _normalize_choice(decision.get("movement"), CAMERA_MOVEMENTS, "Static"),
        "transition": _normalize_choice(decision.get("transition"), TRANSITIONS, "Smooth Cut"),
        "lens": decision.get("lens") or LENS_BY_SIZE.get(size, "35mm – Tự nhiên"),
        "dof": decision.get("dof") or DOF_BY_SIZE.get(size, "Vừa (f/4)"),
        "vfx": decision.get("vfx", ""),
        "reason": decision.get("reason", ""),
        "confidence": int(decision.get("confidence") or 0),
        "warn": dur > max_shot_seconds,
        "character": block.get("character", ""),
        "background": block.get("background", ""),
        "scene_id": block.get("scene_id", block.get("no")),
    }


# ══════════════════════════════════════════════════════════════
#  PHẦN 4 — QC: TÍNH METRIC & PHÁT HIỆN LỖI DỰNG
# ══════════════════════════════════════════════════════════════

def analyze_quality(shots: list, max_shot_seconds: float = DEFAULT_MAX_SHOT_SECONDS) -> dict:
    """
    Soi lại shot list đã dựng, trả về metric tổng quan + danh sách cảnh báo.

    Metric:
        total_shots, total_duration, avg_pace, diversity (%),
        too_long (số shot vượt ngưỡng), warn_count
    Cảnh báo (mỗi cái có shot_no để giao diện nhảy tới):
        - shot vượt ngưỡng giây
        - hai shot liền kề trùng cỡ cảnh
        - ba shot liên tiếp cùng cỡ cảnh (nhịp bị ngộp)
    """
    warnings = []
    if not shots:
        return {
            "metrics": {
                "total_shots": 0, "total_duration": 0, "total_duration_tc": "0:00",
                "avg_pace": 0, "diversity": 0, "too_long": 0, "warn_count": 0,
            },
            "warnings": [],
        }

    total_duration = sum(s.get("dur", 0) for s in shots)
    sizes = [s.get("size", "MS") for s in shots]

    # 1. Shot quá dài
    too_long = 0
    for s in shots:
        if s.get("dur", 0) > max_shot_seconds:
            too_long += 1
            parts = max(2, int(s["dur"] // max_shot_seconds) + 1)
            warnings.append({
                "level": "error",
                "shot_no": s.get("no"),
                "type": "too_long",
                "message": f"Shot {s.get('no'):02d} · {s['dur']}s quá dài → nên tách {parts}",
            })

    # 2. Trùng cỡ cảnh liền kề
    for i in range(1, len(sizes)):
        if sizes[i] == sizes[i - 1]:
            warnings.append({
                "level": "error",
                "shot_no": shots[i].get("no"),
                "type": "repeat_size",
                "message": f"Shot {shots[i-1].get('no'):02d}–{shots[i].get('no'):02d} · lặp cỡ cảnh {sizes[i]}",
            })

    # 3. Ba shot liên tiếp cùng cỡ cảnh → nhịp ngộp
    for i in range(2, len(sizes)):
        if sizes[i] == sizes[i - 1] == sizes[i - 2]:
            warnings.append({
                "level": "warn",
                "shot_no": shots[i].get("no"),
                "type": "monotone",
                "message": f"Shot {shots[i].get('no'):02d} · 3 {sizes[i]} liên tiếp, thiếu nhịp thở",
            })

    # 4. Thiếu shot thiết lập ở đầu
    if sizes and sizes[0] not in ("EWS", "WS"):
        warnings.append({
            "level": "warn",
            "shot_no": shots[0].get("no"),
            "type": "no_establish",
            "message": "Thiếu shot thiết lập rộng ở mở đầu",
        })

    unique_sizes = len(set(sizes))
    diversity = round(unique_sizes / len(SHOT_SIZES) * 100)
    avg_pace = round(total_duration / len(shots), 1) if shots else 0

    mins = int(total_duration // 60)
    secs = int(total_duration % 60)

    return {
        "metrics": {
            "total_shots": len(shots),
            "total_duration": round(total_duration, 1),
            "total_duration_tc": f"{mins}:{secs:02d}",
            "avg_pace": avg_pace,
            "diversity": diversity,
            "too_long": too_long,
            "warn_count": len(warnings),
        },
        "warnings": warnings,
    }


# ══════════════════════════════════════════════════════════════
#  PHẦN 5 — HANDLER CHÍNH (gọi AI)
# ══════════════════════════════════════════════════════════════

class CameraHandler:
    """
    Tool 4 — phân tích SRT và thiết kế góc máy bằng AI.

    Dùng chung ai_client nên hỗ trợ cả ShopAIKey (sk-...) lẫn Gemini key gốc,
    và tự động theo ngôn ngữ của chính nội dung SRT.
    """

    def __init__(self, default_model=DEFAULT_MODEL):
        self.default_model = default_model

    # ---------- Prompt ----------

    @staticmethod
    def _build_system_prompt(style_guide: str = "") -> str:
        base = (
            "You are a senior cinematographer and film editor designing a shot list "
            "for a narrated video. For EACH subtitle line you decide the shot size, "
            "camera movement, transition into the next shot, lighting/VFX note, and "
            "a short reason explaining the choice.\n\n"
            "HARD RULES:\n"
            "1. shot_size MUST be exactly one of: EWS, WS, MS, CU, ECU.\n"
            "2. NEVER use the same shot_size on two consecutive lines — vary the rhythm.\n"
            "3. Open a new topic/section with EWS or WS to establish space.\n"
            "4. Lines containing concrete numbers/statistics get CU or ECU so the "
            "viewer can read them.\n"
            "5. Short punchy statements get CU. Long informational lines get WS or MS.\n"
            "6. Rhetorical questions get MS with a slow push in.\n"
            "7. The 'reason' field MUST be written in Vietnamese, referencing the actual "
            "meaning of that specific line — never a generic sentence.\n"
            "8. Return ONLY valid JSON, no markdown fence, no commentary."
        )
        if style_guide:
            base += f"\n\nCHANNEL STYLE GUIDE (obey this for lighting/VFX notes):\n{style_guide.strip()[:1500]}"
        return base

    @staticmethod
    def _build_user_prompt(blocks, genre_key, transition_default, vfx_style,
                           max_shot_seconds, constraints):
        pace_sec, pace_desc = PACING_PRESETS.get(genre_key, PACING_PRESETS["explainer"])

        lines = []
        for b in blocks:
            lines.append(
                f'{b["no"]}. [{b["tc"]} | {b["dur"]}s] {b["text"]}'
            )
        script_text = "\n".join(lines)

        rules = []
        if constraints.get("split_long"):
            rules.append(f"- Flag any shot longer than {max_shot_seconds}s as needing a split.")
        if constraints.get("no_repeat"):
            rules.append("- Absolutely no two consecutive lines share the same shot_size.")
        if constraints.get("open_wide"):
            rules.append("- The first line and each new topic must start on EWS or WS.")
        if constraints.get("axis_180"):
            rules.append("- Keep the 180-degree rule: do not flip subject screen direction between adjacent shots.")

        return (
            f"GENRE / PACING: {genre_key} — {pace_desc}. Target ~{pace_sec}s per shot.\n"
            f"DEFAULT TRANSITION: {transition_default}\n"
            f"VFX DIRECTION: {vfx_style}\n"
            f"MAX SECONDS PER SHOT: {max_shot_seconds}\n"
            + ("EXTRA RULES:\n" + "\n".join(rules) + "\n" if rules else "")
            + "\nSUBTITLE LINES (number, timecode, duration, text):\n"
            f"{script_text}\n\n"
            "Return a JSON object exactly in this shape — one entry per subtitle line, "
            "same order, same count:\n"
            '{"shots": [{"no": 1, "shot_size": "EWS", "movement": "Slow Push In", '
            '"transition": "Fade", "lens": "24mm – Rộng", "dof": "Sâu (f/8)", '
            '"vfx": "ghi chú ánh sáng bằng tiếng Việt", '
            '"reason": "lý do bằng tiếng Việt, bám sát nội dung câu này", '
            '"confidence": 92}]}'
        )

    # ---------- Gọi AI ----------

    def _call_ai(self, api_key, blocks, genre_key, transition_default,
                 vfx_style, max_shot_seconds, constraints, style_guide, model):
        system_prompt = self._build_system_prompt(style_guide)
        user_prompt = self._build_user_prompt(
            blocks, genre_key, transition_default, vfx_style,
            max_shot_seconds, constraints
        )

        raw = ai_client.generate_content(
            api_key=api_key,
            prompt=user_prompt,
            system_prompt=system_prompt,
            shop_model=model or self.default_model,
            gemini_model=model or self.default_model,
            json_mode=True,
            temperature=0.7,
            max_output_tokens=CAMERA_MAX_OUTPUT_TOKENS,
            timeout=120,
        )

        return self._parse_ai_json(raw)

    @staticmethod
    def _parse_ai_json(raw: str) -> list:
        """Bóc JSON từ phản hồi AI, chịu được trường hợp bị bọc ```json."""
        text = (raw or "").strip()
        if not text:
            return []

        # Gỡ rào markdown nếu có
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Vớt object JSON đầu tiên trong chuỗi
            m = re.search(r"\{[\s\S]*\}", text)
            if not m:
                return []
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return []

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("shots", "data", "result", "items"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    # ---------- API công khai ----------

    def analyze(self, srt_content: str = "", scenes: list = None, api_key: str = "",
                genre: str = "explainer", transition_default: str = "Smooth Cut",
                vfx_style: str = "Cinematic Depth",
                max_shot_seconds: float = DEFAULT_MAX_SHOT_SECONDS,
                constraints: dict = None, style_guide: str = "",
                model: str = "") -> dict:
        """
        Phân tích SRT (hoặc scene list từ Tool 2) và trả về shot list hoàn chỉnh.

        Returns:
            {
              "shots":    [ ... ],           # danh sách shot đã chuẩn hóa
              "metrics":  { ... },           # số liệu cho stat strip
              "warnings": [ ... ],           # cảnh báo dựng
              "source":   "ai" | "fallback", # nguồn quyết định góc máy
              "note":     "..."              # lý do fallback (nếu có)
            }
        """
        constraints = constraints or {}
        try:
            max_shot_seconds = float(max_shot_seconds) or DEFAULT_MAX_SHOT_SECONDS
        except (TypeError, ValueError):
            max_shot_seconds = DEFAULT_MAX_SHOT_SECONDS

        # 1. Lấy block: ưu tiên scene từ Tool 2, không có thì parse SRT
        if scenes:
            blocks = scenes_to_blocks(scenes)
        else:
            blocks = parse_srt(srt_content)

        if not blocks:
            raise ValueError(
                "Không đọc được nội dung nào. Kiểm tra lại file .srt "
                "(cần có dòng timecode dạng 00:00:00,000 --> 00:00:05,000)."
            )

        api_key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        genre_key = (genre or "explainer").strip().lower().replace(" ", "_")

        source = "fallback"
        note = ""
        shots = []

        # 2. Gọi AI nếu có key
        if api_key:
            try:
                ai_rows = self._call_ai(
                    api_key, blocks, genre_key, transition_default, vfx_style,
                    max_shot_seconds, constraints, style_guide, model
                )
                if ai_rows:
                    by_no = {}
                    for row in ai_rows:
                        if not isinstance(row, dict):
                            continue
                        try:
                            by_no[int(row.get("no"))] = row
                        except (TypeError, ValueError):
                            continue

                    prev_size = ""
                    for i, b in enumerate(blocks):
                        row = by_no.get(b["no"]) or (ai_rows[i] if i < len(ai_rows) and isinstance(ai_rows[i], dict) else {})
                        decision = {
                            "size": row.get("shot_size") or row.get("size"),
                            "movement": row.get("movement"),
                            "transition": row.get("transition") or transition_default,
                            "lens": row.get("lens"),
                            "dof": row.get("dof"),
                            "vfx": row.get("vfx") or row.get("lighting"),
                            "reason": row.get("reason"),
                            "confidence": row.get("confidence") or 85,
                        }
                        if not decision["size"]:
                            decision = _heuristic_shot(b, prev_size, i, len(blocks))
                        shots.append(_compose_shot(b, decision, max_shot_seconds))
                        prev_size = shots[-1]["size"]

                    source = "ai"
                else:
                    note = "AI không trả về dữ liệu hợp lệ — đã dùng bộ luật dự phòng."
            except Exception as e:
                # Sai key / hết credit: báo thẳng thay vì trả bảng shot dựng
                # bằng heuristic mà người dùng tưởng là AI phân tích.
                if ai_client.is_fatal_error(e):
                    raise RuntimeError(f"Không gọi được AI: {e}")
                note = f"Lỗi gọi AI ({e}) — đã dùng bộ luật dự phòng."
        else:
            note = "Chưa có API Key — đang dùng bộ luật dự phòng, chất lượng hạn chế."

        # 3. Fallback khi AI không dùng được
        if not shots:
            shots = build_fallback_shots(blocks, max_shot_seconds)

        # 4. QC
        qc = analyze_quality(shots, max_shot_seconds)

        return {
            "shots": shots,
            "metrics": qc["metrics"],
            "warnings": qc["warnings"],
            "source": source,
            "note": note,
        }

    def split_shot(self, shot: dict, parts: int = 2) -> list:
        """
        Tách 1 shot dài thành nhiều shot con, chia đều thời lượng và
        luân phiên cỡ cảnh để không bị trùng.
        """
        parts = max(2, min(int(parts or 2), 5))
        start = float(shot.get("start") or 0)
        dur = float(shot.get("dur") or 0)
        if dur <= 0:
            return [shot]

        step = dur / parts
        base_size = _normalize_size(shot.get("size"))
        idx = SHOT_SIZES.index(base_size)

        out = []
        for i in range(parts):
            s_start = start + step * i
            s_end = s_start + step
            # Luân phiên: shot đầu giữ cỡ gốc, các shot sau lệch 1 bậc
            size = base_size if i == 0 else SHOT_SIZES[min(idx + 1, len(SHOT_SIZES) - 1)] \
                if i % 2 == 1 else SHOT_SIZES[max(idx - 1, 0)]
            out.append({
                **shot,
                "no": f'{shot.get("no")}.{i + 1}',
                "tc": seconds_to_tc(s_start),
                "tc_end": seconds_to_tc(s_end),
                "start": round(s_start, 3),
                "end": round(s_end, 3),
                "dur": round(step, 2),
                "size": size,
                "size_label": SHOT_SIZE_LABELS.get(size, size),
                "warn": False,
                "reason": f'Tách từ shot {shot.get("no")} ({dur}s) thành {parts} phần để giữ nhịp dựng.',
            })
        return out


# Instance dùng chung cho app.py
camera_handler = CameraHandler()
