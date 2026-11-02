"""Regression tests for WhatsApp context assembly and delivery reliability."""

import unittest

from messaging.whatsapp_autoreply import WhatsAppAutoReplyWorker


class FakeWhatsApp:
    def __init__(self, history=None, ack_error=None):
        self.history = history or []
        self.ack_error = ack_error
        self.ack_calls = []

    def get_history(self, chat_jid, limit=12):
        return self.history

    def acknowledge_messages(self, ids):
        self.ack_calls.append(list(ids))
        if self.ack_error:
            raise self.ack_error
        return {"ok": True, "acknowledged": len(ids)}


def make_worker():
    worker = WhatsAppAutoReplyWorker.__new__(WhatsAppAutoReplyWorker)
    worker.context_limit = 12
    worker.context = {
        "chat@s.whatsapp.net": [
            {"role": "incoming", "sender": "Alex", "text": "Earlier topic",
             "message_id": "old-1"},
            {"role": "incoming", "sender": "Alex", "text": "Current message",
             "message_id": "new-1"},
        ]
    }
    worker.whatsapp = FakeWhatsApp()
    worker.handled_ids = set()
    worker.pending_ack_ids = set()
    worker._save_state = lambda: None
    return worker


class WhatsAppContextReliabilityTests(unittest.TestCase):
    def test_bridge_history_excludes_current_batch_and_deduplicates(self):
        worker = make_worker()
        worker.whatsapp.history = [
            {"id": "old-1", "fromMe": False, "pushName": "Alex",
             "text": "Earlier topic"},
            {"id": "new-1", "fromMe": False, "pushName": "Alex",
             "text": "Current message"},
            {"id": "old-1", "fromMe": False, "pushName": "Alex",
             "text": "Earlier topic"},
        ]

        result = worker._history_text(
            "chat@s.whatsapp.net", exclude_ids=["new-1"]
        )

        self.assertEqual(result, "Alex: Earlier topic")
        self.assertNotIn("Current message", result)

    def test_history_failure_is_visible_and_uses_local_context(self):
        worker = make_worker()

        def fail(*args, **kwargs):
            raise RuntimeError("bridge offline")

        worker.whatsapp.get_history = fail
        result = worker._history_text(
            "chat@s.whatsapp.net", exclude_ids=["new-1"]
        )

        self.assertIn("LOCAL FALLBACK", result)
        self.assertIn("bridge retrieval failed", result)
        self.assertIn("Earlier topic", result)
        self.assertNotIn("Current message", result)

    def test_empty_bridge_history_uses_local_fallback(self):
        worker = make_worker()
        worker.whatsapp.history = []
        result = worker._history_text(
            "chat@s.whatsapp.net", exclude_ids=["new-1"]
        )
        self.assertIn("Earlier topic", result)
        self.assertNotIn("Current message", result)

    def test_failed_ack_is_persistently_queued_for_retry(self):
        worker = make_worker()
        worker.whatsapp.ack_error = RuntimeError("temporary failure")

        worker._finish(["msg-1"])

        self.assertIn("msg-1", worker.handled_ids)
        self.assertIn("msg-1", worker.pending_ack_ids)

        worker.whatsapp.ack_error = None
        worker._retry_pending_acknowledgements()

        self.assertNotIn("msg-1", worker.pending_ack_ids)
        self.assertEqual(worker.whatsapp.ack_calls, [["msg-1"], ["msg-1"]])


if __name__ == "__main__":
    unittest.main()
