"""Promotion gates for externally trained LoRA/DPO adapters."""
from __future__ import annotations
import json, math
from pathlib import Path

class ModelEvaluation:
    REQUIRED=("task_accuracy","instruction_following","safety_pass_rate")
    def __init__(self, baseline_metrics_path, candidate_metrics_path):
        self.baseline_path=Path(baseline_metrics_path); self.candidate_path=Path(candidate_metrics_path)
    @staticmethod
    def _read(path):
        data=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data,dict): raise ValueError("Metrics must be a JSON object.")
        return data
    def compare(self,max_regression=0.01):
        if not 0 <= float(max_regression) <= 1: raise ValueError("max_regression must be between 0 and 1.")
        base,candidate=self._read(self.baseline_path),self._read(self.candidate_path)
        for key in self.REQUIRED:
            for label,metrics in (("baseline",base),("candidate",candidate)):
                if key not in metrics: raise ValueError(f"Missing {label}.{key}.")
                value=float(metrics[key])
                if not math.isfinite(value) or not 0 <= value <= 1: raise ValueError(f"{label}.{key} must be between 0 and 1.")
        regressions={k:float(base[k])-float(candidate[k]) for k in self.REQUIRED
                     if float(candidate[k]) < float(base[k])-max_regression}
        return {"promote":not regressions,"baseline":base,"candidate":candidate,"regressions":regressions,
                "rule":f"No required metric may regress by more than {max_regression:.1%}."}
