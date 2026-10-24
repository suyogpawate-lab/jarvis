"""JARVIS Skill Forge: turn completed task workflows into reusable local skills.

Skills are explicit, user-curated templates. Running a skill creates a fresh
normal TaskExecutor task, so existing command routing, journaling, and
destructive-action confirmation remain in force.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILL_DIR = ROOT / "data" / "skills"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_TASK_RE = re.compile(r"^task-[0-9a-f]{8}$")
_MAX_STEPS = 10
_MAX_STEP_LENGTH = 500


class SkillForge:
    def __init__(self, task_executor, skill_dir=None):
        self.task_executor = task_executor
        self.skill_dir = Path(skill_dir) if skill_dir is not None else DEFAULT_SKILL_DIR
        self.skill_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _slug(name: str) -> str:
        value = re.sub(r"[^a-z0-9_-]+", "-", str(name or "").strip().lower())
        value = re.sub(r"-{2,}", "-", value).strip("-_")
        if not _NAME_RE.fullmatch(value):
            raise ValueError("Skill names must be 1–40 characters: letters, numbers, hyphens, or underscores.")
        return value

    def _path(self, name: str) -> Path:
        slug = self._slug(name)
        return self.skill_dir / (slug + ".json")

    def _read(self, name: str) -> dict | None:
        path = self._path(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, json.JSONDecodeError):
            raise ValueError(f"Saved skill '{name}' is unreadable.")
        if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
            raise ValueError(f"Saved skill '{name}' has an invalid format.")
        return data

    def save_completed_task(self, task_id: str, name: str) -> str:
        task_id = str(task_id or "").strip()
        if not _TASK_RE.fullmatch(task_id):
            return "[ERROR] Invalid task ID."
        task = self.task_executor._load(task_id)
        if not task:
            return f"[ERROR] Task not found: {task_id}"
        if task.get("status") != "COMPLETED":
            return "[ERROR] Only successfully completed tasks can be saved as skills."
        steps = [
            str(item.get("command") or "").strip()
            for item in task.get("steps", [])
            if isinstance(item, dict)
        ]
        if not steps or len(steps) > _MAX_STEPS:
            return f"[ERROR] A skill must contain 1–{_MAX_STEPS} valid steps."
        if any(not step or len(step) > _MAX_STEP_LENGTH or re.match(r"^\s*/task\b", step, re.I) for step in steps):
            return "[ERROR] The task contains an invalid or nested task step and cannot be saved."
        try:
            path = self._path(name)
        except ValueError as exc:
            return f"[ERROR] {exc}"
        slug = path.stem
        record = {
            "name": slug,
            "source_task": task_id,
            "created_at": time.time(),
            "steps": steps,
        }
        self.skill_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return f"[ERROR] Could not save skill ({type(exc).__name__}): {exc}"
        return f"[SKILL SAVED] {slug}\nSteps: {len(steps)}\nRun it later with: /skill run {slug}"

    def list_skills(self) -> str:
        items = []
        for path in sorted(self.skill_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                steps = record.get("steps", [])
                if isinstance(steps, list):
                    items.append(f"{path.stem} — {len(steps)} steps")
            except (OSError, ValueError, AttributeError):
                continue
        return "\n".join(items) if items else "[INFO] No saved skills yet. Complete a task, then use /skill save <task-id> as <name>."

    def show(self, name: str) -> str:
        try:
            record = self._read(name)
        except ValueError as exc:
            return f"[ERROR] {exc}"
        if not record:
            return f"[ERROR] Skill not found: {name}"
        lines = [f"Skill: {record.get('name', name)}", f"Steps: {len(record['steps'])}"]
        lines.extend(f"{index}. {step}" for index, step in enumerate(record["steps"], 1))
        lines.append(f"Run: /skill run {record.get('name', name)}")
        return "\n".join(lines)

    def run(self, name: str, source: str = "external") -> str:
        try:
            record = self._read(name)
        except ValueError as exc:
            return f"[ERROR] {exc}"
        if not record:
            return f"[ERROR] Skill not found: {name}"
        steps = record["steps"]
        if not 1 <= len(steps) <= _MAX_STEPS:
            return "[ERROR] Saved skill has an invalid number of steps."
        for step in steps:
            if not isinstance(step, str) or not step.strip() or len(step) > _MAX_STEP_LENGTH or re.match(r"^\s*/task\b", step, re.I):
                return "[ERROR] Saved skill contains an invalid step; refusing to run it."
        created = self.task_executor.create(steps)
        match = re.search(r"\[TASK CREATED\]\s+(task-[0-9a-f]{8})", created)
        if not match:
            return created
        task_id = match.group(1)
        return f"[SKILL RUN] {record.get('name', name)}\n{self.task_executor.handle('/task run ' + task_id, source=source)}"

    def handle(self, command: str, source: str = "external") -> str:
        parts = str(command or "").strip().split(maxsplit=2)
        if len(parts) < 2 or parts[1].lower() in {"help", "?"}:
            return self.help_text()
        action = parts[1].lower()
        value = parts[2].strip() if len(parts) > 2 else ""
        if action == "list":
            return self.list_skills()
        if action == "show":
            return self.show(value) if value else "[ERROR] Usage: /skill show <name>"
        if action == "run":
            return self.run(value, source=source) if value else "[ERROR] Usage: /skill run <name>"
        if action == "save":
            match = re.fullmatch(r"(task-[0-9a-f]{8})\s+as\s+(.+)", value, re.I)
            if not match:
                return "[ERROR] Usage: /skill save <completed-task-id> as <skill-name>"
            return self.save_completed_task(match.group(1), match.group(2))
        return "[ERROR] Unknown /skill action.\n" + self.help_text()

    @staticmethod
    def help_text() -> str:
        return (
            "JARVIS Skill Forge\n"
            "/skill list — list reusable skills\n"
            "/skill show <name> — inspect a saved skill\n"
            "/skill save <completed-task-id> as <name> — save a successful workflow\n"
            "/skill run <name> — execute a saved workflow through the normal task engine\n"
            "Skills are stored locally; destructive steps still pause for the existing confirmation."
        )
