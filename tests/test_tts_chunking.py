import unittest

from voice.text_chunking import kitten_chunk_text, phonon_chunk_text
from voice.spoken import to_speakable


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


    def test_kitten_keeps_normal_replies_in_one_prosodic_pass(self):
        text = " ".join(f"word{i}" for i in range(120)) + "."
        self.assertEqual(kitten_chunk_text(text), [text])

    def test_kitten_splits_only_very_long_replies(self):
        text = " ".join(f"word{i}." for i in range(320))
        chunks = kitten_chunk_text(text)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(" ".join(chunks), text)

    def test_speech_text_is_not_silently_cut_at_99_words(self):
        text = " ".join(f"word{i}" for i in range(140)) + "."
        self.assertEqual(to_speakable(text), text)

    def test_explicit_word_limit_remains_available(self):
        text = " ".join(f"word{i}" for i in range(140)) + "."
        self.assertLessEqual(len(to_speakable(text, max_words=99).split()), 99)

    def test_comma_immediately_before_sir_is_removed(self):
        self.assertEqual(to_speakable("Certainly, sir."), "Certainly sir.")
        self.assertEqual(to_speakable("Done, Sir."), "Done Sir.")
        self.assertEqual(to_speakable("Yes,sir, I understand."), "Yes sir, I understand.")

    def test_other_commas_are_preserved(self):
        self.assertEqual(
            to_speakable("Hello, how are you, sir?"),
            "Hello, how are you sir?",
        )
        self.assertEqual(to_speakable("The sirloin is ready, sir."), "The sirloin is ready sir.")


if __name__ == "__main__":
    unittest.main()
