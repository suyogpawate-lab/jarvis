"""Regression tests for explicit WhatsApp group-send confirmation."""

import queue
import unittest

from messaging.whatsapp_autoreply import WhatsAppAutoReplyWorker


class FakeWhatsApp:
    def __init__(self):
        self.sent = []

    def send(self, to, message):
        self.sent.append((to, message))
        return {"status": "sent", "to": to}


def make_worker():
    worker = WhatsAppAutoReplyWorker.__new__(WhatsAppAutoReplyWorker)
    worker.whatsapp = FakeWhatsApp()
    worker.pending_group_replies = {}
    worker._events = queue.Queue()
    worker._save_state = lambda: None
    return worker


class WhatsAppGroupConfirmationTests(unittest.TestCase):
    def test_explicit_group_message_is_queued_not_sent(self):
        worker = make_worker()
        result = worker.prepare_explicit_group_message(
            "120363012345678901@g.us",
            "Hello, I'm JARVIS.",
        )

        self.assertTrue(result["pending"])
        self.assertEqual(worker.whatsapp.sent, [])
        event = worker._events.get_nowait()
        self.assertEqual(event["type"], "GROUP_CONFIRMATION")
        self.assertEqual(event["group_subject"], "120363012345678901@g.us")
        self.assertEqual(event["text"], "Hello, I'm JARVIS.")

    def test_yes_sends_pending_message_to_group(self):
        worker = make_worker()
        worker.prepare_explicit_group_message(
            "120363012345678901@g.us",
            "Hello, I'm JARVIS.",
        )

        result = worker.confirm_latest_group_reply(True)

        self.assertEqual(
            worker.whatsapp.sent,
            [("120363012345678901@g.us", "Hello, I'm JARVIS.")],
        )
        self.assertIn("120363012345678901@g.us", result)
        self.assertEqual(worker.pending_group_replies, {})

    def test_no_cancels_without_sending(self):
        worker = make_worker()
        worker.prepare_explicit_group_message(
            "120363012345678901@g.us",
            "Hello, I'm JARVIS.",
        )

        result = worker.confirm_latest_group_reply(False)

        self.assertIn("cancelled", result.lower())
        self.assertEqual(worker.whatsapp.sent, [])
        self.assertEqual(worker.pending_group_replies, {})


if __name__ == "__main__":
    unittest.main()
