"""Turn any reply into speakable prose: no lists/markdown, max 99 words."""
import re
from voice.tts import strip_markdown
from voice.text_chunking import sentence_list

MAX_WORDS = 99


def to_speakable(text, max_words=MAX_WORDS):
    text = strip_markdown(text)
    # Treat the product name as a proper name, not an all-caps initialism.
    text = re.sub(r"\bjarvis\b", "Jarvis", text, flags=re.IGNORECASE)
    # Remove only the comma immediately before the honorific "sir".
    text = re.sub(r",\s*(?=sir\b)", " ", text, flags=re.IGNORECASE)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(\d+[.)]|[a-zA-Z][.)])\s+", "", line).strip()
        if not line:
            continue
        if line[-1] not in ".!?:":
            line += "."
        lines.append(line.rstrip(":") if line.endswith(":") else line)
    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    words = text.split()
    if len(words) <= max_words:
        return text
    out, count = [], 0
    for s in sentence_list(text):
        n = len(s.split())
        if count + n > max_words:
            break
        out.append(s)
        count += n
    if out:
        return " ".join(out)
    return " ".join(words[:max_words]).rstrip(",;:") + "."
