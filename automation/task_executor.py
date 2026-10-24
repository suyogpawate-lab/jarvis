"""Persistent multi-step task execution for JARVIS.

Plans are explicit, bounded, sequential, and stored locally. Ordinary steps run
without extra task approval; destructive data-loss steps pause for confirmation.
Execution stops on the first failed step. This is not a sandbox: steps still use
the normal CommandDispatcher and its existing permissions/guards.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Callable

from android.command_guard import authorize_command_once, requires_approval, revoke_command_authorization


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TASK_DIR = ROOT / "data" / "tasks"
MAX_STEPS = 10
MAX_STEP_LENGTH = 500

# Only actions likely to destroy or irreversibly replace data require an
# extra task-level confirmation. Routine communication, installs, settings,
# and ordinary shell steps do not trigger this blanket gate.
DESTRUCTIVE = re.compile(
    r"\b(?:delete|erase|wipe|shred|truncate|format|overwrite|purge|"
    r"factory\s+reset|reset\s+(?:the\s+)?device)\b"
    r"|(?:^|[;&|]\s*)\b(?:rm|rmdir|unlink|shred)\b"
    r"|\bdd\s+if=",
    re.IGNORECASE,
)
NESTED_TASK = re.compile(r"^\s*/task\b", re.IGNORECASE)
FAILURE_PREFIXES = ("[ERROR]", "[FAIL]", "[FAILED]", "[BLOCKED]", "[NEEDS_APPROVAL]")


class TaskExecutor:
    """Sequential task runner with durable state and destructive-action confirmation."""

    def __init__(
        self,
        dispatch: Callable[[str], object],
        task_dir=None,
        max_steps: int = MAX_STEPS,
    ):
        self.dispatch = dispatch
        self.task_dir = Path(task_dir) if task_dir is not None else DEFAULT_TASK_DIR
        self.max_steps = max(1, min(int(max_steps), MAX_STEPS))
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        if not re.fullmatch(r"task-[0-9a-f]{8}", str(task_id or "")):
            raise ValueError("Invalid task ID.")
        return self.task_dir / (task_id + ".json")

    def _save(self, task: dict) -> None:
        self.task_dir.mkdir(parents=True, exist_ok=True)
        task["updated_at"] = time.time()
        path = self._path(task["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)

    def _load(self, task_id: str):
        try:
            return json.loads(self._path(task_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _is_failure(result) -> bool:
        if result is None:
            return True
        if isinstance(result, dict):
            if result.get("error") or result.get("ok") is False:
                return True
            for key in ("exit", "exit_code", "returncode"):
                if key in result:
                    try:
                        if int(result[key]) != 0:
                            return True
                    except (TypeError, ValueError):
                        return True
            return False
        text = str(result).strip()
        upper = text.upper()
        if not text or any(upper.startswith(prefix) for prefix in FAILURE_PREFIXES):
            return True
        match = re.search(r"(?m)^\[EXIT\]\s*(-?\d+)\s*$", text)
        return bool(match and int(match.group(1)) != 0)

    @staticmethod
    def _is_destructive(step: str) -> bool:
        # Use the same risk rules as the shell guard, so one task approval
        # authorizes this exact command once instead of prompting twice.
        return bool(DESTRUCTIVE.search(step)) or requires_approval(step)

    def create(self, steps):
        if not isinstance(steps, (list, tuple)):
            return "[ERROR] Task steps must be a list."
        normalized = [str(step).strip() for step in steps]
        if not normalized or len(normalized) > self.max_steps:
            return f"[ERROR] A task must contain between 1 and {self.max_steps} steps."
        for index, step in enumerate(normalized, 1):
            if not step:
                return f"[ERROR] Step {index} is empty."
            if len(step) > MAX_STEP_LENGTH:
                return f"[ERROR] Step {index} exceeds {MAX_STEP_LENGTH} characters."
            if NESTED_TASK.match(step):
                return "[ERROR] Nested /task commands are not allowed inside a plan."
        task_id = "task-" + uuid.uuid4().hex[:8]
        task = {
            "id": task_id,
            "goal": " then ".join(normalized),
            "status": "PLANNED",
            "current_step": 0,
            "steps": [
                {
                    "number": i,
                    "command": step,
                    "status": "PENDING",
                    "requires_approval": self._is_destructive(step),
                    "result": None,
                    "started_at": None,
                    "finished_at": None,
                }
                for i, step in enumerate(normalized, 1)
            ],
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._save(task)
        preview = "\n".join(
            f"  {s['number']}. {s['command']}"
            + (" [destructive confirmation required]" if s["requires_approval"] else "")
            for s in task["steps"]
        )
        return (
            f"[TASK CREATED] {task_id}\n"
            f"Steps: {len(task['steps'])}\n{preview}\n"
            f"Review the plan, then run: /task run {task_id}"
        )

    def _render(self, task):
        lines = [
            f"Task {task['id']} — {task['status']}",
            f"Progress: {sum(s['status'] == 'COMPLETED' for s in task['steps'])}/{len(task['steps'])}",
        ]
        for step in task["steps"]:
            result = step.get("result")
            if result is not None:
                summary = str(result).replace("\n", " ").strip()
                if len(summary) > 180:
                    summary = summary[:177] + "..."
            else:
                summary = ""
            lines.append(f"{step['number']}. [{step['status']}] {step['command']}")
            if summary:
                lines.append(f"   Result: {summary}")
        if task["status"] == "WAITING_APPROVAL":
            current = task["steps"][task["current_step"]]
            lines.append(f"Approval needed for step {current['number']}. Reply: /task approve {task['id']}")
            lines.append(f"To refuse this step and stop the plan: /task deny {task['id']}")
        return "\n".join(lines)

    def _advance(self, task):
        while task["current_step"] < len(task["steps"]):
            step = task["steps"][task["current_step"]]
            if step["status"] == "COMPLETED":
                task["current_step"] += 1
                continue
            if step["requires_approval"] and step["status"] != "APPROVED":
                step["status"] = "WAITING_APPROVAL"
                task["status"] = "WAITING_APPROVAL"
                self._save(task)
                return self._render(task)
            task_approved = step["status"] == "APPROVED"
            step["status"] = "RUNNING"
            step["started_at"] = time.time()
            self._save(task)
            try:
                if task_approved:
                    authorize_command_once(step["command"])
                try:
                    result = self.dispatch(step["command"])
                finally:
                    if task_approved:
                        revoke_command_authorization(step["command"])
            except Exception as exc:
                result = f"[ERROR] {type(exc).__name__}: {exc}"
            step["result"] = result if isinstance(result, (str, int, float, bool, dict, list)) else str(result)
            step["finished_at"] = time.time()
            if self._is_failure(result):
                step["status"] = "FAILED"
                task["status"] = "FAILED"
                task["failure"] = f"Step {step['number']} failed; remaining steps were not executed."
                self._save(task)
                return self._render(task)
            step["status"] = "COMPLETED"
            task["current_step"] += 1
            self._save(task)
        task["status"] = "COMPLETED"
        self._save(task)
        return self._render(task)

    def recover_interrupted(self):
        """Pause tasks interrupted by process exit without blindly repeating work."""
        recovered = []
        for path in self.task_dir.glob("task-????????.json"):
            try:
                task = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if task.get("status") != "RUNNING":
                continue
            index = task.get("current_step", 0)
            steps = task.get("steps", [])
            if not isinstance(index, int) or not 0 <= index < len(steps):
                task["status"] = "PAUSED_RECOVERY"
                task["failure"] = "Interrupted task has an invalid current step; inspect status before resuming."
            else:
                step = steps[index]
                if step.get("status") == "RUNNING":
                    step["status"] = "PENDING"
                    step["result"] = "[RECOVERY] Previous process ended before completion was verified; this step was not automatically repeated."
                    step["started_at"] = None
                    step["finished_at"] = None
                task["status"] = "PAUSED_RECOVERY"
                task["failure"] = "Task was interrupted. Review the current step before resuming."
            self._save(task)
            recovered.append(task.get("id", path.stem))
        return recovered

    def handle(self, command: str, source: str = "external"):
        """Handle /task subcommands. Step text is always passed to normal dispatch."""
        parts = str(command or "").strip().split(maxsplit=2)
        if len(parts) < 2:
            return (
                "Usage:\n"
                "/task plan <step 1> || <step 2> [|| ...]\n"
                "/task run <task-id>\n/task status <task-id>\n"
                "/task list\n/task approve <task-id>\n"
                "/task deny <task-id>\n/task cancel <task-id>"
            )
        action = parts[1].lower()
        value = parts[2].strip() if len(parts) > 2 else ""
        if action == "plan":
            # Deliberately use a literal delimiter; don't guess natural-language boundaries.
            steps = [item.strip() for item in value.split("||")]
            return self.create(steps)
        if action == "list":
            tasks = []
            for path in self.task_dir.glob("task-????????.json"):
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                    tasks.append(item)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
            tasks.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
            if not tasks:
                return "[INFO] No saved multi-step tasks."
            return "\n\n".join(
                f"{item['id']} — {item['status']} — {len(item.get('steps', []))} steps"
                for item in tasks[:20]
            )
        if action not in {"run", "status", "approve", "deny", "cancel"}:
            return "[ERROR] Unknown task action. Use /task for usage."
        if not value:
            return f"[ERROR] Task ID required for /task {action}."
        task = self._load(value)
        if not task:
            return f"[ERROR] Task not found: {value}"
        if action == "status":
            return self._render(task)
        if action == "cancel":
            if task["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                return f"[INFO] Task is already {task['status']}."
            task["status"] = "CANCELLED"
            if task["current_step"] < len(task["steps"]):
                current = task["steps"][task["current_step"]]
                if current["status"] in {"PENDING", "WAITING_APPROVAL", "APPROVED"}:
                    current["status"] = "CANCELLED"
            self._save(task)
            return self._render(task)
        if action == "deny":
            if task["status"] != "WAITING_APPROVAL":
                return "[ERROR] This task is not waiting for a step approval."
            step = task["steps"][task["current_step"]]
            step["status"] = "DENIED"
            step["finished_at"] = time.time()
            task["status"] = "CANCELLED"
            task["failure"] = f"Step {step['number']} was denied; remaining steps were not executed."
            self._save(task)
            return self._render(task)
        if action == "run":
            if task["status"] not in {"PLANNED", "PAUSED_RECOVERY"}:
                return f"[ERROR] Only PLANNED or PAUSED_RECOVERY tasks can be started; current status is {task['status']}."
            task["status"] = "RUNNING"
            self._save(task)
            return self._advance(task)
        if action == "approve":
            if source != "text":
                return "[BLOCKED] Step approval is accepted only from typed terminal input."
            if task["status"] != "WAITING_APPROVAL":
                return "[ERROR] This task is not waiting for a step approval."
            step = task["steps"][task["current_step"]]
            # Approval is one-time and tied to the exact stored step text.
            step["status"] = "APPROVED"
            self._save(task)
            return self._advance(task)
        return "[ERROR] Unsupported task action."
