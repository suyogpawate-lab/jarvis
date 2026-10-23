#!/usr/bin/env python3
"""Run fast, local-only JARVIS Phase 1 checks without provider/API calls."""
from __future__ import annotations

import ast
import pathlib
import subprocess
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
            errors.append("{}: {}: {}".format(path.relative_to(ROOT), type(exc).__name__, exc))

    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=60,
    )
    print("JARVIS smoke test: parsed {} Python files".format(checked))
    print(result.stdout.rstrip())
    if result.returncode:
        errors.append("unit tests exited with status {}".format(result.returncode))
    if errors:
        print("FAIL")
        for error in errors:
            print(" - " + error)
        return 1
    print("PASS: syntax scan and local regression tests; no provider/network calls performed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
