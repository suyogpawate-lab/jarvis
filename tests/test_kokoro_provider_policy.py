import unittest

from voice.onnx_provider_policy import select_onnx_providers


class KokoroProviderPolicyTests(unittest.TestCase):
    def test_int8_prefers_cpu_even_when_xnnpack_is_available(self):
        self.assertEqual(
            select_onnx_providers(
                "auto", True,
                {"CPUExecutionProvider", "XnnpackExecutionProvider", "NnapiExecutionProvider"},
            ),
            ["CPUExecutionProvider"],
        )

    def test_int8_uses_cpu_when_it_is_the_only_provider(self):
        self.assertEqual(
            select_onnx_providers("auto", True, {"CPUExecutionProvider"}),
            ["CPUExecutionProvider"],
        )

    def test_fp16_prefers_nnapi_then_cpu_fallback(self):
        self.assertEqual(
            select_onnx_providers(
                "auto", False,
                {"CPUExecutionProvider", "XnnpackExecutionProvider", "NnapiExecutionProvider"},
            ),
            ["NnapiExecutionProvider", "CPUExecutionProvider"],
        )

    def test_fp16_falls_back_to_xnnpack_when_nnapi_is_missing(self):
        self.assertEqual(
            select_onnx_providers(
                "auto", False,
                {"CPUExecutionProvider", "XnnpackExecutionProvider"},
            ),
            ["XnnpackExecutionProvider", "CPUExecutionProvider"],
        )

    def test_cpu_override_is_respected(self):
        self.assertEqual(
            select_onnx_providers(
                "cpu", True,
                {"CPUExecutionProvider", "XnnpackExecutionProvider"},
            ),
            ["CPUExecutionProvider"],
        )

    def test_explicit_xnnpack_override_is_respected_for_int8(self):
        self.assertEqual(
            select_onnx_providers(
                "xnnpack", True,
                {"CPUExecutionProvider", "XnnpackExecutionProvider"},
            ),
            ["XnnpackExecutionProvider", "CPUExecutionProvider"],
        )

    def test_unavailable_explicit_provider_falls_back_to_cpu(self):
        self.assertEqual(
            select_onnx_providers("nnapi", True, {"CPUExecutionProvider"}),
            ["CPUExecutionProvider"],
        )


if __name__ == "__main__":
    unittest.main()
