"""
modules/ai_client.py

Module dùng chung để gọi mô hình AI sinh nội dung (text generation),
hỗ trợ đồng thời 2 loại API key:
  1. ShopAIKey (key bắt đầu bằng "sk-") -> gọi qua endpoint
     https://direct.shopaikey.com/v1/chat/completions (chuẩn OpenAI-compatible)
  2. Gemini API key gốc (key khác) -> gọi qua thư viện google-genai

Tất cả các module khác (topic_ideator, research_script_writer,
direct_script_writer, assign_assets_handler, auto_extractor, ...) nên
import và dùng hàm generate_content() ở đây thay vì tự viết logic gọi
API riêng lẻ, để đảm bảo đồng bộ và dễ bảo trì.
"""

import os
import requests
from google import genai

# Model dùng khi gọi qua ShopAIKey (endpoint OpenAI-compatible).
#
# ShopAIKey bán NHIỀU dòng model trên cùng một endpoint — chỉ cần đổi tên
# model là chuyển nhà cung cấp, không phải đổi key hay endpoint.
#
# Key đang dùng thuộc nhóm claude_discount — nhóm này KHÔNG bán model
# Gemini, để gemini-* sẽ lỗi model_not_found.
#
# Tốc độ đo thực tế (sinh 10 topic, cùng prompt):
#     claude-haiku-4-5-20251001    18.2s
#     claude-sonnet-4-5            64.2s
#     claude-opus-4-5              chậm hơn nữa
#
# KHÔNG dùng claude-haiku-4-5-20251001 dù nhanh nhất: model này trên
# ShopAIKey hành xử sai — tự xưng là trợ lý khác, hỏi lại thay vì trả JSON,
# làm mọi handler parse lỗi. Đã kiểm chứng bằng test thực tế.
#
# Sonnet là lựa chọn nhanh nhất trong số các model hoạt động đúng.
SHOPAIKEY_MODEL = os.environ.get("SHOPAIKEY_MODEL", "claude-sonnet-4-5").strip()

# Model cho việc cần đọc hiểu / suy luận nhiều bước: viết kịch bản dài,
# thiết kế góc máy theo mạch phim, phân tích ảnh tham chiếu.
MODEL_DEEP = os.environ.get("SHOPAIKEY_MODEL_DEEP", "claude-sonnet-4-5").strip()

# Model dùng khi gọi trực tiếp Gemini API (SDK google-genai)
# Lưu ý: dùng tên model có thật, đang được Google hỗ trợ tại thời điểm chạy.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()

# --- CLAUDE (ANTHROPIC) ---
# Model mặc định khi dùng key Claude. Đổi được qua biến môi trường
# CLAUDE_MODEL nếu muốn dùng bản khác.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Endpoint chính chủ Anthropic, dùng cho key dạng sk-ant-...
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Một số dịch vụ trung gian bán key Claude qua giao diện OpenAI-compatible.
# Key của họ KHÔNG có tiền tố sk-ant- nên không thể phân biệt bằng tên key.
# Khai báo endpoint ở đây (hoặc biến môi trường CLAUDE_PROXY_URL) để ép
# những key đó đi đúng nơi.
CLAUDE_PROXY_URL = os.environ.get("CLAUDE_PROXY_URL", "").strip()


def is_claude_key(api_key: str) -> bool:
    """
    Nhận diện key Claude chính chủ của Anthropic.

    Key Anthropic luôn có dạng sk-ant-api03-... nên tiền tố sk-ant- là dấu
    hiệu chắc chắn. Key proxy trung gian cũng bắt đầu bằng sk- giống
    ShopAIKey, không thể phân biệt bằng tên — những key đó đi theo
    CLAUDE_PROXY_URL nếu người dùng khai báo.
    """
    return (api_key or "").strip().startswith("sk-ant-")

def is_fatal_error(err) -> bool:
    """
    Lỗi KHÔNG thể chữa bằng cách thử lại hay dùng dữ liệu dự phòng:
    sai key, key bị thu hồi, hết credit, vượt hạn mức.

    Những lỗi này phải báo thẳng cho người dùng. Nuốt chúng rồi trả về
    fallback là tệ nhất — giao diện báo "thành công" trong khi kết quả
    hoàn toàn không do AI sinh ra.
    """
    msg = str(err).lower()
    dau_hieu = (
        "invalid_api_key", "authentication failed", "xác thực thất bại",
        "unauthorized", "(401)", "(403)", "permission_denied",
        "insufficient", "quota", "hết hạn mức", "billing",
    )
    return any(d in msg for d in dau_hieu)


# --- NGÔN NGỮ ĐẦU RA ---
# Giao diện gửi nhãn tiếng Việt ("Tiếng Hàn"). Nhét thẳng nhãn này vào một
# prompt tiếng Anh thì chỉ thị rất yếu, model hay bỏ qua. Map sang tên chuẩn
# tiếng Anh ("Korean") để chỉ thị ngôn ngữ có hiệu lực thật sự.
VO_LANG_NAMES = {
    "Tiếng Việt": "Vietnamese",
    "English": "English",
    "Tiếng Anh": "English",
    "Tiếng Đức": "German",
    "Tiếng Bồ Đào Nha": "Portuguese",
    "Tiếng Tây Ban Nha": "Spanish",
    "Tiếng Hàn": "Korean",
    "Tiếng Nhật": "Japanese",
    "Tiếng Trung": "Chinese",
    "Tiếng Pháp": "French",
    "Tiếng Thái": "Thai",
}

# Tên chuẩn hợp lệ (cho phép người gọi truyền sẵn "Korean" thay vì nhãn Việt)
_CANONICAL_LANGS = {name.lower(): name for name in VO_LANG_NAMES.values()}


def resolve_lang(vo_lang: str, default: str = "Vietnamese") -> str:
    """
    Chuẩn hóa ngôn ngữ đầu ra về tên tiếng Anh dùng trong prompt.

    Chấp nhận cả nhãn giao diện lẫn tên chuẩn để không vỡ khi frontend đổi:
        "Tiếng Hàn" -> "Korean"
        "Korean"    -> "Korean"
        "xyz"       -> default
    """
    raw = (vo_lang or "").strip()
    if not raw:
        return default
    if raw in VO_LANG_NAMES:
        return VO_LANG_NAMES[raw]
    return _CANONICAL_LANGS.get(raw.lower(), default)


def generate_content(api_key: str, prompt: str, system_prompt: str = None,
                      shop_model: str = SHOPAIKEY_MODEL,
                      gemini_model: str = GEMINI_MODEL,
                      json_mode: bool = False,
                      temperature: float = None,
                      max_output_tokens: int = None,
                      timeout: int = 180) -> str:
    """
    Gọi AI sinh nội dung text từ 1 prompt, tự động chọn đúng nhà cung cấp
    dựa trên định dạng của api_key.

    Args:
        api_key: API key do người dùng nhập (sk-... hoặc key Gemini gốc)
        prompt: Nội dung prompt chính (user message)
        system_prompt: (tùy chọn) system message
        shop_model: tên model dùng khi gọi qua ShopAIKey
        gemini_model: tên model dùng khi gọi Gemini trực tiếp
        json_mode: nếu True, yêu cầu AI trả về đúng định dạng JSON thuần
                   (bật response_format/response_mime_type tương ứng)
        temperature: (tùy chọn) độ sáng tạo, để None thì dùng mặc định của model
        timeout: thời gian chờ tối đa (giây), chỉ áp dụng cho ShopAIKey

    Returns:
        str: nội dung text trả về từ AI (đã strip khoảng trắng đầu/cuối)

    Raises:
        RuntimeError: khi gọi API thất bại, kèm thông báo lỗi chi tiết
    """
    if not api_key:
        raise RuntimeError("Thiếu API Key. Vui lòng nhập API Key trước khi sử dụng.")

    api_key = api_key.strip()

    # --- Nhánh 0: Claude chính chủ (Anthropic) ---
    if is_claude_key(api_key):
        return _call_anthropic(
            api_key=api_key,
            prompt=prompt,
            system_prompt=system_prompt,
            model=claude_model,
            json_mode=json_mode,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout=timeout,
        )

    # --- Nhánh 1: ShopAIKey / proxy Claude (OpenAI-compatible endpoint) ---
    if api_key.startswith("sk-"):
        # Người dùng có thể khai CLAUDE_PROXY_URL để trỏ key sang dịch vụ
        # trung gian bán Claude; mặc định vẫn là ShopAIKey như trước.
        url = CLAUDE_PROXY_URL or "https://direct.shopaikey.com/v1/chat/completions"
        provider = "Claude Proxy" if CLAUDE_PROXY_URL else "ShopAIKey"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": shop_model,
            "messages": messages
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_output_tokens:
            payload["max_tokens"] = int(max_output_tokens)

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            raise RuntimeError(f"Lỗi kết nối tới {provider}: {e}")

        if resp.status_code != 200:
            raise RuntimeError(f"{provider} Error ({resp.status_code}): {resp.text}")

        try:
            resp_json = resp.json()
            text = resp_json["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, ValueError) as e:
            raise RuntimeError(f"Không đọc được phản hồi từ {provider}: {e} | Raw: {resp.text}")

        # Model Claude chạy qua endpoint này vẫn bọc kết quả trong ```json
        # dù đã bật response_format. Dọn sẵn ở đây để mọi handler gọi
        # json.loads() trực tiếp không bị vỡ.
        return clean_json_text(text) if json_mode else text

    # --- Nhánh 2: Gemini API gốc ---
    else:
        try:
            client = genai.Client(api_key=api_key)
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"

            config_kwargs = {}
            if json_mode:
                config_kwargs["response_mime_type"] = "application/json"
            if temperature is not None:
                config_kwargs["temperature"] = temperature
            if max_output_tokens:
                config_kwargs["max_output_tokens"] = int(max_output_tokens)

            if config_kwargs:
                from google.genai import types
                response = client.models.generate_content(
                    model=gemini_model,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
            else:
                response = client.models.generate_content(
                    model=gemini_model,
                    contents=full_prompt,
                )
            return response.text.strip()
        except Exception as e:
            raise RuntimeError(f"Lỗi gọi Gemini API: {e}")


def generate_content_with_image(api_key: str, prompt: str, image_base64: str,
                                 system_prompt: str = None,
                                 gemini_model: str = GEMINI_MODEL,
                                 shop_model: str = SHOPAIKEY_MODEL,
                                 json_mode: bool = False,
                                 temperature: float = None,
                                 max_output_tokens: int = None) -> str:
    """
    Gọi AI với image + text (vision multimodal).

    Hỗ trợ cả hai loại key:
      - ShopAIKey (sk-): gửi ảnh qua content part "image_url" (chuẩn OpenAI)
      - Gemini key gốc: gửi ảnh qua inline Part.from_bytes

    Args:
        api_key: ShopAIKey (sk-...) hoặc Gemini API key gốc
        prompt: Text prompt
        image_base64: Base64 image data (với hoặc không có data:image prefix)
        system_prompt: System message (optional)
        gemini_model: Model name
        json_mode: True để yêu cầu JSON response
        temperature: Độ sáng tạo
        max_output_tokens: Max tokens

    Returns:
        str: AI response text

    Raises:
        RuntimeError: Nếu gọi với ShopAIKey hoặc API lỗi
    """
    if not api_key:
        raise RuntimeError("Thiếu API Key.")

    api_key = api_key.strip()

    # --- Nhánh 1: ShopAIKey (OpenAI-compatible endpoint hỗ trợ vision) ---
    # Endpoint chuẩn OpenAI nhận ảnh qua content part kiểu "image_url",
    # với data URL base64 nhúng trực tiếp. Model gemini-* phía sau đọc được ảnh.
    if api_key.startswith("sk-"):
        url = "https://direct.shopaikey.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        # Chuẩn hóa thành data URL đầy đủ (endpoint yêu cầu có prefix)
        data_url = image_base64.strip()
        if not data_url.startswith("data:"):
            data_url = f"data:image/jpeg;base64,{data_url}"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        })

        payload = {
            "model": shop_model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_output_tokens:
            payload["max_tokens"] = int(max_output_tokens)

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
        except requests.RequestException as e:
            raise RuntimeError(f"Lỗi kết nối tới ShopAIKey (vision): {e}")

        if resp.status_code != 200:
            raise RuntimeError(f"ShopAIKey Vision Error ({resp.status_code}): {resp.text}")

        try:
            return resp.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, ValueError) as e:
            raise RuntimeError(f"Không đọc được phản hồi vision từ ShopAIKey: {e} | Raw: {resp.text}")

    # --- Nhánh 2: Gemini API gốc ---
    try:
        from google.genai import types
        client = genai.Client(api_key=api_key)

        # Xử lý base64: loại bỏ data:image/... prefix nếu có, giữ mime type
        mime_type = "image/jpeg"
        if image_base64.startswith("data:"):
            header, _, payload = image_base64.partition(",")
            image_base64 = payload
            # data:image/png;base64 → image/png
            if header.startswith("data:") and ";" in header:
                mime_type = header[5:].split(";")[0] or "image/jpeg"

        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        config_kwargs = {}
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"
        if temperature is not None:
            config_kwargs["temperature"] = temperature
        if max_output_tokens:
            config_kwargs["max_output_tokens"] = int(max_output_tokens)

        # Tạo parts: text + inline image
        parts = [
            full_prompt,
            types.Part.from_bytes(
                data=__import__("base64").b64decode(image_base64),
                mime_type=mime_type
            )
        ]

        if config_kwargs:
            response = client.models.generate_content(
                model=gemini_model,
                contents=parts,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        else:
            response = client.models.generate_content(
                model=gemini_model,
                contents=parts,
            )
        return response.text.strip()
    except Exception as e:
        raise RuntimeError(f"Lỗi gọi Gemini Vision API: {e}")


def clean_json_text(raw_text: str) -> str:
    """
    Tiện ích: loại bỏ các dấu ```json ... ``` (markdown code fence) nếu AI lỡ
    trả về kèm theo, để json.loads() không bị lỗi.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    return text.strip()