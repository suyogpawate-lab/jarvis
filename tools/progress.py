"""Live progress updates for multi-step tasks.

FastAgent calls emit() before each tool step, so JARVIS tells you what it is
doing as it goes (like Claude Code does) instead of going silent until the end.

Where the text appears:
  - request came from the web UI / terminal UI -> shown in its reply box
  - request came from the plain terminal       -> printed in the terminal
Only the final answer is spoken aloud; progress lines are text only.
"""

import sys
import time


def _ui_state():
    """The shared UI state dict, but only while a UI request is running."""
    ui = sys.modules.get("jarvis_ui")
    state = getattr(ui, "S", None)
    if isinstance(state, dict) and state.get("busy"):
        return state
    return None


def emit(text):
    text = str(text or "").strip()
    if not text:
        return

    state = _ui_state()
    if state is not None:
        current = state.get("reply") or ""
        if not current:
            state["reply_t"] = time.time()
        state["reply"] = (current + "\n" if current else "") + text
        return

    print(f"\n  {text}", flush=True)
