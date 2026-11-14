"""Explicit human-preference capture for future LoRA/DPO alignment.

Nothing is collected automatically. The owner must explicitly submit a prompt,
a preferred answer and a rejected answer. Data stays in the local ignored data/
directory and can be exported as prompt/chosen/rejected JSONL.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = ROOT / "data" / "learning" / "preferences.jsonl"
DEFAULT_EXPORT = ROOT / "data" / "learning" / "dpo_preferences.jsonl"
_LOCK = threading.RLock()


class FeedbackStore:
    def __init__(self, path=None, export_path=None):
        self.path = Path(path or DEFAULT_FILE)
        self.export_path = Path(export_path or DEFAULT_EXPORT)

    @staticmethod
    def _clean(value, label, limit=6000):
        if not isinstance(value, str):
            raise ValueError(label + " must be text.")
        value = value.strip()
        if not value:
            raise ValueError(label + " cannot be empty.")
        if len(value) > limit:
            raise ValueError(label + f" exceeds {limit} characters.")
        return value

    def add_preference(self, prompt, chosen, rejected, note=""):
        prompt = self._clean(prompt, "Prompt")
        chosen = self._clean(chosen, "Preferred answer")
        rejected = self._clean(rejected, "Rejected answer")
        note = str(note or "").strip()[:1000]
        if chosen == rejected:
            raise ValueError("Preferred and rejected answers must differ.")
        record = {
            "schema_version": 1,
            "created_at": time.time(),
            "source": "explicit_owner_preference",
            "prompt": prompt,
            "chosen": chosen,
            "rejected": rejected,
            "note": note,
        }
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        return record

    def _records(self):
        if not self.path.is_file():
            return []
        records = []
        with self.path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("prompt"), str)
                    and isinstance(item.get("chosen"), str)
                    and isinstance(item.get("rejected"), str)
                ):
                    records.append(item)
        return records

    def status(self):
        records = self._records()
        exported = self.export_path.is_file()
        return (
            f"[LEARNING] Explicit preference pairs: {len(records)}\n"
            f"Export file: {'present' if exported else 'not created'}\n"
            "Collection: opt-in only; no conversations are captured automatically.\n"
            "Training: export is dataset preparation, not model training."
        )

    def export_dpo(self):
        records = self._records()
        if not records:
            return "[LEARNING] No preference pairs to export."
        self.export_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.export_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            for item in records:
                stream.write(json.dumps({
                    "prompt": item["prompt"],
                    "chosen": item["chosen"],
                    "rejected": item["rejected"],
                }, ensure_ascii=False) + "\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.export_path)
        return (
            f"[LEARNING EXPORT] Wrote {len(records)} preference pair(s) to "
            f"{self.export_path}.\n"
            "This JSONL is suitable as a DPO-style preference dataset for an "
            "off-device LoRA fine-tuning workflow."
        )

    def evaluate_candidate(self, arguments):
        from intelligence.model_evaluation import ModelEvaluation
        parts = str(arguments or "").split()
        if len(parts) not in {2, 3}:
            return "Usage: /learn evaluate <baseline-metrics.json> <candidate-metrics.json> [max-regression]"
        paths = []
        for name in parts[:2]:
            candidate = (self.path.parent / name).resolve()
            if candidate.parent != self.path.parent.resolve() or not candidate.is_file():
                return "[LEARNING ERROR] Metrics files must exist directly inside the local learning data directory."
            paths.append(candidate)
        try:
            tolerance = float(parts[2]) if len(parts) == 3 else 0.01
            result = ModelEvaluation(*paths).compare(max_regression=tolerance)
        except Exception as exc:
            return f"[LEARNING EVALUATION ERROR] {type(exc).__name__}: {exc}"
        return "[LEARNING EVALUATION] " + json.dumps(result, ensure_ascii=False)

    def handle(self, command):
        text = str(command or "").strip()
        if text.lower() in {"", "help", "?"}:
            return (
                "/learn status\n"
                "/learn prefer <prompt> || <preferred answer> || <rejected answer>\n"
                "/learn export\n"
                "Only explicitly submitted preference pairs are stored."
            )
        action, _, rest = text.partition(" ")
        action = action.lower()
        rest = rest.strip()
        if action == "status":
            return self.status()
        if action == "export":
            return self.export_dpo()
        if action == "evaluate":
            return self.evaluate_candidate(rest)
        if action == "prefer":
            parts = [part.strip() for part in rest.split("||")]
            if len(parts) != 3:
                return (
                    "[LEARNING] Use: /learn prefer <prompt> || "
                    "<preferred answer> || <rejected answer>"
                )
            try:
                self.add_preference(*parts)
            except ValueError as exc:
                return "[LEARNING ERROR] " + str(exc)
            return "[LEARNING] Preference pair saved locally. No model was trained."
        return "Use /learn status, /learn prefer ... or /learn export."
