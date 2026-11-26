#!/usr/bin/env python3
"""Run fast, local-only JARVIS Phase 1 checks without provider/API calls."""
from __future__ import annotations

import argparse
import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "data"}


def iter_python_files():
    """Yield repository Python files, excluding only repository-relative directories."""
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--syntax-only",
        action="store_true",
        help="scan Python syntax without running unittest discovery (for CI before pytest)",
    )
    args = parser.parse_args()

    errors = []
    checked = 0
    for path in iter_python_files():
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            checked += 1
        except Exception as exc:
            errors.append("{}: {}: {}".format(path.relative_to(ROOT), type(exc).__name__, exc))

    if checked == 0:
        errors.append("syntax scan found no Python files; refusing a false pass")

    if args.syntax_only:
        if errors:
            print("FAIL")
            for error in errors:
                print(" - " + error)
            return 1
        print("PASS: syntax scan parsed {} Python files.".format(checked))
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=180,
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
