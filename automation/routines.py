"""Small, auditable multi-step routine runner.

Routines are Python data, not model-generated shell scripts. Each action is
validated and executed through an injected handler; a failed step stops the run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Step:
    name: str
    action: str
    argument: str = ""


ROUTINES = {
    "device_check": (
        Step("Local diagnostics", "doctor", "local"),
        Step("Provider configuration", "doctor", "providers"),
    ),
}


class RoutineRunner:
    def __init__(self, handler: Callable[[str, str], str]):
        self.handler = handler
        self.last_run = None

    @staticmethod
    def names():
        return sorted(ROUTINES)

    def run(self, name):
        key = str(name).strip().lower()
        if key not in ROUTINES:
            return {"ok": False, "error": "Unknown routine. Available: " + ", ".join(self.names())}
        results = []
        self.last_run = {"name": key, "status": "running", "steps": results}
        for step in ROUTINES[key]:
            if step.action not in {"doctor"}:
                results.append({"step": step.name, "ok": False, "result": "Action not allowlisted"})
                self.last_run["status"] = "failed"
                return self.last_run
            try:
                result = self.handler(step.action, step.argument)
                results.append({"step": step.name, "ok": True, "result": str(result)})
            except Exception as exc:
                results.append({"step": step.name, "ok": False, "result": type(exc).__name__})
                self.last_run["status"] = "failed"
                return self.last_run
        self.last_run["status"] = "complete"
        self.last_run["ok"] = True
        return self.last_run

    def format_result(self, name):
        result = self.run(name)
        if not result.get("ok"):
            return "[ROUTINE ERROR] " + result.get("error", result.get("status", "failed"))
        lines = ["[ROUTINE] {} — {}".format(result["name"], result["status"])]
        for item in result["steps"]:
            lines.append("{}: {}".format("OK" if item["ok"] else "FAILED", item["step"]))
            lines.append(item["result"])
        return "\n".join(lines)
