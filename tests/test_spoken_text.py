import unittest

from voice.spoken import to_speakable


class SpokenTextTests(unittest.TestCase):
    def test_line_wrap_does_not_insert_a_sentence_boundary(self):
        text = (
            "All of your unread emails have been marked\n"
            "as read. Let me know if there's anything else you'd like to\n"
            "do!"
        )
        self.assertEqual(
            to_speakable(text),
            "All of your unread emails have been marked as read. "
            "Let me know if there's anything else you'd like to do!",
        )

    def test_existing_sentence_punctuation_is_preserved(self):
        self.assertEqual(
            to_speakable("First sentence.\nSecond sentence!"),
            "First sentence. Second sentence!",
        )

    def test_unpunctuated_final_reply_gets_one_terminal_period(self):
        self.assertEqual(to_speakable("JARVIS is ready\nAwaiting commands"), "Jarvis is ready Awaiting commands.")


if __name__ == "__main__":
    unittest.main()
