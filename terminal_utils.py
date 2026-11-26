"""Small terminal-display helpers used by the JARVIS CLI."""
from __future__ import annotations

import os
import sys


def clear_scrollback(stream=None) -> bool:
    """Clear the visible terminal and its scrollback without touching chat data.

    Write the terminal control bytes directly to the TTY file descriptor. This
    avoids text-stream wrappers that may sanitize or rewrite ESC characters.
    CSI 3 J clears saved scrollback; CSI 2 J clears the visible screen; CSI H
    homes the cursor. Return False when output is not a TTY.
    """
    target = sys.stdout if stream is None else stream
    isatty = getattr(target, "isatty", None)
    if not callable(isatty) or not isatty():
        return False

    sequence = b"\x1b[3J\x1b[2J\x1b[H"
    target.flush()
    try:
        fd = target.fileno()
    except (AttributeError, OSError, ValueError):
        target.write(sequence.decode("ascii"))
        target.flush()
        return True

    view = memoryview(sequence)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("terminal clear sequence could not be written")
        view = view[written:]
    return True
