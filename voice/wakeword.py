"""
Wake-word controller.

Initial implementation:
    local STT -> normalized text -> "jarvis" keyword

This is intentionally separated from the audio and STT layers.

Later we can replace this with a dedicated offline acoustic
wake-word model without changing the rest of JARVIS.
"""


class WakeWordDetector:

    def __init__(self, wake_word="jarvis"):
        self.wake_word = wake_word.lower().strip()

    def detect(self, text):
        if not text:
            return False

        normalized = (
            text.lower()
            .strip()
            .replace(",", " ")
            .replace(".", " ")
            .replace("!", " ")
            .replace("?", " ")
        )

        words = normalized.split()

        return self.wake_word in words

    def remove_wake_word(self, text):
        if not text:
            return ""

        words = text.split()

        result = [
            word
            for word in words
            if word.lower().strip(".,!?") != self.wake_word
        ]

        return " ".join(result).strip()
