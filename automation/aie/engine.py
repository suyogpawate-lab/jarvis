"""Persistent, event-driven AIE kernel.

The kernel stores goals, observations, missions, decisions, approvals and memory
in SQLite. It only executes registered capabilities; model or event text is
never interpreted as a shell command. The initial built-in capability is
read-only health inspection. Other existing services can be registered through
the typed capability API by the dispatcher.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
import uuid
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 2
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "REJECTED"}
RISK_ORDER = {"read_only": 0, "reversible": 1, "approval": 2, "external": 3, "destructive": 4}


class AIEError(Exception):
    pass


class AIEEngine:
    def __init__(self, db_path="data/aie/aie.db", health_provider=None, max_active_missions=2, goal_planner=None, notifier=None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.health_provider = health_provider
        self.goal_planner = goal_planner
        self.notifier = notifier
        self.max_active_missions = max(1, min(int(max_active_missions), 4))
        self._lock = threading.RLock()
        self._capabilities: dict[str, dict[str, Any]] = {}
        self._register_builtin_capabilities()
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def _db(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self):
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS goals(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
              status TEXT NOT NULL, priority INTEGER NOT NULL, created_at REAL NOT NULL,
              updated_at REAL NOT NULL, success_criteria TEXT NOT NULL, source TEXT NOT NULL,
              review_interval REAL NOT NULL DEFAULT 21600, next_review_at REAL NOT NULL DEFAULT 0,
              last_review_at REAL);
            CREATE TABLE IF NOT EXISTS events(
              id TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL,
              payload TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
              updated_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS events_status_idx ON events(status, created_at);
            CREATE TABLE IF NOT EXISTS missions(
              id TEXT PRIMARY KEY, goal_id TEXT, title TEXT NOT NULL, status TEXT NOT NULL,
              risk TEXT NOT NULL, plan TEXT NOT NULL, result TEXT, created_at REAL NOT NULL,
              updated_at REAL NOT NULL, FOREIGN KEY(goal_id) REFERENCES goals(id));
            CREATE INDEX IF NOT EXISTS missions_status_idx ON missions(status, created_at);
            CREATE TABLE IF NOT EXISTS tasks(
              id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, capability TEXT NOT NULL,
              arguments TEXT NOT NULL, dependencies TEXT NOT NULL, status TEXT NOT NULL,
              result TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
              FOREIGN KEY(mission_id) REFERENCES missions(id));
            CREATE TABLE IF NOT EXISTS approvals(
              id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, status TEXT NOT NULL,
              scope TEXT NOT NULL, created_at REAL NOT NULL, decided_at REAL,
              FOREIGN KEY(mission_id) REFERENCES missions(id));
            CREATE TABLE IF NOT EXISTS decisions(
              id TEXT PRIMARY KEY, event_id TEXT, goal_id TEXT, decision TEXT NOT NULL,
              rationale TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS memories(
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, content TEXT NOT NULL,
              provenance TEXT NOT NULL, confidence REAL NOT NULL, created_at REAL NOT NULL,
              expires_at REAL);
            """)
            cols = {r['name'] for r in db.execute('PRAGMA table_info(goals)')}
            for col, decl in (("review_interval", "REAL NOT NULL DEFAULT 21600"), ("next_review_at", "REAL NOT NULL DEFAULT 0"), ("last_review_at", "REAL")):
                if col not in cols: db.execute(f"ALTER TABLE goals ADD COLUMN {col} {decl}")
            version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if version and int(version["value"]) > SCHEMA_VERSION:
                raise AIEError("AIE database schema is newer than this JARVIS version.")
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
            # Events are side-effect-free assessments and may safely be retried.
            # Running missions may have side effects; require explicit recovery.
            db.execute("UPDATE events SET status='PENDING',updated_at=? WHERE status='PROCESSING'", (time.time(),))
            db.execute("UPDATE missions SET status='PAUSED_RECOVERY',updated_at=? WHERE status='RUNNING'", (time.time(),))
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def register_capability(self, capability_id: str, handler: Callable, risk="read_only",
                            description="", input_validator: Callable | None = None,
                            idempotent=True, requires_approval=False):
        if not capability_id or not capability_id.replace(".", "").replace("_", "").isalnum():
            raise ValueError("Invalid capability identifier.")
        if risk not in RISK_ORDER:
            raise ValueError("Unknown capability risk.")
        self._capabilities[capability_id] = {
            "handler": handler, "risk": risk, "description": str(description)[:300],
            "validator": input_validator, "idempotent": bool(idempotent),
            "requires_approval": bool(requires_approval) or RISK_ORDER[risk] >= 2,
        }

    def _register_builtin_capabilities(self):
        if self.health_provider:
            self.register_capability("system.health_snapshot", self.health_provider,
                                     "read_only", "Collect read-only device and service health.")

    @staticmethod
    def _id(prefix):
        return prefix + "-" + uuid.uuid4().hex[:12]

    def create_goal(self, title, description=None, priority=5, success_criteria=None, source="owner", review_interval=21600):
        title = " ".join(str(title or "").split())[:240]
        if not title:
            raise ValueError("A goal description is required.")
        priority = max(1, min(int(priority), 10))
        now = time.time()
        goal_id = self._id("goal")
        criteria = success_criteria if isinstance(success_criteria, list) else []
        review_interval = max(900, min(float(review_interval), 2592000))
        with self._db() as db:
            db.execute("""INSERT INTO goals (id,title,description,status,priority,created_at,updated_at,success_criteria,source,review_interval,next_review_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (goal_id,title,str(description or title)[:2000],"ACTIVE",priority,now,now,json.dumps(criteria,ensure_ascii=False),str(source)[:40],review_interval,now+review_interval))
        return self.get_goal(goal_id)

    def get_goal(self, goal_id):
        with self._db() as db:
            row = db.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
        return dict(row) if row else None

    def list_goals(self, include_terminal=False, limit=30):
        query = "SELECT * FROM goals"
        params = []
        if not include_terminal:
            query += " WHERE status NOT IN ('COMPLETED','CANCELLED')"
        query += " ORDER BY priority DESC, updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        with self._db() as db:
            return [dict(x) for x in db.execute(query, params).fetchall()]

    def set_goal_status(self, goal_id, status):
        if status not in {"ACTIVE", "PAUSED", "COMPLETED", "CANCELLED"}:
            raise ValueError("Invalid goal status.")
        with self._db() as db:
            cur = db.execute("UPDATE goals SET status=?,updated_at=?,next_review_at=? WHERE id=?",
                             (status,time.time(),time.time()+900 if status=="ACTIVE" else 0,goal_id))
        return {"ok": cur.rowcount == 1, "goal_id": goal_id, "status": status}

    def ingest_event(self, source, kind, payload=None, event_id=None):
        identifier = str(event_id or self._id("evt"))[:128]
        now = time.time()
        safe_payload = json.dumps(payload if isinstance(payload, (dict, list, str, int, float, bool)) else str(payload),
                                  ensure_ascii=False)[:8000]
        with self._db() as db:
            cur = db.execute("""INSERT OR IGNORE INTO events
                (id,source,kind,payload,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)""",
                (identifier, str(source)[:80], str(kind)[:100], safe_payload, "PENDING", now, now))
        return {"accepted": cur.rowcount == 1, "duplicate": cur.rowcount == 0, "event_id": identifier}

    def create_mission(self, title, goal_id=None, tasks=None, risk="read_only"):
        if risk not in RISK_ORDER:
            raise ValueError("Invalid mission risk.")
        if goal_id and not self.get_goal(goal_id):
            raise ValueError("Unknown goal.")
        task_specs = tasks if isinstance(tasks, list) else []
        if len(task_specs) > 20:
            raise ValueError("A mission may contain at most 20 tasks.")
        normalized = []
        for index, spec in enumerate(task_specs):
            if not isinstance(spec, dict):
                raise ValueError("Every mission task must be an object.")
            capability = str(spec.get("capability", ""))
            arguments = spec.get("arguments", {})
            dependencies = spec.get("dependencies", [])
            if not capability or not isinstance(arguments, dict) or not isinstance(dependencies, list):
                raise ValueError("Task capability, object arguments and dependency list are required.")
            if any(not isinstance(dep, int) or isinstance(dep, bool) or dep < 0 or dep >= index for dep in dependencies):
                raise ValueError("Dependencies must reference earlier task indexes.")
            normalized.append({"capability": capability, "arguments": arguments, "dependencies": dependencies})
        task_specs = normalized
        mission_id, now = self._id("mission"), time.time()
        needs_approval = RISK_ORDER[risk] >= 2
        status = "WAITING_APPROVAL" if needs_approval else "READY"
        with self._db() as db:
            db.execute("INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)",
                       (mission_id, goal_id, str(title)[:240], status, risk,
                        json.dumps(task_specs, ensure_ascii=False), None, now, now))
            for spec in task_specs:
                capability = str(spec.get("capability", "")) if isinstance(spec, dict) else ""
                args = spec.get("arguments", {}) if isinstance(spec, dict) else {}
                deps = spec.get("dependencies", []) if isinstance(spec, dict) else []
                db.execute("INSERT INTO tasks(id,mission_id,capability,arguments,dependencies,status,result,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           (self._id("task"), mission_id, capability,
                            json.dumps(args, ensure_ascii=False), json.dumps(deps),
                            "PENDING", None, now, now))
            if needs_approval:
                db.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?)",
                           (self._id("approval"), mission_id, "PENDING",
                            json.dumps({"mission_id": mission_id, "risk": risk}), now, None))
        return self.get_mission(mission_id)

    def create_planned_mission(self, goal_id, plan):
        """Validate model output against registered capabilities before persistence."""
        goal = self.get_goal(goal_id)
        if not goal or goal["status"] != "ACTIVE":
            raise AIEError("Only an active goal can receive a plan.")
        if not isinstance(plan, dict) or not isinstance(plan.get("tasks"), list):
            raise AIEError("Planner output must contain a task list.")
        tasks = plan["tasks"]
        if not tasks or len(tasks) > 12:
            raise AIEError("A plan must contain between 1 and 12 tasks.")
        risk = "read_only"
        for spec in tasks:
            if not isinstance(spec, dict):
                raise AIEError("Each task must be an object.")
            cap = self._capabilities.get(str(spec.get("capability", "")))
            if not cap:
                raise AIEError("Planner selected an unavailable capability.")
            args = spec.get("arguments", {})
            if not isinstance(args, dict) or (cap["validator"] and not cap["validator"](args)):
                raise AIEError("Planner arguments failed validation.")
            if RISK_ORDER[cap["risk"]] > RISK_ORDER[risk]:
                risk = cap["risk"]
        title = " ".join(str(plan.get("title") or goal["title"]).split())[:240]
        return self.create_mission(title, goal_id=goal_id, tasks=tasks, risk=risk)

    def get_mission(self, mission_id):
        with self._db() as db:
            row = db.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["plan"] = json.loads(result["plan"])
            result["result"] = json.loads(result["result"]) if result["result"] else None
            result["tasks"] = [dict(x) for x in db.execute(
                "SELECT * FROM tasks WHERE mission_id=? ORDER BY created_at", (mission_id,)).fetchall()]
            return result

    def list_missions(self, limit=30):
        with self._db() as db:
            rows = db.execute("SELECT id FROM missions ORDER BY created_at DESC LIMIT ?",
                              (max(1, min(int(limit), 100)),)).fetchall()
        return [self.get_mission(x["id"]) for x in rows]

    def decide(self, event_id, decision, rationale, goal_id=None):
        with self._db() as db:
            db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?)",
                       (self._id("decision"), event_id, goal_id, str(decision)[:100],
                        str(rationale)[:1000], time.time()))

    def remember(self, kind, content, provenance="aie", confidence=0.7, ttl_seconds=None):
        kind = str(kind)[:40]
        content = " ".join(str(content or "").split())[:4000]
        if not content:
            return False
        confidence = max(0.0, min(float(confidence), 1.0))
        expires = time.time() + int(ttl_seconds) if ttl_seconds else None
        with self._db() as db:
            db.execute("INSERT INTO memories VALUES(?,?,?,?,?,?,?)",
                       (self._id("mem"), kind, content, str(provenance)[:200],
                        confidence, time.time(), expires))
        return True

    def recall(self, query="", limit=8):
        terms = [x.lower() for x in str(query).split() if len(x) > 2][:8]
        with self._db() as db:
            rows = db.execute("SELECT * FROM memories WHERE expires_at IS NULL OR expires_at>?",
                              (time.time(),)).fetchall()
        scored = []
        for row in rows:
            content = row["content"].lower()
            score = sum(term in content for term in terms)
            if not terms or score:
                scored.append((score, dict(row)))
        scored.sort(key=lambda x: (x[0], x[1]["created_at"]), reverse=True)
        return [x[1] for x in scored[:max(1, min(int(limit), 30))]]

    def approve(self, approval_id, approved=True):
        status = "APPROVED" if approved else "REJECTED"
        now = time.time()
        with self._db() as db:
            row = db.execute("SELECT mission_id,status FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not row or row["status"] != "PENDING":
                return {"ok": False, "error": "approval_not_pending"}
            db.execute("UPDATE approvals SET status=?,decided_at=? WHERE id=?",
                       (status, now, approval_id))
            db.execute("UPDATE missions SET status=?,updated_at=? WHERE id=?",
                       ("READY" if approved else "REJECTED", now, row["mission_id"]))
        return {"ok": True, "status": status, "mission_id": row["mission_id"]}

    def execute_mission(self, mission_id):
        with self._lock:
            mission = self.get_mission(mission_id)
            if not mission:
                return {"ok": False, "error": "mission_not_found"}
            if mission["status"] != "READY":
                return {"ok": False, "error": "mission_not_ready", "status": mission["status"]}
            if not mission["tasks"]:
                with self._db() as db:
                    db.execute("UPDATE missions SET status='UNVERIFIED',result=?,updated_at=? WHERE id=?",
                               (json.dumps({"verified": False, "error": "empty_mission_has_no_verifiable_work"}),
                                time.time(), mission_id))
                return {"ok": False, "status": "UNVERIFIED", "verified": False}
            with self._db() as db:
                db.execute("UPDATE missions SET status='RUNNING',updated_at=? WHERE id=?",
                           (time.time(), mission_id))
            results = []
            try:
                completed_indexes = set()
                for index, task in enumerate(mission["tasks"]):
                    dependencies = json.loads(task["dependencies"])
                    if any(dep not in completed_indexes for dep in dependencies):
                        raise AIEError("Task dependency has not completed successfully.")
                    cap = self._capabilities.get(task["capability"])
                    if not cap:
                        raise AIEError("Capability is not registered: " + task["capability"])
                    if RISK_ORDER[cap["risk"]] > RISK_ORDER[mission["risk"]]:
                        raise AIEError("Mission risk is below the capability's declared risk.")
                    if cap["requires_approval"] and RISK_ORDER[mission["risk"]] < 2:
                        raise AIEError("Capability requires an approved higher-risk mission.")
                    args = json.loads(task["arguments"])
                    if not isinstance(args, dict):
                        raise AIEError("Capability arguments must be an object.")
                    if cap["validator"] and not cap["validator"](args):
                        raise AIEError("Capability arguments failed validation.")
                    result = cap["handler"](**args)
                    verified = isinstance(result, dict) and result.get("ok") is True and result.get("verified") is True
                    if not verified:
                        raise AIEError("Capability did not return independently verified success.")
                    results.append({"task_id": task["id"], "capability": task["capability"], "result": result})
                    completed_indexes.add(index)
                    with self._db() as db:
                        db.execute("UPDATE tasks SET status='COMPLETED',result=?,updated_at=? WHERE id=?",
                                   (json.dumps(result, ensure_ascii=False)[:8000], time.time(), task["id"]))
                status = "COMPLETED"
            except Exception as exc:
                status = "UNVERIFIED" if isinstance(exc, AIEError) else "FAILED"
                results.append({"error": type(exc).__name__, "message": str(exc)[:500]})
            with self._db() as db:
                db.execute("UPDATE missions SET status=?,result=?,updated_at=? WHERE id=?",
                           (status, json.dumps({"verified": status == "COMPLETED", "tasks": results},
                                               ensure_ascii=False)[:16000], time.time(), mission_id))
            return {"ok": status == "COMPLETED", "status": status, "verified": status == "COMPLETED",
                    "results": results}

    @staticmethod
    def _normalize_plan(raw):
        """Parse planner JSON without treating model output as executable instructions."""
        if isinstance(raw, dict):
            plan = raw
        else:
            value = str(raw or "").strip()
            fence = chr(96) * 3
            if value.startswith(fence):
                value = value.split("\\n", 1)[-1]
                if value.rstrip().endswith(fence):
                    value = value.rstrip()[:-3].strip()
            plan = json.loads(value)
        if not isinstance(plan, dict) or not isinstance(plan.get("tasks"), list):
            raise AIEError("Planner response was not a valid mission object.")
        return plan

    def evaluate_due_goals(self, limit=1):
        """Create review proposals on a cadence; never execute missions."""
        now = time.time()
        with self._db() as db:
            due = db.execute("SELECT * FROM goals WHERE status='ACTIVE' AND next_review_at<=? ORDER BY priority DESC,next_review_at LIMIT ?",(now,max(1,min(int(limit),2)))).fetchall()
        results = []
        for item in due:
            goal = dict(item)
            result = {"goal_id":goal["id"],"proposal":None,"error":None}
            try:
                if callable(self.goal_planner):
                    with self._db() as db:
                        existing = db.execute("SELECT id FROM missions WHERE goal_id=? AND status IN ('DRAFT','READY','RUNNING','PAUSED_RECOVERY') ORDER BY created_at DESC LIMIT 1", (goal["id"],)).fetchone()
                    if existing:
                        result["proposal"] = existing["id"]
                        self.decide(None,"EXISTING_PROPOSAL","An unfinished mission already exists; duplicate proposal suppressed.",goal["id"])
                    else:
                        raw_plan = self.goal_planner(goal)
                        plan = self._normalize_plan(raw_plan)
                        mission = self.create_planned_mission(goal["id"],plan)
                        result["proposal"] = mission["id"]
                        self.decide(None,"MISSION_PROPOSED","Periodic review prepared a mission for owner review.",goal["id"])
                        if callable(self.notifier):
                            try: self.notifier("JARVIS goal review",f"Plan ready: {mission['id']}",mission['id'])
                            except Exception: pass
                    else:
                        self.decide(None,"WAIT","No actionable work found during periodic review.",goal["id"])
                else:
                    self.decide(None,"WAIT","Planner unavailable; no action taken.",goal["id"])
            except Exception as exc:
                result["error"] = type(exc).__name__
                self.decide(None,"REVIEW_FAILED",f"Review failed safely: {type(exc).__name__}.",goal["id"])
            finally:
                with self._db() as db:
                    db.execute("UPDATE goals SET last_review_at=?,next_review_at=? WHERE id=? AND status='ACTIVE'",(now,now+float(goal.get("review_interval",21600)),goal["id"]))
            results.append(result)
        return results

    def process_one_event(self):
        with self._db() as db:
            row = db.execute("SELECT * FROM events WHERE status='PENDING' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return {"processed": False}
            db.execute("UPDATE events SET status='PROCESSING',updated_at=? WHERE id=?",
                       (time.time(), row["id"]))
        payload = json.loads(row["payload"])
        # Observations can create opportunities, but never execute arbitrary event content.
        active_goals = self.list_goals()
        relevant = bool(active_goals)
        decision = "REVIEW_ACTIVE_GOALS" if relevant else "RECORD_ONLY"
        rationale = "An observation arrived; active objectives were checked. No model text is executable."
        self.decide(row["id"], decision, rationale)
        with self._db() as db:
            db.execute("UPDATE events SET status='ASSESSED',updated_at=? WHERE id=?",
                       (time.time(), row["id"]))
        return {"processed": True, "event_id": row["id"], "decision": decision,
                "active_goals": len(active_goals), "payload_kind": type(payload).__name__}

    def start(self, interval=5.0):
        """Start one lightweight event worker; model calls are not polled."""
        if getattr(self, "_worker", None) and self._worker.is_alive():
            return False
        self._stop_event = threading.Event()
        self._interval = max(1.0, min(float(interval), 60.0))
        self._worker = threading.Thread(target=self._run, name="jarvis-aie", daemon=True)
        self._worker.start()
        return True

    def stop(self, timeout=2.0):
        event = getattr(self, "_stop_event", None)
        if event:
            event.set()
        worker = getattr(self, "_worker", None)
        if worker and worker.is_alive():
            worker.join(max(0.0, min(float(timeout), 10.0)))

    def _run(self):
        while not self._stop_event.wait(self._interval):
            try:
                self.process_one_event()
                self.evaluate_due_goals(limit=1)
            except Exception:
                continue

    def status(self):
        with self._db() as db:
            counts = {}
            for table, column in (("goals","status"),("events","status"),("missions","status"),("approvals","status")):
                counts[table] = {r["status"]: r["n"] for r in db.execute(
                    f"SELECT {column} AS status,COUNT(*) AS n FROM {table} GROUP BY {column}")}
        with self._db() as db:
            due = db.execute("SELECT COUNT(*) FROM goals WHERE status='ACTIVE' AND next_review_at<=?", (time.time(),)).fetchone()[0]
        worker = getattr(self, "_worker", None)
        return {"schema_version": SCHEMA_VERSION, "database": str(self.db_path),
                "capabilities": sorted(self._capabilities), "counts": counts,
                "active_goals": len(self.list_goals()), "due_goal_reviews": due,
                "worker_alive": bool(worker and worker.is_alive())}
