import unittest

from voice.text_chunking import chunk_text


class SpeechChunkingTests(unittest.TestCase):
    def test_short_response_is_not_split(self):
        text = "This is short. It should remain one response."
        self.assertEqual(chunk_text(text), [text])

    def test_long_response_groups_near_fifteen_words(self):
        text = (
            "One two three four five. "
            "Six seven eight nine ten. "
            "Eleven twelve thirteen fourteen fifteen. "
            "Sixteen seventeen eighteen nineteen twenty. "
            "Twenty one twenty two twenty three twenty four."
        )
        chunks = chunk_text(text)
        self.assertEqual([len(chunk.split()) for chunk in chunks], [15, 11])
        self.assertTrue(chunks[0].endswith("."))
        self.assertTrue(chunks[1].endswith("."))

    def test_commas_do_not_create_chunk_boundaries(self):
        first = (
            "This sentence includes commas, but the commas, never end a chunk "
            "because they are not sentence punctuation and should remain inside "
            "the same long sentence."
        )
        text = first + " The next sentence ends here!"
        chunks = chunk_text(text)
        self.assertEqual(chunks[0], first)
        self.assertTrue(chunks[-1].endswith("!"))

    def test_question_and_exclamation_marks_are_supported(self):
        text = (
            "Can we start now? Yes we can start now. "
            "This part is ready! And this part is ready too."
        )
        chunks = chunk_text(text)
        self.assertTrue(chunks)
        self.assertTrue(all(chunk[-1] in ".?!" for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
