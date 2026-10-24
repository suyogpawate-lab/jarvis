import json
import unittest
from unittest.mock import MagicMock, patch

from screen_cast.receiver import ScreenCastReceiver, _coordinate


class ScreenCastReceiverTests(unittest.TestCase):
    def test_status_starts_empty_and_ram_only(self):
        status = ScreenCastReceiver(port=0).status()
        self.assertFalse(status["streaming"])
        self.assertEqual(status["storage"], "RAM only")
        self.assertEqual(status["frames_received"], 0)

    def test_coordinate_validation(self):
        self.assertEqual(_coordinate(42, "x"), 42)
        for value in (-1, 10001, "42", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _coordinate(value, "x")

    def test_unknown_action_rejected_before_connect(self):
        with self.assertRaises(ValueError):
            ScreenCastReceiver().control({"action": "unsupported"})

    def test_snapshot_action_is_allowed_and_forwarded(self):
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.recv.side_effect = [b'{"ok":true,"type":"screen_accessibility","elements":[]}', b'\n']
        with patch("screen_cast.receiver.socket.create_connection", return_value=fake):
            result = ScreenCastReceiver().control({"action": "snapshot"})
        self.assertTrue(result["ok"])
        payload = json.loads(fake.sendall.call_args.args[0].decode().strip())
        self.assertEqual(payload["action"], "snapshot")

    def test_click_element_index_is_validated(self):
        with self.assertRaises(ValueError):
            ScreenCastReceiver().control({"action": "click_element", "element_index": 250})

    def test_swipe_duration_is_bounded(self):
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.recv.side_effect = [b'{"ok":true}\n']
        with patch("screen_cast.receiver.socket.create_connection", return_value=fake):
            result = ScreenCastReceiver().control({
                "action": "swipe", "x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_ms": 99999
            })
        self.assertTrue(result["ok"])
        payload = json.loads(fake.sendall.call_args.args[0].decode().strip())
        self.assertEqual(payload["duration_ms"], 1500)

    def test_frame_reader_handles_partial_reads(self):
        class FakeSocket:
            def __init__(self):
                self.parts = [b"\x00", b"\x00\x00", b"\x03", b"abc"]
            def recv(self, count):
                return self.parts.pop(0) if self.parts else b""
        fake = FakeSocket()
        self.assertEqual(ScreenCastReceiver._read_exact(fake, 4), b"\x00\x00\x00\x03")
        self.assertEqual(ScreenCastReceiver._read_exact(fake, 3), b"abc")


if __name__ == "__main__":
    unittest.main()
