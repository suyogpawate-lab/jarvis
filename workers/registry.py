"""Optional worker registry.

No external coding-worker adapters are enabled in the lightweight Termux build.
Shared worker utilities and the independent Owl orchestrator remain available.
"""


def build_worker_registry():
    return {}
