"""Turn a reply into speakable prose without silently truncating its content."""
import re
from voice.tts import strip_markdown
from voice.text_chunking import sentence_list



def to_speakable(text, max_words=None):
    text = strip_markdown(text)
    # Treat the product name as a proper name, not an all-caps initialism.
    text = re.sub(r"\bjarvis\b", "Jarvis", text, flags=re.IGNORECASE)
    # Remove only the comma immediately before the honorific "sir".
    text = re.sub(r",\s*(?=sir\b)", " ", text, flags=re.IGNORECASE)
    # A line wrap is formatting, not a spoken sentence boundary. Collapse it
    # before punctuation handling so TTS never inserts a false pause mid-clause.
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(\d+[.)]|[a-zA-Z][.)])\s+", "", line).strip()
        if line:
            lines.append(line)
    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if text and text[-1] not in ".!?":
        text += "."
    words = text.split()
    if max_words is None or len(words) <= max(1, int(max_words)):
        return text
    max_words = max(1, int(max_words))
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
