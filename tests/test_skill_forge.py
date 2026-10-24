"""Regression tests for reusable local JARVIS skills."""
import tempfile
import unittest
from pathlib import Path

from automation.skill_forge import SkillForge


class FakeTaskExecutor:
    def __init__(self):
        self.tasks = {}
        self.created_steps = []
        self.handled = []
        self.next_id = 1

    def _load(self, task_id):
        return self.tasks.get(task_id)

    def create(self, steps):
        task_id = f"task-{self.next_id:08x}"
        self.next_id += 1
        self.created_steps.append(list(steps))
        return f"[TASK CREATED] {task_id}\nSteps: {len(steps)}"

    def handle(self, command, source="external"):
        self.handled.append((command, source))
        return f"Task started: {command}"


class SkillForgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.executor = FakeTaskExecutor()
        self.forge = SkillForge(self.executor, Path(self.temp.name) / "skills")
        self.executor.tasks["task-1234abcd"] = {
            "id": "task-1234abcd",
            "status": "COMPLETED",
            "steps": [
                {"command": "show battery status"},
                {"command": "show storage status"},
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_save_list_and_show_completed_task(self):
        result = self.forge.handle("/skill save task-1234abcd as Device Check")
        self.assertIn("[SKILL SAVED] device-check", result)
        self.assertIn("device-check — 2 steps", self.forge.list_skills())
        self.assertIn("show battery status", self.forge.show("device-check"))

    def test_only_completed_tasks_can_be_saved(self):
        self.executor.tasks["task-deadbeef"] = {
            "id": "task-deadbeef",
            "status": "FAILED",
            "steps": [{"command": "show battery status"}],
        }
        result = self.forge.save_completed_task("task-deadbeef", "bad-skill")
        self.assertIn("Only successfully completed", result)
        self.assertFalse((Path(self.temp.name) / "skills" / "bad-skill.json").exists())

    def test_run_creates_a_fresh_normal_task(self):
        self.forge.save_completed_task("task-1234abcd", "device-check")
        result = self.forge.handle("/skill run device-check", source="text")
        self.assertIn("[SKILL RUN] device-check", result)
        self.assertEqual(self.executor.created_steps, [[
            "show battery status", "show storage status"
        ]])
        self.assertEqual(self.executor.handled, [("/task run task-00000001", "text")])

    def test_nested_task_steps_are_rejected(self):
        self.executor.tasks["task-87654321"] = {
            "id": "task-87654321",
            "status": "COMPLETED",
            "steps": [{"command": "/task run task-deadbeef"}],
        }
        result = self.forge.save_completed_task("task-87654321", "nested")
        self.assertIn("invalid or nested", result)

    def test_invalid_skill_names_are_rejected(self):
        result = self.forge.save_completed_task("task-1234abcd", "../../unsafe")
        self.assertIn("[ERROR]", result)


if __name__ == "__main__":
    unittest.main()
