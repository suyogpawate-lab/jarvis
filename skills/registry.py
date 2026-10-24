"""Small, explicit registry for executable JARVIS skills.

Skills are registered by trusted Python code; this module never imports arbitrary
modules based on user input or scans the filesystem for executable plugins.
"""
from dataclasses import dataclass, field
from typing import Any, Callable
import re


_PERMISSION_LEVELS = {"read", "write", "restricted"}
_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")


class SkillError(Exception):
    """Base error for skill registry operations."""


class SkillNotFound(SkillError):
    """Raised when a requested skill is not registered."""


class SkillPermissionError(SkillError):
    """Raised when a skill needs explicit approval."""


class SkillValidationError(SkillError):
    """Raised when skill metadata or parameters are invalid."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    handler: Callable[..., Any]
    permission: str = "read"
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    requires_confirmation: bool = False

    def __post_init__(self):
        if not _NAME_RE.fullmatch(self.name):
            raise SkillValidationError(f"Invalid skill name: {self.name!r}")
        if not self.description.strip():
            raise SkillValidationError("Skill description cannot be empty.")
        if not callable(self.handler):
            raise SkillValidationError(f"Skill {self.name!r} needs a callable handler.")
        if self.permission not in _PERMISSION_LEVELS:
            raise SkillValidationError(
                f"Permission must be one of: {', '.join(sorted(_PERMISSION_LEVELS))}."
            )
        if self.permission != "read" and not self.requires_confirmation:
            raise SkillValidationError(
                "Write and restricted skills must require explicit confirmation."
            )
        unknown_required = set(self.required) - set(self.parameters)
        if unknown_required:
            raise SkillValidationError(
                f"Required parameters are not defined: {', '.join(sorted(unknown_required))}."
            )


class SkillRegistry:
    """In-memory registry with parameter validation and permission gates."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> Skill:
        if not isinstance(skill, Skill):
            raise TypeError("register() expects a Skill instance.")
        if skill.name in self._skills:
            raise SkillValidationError(f"Skill already registered: {skill.name}")
        self._skills[skill.name] = skill
        return skill

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name.strip().lower()]
        except (KeyError, AttributeError):
            raise SkillNotFound(f"Unknown skill: {name}") from None

    def list_skills(self) -> list[dict[str, Any]]:
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "permission": skill.permission,
                "parameters": skill.parameters,
                "required": list(skill.required),
                "requires_confirmation": skill.requires_confirmation,
            }
            for skill in sorted(self._skills.values(), key=lambda item: item.name)
        ]

    def execute(
        self,
        name: str,
        parameters: dict[str, Any] | None = None,
        *,
        approved: bool = False,
    ) -> Any:
        skill = self.get(name)
        params = {} if parameters is None else parameters
        if not isinstance(params, dict):
            raise SkillValidationError("Skill parameters must be a dictionary.")

        missing = [key for key in skill.required if key not in params]
        if missing:
            raise SkillValidationError(
                f"Missing required parameter(s): {', '.join(missing)}."
            )

        unknown = set(params) - set(skill.parameters)
        if unknown:
            raise SkillValidationError(
                f"Unknown parameter(s): {', '.join(sorted(unknown))}."
            )

        for key, value in params.items():
            spec = skill.parameters[key]
            expected = spec.get("type")
            if expected == "string" and not isinstance(value, str):
                raise SkillValidationError(f"Parameter {key!r} must be a string.")
            if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise SkillValidationError(f"Parameter {key!r} must be an integer.")
            if expected == "boolean" and not isinstance(value, bool):
                raise SkillValidationError(f"Parameter {key!r} must be a boolean.")
            if expected == "number" and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                raise SkillValidationError(f"Parameter {key!r} must be a number.")
            choices = spec.get("enum")
            if choices is not None and value not in choices:
                raise SkillValidationError(
                    f"Parameter {key!r} must be one of: {', '.join(map(str, choices))}."
                )

        if skill.requires_confirmation and not approved:
            raise SkillPermissionError(
                f"Skill {skill.name!r} requires explicit approval before execution."
            )

        return skill.handler(**params)
