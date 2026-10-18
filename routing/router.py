"""
JARVIS discussion router.

Priority:
1. Explicit creative detection.
2. Technical/domain detection.
3. Simple factual detection.
4. Ollama classification for ambiguous topics.
5. Safe fallback -> COMPLEX.
"""

import json
import re

from agents.providers.ollama import OllamaAgent


class DiscussionRouter:

    def __init__(self):

        self.ollama = OllamaAgent()

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
    # OLLAMA CLASSIFIER
    # ============================================================

    def _ollama_classify(
        self,
        topic: str,
    ):

        prompt = f"""
Classify the following user topic into exactly ONE category:

SIMPLE
CREATIVE
COMPLEX

SIMPLE:
Straightforward factual questions and basic definitions.

CREATIVE:
Writing, storytelling, naming, brainstorming, fiction,
design and imaginative tasks.

COMPLEX:
Science, physics, cosmology, mathematics, programming,
engineering, research, technical analysis, difficult reasoning,
or questions with multiple competing explanations.

Topic:
{topic}

Return ONLY valid JSON:

{{"category":"SIMPLE"}}
"""

        try:

            result = (
                self.ollama.ask(
                    prompt
                )
                .strip()
            )

            match = re.search(
                r"\{.*?\}",
                result,
                re.DOTALL,
            )

            if match:

                data = json.loads(
                    match.group(0)
                )

                category = str(
                    data.get(
                        "category",
                        ""
                    )
                ).lower().strip()

                if category in {
                    "simple",
                    "creative",
                    "complex",
                }:

                    print(
                        f"[ROUTER] Ollama -> "
                        f"{category.upper()}",
                        flush=True,
                    )

                    return category

        except Exception as e:

            print(
                f"[ROUTER WARN] "
                f"Ollama classifier failed: {e}",
                flush=True,
            )

        return "complex"

    # ============================================================
    # PUBLIC
    # ============================================================

    def classify(
        self,
        topic: str,
    ):

        local = self._local_classify(
            topic
        )

        if local:

            print(
                f"[ROUTER] Local domain detection -> "
                f"{local.upper()}",
                flush=True,
            )

            return local

        return self._ollama_classify(
            topic
        )
