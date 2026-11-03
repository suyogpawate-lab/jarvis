"""Compact, device-local temporal context for JARVIS reasoning."""
from __future__ import annotations

from datetime import datetime


def build_temporal_context(scheduler=None, now=None, max_items=8):
    """Return factual local time and upcoming scheduler jobs; never infer deadlines."""
    timezone = getattr(scheduler, "timezone", None)
    timezone_name = getattr(scheduler, "timezone_name", "LOCAL")
    current = now or (datetime.now(timezone) if timezone else datetime.now().astimezone())
    lines = [
        "CURRENT LOCAL TIME (device clock): " + current.isoformat(timespec="seconds"),
        "TIMEZONE: " + str(timezone_name),
        "Use this timestamp when interpreting today, tonight, tomorrow, deadlines, and scheduling.",
        "Do not invent calendar events or deadlines; ask if the requested time is ambiguous.",
    ]
    if scheduler is not None:
        try:
            upcoming = []
            for item in scheduler.list():
                if item.get("status") != "SCHEDULED" or item.get("next_run") is None:
                    continue
                when = datetime.fromtimestamp(float(item["next_run"]), timezone or current.tzinfo)
                upcoming.append((when, str(item.get("description") or item.get("command") or "Scheduled task")[:140]))
            upcoming.sort(key=lambda value: value[0])
            if upcoming:
                lines.append("UPCOMING SCHEDULED WORK:")
                for when, label in upcoming[:max(0, int(max_items))]:
                    lines.append("- " + when.isoformat(timespec="minutes") + ": " + label)
        except Exception:
            lines.append("UPCOMING SCHEDULED WORK: unavailable (scheduler read failed).")
    return "\n".join(lines)
