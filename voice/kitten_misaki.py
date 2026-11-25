"""Lightweight Misaki English G2P adapter using NLTK instead of spaCy.

Misaki supplies the pronunciation lexicon and phonological rules. NLTK supplies
word tokenization/Penn POS tags. The adapter avoids loading spaCy, PyTorch, and
Transformers, which are unnecessary for Kitten's ONNX inference path.
"""
from __future__ import annotations

import importlib
import sys
import types


_MISSING = object()


def _import_misaki_en():
    """Import Misaki's lexicon/G2P algorithms without importing heavyweight extras.

    Misaki 0.9.4 imports spaCy, torch, and Transformers at module scope even
    when its transformer fallback is disabled. Those names are only needed by
    its default model-backed tokenizer/fallback, both of which this adapter
    replaces. Temporary stubs keep those optional stacks out of the process.
    """
    cached = sys.modules.get("misaki.en")
    if cached is not None:
        return cached

    stubs = {}
    for name in ("spacy", "torch", "transformers"):
        stub = types.ModuleType(name)
        if name == "transformers":
            stub.BartForConditionalGeneration = object
        stubs[name] = stub

    previous = {name: sys.modules.get(name, _MISSING) for name in stubs}
    try:
        sys.modules.update(stubs)
        return importlib.import_module("misaki.en")
    finally:
        for name, old in previous.items():
            if old is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def _nltk_tokens(text, nltk, mtoken_type, tokenizer):
    """Tokenize with NLTK spans while preserving exact source whitespace."""
    spans = list(tokenizer.span_tokenize(text))
    if not spans:
        return []
    words = [text[start:end] for start, end in spans]
    tagged = nltk.pos_tag(words)
    mutable = []
    for index, ((start, end), (word, tag)) in enumerate(zip(spans, tagged)):
        next_start = spans[index + 1][0] if index + 1 < len(spans) else len(text)
        mutable.append(mtoken_type(
            text=word,
            tag=tag,
            whitespace=text[end:next_start],
            _=mtoken_type.Underscore(is_head=True, num_flags="", prespace=False),
        ))
    return mutable


def nltk_misaki_class():
    """Build a Misaki G2P class whose tokenizer/POS tagger are NLTK-backed."""
    en = _import_misaki_en()
    import nltk
    from nltk.tokenize import TreebankWordTokenizer
    from kittenml.kittentts2_tiny.frontend import espeak

    class NltkMisakiG2P(en.G2P):
        def __init__(self):
            # Bypass Misaki's spaCy model and PyTorch BART fallback.
            self.version = None
            self.british = False
            self.lexicon = en.Lexicon(british=False)
            self.fallback = espeak.EspeakFallback(british=False)
            self.unk = ""
            self._nltk = nltk
            self._tokenizer = TreebankWordTokenizer()

        def tokenize(self, text, tokens, features):
            return _nltk_tokens(text, self._nltk, en.MToken, self._tokenizer)

    return NltkMisakiG2P


class MisakiNltkEnglishG2P:
    """Kitten frontend-compatible English G2P backed by Misaki + NLTK."""

    def __init__(self, vocab, g2p_dir=None):
        from kittenml.kittentts2_tiny.frontend import phonemize_v1
        from kittenml.kittentts2_tiny.frontend.english import G2PResult
        from kittenml.kittentts2_tiny.frontend.tts_norm import normalize

        self._phonemizer = phonemize_v1
        self._result_type = G2PResult
        self._normalize = normalize
        self.vocab = dict(vocab)
        self._g2p = nltk_misaki_class()()
        self._unsaid = []

    def _run(self, text):
        phonemes, tokens = self._g2p(text, preprocess=False)
        self._unsaid = [token.text for token in tokens if token.phonemes is None]
        return phonemes, tokens

    def __call__(self, text, normalise=True):
        text = self._normalize(text) if normalise else text
        self._unsaid = []
        phonemes = self._phonemizer.phonemize_lang(self._run, text, "en")
        dropped = sorted({symbol for symbol in phonemes if symbol not in self.vocab})
        if dropped:
            phonemes = "".join(symbol for symbol in phonemes if symbol in self.vocab)
        return self._result_type(
            text,
            phonemes,
            [],
            list(dict.fromkeys(self._unsaid)),
            dropped,
        )
