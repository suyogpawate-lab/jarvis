import tempfile
import unittest
from pathlib import Path

from scripts.build_kokoro_voice_blend import blend


class KokoroVoiceBlendTests(unittest.TestCase):
    def test_blend_is_70_percent_base_and_30_percent_nicole(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "am_onyx.bin"
            donor = root / "af_nicole.bin"
            output = root / "jarvis_nicole30.bin"
            base.write_bytes(b"".join(__import__("struct").pack("<f", 0.0) for _ in range(256)))
            donor.write_bytes(b"".join(__import__("struct").pack("<f", 1.0) for _ in range(256)))
            size = blend(base, donor, output, 0.30)
            values = __import__("struct").unpack("<256f", output.read_bytes())
            self.assertEqual(size, 1024)
            self.assertTrue(all(abs(value - 0.30) < 1e-6 for value in values))

    def test_rejects_different_voice_pack_sizes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, donor = root / "a.bin", root / "b.bin"
            base.write_bytes(b"\0" * 1024)
            donor.write_bytes(b"\0" * 2048)
            with self.assertRaises(ValueError):
                blend(base, donor, root / "out.bin", 0.30)


if __name__ == "__main__":
    unittest.main()
