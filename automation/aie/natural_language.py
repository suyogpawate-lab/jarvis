"""Natural-language intake and control for the JARVIS AIE."""
from __future__ import annotations
import re
from .engine import AIEEngine


class NaturalLanguageAIE:
    """Conservative NL parser: recognizes goal intent; ambiguous requests pass through."""

    CREATE = re.compile(
        r"^(?:jarvis[, ]+)?(?:i want you to\s+|from now on[, ]+|keep|continue|start|begin|work|help me|please)\s+"
        r"(?:working\s+on\s+|to\s+|with\s+)?(.+)$", re.I)
    STATUS = re.compile(r"^(?:what are you working on|aie status|autonomy status|show (?:my )?goals|list (?:my )?goals)$", re.I)
    PAUSE = re.compile(r"^(?:pause|stop working on)\s+(.+)$", re.I)
    RESUME = re.compile(r"^(?:resume|continue working on)\s+(.+)$", re.I)
    GOAL_PREFIX = re.compile(r"^(?:my goal is to|your goal is to|keep an eye on|from now on,? keep track of)\s+(.+)$", re.I)

    def __init__(self, engine: AIEEngine):
        self.engine = engine

    def handle(self, text, source="text"):
        value = " ".join(str(text or "").split()).strip()
        if not value or len(value) > 1000:
            return None
        if self.STATUS.fullmatch(value):
            return self.status_text()
        match = self.PAUSE.fullmatch(value)
        if match:
            return self._change_goal(match.group(1), "PAUSED")
        match = self.RESUME.fullmatch(value)
        if match:
            return self._change_goal(match.group(1), "ACTIVE")
        match = self.GOAL_PREFIX.fullmatch(value)
        if match:
            return self._create(match.group(1), source)
        match = self.CREATE.fullmatch(value)
        if match and re.search(r"\b(goal|project|task|mission|monitor|research|build|develop|learn|track|autonom)\b", match.group(1), re.I):
            return self._create(match.group(1), source)
        return None

    def _create(self, title, source):
        title = re.sub(r"\s+(?:for me|please)$", "", title, flags=re.I).strip(" .")
        if len(title) < 5:
            return None
        goal = self.engine.create_goal(title, source=source)
        self.engine.remember("goal", title, provenance=goal["id"], confidence=1.0)
        return ("[AIE] Persistent goal created.\n"
                f"ID: {goal['id']}\nGoal: {goal['title']}\n"
                "Status: ACTIVE\nI will track this objective and evaluate incoming events. "
                "Execution remains limited to registered capabilities and configured permissions.")

    def _change_goal(self, phrase, status):
        goals = self.engine.list_goals(include_terminal=True)
        needle = phrase.lower()
        matches = [g for g in goals if needle in g["title"].lower() or g["id"].lower() == needle]
        if len(matches) != 1:
            return "[AIE] I could not identify exactly one matching goal. Say 'show my goals' to inspect them."
        result = self.engine.set_goal_status(matches[0]["id"], status)
        return f"[AIE] Goal {matches[0]['id']} is now {status}."

    def status_text(self):
        state = self.engine.status()
        goals = self.engine.list_goals(limit=8)
        lines = ["JARVIS AUTONOMOUS INTELLIGENCE ENGINE"]
        lines.append(f"Active goals: {state['active_goals']}")
        lines.append(f"Registered capabilities: {len(state['capabilities'])}")
        lines.append(f"Events: {state['counts']['events']}")
        lines.append(f"Missions: {state['counts']['missions']}")
        if goals:
            lines.append("Current objectives:")
            lines.extend(f"- [{g['priority']}/10] {g['id']}: {g['title']} ({g['status']})" for g in goals)
        else:
            lines.append("No active goals. Tell me naturally what you want me to work toward.")
        return "\n".join(lines)
