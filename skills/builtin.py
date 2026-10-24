"""Trusted built-in skills exposed through the registry."""
from datetime import datetime
from monitoring.system_telemetry import get_telemetry
from .registry import Skill, SkillRegistry


def build_default_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(Skill(
        name="system.time",
        description="Return the device's current local time.",
        handler=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
        permission="read",
    ))
    registry.register(Skill(
        name="system.telemetry",
        description="Return live CPU, memory, process-count, and JARVIS uptime telemetry.",
        handler=get_telemetry,
        permission="read",
    ))
    return registry
