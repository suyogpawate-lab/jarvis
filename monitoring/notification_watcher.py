"""
Automatic Android notification watcher for JARVIS.

Notifications are tracked in RAM only.
New notifications are collected into a short batch and analyzed together.
"""

import threading
import queue
import time

from monitoring.notification_ingestor import NotificationIngestor
from agents.fast_agent import FastAgent


class NotificationWatcher:
    def __init__(
        self,
        output_queue,
        poll_interval=2.0,
        batch_window=3.0,
        max_seen=500,
        output_callback=None,
        cooldown_seconds=30.0,
    ):
        self.output_queue = output_queue
        self.output_callback = output_callback

        self.poll_interval = poll_interval
        self.batch_window = batch_window
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.last_summary_at = 0.0
        self.max_seen = max_seen

        self.notifications = NotificationIngestor(timeout=4)
        self.fast_agent = FastAgent()

        self.seen = {}
        self.pending = []

        self.stop_event = threading.Event()
        self.thread = None

    def _signature(self, notification):
        return (
            notification.get("key", ""),
            notification.get("title", ""),
            notification.get("content", ""),
            notification.get("when", ""),
        )

    def _trim(self):
        while len(self.seen) > self.max_seen:
            oldest = next(iter(self.seen))
            self.seen.pop(oldest, None)

    def _baseline(self):
        current = self.notifications.list()

        if isinstance(current, dict):
            return

        for notification in current:
            key = notification.get("key") or self._signature(
                notification
            )
            self.seen[key] = self._signature(notification)

        self._trim()

    def _collect_new(self):
        current = self.notifications.list()

        if isinstance(current, dict):
            return

        for notification in current:
            package = notification.get("package", "")

            if package == "com.termux":
                continue

            key = notification.get("key") or self._signature(
                notification
            )
            signature = self._signature(notification)

            previous = self.seen.get(key)

            if previous is None:
                self.seen[key] = signature
                self.pending.append(notification)

            elif previous != signature:
                self.seen[key] = signature
                self.pending.append(notification)

        self._trim()

    def _analyze_batch(self, notifications):
        if not notifications:
            return

        items = []

        for notification in notifications:
            package = notification.get("package", "")
            title = notification.get("title", "")
            content = notification.get("content", "")

            if not title and not content:
                continue

            items.append(
                f"APP: {package}\n"
                f"TITLE: {title}\n"
                f"CONTENT: {content}"
            )

        if not items:
            return

        prompt = (
            "You are JARVIS. Summarize these newly received Android "
            "notifications into ONE extremely concise, informative paragraph. "
            "Combine related notifications naturally. Mention only important "
            "information. Do not invent anything. Do not use bullets, headings, "
            "labels, or Markdown. Plain paragraph only.\n\n"
            + "\n\n".join(items)
        )

        try:
            result = self.fast_agent.ask(prompt)

            if not result:
                return

            result = result.strip()

            if self.output_callback:
                delivered = self.output_callback(result)

                if delivered:
                    self.last_summary_at = time.monotonic()
                    return

            self.output_queue.put(result)
            self.last_summary_at = time.monotonic()

        except Exception:
            pass

    def _flush_pending(self):
        if not self.pending:
            return

        # Keep queued notifications until the cooldown expires; this prevents
        # a sustained notification storm from triggering repeated summaries.
        remaining = self.cooldown_seconds - (
            time.monotonic() - self.last_summary_at
        )
        if remaining > 0:
            return

        batch = self.pending[:]
        self.pending.clear()
        self._analyze_batch(batch)

    def _run(self):
        self._baseline()

        while not self.stop_event.is_set():
            try:
                self._collect_new()

                if self.pending:
                    deadline = (
                        time.monotonic()
                        + self.batch_window
                    )

                    while (
                        time.monotonic() < deadline
                        and not self.stop_event.is_set()
                    ):
                        self._collect_new()
                        self.stop_event.wait(0.5)

                    # During cooldown, keep collecting new notifications into
                    # the same pending batch instead of summarizing each burst.
                    while self.pending and not self.stop_event.is_set():
                        remaining = self.cooldown_seconds - (
                            time.monotonic() - self.last_summary_at
                        )
                        if remaining <= 0:
                            break
                        self._collect_new()
                        self.stop_event.wait(min(0.5, remaining))

                    self._flush_pending()

            except Exception:
                pass

            self.stop_event.wait(
                self.poll_interval
            )

    def start(self):
        if self.thread and self.thread.is_alive():
            return self

        self.stop_event.clear()

        self.thread = threading.Thread(
            target=self._run,
            name="JARVIS-NotificationWatcher",
            daemon=True,
        )

        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()
