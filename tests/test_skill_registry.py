"""Unit tests for the Phase 2 skill registry."""
import unittest

from skills.registry import (
    Skill,
    SkillPermissionError,
    SkillRegistry,
    SkillValidationError,
)
from skills.builtin import build_default_registry


class SkillRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry()

    def test_register_and_execute_skill(self):
        self.registry.register(Skill(
            name="test.add",
            description="Add two numbers.",
            handler=lambda left, right: left + right,
            parameters={"left": {"type": "integer"}, "right": {"type": "integer"}},
            required=("left", "right"),
        ))
        self.assertEqual(
            self.registry.execute("test.add", {"left": 2, "right": 3}),
            5,
        )

    def test_reject_duplicate_names(self):
        skill = Skill("test.echo", "Echo text.", lambda text: text,
                      parameters={"text": {"type": "string"}}, required=("text",))
        self.registry.register(skill)
        with self.assertRaises(SkillValidationError):
            self.registry.register(skill)

    def test_reject_unknown_parameters(self):
        self.registry.register(Skill(
            "test.echo", "Echo text.", lambda text: text,
            parameters={"text": {"type": "string"}}, required=("text",),
        ))
        with self.assertRaises(SkillValidationError):
            self.registry.execute("test.echo", {"text": "hi", "shell": "whoami"})

    def test_validate_parameter_types(self):
        self.registry.register(Skill(
            "test.count", "Accept a count.", lambda count: count,
            parameters={"count": {"type": "integer"}}, required=("count",),
        ))
        with self.assertRaises(SkillValidationError):
            self.registry.execute("test.count", {"count": True})

    def test_restricted_skill_requires_approval(self):
        self.registry.register(Skill(
            "test.send", "Send a message.", lambda: "sent",
            permission="restricted", requires_confirmation=True,
        ))
        with self.assertRaises(SkillPermissionError):
            self.registry.execute("test.send")
        self.assertEqual(self.registry.execute("test.send", approved=True), "sent")

    def test_restricted_skills_must_have_confirmation(self):
        with self.assertRaises(SkillValidationError):
            Skill("test.danger", "Dangerous action.", lambda: None,
                  permission="restricted")

    def test_builtin_registry_has_safe_read_only_skills(self):
        names = {item["name"] for item in build_default_registry().list_skills()}
        self.assertIn("system.time", names)
        self.assertIn("system.telemetry", names)


if __name__ == "__main__":
    unittest.main()
