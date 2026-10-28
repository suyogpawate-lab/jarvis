"""
JARVIS discussion router.

Priority:
1. Explicit creative detection.
2. Technical/domain detection.
3. Simple factual detection.
4. Ollama classification for ambiguous topics.
5. Safe fallback -> COMPLEX.
"""

import os
import re

import requests
from routing.model_registry import get_complex_profile


class DiscussionRouter:

    def __init__(self):
        # Zero model warm-up here: routing starts with Python rules, keeping
        # resident RAM and first-request latency low on Android.
        pass

    # ============================================================
    # LOCAL CLASSIFICATION
    # ============================================================

    def _local_classify(
        self,
        topic: str,
    ):

        text = topic.lower().strip()

        # --------------------------------------------------------
        # CREATIVE
        # --------------------------------------------------------

        creative_patterns = (
            "write a story",
            "write me a story",
            "story about",
            "fiction",
            "science fiction",
            "sci-fi",
            "brainstorm",
            "brainstorming",
            "give me names",
            "name my",
            "names for my",
            "design an",
            "design a",
            "creative ideas",
            "invent",
            "imagine",
            "plot ideas",
        )

        if any(
            pattern in text
            for pattern in creative_patterns
        ):

            return "creative"

        # --------------------------------------------------------
        # TECHNICAL / COMPLEX
        # --------------------------------------------------------

        complex_domains = (
            "physics",
            "quantum",
            "relativity",
            "mechanics",
            "mathematics",
            "math",
            "calculus",
            "programming",
            "python",
            "coding",
            "algorithm",
            "robotics",
            "engineering",
            "chemistry",
            "organic chemistry",
            "neural network",
            "machine learning",
            "deep learning",
            "artificial intelligence",
            "ai",
            "thermodynamics",
            "electromagnetism",
            "astrophysics",
            "cosmology",
            "cosmological",
            "universe",
            "multiverse",
            "big bang",
            "big crunch",
            "inflation",
            "black hole",
            "dark matter",
            "dark energy",
            "spacetime",
            "gravity",
            "relativity",
            "biology",
            "genetics",
            "photosynthesis",
            "research",
        )

        if any(
            domain in text
            for domain in complex_domains
        ):

            return "complex"

        # --------------------------------------------------------
        # SIMPLE
        # --------------------------------------------------------

        simple_patterns = (
            "what is ",
            "who is ",
            "where is ",
            "when is ",
            "define ",
            "meaning of ",
            "meaning?",
            "how many ",
            "how much ",
            "what does ",
            "what are ",
        )

        if any(
            pattern in text
            for pattern in simple_patterns
        ):

            return "simple"

        return None

    # ============================================================
    # PUBLIC
    # ============================================================

    def _needle3_classify(self, topic: str):
        """Ask an already-running local Needle 3 endpoint on ambiguous inputs.

        Configure NEEDLE3_ROUTER_URL to the endpoint ending in /complete.
        No server or model is launched by the router, so idle RAM stays low.
        """
        url = os.getenv("NEEDLE3_ROUTER_URL", "").strip()
        if not url:
            return None
        if not url.endswith("/complete"):
            url = url.rstrip("/") + "/complete"
        try:
            response = requests.post(
                url,
                json={"input": (
                    "Classify this request as exactly SIMPLE, CREATIVE, or COMPLEX. "
                    "SIMPLE means a straightforward factual question; CREATIVE means "
                    "writing/brainstorming; COMPLEX means coding, research, planning, "
                    "or multi-step reasoning. Return only the category.\n\n"
                    f"Request: {str(topic)[:1200]}"
                )},
                timeout=(0.25, 1.5),
            )
            response.raise_for_status()
            try:
                payload = response.json()
                output = " ".join(
                    str(payload.get(key, ""))
                    for key in ("category", "intent", "classification", "output", "text", "response", "completion")
                )
            except ValueError:
                output = response.text
            match = re.search(r"\b(simple|creative|complex)\b", output, re.IGNORECASE)
            if match:
                return match.group(1).lower()
        except (requests.RequestException, ValueError, TypeError) as exc:
            print(
                f"[ROUTER WARN] Needle 3 unavailable; using local fallback ({type(exc).__name__}).",
                flush=True,
            )
        return None

    def classify(self, topic: str):
        """Use zero-cost local rules first and Needle 3 only for ambiguity."""
        local = self._local_classify(topic)
        category = local or self._needle3_classify(topic) or "complex"
        source = "local" if local else ("Needle 3" if category != "complex" else "fallback")
        print(
            f"[ROUTER] {source} classification -> {category.upper()}",
            flush=True,
        )
        return category

    def model_profile(self, topic: str):
        """Return the central OmniRoute coding/smart profile for a topic."""
        return get_complex_profile(topic)
