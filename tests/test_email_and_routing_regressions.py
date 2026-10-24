"""Regression tests for Gmail read status and conversation routing."""

import unittest
from unittest.mock import patch

from messaging.email_manager import EmailManager
from agents.fast_agent import FastAgent


class FakeIMAP:
    def __init__(self, unread_uids):
        self.unread_uids = unread_uids
        self.selected = []
        self.stored = []
        self.closed = False

    def select(self, mailbox, readonly=False):
        self.selected.append((mailbox, readonly))
        return "OK", [b"1"]

    def uid(self, command, *args):
        if command == "search":
            return "OK", [b" ".join(self.unread_uids)]
        if command == "store":
            self.stored.append((args[0], args[1], args[2]))
            return "OK", [b"updated"]
        raise AssertionError(f"Unexpected IMAP command: {command}")

    def close(self):
        self.closed = True

    def logout(self):
        return "BYE", []


class EmailMarkReadTests(unittest.TestCase):
    def test_marks_all_unread_inbox_messages_read(self):
        manager = EmailManager()
        fake = FakeIMAP([b"12", b"15", b"19"])
        manager._account = lambda requested=None: {
            "email": "test@example.com",
            "password": "unused",
        }
        manager._imap = lambda account: fake

        result = manager.mark_all_unread_as_read()

        self.assertEqual(result["marked_read"], 3)
        self.assertEqual(result["mailbox"], "INBOX")
        self.assertEqual(fake.selected, [("INBOX", False)])
        self.assertEqual(fake.stored, [(b"12,15,19", "+FLAGS", r"(\Seen)")])

    def test_no_unread_messages_is_a_successful_noop(self):
        manager = EmailManager()
        fake = FakeIMAP([])
        manager._account = lambda requested=None: {
            "email": "test@example.com",
            "password": "unused",
        }
        manager._imap = lambda account: fake

        result = manager.mark_all_unread_as_read()

        self.assertEqual(result["marked_read"], 0)
        self.assertEqual(fake.stored, [])

    def test_old_conversation_context_does_not_trigger_engineering_plan(self):
        prompt = (
            "Conversation history: fix the repository and run tests.\n"
            "CURRENT USER MESSAGE:\n"
            "say hey jarvis\n"
            "Older task: modify the project files."
        )
        self.assertFalse(FastAgent._is_complex_shell_project(prompt))

    def test_real_project_task_still_triggers_engineering_plan(self):
        prompt = "CURRENT USER MESSAGE:\nFix the JARVIS repository tests across files."
        self.assertTrue(FastAgent._is_complex_shell_project(prompt))


if __name__ == "__main__":
    unittest.main()
