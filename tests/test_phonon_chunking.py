import unittest

from voice.text_chunking import phonon_chunk_text


class PhononChunkingTests(unittest.TestCase):
    def test_replies_of_50_words_or_fewer_remain_one_utterance(self):
        text = " ".join(f"word{i}" for i in range(50)) + "."
        self.assertEqual(phonon_chunk_text(text), [text])

    def test_first_chunk_rounds_up_to_sentence_end_at_50_words(self):
        first = " ".join(f"word{i}" for i in range(25)) + "."
        second = " ".join(f"word{i}" for i in range(25, 51)) + "."
        third = " ".join(f"word{i}" for i in range(51, 66)) + "."
        fourth = " ".join(f"word{i}" for i in range(66, 81)) + "."
        chunks = phonon_chunk_text(" ".join((first, second, third, fourth)))
        self.assertEqual(chunks, [first + " " + second, third, fourth])

    def test_later_chunks_target_15_words_and_keep_final_remainder(self):
        sentences = [
            " ".join(f"w{i}" for i in range(start, start + 5)) + "."
            for start in range(0, 80, 5)
        ]
        chunks = phonon_chunk_text(" ".join(sentences))
        self.assertEqual([len(chunk.split()) for chunk in chunks], [50, 15, 15])

    def test_commas_do_not_create_chunk_boundaries(self):
        first = " ".join(f"word{i}," for i in range(49)) + " word49."
        second = " ".join(f"word{i}" for i in range(50, 65)) + "."
        chunks = phonon_chunk_text(first + " " + second)
        self.assertEqual(chunks[0], first)
        self.assertTrue(chunks[0].endswith("."))

    def test_empty_text_returns_no_chunks(self):
        self.assertEqual(phonon_chunk_text("   "), [])


if __name__ == "__main__":
    unittest.main()
