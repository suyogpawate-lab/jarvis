import unittest

from voice.text_chunking import phonon_chunk_text


class SpeechChunkingTests(unittest.TestCase):
    def test_short_response_is_not_split(self):
        text = "This is short. It should remain one response."
        self.assertEqual(phonon_chunk_text(text), [text])

    def test_long_response_uses_50_word_lead_then_15_word_chunks(self):
        sentences = [
            " ".join(f"word{i}" for i in range(start, start + 5)) + "."
            for start in range(0, 80, 5)
        ]
        chunks = phonon_chunk_text(" ".join(sentences))
        self.assertEqual([len(chunk.split()) for chunk in chunks], [50, 15, 15])
        self.assertTrue(all(chunk.endswith(".") for chunk in chunks))

    def test_commas_do_not_create_chunk_boundaries(self):
        first = " ".join(f"word{i}," for i in range(49)) + " word49."
        second = " ".join(f"word{i}" for i in range(50, 65)) + "!"
        chunks = phonon_chunk_text(first + " " + second)
        self.assertEqual(chunks, [first, second])
        self.assertTrue(chunks[0].endswith("."))
        self.assertTrue(chunks[1].endswith("!"))

    def test_question_and_exclamation_marks_are_supported(self):
        sentences = [
            " ".join(f"word{i}" for i in range(start, start + 10)) + ending
            for start, ending in zip(range(0, 80, 10), ["?", ".", "!", ".", "?", ".", "!", "."])
        ]
        chunks = phonon_chunk_text(" ".join(sentences))
        self.assertEqual([len(chunk.split()) for chunk in chunks], [50, 20, 10])
        self.assertTrue(all(chunk[-1] in ".?!" for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
