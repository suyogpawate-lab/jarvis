"""Small terminal-display helpers used by the JARVIS CLI."""
from __future__ import annotations

import sys


def clear_scrollback(stream=None) -> bool:
    """Clear the visible terminal and its scrollback without touching chat data.

    CSI 3 J clears the terminal emulator's saved scrollback; CSI 2 J clears the
    visible screen; CSI H homes the cursor. Return False when output is not a TTY.
    """
    target = sys.stdout if stream is None else stream
    isatty = getattr(target, "isatty", None)
    if not callable(isatty) or not isatty():
        return False
    target.write("\x1b[3J\x1b[2J\x1b[H")
    target.flush()
    return True
