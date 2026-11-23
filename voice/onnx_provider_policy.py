"""Conservative ONNX Runtime provider selection for Android Kokoro."""


def select_onnx_providers(requested_ep, quantized_int8, available):
    """Choose an Android accelerator when available, retaining CPU fallback.

    INT8 models use XNNPACK first; FP16 models use NNAPI first. Explicit
    JARVIS_KOKORO_EP settings remain authoritative.
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
            ["XnnpackExecutionProvider", "NnapiExecutionProvider"]
            if quantized_int8 else ["NnapiExecutionProvider"]
        )
        selected = next((name for name in preferred if name in available), cpu)
    else:
        selected = choices.get(requested, cpu)
        if selected not in available:
            selected = cpu
    if selected == cpu:
        return [cpu]
    return [selected, cpu]
