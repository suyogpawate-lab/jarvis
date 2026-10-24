#!/usr/bin/env python3
"""Compact JARVIS launcher for the Termux:Float terminal app.

Uses the same project, configuration, services, voice listener, and memory as
the normal CLI. It does not install or replace any Android application.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
os.environ["JARVIS_FLOAT_MODE"] = "1"
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis import main


if __name__ == "__main__":
    main()
