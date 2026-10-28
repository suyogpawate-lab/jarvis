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

    def test_cooldown_can_be_disabled(self):
        watcher = self.make_watcher(cooldown=0)
        with patch.object(watcher, "_analyze_batch") as analyze:
            watcher._flush_pending()
        analyze.assert_called_once()


if __name__ == "__main__":
    unittest.main()
