from . import ai_client


MAX_PRESCAN_OUTPUT_TOKENS = 8192


# Dòng bối cảnh dự phòng khi AI quên khối BACKGROUNDS — viết theo đúng ngôn
# ngữ người dùng chọn, không hardcode tiếng Việt như trước.
_FALLBACK_BG = {
    "Vietnamese": "Không gian chính của câu chuyện (bối cảnh tổng quát, cần bổ sung thủ công)",
    "English": "Main setting of the story (general location, please refine manually)",
    "German": "Hauptschauplatz der Geschichte (allgemeiner Ort, bitte manuell ergänzen)",
    "Portuguese": "Cenário principal da história (local geral, ajuste manualmente)",
    "Spanish": "Escenario principal de la historia (lugar general, ajústelo manualmente)",
    "Korean": "이야기의 주요 공간 (전반적인 배경, 필요 시 직접 보완)",
    "Japanese": "物語の主要な舞台（全体的な背景、必要に応じて手動で補完）",
    "Chinese": "故事的主要场景（整体背景，可手动补充）",
    "French": "Décor principal de l'histoire (lieu général, à compléter manuellement)",
    "Thai": "ฉากหลักของเรื่อง (สถานที่โดยรวม ปรับแก้ด้วยตนเองได้)",
}


def _normalize_prescan_output(text, lang_name="Vietnamese"):
    """Giữ output đúng 2 khối CHARACTERS/BACKGROUNDS để frontend parse ổn định."""
    text = (text or "").strip()
    if "```" in text:
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    upper_text = text.upper()
    if "CHARACTERS:" not in upper_text:
        text = "CHARACTERS:\n" + text
    if "BACKGROUNDS:" not in text.upper():
        fallback = _FALLBACK_BG.get(lang_name, _FALLBACK_BG["English"])
        text = text.rstrip() + f"\n\nBACKGROUNDS:\n- BACKGROUNDS 001: {fallback}"

    return text


def process_prescan(script_text, api_key, vo_lang="Tiếng Việt", min_char="30", max_char="100"):
    api_key = (api_key or "").strip()
    script_text = (script_text or "").strip()

    if not script_text:
        raise ValueError("Kịch bản trống, vui lòng nhập nội dung trước khi Pre-scan!")
    if not api_key:
        raise ValueError("Chưa có API Key! Vui lòng nhập API Key ở sidebar.")

    lang_name = ai_client.resolve_lang(vo_lang)

    prompt = f"""
[SYSTEM ROLE]
You are an expert AI Video Production Script Analyzer, Casting Director, and Background Art Director.
Your task is to read the entire voice-over script carefully and extract the clearest, most useful CHARACTER and BACKGROUND asset list for image/video production.

[OUTPUT LANGUAGE — ABSOLUTE REQUIREMENT]
Write EVERY character name, location name, and description in {lang_name}.
This applies to all human-readable text you produce. Do not use any other language.
The only exception is the literal ID prefix ("CHARACTERS 001", "BACKGROUNDS 001"),
which is a technical key and must stay exactly in that English form.

[CONFIGURATION]
- Voice-over language: {lang_name}
- Scene splitting reference: Min {min_char} chars / Max {max_char} chars per scene
- Output language for names/descriptions: {lang_name}

[DEEP ANALYSIS METHOD — MUST FOLLOW]
1. Read the whole script first. Understand the topic, timeline, who appears, where events happen, and what visual scenes the editor will need.
2. Build a mental timeline of the story before extracting assets. Do not extract randomly from isolated words.
3. Deduplicate aliases: if the same person/role is mentioned in different ways, merge them into one CHARACTER ID.
4. Only create a CHARACTER when it is visually useful on screen:
   - named historical/person characters,
   - explicit roles (king, queen, official, merchant, worker, soldier, mother, child...),
   - recurring groups that need a visible design.
   Do NOT list abstract concepts, countries, organizations, emotions, or objects as characters.
5. For every CHARACTER, make the description visually actionable:
   - age range or life stage if inferable,
   - clothing/costume/era/class status,
   - facial expression/body language,
   - 1-2 props or visual identifiers if useful,
   - role in the narrative.
6. Extract BACKGROUNDS as concrete physical places, not abstract chapter topics:
   - palace room, royal court, village road, market, prison cell, battlefield, study room, harbor, archive, etc.
   - Include atmosphere, time period, lighting, weather, props, and historical/environmental details.
7. Keep the asset list compact but complete: include all important recurring visual assets; avoid one-off vague assets unless a scene clearly needs them.
8. If the script implies a place/person without naming it, infer the most likely visual asset and label it clearly as a role/location, not as a made-up proper name.

[OUTPUT FORMAT — STRICT]
Return raw text only, no markdown fences, no explanations outside the format below.
Number IDs sequentially with exactly 3 digits.

Keep the section headers and the ID prefixes exactly as written below (English, unchanged).
Everything inside the brackets must be written in {lang_name}.

CHARACTERS:
- CHARACTERS 001: [character name or clear role] ([concrete visual description: age / social class / clothing / expression / props / narrative role])
- CHARACTERS 002: [character name or clear role] ([concrete visual description])

BACKGROUNDS:
- BACKGROUNDS 001: [specific location name] ([concrete spatial description: era / lighting / weather / props / atmosphere])
- BACKGROUNDS 002: [specific location name] ([concrete spatial description])

[QUALITY BAR — JUDGED BY SPECIFICITY, NOT BY LANGUAGE]
A BAD character entry names a generic person with no role and no visual detail —
the equivalent of "a man" or "an old person". A BAD background entry names an
abstract concept, an era, a society, or a topic rather than a physical place you
could actually point a camera at.

A GOOD character entry gives the role plus age range, clothing, expression,
a distinguishing prop, and the part they play in the story.
A GOOD background entry gives a concrete physical place plus its era, light
source, weather, notable props, and mood.

Apply this standard while writing every entry in {lang_name}.

[FINAL REMINDER]
All names and descriptions must be written in {lang_name}.
Only the "CHARACTERS NNN" / "BACKGROUNDS NNN" ID prefixes stay in English.

[SCRIPT TO ANALYZE]
{script_text}
"""

    result_text = ai_client.generate_content(
        api_key=api_key,
        prompt=prompt,
        system_prompt=(
            "You are a production asset extraction assistant. Return only the requested "
            f"raw text format. Write all names and descriptions in {lang_name}, keeping "
            "the CHARACTERS/BACKGROUNDS ID prefixes in English."
        ),
        temperature=0.35,
        max_output_tokens=MAX_PRESCAN_OUTPUT_TOKENS,
        timeout=300
    )

    return _normalize_prescan_output(result_text, lang_name)
