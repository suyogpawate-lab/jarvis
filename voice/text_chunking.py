"""Shared chunking policy for JARVIS speech synthesis.

Replies of 60 words or fewer remain a single utterance. Longer replies are
split into chunks near 22 words, preferring sentence boundaries (.?!).
Commas are never treated as chunk boundaries.
"""
from __future__ import annotations

import re

_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.",
    "etc.", "e.g.", "i.e.", "no.", "fig.", "approx.", "inc.", "ltd.",
    "co.", "u.s.", "u.k.", "a.m.", "p.m.",
}


def sentence_list(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    sentences: list[str] = []
    start = 0
    for match in re.finditer(r"[.!?]+(?=\s|$)", text):
        end = match.end()
        token_start = text.rfind(" ", start, match.start()) + 1
        token = text[token_start:end].lower()
        if token in _ABBREVIATIONS or re.fullmatch(r"\d+\.", token):
            continue
        if (
            text[match.start():match.end()] == "."
            and match.start() > 0
            and end < len(text)
            and text[match.start() - 1].isdigit()
            and text[end].isdigit()
        ):
            continue
        piece = text[start:end].strip()
        if piece:
            sentences.append(piece)
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
    if text[start:].strip():
        sentences.append(text[start:].strip())

    merged: list[str] = []
    for sentence in sentences:
        if merged and merged[-1].split()[-1].lower() in _ABBREVIATIONS:
            merged[-1] += " " + sentence
        else:
            merged.append(sentence)
    return merged


def _split_long_sentence(sentence: str, target_words: int) -> list[str]:
    """Split a single long sentence at word boundaries, never at a comma."""
    words = sentence.split()
    if len(words) <= target_words:
        return [sentence]
    chunks: list[str] = []
    while len(words) > target_words:
        boundary = target_words
        # Do not leave a comma at the end of a chunk; include the next word.
        while boundary < len(words) and words[boundary - 1].endswith(","):
            boundary += 1
        chunks.append(" ".join(words[:boundary]).strip())
        words = words[boundary:]
    if words:
        chunks.append(" ".join(words).strip())
    return chunks


def chunk_text(text: str, target_words: int = 22, threshold_words: int = 60) -> list[str]:
    """Keep replies up to 60 words intact; chunk longer replies around 22 words.

    Sentence boundaries are preferred. When one sentence itself exceeds the
    target, it is split at a word boundary (not at commas) to avoid one long
    playback pause. Short sentence fragments are grouped where practical.
    """
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return []
    words = normalized.split()
    if len(words) <= max(0, int(threshold_words)):
        return [normalized]

    target_words = max(1, int(target_words))
    sentences = sentence_list(normalized)
    if len(sentences) == 1:
        return _split_long_sentence(sentences[0], target_words)

    units: list[str] = []
    for sentence in sentences:
        units.extend(_split_long_sentence(sentence, target_words))

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for unit in units:
        unit_words = len(unit.split())
        if current:
            combined = current_words + unit_words
            if current_words >= target_words or (
                combined > target_words
                and abs(current_words - target_words) <= abs(combined - target_words)
            ):
                chunks.append(" ".join(current).strip())
                current = []
                current_words = 0
        current.append(unit)
        current_words += unit_words
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk]
