"""
JARVIS discussion router.

Priority:
1. Explicit creative detection.
2. Technical/domain detection.
3. Simple factual detection.
4. Ollama classification for ambiguous topics.
5. Safe fallback -> COMPLEX.
"""

import re

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

    def classify(self, topic: str):
        """Classify locally; ambiguous requests safely take the complex path."""
        local = self._local_classify(topic)
        category = local or "complex"
        print(
            f"[ROUTER] Local classification -> {category.upper()}",
            flush=True,
        )
        return category

    def model_profile(self, topic: str):
        """Return the central OmniRoute coding/smart profile for a topic."""
        return get_complex_profile(topic)
