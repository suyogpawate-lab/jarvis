# JARVIS local intelligence engines

These optional engines do not replace Groq as the primary reasoning model.

## Vector-only vision

Configure JARVIS_VISION_ONNX and JARVIS_VISION_PROTOTYPES. The ONNX image encoder
must share an embedding space with the precomputed text prototypes. The manifest
contains schema_version=1, input_size, mean, std and labels [{label, embedding}].
Prototype vectors must come from the matching text encoder and match the image
encoder output dimension. Arbitrary SmolVLM vision outputs are not assumed to be
CLIP-aligned. The engine does not perform OCR or accessibility extraction.

Optional test dependencies: Termux python-numpy, onnxruntime and Pillow.
Model weights and prototype files are not committed to Git.

## Forecasting

ForecastEngine currently provides a deterministic damped-median-trend baseline.
It is not Chronos-Bolt, Timestral or Lag-Llama. A foundation model requires a
validated ONNX export plus a model-specific input/output adapter. Benchmark against
the baseline on chronological held-out device telemetry before enabling it.

## LoRA / DPO / RLHF

Collect only explicitly approved prompt/chosen/rejected pairs using the existing
learning feedback store. Train adapters off-device. Preserve a frozen baseline and
a versioned, leakage-free evaluation set. Promotion requires task accuracy,
instruction-following and safety metrics to remain within the configured regression
budget. Never automatically replace the baseline. Classical RLHF additionally
requires a reward model and controlled policy optimization; preference capture alone
is not RLHF.
