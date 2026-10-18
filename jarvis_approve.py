#!/usr/bin/env python3
"""Owner-only approval for shell commands JARVIS wants to run.

    python jarvis_approve.py list
    python jarvis_approve.py yes <code>
    python jarvis_approve.py no  <code>
"""
import sys
import time

from android.command_guard import _load, _purge, _save


def main(argv):
    data = _purge(_load())
    if not argv or argv[0] == "list":
        if not data:
            print("Nothing waiting for approval.")
        for code, e in data.items():
            left = int(e["expires"] - time.time())
            state = "APPROVED" if e.get("approved") else "waiting"
            print(f"[{code}] {state}, {left}s left\n    {e['command']}")
        return 0

    if len(argv) != 2 or argv[0] not in ("yes", "no") or argv[1] not in data:
        print("Usage: jarvis_approve.py list | yes <code> | no <code>  (unknown or expired code?)")
        return 1

    action, code = argv
    entry = data[code]
    if action == "no":
        del data[code]
        _save(data)
        print("Denied and removed.")
        return 0

    print("JARVIS wants to run, ONCE:\n\n    " + entry["command"] + "\n")
    if input("Allow this exact command? [y/N] ").strip().lower() != "y":
        print("Not approved.")
        return 1
    entry["approved"] = True
    _save(data)
    print("Approved. Ask JARVIS to run it again.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
