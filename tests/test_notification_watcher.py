import queue
import time
import unittest
from unittest.mock import patch

from monitoring.notification_watcher import NotificationWatcher


class NotificationWatcherCooldownTests(unittest.TestCase):
    def make_watcher(self, cooldown=30.0):
        watcher = NotificationWatcher(
            output_queue=queue.Queue(),
            cooldown_seconds=cooldown,
        )
        watcher.pending = [{"title": "Message", "content": "Hello"}]
        return watcher

    def test_flush_keeps_pending_batch_during_cooldown(self):
        watcher = self.make_watcher(cooldown=30.0)
        watcher.last_summary_at = time.monotonic()

        with patch.object(watcher, "_analyze_batch") as analyze:
            watcher._flush_pending()

        analyze.assert_not_called()
        self.assertEqual(len(watcher.pending), 1)

    def test_flush_summarizes_accumulated_batch_after_cooldown(self):
        watcher = self.make_watcher(cooldown=30.0)
        watcher.last_summary_at = time.monotonic() - 31
        batch = watcher.pending[:]

        with patch.object(watcher, "_analyze_batch") as analyze:
            watcher._flush_pending()

        analyze.assert_called_once_with(batch)
        self.assertEqual(watcher.pending, [])

    def test_new_notification_emits_only_opaque_event_identifier(self):
        events = []
        watcher = NotificationWatcher(
            output_queue=queue.Queue(),
            autonomy_event_callback=lambda source, event_id: events.append((source, event_id)),
        )
        watcher.notifications.list = lambda: [{
            "key": "private-notification-key",
            "package": "com.example.chat",
            "title": "Security alert",
            "content": "Urgent security alert: private message body",
            "when": "123",
        }]
        watcher._collect_new()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "notification")
        self.assertNotIn("Private", events[0][1])
        self.assertNotIn("private-notification-key", events[0][1])

    def test_routine_notification_is_ignored(self):
        watcher = NotificationWatcher(output_queue=queue.Queue())
        watcher.notifications.list = lambda: [{
            "key": "routine-key",
            "package": "com.example.social",
            "title": "New activity",
            "content": "Someone liked a post",
            "when": "123",
        }]
        watcher._collect_new()
        self.assertEqual(watcher.pending, [])

    def test_same_notification_is_not_requeued_when_timestamp_changes(self):
        watcher = NotificationWatcher(output_queue=queue.Queue())
        current = [{
            "key": "stable-key",
            "package": "com.example.chat",
            "title": "Security alert",
            "content": "Urgent security alert: sign-in attempt",
            "when": "123",
        }]
        watcher.notifications.list = lambda: current
        watcher._collect_new()
        current[0] = {**current[0], "when": "456"}
        watcher._collect_new()
        self.assertEqual(len(watcher.pending), 1)

    def test_cooldown_can_be_disabled(self):
        watcher = self.make_watcher(cooldown=0)
        with patch.object(watcher, "_analyze_batch") as analyze:
            watcher._flush_pending()
        analyze.assert_called_once()


if __name__ == "__main__":
    unittest.main()
