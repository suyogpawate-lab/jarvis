"""Durable, event-driven autonomy supervisor for JARVIS.

The supervisor coordinates observations and bounded decisions; it does not
replace the command dispatcher, scheduler, task executor, or their safeguards.
Only explicitly classified low-risk actions may run unattended. Unknown or
sensitive actions are persisted for approval. Interrupted actions are never
blindly replayed after a process restart.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

MAX_EVENTS = 500
MAX_EVENT_TEXT = 4000
MAX_ACTIONS_PER_EVENT = 8
TERMINAL = {"COMPLETED", "FAILED", "BLOCKED", "UNVERIFIED", "REJECTED", "CANCELLED"}
AUTO_RISK = {"read_only"}
READ_ONLY_OPERATIONS = frozenset({
    "health_snapshot",
    "notification_observed",
    "whatsapp_message_observed",
    "planning_checkpoint",
    "android_foreground_snapshot",
})


def _policy_risk(action: str) -> str:
    """Classify only exact structured operation identifiers as unattended-safe."""
    if isinstance(action, str) and action.strip() in READ_ONLY_OPERATIONS:
        return "read_only"
    return "approval_required"


def _bounded_text(value: Any, limit: int = MAX_EVENT_TEXT) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text[:limit]


class AutonomySupervisor:
    """Persistent event/mission loop with conservative unattended execution.

    decide(event) returns action dictionaries. Only exact operation identifiers
    in READ_ONLY_OPERATIONS may execute unattended. The injected execute callback
    must independently enforce the same allowlist and return a structured,
    independently verified result before a mission can become COMPLETED.
    """

    def __init__(
        self,
        decide: Callable[[dict[str, Any]], list[dict[str, Any]]],
        execute: Callable[[str], Any],
        state_path: str | os.PathLike = "data/autonomy/state.json",
        interval: float = 3.0,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.decide = decide
        self.execute = execute
        self.state_path = Path(state_path)
        self.interval = max(0.5, min(float(interval), 60.0))
        self.on_update = on_update
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = self._load()
        self._recover_interrupted()

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "created_at": time.time(),
            "updated_at": time.time(),
            "events": [],
            "missions": [],
            "seen_event_ids": [],
        }

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("schema") != 1:
                raise ValueError("Unsupported autonomy state schema")
            for key in ("events", "missions", "seen_event_ids"):
                if not isinstance(value.get(key), list):
                    value[key] = []
            return value
        except FileNotFoundError:
            return self._empty_state()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # Preserve a corrupt state file for inspection; never overwrite it.
            self.state_path = self.state_path.with_name(
                self.state_path.stem + ".recovery-" + str(int(time.time())) + self.state_path.suffix
            )
            return self._empty_state()

    def _save(self) -> None:
        self._state["updated_at"] = time.time()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        payload = json.dumps(self._state, ensure_ascii=False, indent=2)
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
        os.replace(tmp, self.state_path)

    def _recover_interrupted(self) -> None:
        changed = False
        for mission in self._state["missions"]:
            if mission.get("status") == "RUNNING":
                mission["status"] = "PAUSED_RECOVERY"
                mission["recovery_note"] = (
                    "Process ended before completion was verified. Review before resuming; "
                    "the action was not automatically repeated."
                )
                mission["updated_at"] = time.time()
                changed = True
        for event in self._state["events"]:
            if event.get("status") == "PROCESSING":
                event["status"] = "PAUSED_RECOVERY"
                changed = True
        if changed:
            self._save()

    def ingest(self, source: str, payload: Any, event_id: str | None = None) -> dict[str, Any]:
        """Persist an observation before acknowledging it to its producer."""
        identifier = _bounded_text(event_id or uuid.uuid4().hex, 128)
        with self._lock:
            if identifier in self._state["seen_event_ids"]:
                return {"accepted": False, "duplicate": True, "event_id": identifier}
            event = {
                "id": identifier,
                "source": _bounded_text(source, 80) or "unknown",
                "payload": _bounded_text(payload),
                "status": "PENDING",
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._state["events"].append(event)
            self._state["seen_event_ids"].append(identifier)
            self._state["events"] = self._state["events"][-MAX_EVENTS:]
            self._state["seen_event_ids"] = self._state["seen_event_ids"][-MAX_EVENTS:]
            self._save()
        self._notify()
        return {"accepted": True, "duplicate": False, "event_id": identifier}

    def _notify(self) -> None:
        if self.on_update:
            try:
                self.on_update(self.status())
            except Exception:
                pass

    def _next_pending_event(self) -> dict[str, Any] | None:
        for event in self._state["events"]:
            if event.get("status") == "PENDING":
                return event
        return None

    def process_once(self) -> dict[str, Any]:
        """Process at most one event. Safe to call from tests or a worker loop."""
        with self._lock:
            event = self._next_pending_event()
            if event is None:
                return {"processed": False, "reason": "no_pending_events"}
            event["status"] = "PROCESSING"
            event["updated_at"] = time.time()
            self._save()
            snapshot = dict(event)

        try:
            proposals = self.decide(snapshot)
            if not isinstance(proposals, list):
                raise ValueError("Decision engine must return a list of actions.")
            if len(proposals) > MAX_ACTIONS_PER_EVENT:
                raise ValueError(f"Decision exceeded {MAX_ACTIONS_PER_EVENT} actions.")
            missions = []
            for proposal in proposals:
                if not isinstance(proposal, dict):
                    raise ValueError("Each proposed action must be an object.")
                action = _bounded_text(proposal.get("action", ""), 1000)
                if not action:
                    continue
                risk = _policy_risk(action)
                mission = {
                    "id": "mission-" + uuid.uuid4().hex[:10],
                    "event_id": snapshot["id"],
                    "description": _bounded_text(proposal.get("description") or action, 300),
                    "action": action,
                    "risk": risk,
                    "status": "PENDING" if risk in AUTO_RISK else "WAITING_APPROVAL",
                    "created_at": time.time(),
                    "updated_at": time.time(),
                    "result": None,
                }
                with self._lock:
                    self._state["missions"].append(mission)
                    self._state["missions"] = self._state["missions"][-MAX_EVENTS:]
                    self._save()
                missions.append(mission)

            with self._lock:
                current = next((x for x in self._state["events"] if x["id"] == snapshot["id"]), None)
                if current:
                    current["status"] = "ASSESSED"
                    current["updated_at"] = time.time()
                    self._save()
            self._notify()
            return {"processed": True, "event_id": snapshot["id"], "missions_created": len(missions)}
        except Exception as exc:
            with self._lock:
                current = next((x for x in self._state["events"] if x["id"] == snapshot["id"]), None)
                if current:
                    current["status"] = "FAILED"
                    current["error"] = _bounded_text(f"{type(exc).__name__}: {exc}", 500)
                    current["updated_at"] = time.time()
                    self._save()
            self._notify()
            return {"processed": True, "event_id": snapshot["id"], "error": str(exc)}

    def execute_once(self) -> dict[str, Any]:
        """Execute at most one explicitly low-risk mission; never replay interrupted work."""
        with self._lock:
            mission = next((m for m in self._state["missions"] if m.get("status") == "PENDING"), None)
            if mission is None:
                return {"executed": False, "reason": "no_approved_pending_missions"}
            # Re-evaluate the stored operation immediately before execution.
            # Approval never expands the unattended operation allowlist.
            if mission.get("risk") not in AUTO_RISK or _policy_risk(mission.get("action", "")) != "read_only":
                if mission.get("status") == "PENDING":
                    mission["status"] = "BLOCKED"
                    mission["result"] = "Operation is not in the restricted unattended allowlist."
                    mission["updated_at"] = time.time()
                    self._save()
                return {"executed": False, "reason": "operation_not_allowlisted"}
            mission["status"] = "RUNNING"
            mission["updated_at"] = time.time()
            self._save()
            mission_id = mission["id"]
            action = mission["action"]

        try:
            result = self.execute(action)
            rendered = _bounded_text(result, 1000)
            if isinstance(result, dict) and result.get("ok") is False:
                status = "FAILED"
            elif isinstance(result, dict) and result.get("ok") is True and result.get("verified") is True:
                status = "COMPLETED"
            elif result is None:
                status = "FAILED"
            else:
                status = "UNVERIFIED"
        except Exception as exc:
            rendered = _bounded_text(f"{type(exc).__name__}: {exc}", 1000)
            status = "FAILED"

        with self._lock:
            current = next((m for m in self._state["missions"] if m["id"] == mission_id), None)
            if current:
                current["status"] = status
                current["result"] = rendered
                current["updated_at"] = time.time()
                self._save()
        self._notify()
        return {"executed": True, "mission_id": mission_id, "status": status, "result": rendered}

    def approve(self, mission_id: str) -> dict[str, Any]:
        """Explicitly authorize one stored mission; caller must enforce trusted input."""
        with self._lock:
            mission = next((m for m in self._state["missions"] if m.get("id") == mission_id), None)
            if not mission:
                return {"ok": False, "error": "mission_not_found"}
            if mission.get("status") != "WAITING_APPROVAL":
                return {"ok": False, "error": "mission_not_waiting_for_approval"}
            mission["status"] = "PENDING"
            # Approval is recorded for this mission only. It does not alter
            # risk classification or grant access to the execution adapter.
            mission["approved_at"] = time.time()
            mission["updated_at"] = time.time()
            self._save()
        self._notify()
        return {"ok": True, "mission_id": mission_id}

    def reject(self, mission_id: str) -> dict[str, Any]:
        with self._lock:
            mission = next((m for m in self._state["missions"] if m.get("id") == mission_id), None)
            if not mission:
                return {"ok": False, "error": "mission_not_found"}
            if mission.get("status") != "WAITING_APPROVAL":
                return {"ok": False, "error": "mission_not_waiting_for_approval"}
            mission["status"] = "REJECTED"
            mission["updated_at"] = time.time()
            self._save()
        self._notify()
        return {"ok": True, "mission_id": mission_id}

    def status(self) -> dict[str, Any]:
        with self._lock:
            events = list(self._state["events"])
            missions = list(self._state["missions"])
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "pending_events": sum(e.get("status") == "PENDING" for e in events),
                "paused_events": sum(e.get("status") == "PAUSED_RECOVERY" for e in events),
                "pending_missions": sum(m.get("status") == "PENDING" for m in missions),
                "waiting_approval": sum(m.get("status") == "WAITING_APPROVAL" for m in missions),
                "completed_missions": sum(m.get("status") == "COMPLETED" for m in missions),
                "failed_missions": sum(m.get("status") == "FAILED" for m in missions),
                "blocked_missions": sum(m.get("status") == "BLOCKED" for m in missions),
                "unverified_missions": sum(m.get("status") == "UNVERIFIED" for m in missions),
                "paused_missions": sum(m.get("status") == "PAUSED_RECOVERY" for m in missions),
                "recent_missions": [
                    {k: m.get(k) for k in ("id", "description", "risk", "status", "result")}
                    for m in missions[-10:]
                ],
                "updated_at": self._state.get("updated_at"),
            }

    def tick(self) -> dict[str, Any]:
        """One bounded cycle: assess one event, then execute one safe mission."""
        assessed = self.process_once()
        executed = self.execute_once()
        return {"assessment": assessed, "execution": executed}

    def start(self) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="jarvis-autonomy-supervisor", daemon=True)
            self._thread.start()
            return True

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(max(0.0, min(float(timeout), 10.0)))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                # Keep the supervisor alive; the next cycle can recover.
                with self._lock:
                    self._state["last_loop_error"] = _bounded_text(
                        f"{type(exc).__name__}: {exc}", 500
                    )
                    self._save()
            self._stop.wait(self.interval)
