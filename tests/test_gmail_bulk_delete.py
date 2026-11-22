import unittest
from unittest.mock import patch

from messaging.email_manager import EmailManager


class FakeIMAP:
    def __init__(self):
        self.calls = []
        self.logged_out = False

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b""]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "search":
            return "OK", [b"101 102 103"]
        if command == "store":
            uid = args[0]
            if uid == b"102" and args[1] == "+X-GM-LABELS":
                return "NO", []
            return "OK", []
        raise AssertionError(f"Unexpected IMAP command: {command}")

    def logout(self):
        self.logged_out = True
        return "BYE", []


class GmailBulkDeleteTests(unittest.TestCase):
    def test_bulk_delete_moves_matches_to_trash_without_expunging(self):
        manager = EmailManager()
        fake = FakeIMAP()
        account = {"email": "owner@example.com", "password": "unused"}

        with patch.object(manager, "_account", return_value=account), patch.object(
            manager, "_imap", return_value=fake
        ):
            result = manager.delete_matching_sender("github.com")

        self.assertEqual(result["matched"], 3)
        self.assertEqual(result["processed"], 3)
        self.assertEqual(result["moved_to_trash"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertFalse(result["permanent_delete"])
        self.assertTrue(fake.logged_out)
        self.assertFalse(any(call[0] == "expunge" for call in fake.calls))
        self.assertIn(("select", "[Gmail]/All Mail", False), fake.calls)
        self.assertIn(("store", b"101", "+X-GM-LABELS", r"(\Trash)"), fake.calls)

    def test_bulk_delete_rejects_invalid_sender_domain(self):
        manager = EmailManager()
        with self.assertRaises(ValueError):
            manager.delete_matching_sender("not a domain")


if __name__ == "__main__":
    unittest.main()
