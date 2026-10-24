"""Shared message-style policy for JARVIS outbound and automatic WhatsApp replies."""
import os
import re

STYLES = {"mirror", "casual", "genz", "friendly", "formal"}
DEFAULT_STYLE = "mirror"


def message_style_config():
    style = (os.getenv("JARVIS_MESSAGE_STYLE", DEFAULT_STYLE) or DEFAULT_STYLE).strip().lower()
    if style not in STYLES:
        style = DEFAULT_STYLE
    language = (os.getenv("JARVIS_MESSAGE_LANGUAGE", "match") or "match").strip()[:40]
    examples = (os.getenv("JARVIS_MESSAGE_EXAMPLES", "") or "").strip()
    examples = re.sub(r"[\r\n]+", " ", examples)[:500]
    return {"style": style, "language": language, "examples": examples}


def style_instructions(context="outbound"):
    cfg = message_style_config()
    style_rules = {
        "mirror": "Naturally mirror the account owner's usual wording and energy without copying every typo.",
        "casual": "Use relaxed, natural, concise everyday language.",
        "genz": "Use contemporary Gen Z casual wording only when it fits the recipient and situation; slang such as 'damnnn' or 'gng' is an example, not a requirement. Do not force slang into every sentence.",
        "friendly": "Use warm, approachable, clear wording without excessive slang.",
        "formal": "Use professional, respectful, grammatically clear language and avoid slang or emojis unless explicitly requested.",
    }
    language_rule = (
        "Use the language the owner uses in the request and conversation."
        if cfg["language"].lower() in {"match", "auto", "same"}
        else "Prefer this language: " + cfg["language"] + ". If the recipient's conversation clearly uses another language, follow that context."
    )
    examples_rule = (
        "Owner-provided style examples (style reference only; do not blindly copy): " + cfg["examples"]
        if cfg["examples"] else ""
    )
    return (
        "MESSAGE STYLE PROFILE: " + style_rules[cfg["style"]] + " " + language_rule + " " + examples_rule + " "
        "CONTEXTUAL FORMALITY OVERRIDE: If the owner explicitly asks for formal/professional/respectful wording, "
        "or the recipient/context indicates a teacher, employer, official, unfamiliar adult, serious/sensitive matter, "
        "apology, complaint, application, or professional request, switch to formal language for that message even "
        "when the saved default is casual or Gen Z. Do not infer that every adult or every conversation is formal; "
        "use the actual context. Explicit style instructions for the current message take priority over the saved profile. "
        "Keep meaning and facts unchanged; never invent commitments or claims."
    )
