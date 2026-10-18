#!/usr/bin/env python3

import sys
import traceback

from core import Jarvis
from automation.command_dispatcher import CommandDispatcher
from core.discussion import DiscussionCoordinator
from memory import MemoryManager


def main():
    if len(sys.argv) < 2:
        print("ERROR: missing command", flush=True)
        return 2

    command = " ".join(sys.argv[1:]).strip()

    if not command:
        print("ERROR: empty command", flush=True)
        return 2

    try:
        jarvis = Jarvis()
        discussion = DiscussionCoordinator()
        memory = MemoryManager()

        dispatcher = CommandDispatcher(
            jarvis,
            discussion,
            memory,
        )

        result = dispatcher.dispatch(command)

        if result is None:
            result = ""

        print(str(result).strip(), flush=True)
        return 0

    except Exception as exc:
        print(
            f"JARVIS BRIDGE ERROR: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
