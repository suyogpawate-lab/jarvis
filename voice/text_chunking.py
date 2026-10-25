"""Sentence-boundary chunking for streaming speech synthesis.

Long responses are grouped near 15 words, but boundaries are only placed after
sentence-ending punctuation (.?!). Commas are deliberately not boundaries.
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
        # Do not split a decimal such as 3.14.
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

    # Abbreviations can be split by punctuation matching; join them back.
    merged: list[str] = []
    for sentence in sentences:
        if merged and merged[-1].split()[-1].lower() in _ABBREVIATIONS:
            merged[-1] += " " + sentence
        else:
            merged.append(sentence)
    return merged


def chunk_text(text: str, target_words: int = 15, threshold_words: int = 20) -> list[str]:
    """Group complete sentences near target_words for long responses.

    Responses of at most threshold_words stay intact. A long single sentence
    also stays intact rather than being cut at a comma or arbitrary word.
    """
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return []
    words = normalized.split()
    if len(words) <= threshold_words:
        return [normalized]

    sentences = sentence_list(normalized)
    if len(sentences) <= 1:
        return [normalized]

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    target_words = max(1, int(target_words))

    for sentence in sentences:
        sentence_words = len(sentence.split())
        if not current:
            current = [sentence]
            current_words = sentence_words
            continue

        combined_words = current_words + sentence_words
        # Choose the nearest available sentence boundary to the 15-word
        # target, without splitting at commas or inside a sentence.
        if current_words >= target_words or (
            combined_words > target_words
            and abs(current_words - target_words) <= abs(combined_words - target_words)
        ):
            chunks.append(" ".join(current).strip())
            current = [sentence]
            current_words = sentence_words
        else:
            current.append(sentence)
            current_words = combined_words

    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk]
