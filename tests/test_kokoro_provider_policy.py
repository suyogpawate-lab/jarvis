import unittest

from voice.onnx_provider_policy import select_onnx_providers
from voice.text_chunking import bounded_token_runs


class KokoroProviderPolicyTests(unittest.TestCase):
    def test_int8_prefers_xnnpack_on_android(self):
        self.assertEqual(
            select_onnx_providers(
                "auto", True,
                {"CPUExecutionProvider", "XnnpackExecutionProvider", "NnapiExecutionProvider"},
            ),
            ["XnnpackExecutionProvider", "CPUExecutionProvider"],
        )

    def test_fp16_prefers_nnapi_on_android(self):
        self.assertEqual(
            select_onnx_providers(
                "auto", False,
                {"CPUExecutionProvider", "XnnpackExecutionProvider", "NnapiExecutionProvider"},
            ),
            ["NnapiExecutionProvider", "CPUExecutionProvider"],
        )

    def test_cpu_fallback_when_android_accelerators_are_missing(self):
        self.assertEqual(
            select_onnx_providers("auto", False, {"CPUExecutionProvider"}),
            ["CPUExecutionProvider"],
        )

    def test_explicit_cpu_override_is_respected(self):
        self.assertEqual(
            select_onnx_providers(
                "cpu", True,
                {"CPUExecutionProvider", "XnnpackExecutionProvider"},
            ),
            ["CPUExecutionProvider"],
        )

    def test_long_token_runs_prefer_sentence_boundary(self):
        # 1 = ordinary phoneme, 2 = whitespace, 3 = sentence punctuation.
        tokens = [1] * 20 + [3] + [1] * 5 + [2] + [1] * 20
        runs = bounded_token_runs(
            tokens, limit=30, punctuation_tokens={3}, whitespace_token=2
        )
        self.assertEqual(runs[0][-1], 3)
        self.assertEqual([token for run in runs for token in run], tokens)

    def test_long_word_stream_falls_back_to_whitespace(self):
        tokens = [1] * 20 + [2] + [1] * 20
        runs = bounded_token_runs(tokens, limit=30, whitespace_token=2)
        self.assertEqual(runs[0][-1], 2)
        self.assertEqual([token for run in runs for token in run], tokens)

    def test_whitespace_free_stream_uses_hard_limit(self):
        tokens = list(range(70))
        runs = bounded_token_runs(tokens, limit=30)
        self.assertEqual([len(run) for run in runs], [30, 30, 10])
        self.assertEqual([token for run in runs for token in run], tokens)


if __name__ == "__main__":
    unittest.main()
