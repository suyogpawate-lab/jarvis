"""
Tiny .env loader (no third-party dependency).

Reads <project root>/.env and puts its KEY=VALUE pairs into os.environ.
Variables that are already set in the real environment always win, so
`export GROQ_API_KEYS=...` in your shell still overrides the file.

`python setup.py` writes this file for you.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"


def parse_env_line(line):
    """Return (key, value) for a KEY=VALUE line, or None for blanks/comments."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].lstrip()
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key, value = key.strip(), value.strip()
    if not key:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    elif " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return key, value


def load_env(path=ENV_FILE, override=False):
    """Load the .env file. Returns True if a file was read."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    for line in text.splitlines():
        parsed = parse_env_line(line)
        if not parsed:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value
    return True
TERMUX_BASH = "/data/data/com.termux/files/usr/bin/bash"
