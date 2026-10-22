#!/usr/bin/env python3
"""Local, side-effect-minimized JARVIS smoke checks; no provider calls."""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "data"}


def main():
    errors = []
    checked = 0
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            checked += 1
        except Exception as exc:
            errors.append("{}: {}".format(path.relative_to(ROOT), type(exc).__name__))
    try:
        import monitoring.doctor
        import automation.routines
        from android import command_guard
        assert callable(monitoring.doctor.run_doctor)
        assert "device_check" in automation.routines.RoutineRunner.names()
        assert callable(command_guard.check)
    except Exception as exc:
        errors.append("focused imports: {}: {}".format(type(exc).__name__, str(exc)[:160]))
    print("JARVIS smoke test: parsed {} Python files".format(checked))
    if errors:
        print("FAIL")
        for error in errors:
            print(" - " + error)
        return 1
    print("PASS: focused local imports; no provider/network calls performed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
