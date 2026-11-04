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
    def test_incoming_dm_emits_only_opaque_message_identifier(self):
        worker = WhatsAppAutoReplyWorker.__new__(WhatsAppAutoReplyWorker)
        events = []
        worker.autonomy_event_callback = lambda source, event_id: events.append((source, event_id))
        worker.handled_ids = set()
        worker.file_contacts = set()
        worker._failures = {}
        worker.max_age_seconds = 600
        worker._rate_limited = lambda chat: False
        worker._remember = lambda *args, **kwargs: None
        worker._history_text = lambda *args, **kwargs: "prior context"
        worker._generate_reply = lambda *args, **kwargs: (
            {"decision": "skip", "reason": "No reply needed"}, []
        )
        worker._finish = lambda ids: None
        message = {
            "id": "opaque-message-id",
            "timestamp": __import__("time").time(),
            "text": "PRIVATE MESSAGE BODY",
            "pushName": "PRIVATE SENDER",
        }
        worker._process_chat("contact@s.whatsapp.net", [message])
        self.assertEqual(events, [("whatsapp", "opaque-message-id")])
        self.assertNotIn("PRIVATE MESSAGE BODY", str(events))
        self.assertNotIn("PRIVATE SENDER", str(events))


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



    def test_youtube_video_id_accepts_youtube_hosts_only(self):
        self.assertEqual(
            WhatsAppAutoReplyWorker._youtube_video_id(
                "https://youtu.be/nSWEroBrY_w?si=example"
            ),
            "nSWEroBrY_w",
        )
        self.assertEqual(
            WhatsAppAutoReplyWorker._youtube_video_id(
                "https://www.youtube.com/watch?v=nSWEroBrY_w"
            ),
            "nSWEroBrY_w",
        )
        self.assertIsNone(
            WhatsAppAutoReplyWorker._youtube_video_id(
                "https://example.com/watch?v=nSWEroBrY_w"
            )
        )
        self.assertIsNone(
            WhatsAppAutoReplyWorker._youtube_video_id(
                "https://youtube.com.evil.example/watch?v=nSWEroBrY_w"
            )
        )

    def test_link_inspection_tool_is_available_without_file_permissions(self):
        worker = WhatsAppAutoReplyWorker.__new__(WhatsAppAutoReplyWorker)
        names = [
            item["function"]["name"]
            for item in worker._reply_tools(files_enabled=False)
        ]
        self.assertEqual(names, ["inspect_youtube_link"])

    def test_ask_owner_review_does_not_send_generic_acknowledgement(self):
        import queue
        import time

        class WhatsAppWithSend(FakeWhatsApp):
            def __init__(self):
                super().__init__()
                self.sent = []

            def send(self, chat_jid, message):
                self.sent.append((chat_jid, message))

        worker = WhatsAppAutoReplyWorker.__new__(WhatsAppAutoReplyWorker)
        worker.handled_ids = set()
        worker.max_age_seconds = 600
        worker.autonomy_event_callback = None
        worker.file_contacts = set()
        worker.pending_reply_reviews = {}
        worker._events = queue.Queue()
        worker.whatsapp = WhatsAppWithSend()
        worker._rate_limited = lambda chat: False
        worker._remember = lambda *args, **kwargs: None
        worker._history_text = lambda *args, **kwargs: "Earlier context"
        worker._generate_reply = lambda *args, **kwargs: (
            {
                "decision": "ask_owner",
                "reason": "The link's purpose is unclear.",
                "evidence": "YouTube link received; metadata needs owner review.",
                "reply": "",
                "alternatives": [],
            },
            [],
        )
        worker._save_state = lambda: None
        worker._finish = lambda ids: None

        worker._process_chat(
            "contact@s.whatsapp.net",
            [{
                "id": "review-message-1",
                "timestamp": time.time(),
                "text": "https://youtu.be/nSWEroBrY_w",
                "pushName": "Nehanth",
            }],
        )

        self.assertEqual(worker.whatsapp.sent, [])
        self.assertIn("review-message-1", worker.pending_reply_reviews)
        self.assertEqual(
            worker.pending_reply_reviews["review-message-1"]["reason"],
            "The link's purpose is unclear.",
        )


if __name__ == "__main__":
    unittest.main()
