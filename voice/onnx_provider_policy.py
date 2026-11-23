"""Conservative ONNX Runtime provider selection for Android Kokoro."""


def select_onnx_providers(requested_ep, quantized_int8, available):
    """Choose a provider based on model quantization, retaining CPU fallback.

    ONNX Runtime's mobile guidance recommends starting with CPU for quantized
    models. XNNPACK is primarily a floating-point CPU accelerator and may not
    cover the quantized operators in every Kokoro INT8 graph. Keep it available
    through JARVIS_KOKORO_EP=xnnpack so device-specific benchmarks can compare
    it against CPU. FP16 can use NNAPI when the runtime exposes that provider.
    """
    available = set(available or ())
    cpu = "CPUExecutionProvider"
    choices = {
        "xnnpack": "XnnpackExecutionProvider",
        "nnapi": "NnapiExecutionProvider",
        "cpu": cpu,
    }
    requested = str(requested_ep or "auto").strip().lower()
    if requested == "auto":
        preferred = (
            [cpu] if quantized_int8 else ["NnapiExecutionProvider", "XnnpackExecutionProvider"]
        )
        selected = next((name for name in preferred if name in available), cpu)
    else:
        selected = choices.get(requested, cpu)
        if selected not in available:
            selected = cpu
    if selected == cpu:
        return [cpu]
    return [selected, cpu]
