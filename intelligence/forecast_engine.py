"""Low-memory forecasting baseline; no PyTorch dependency."""
from __future__ import annotations
import math, os
from pathlib import Path

class ForecastEngine:
    def __init__(self, model_path=None):
        root=Path(__file__).resolve().parents[1]
        self.model_path=Path(model_path or os.getenv("JARVIS_FORECAST_ONNX",root/"models/forecast/forecast.onnx"))
        self.last_error=None

    def status(self):
        return {"backend":"statistical_baseline","model_present":self.model_path.is_file(),"last_error":self.last_error}

    @staticmethod
    def _clean(values):
        result=[]
        for value in values:
            try:
                n=float(value)
                if math.isfinite(n): result.append(n)
            except (TypeError,ValueError,OverflowError): pass
        return result

    def forecast(self, values, horizon=5):
        series=self._clean(values)
        try: horizon=max(1,min(int(horizon),64))
        except (TypeError,ValueError): return {"ok":False,"error":"Horizon must be an integer."}
        if len(series)<3: return {"ok":False,"error":"At least three finite observations are required."}
        window=series[-min(12,len(series)):]
        diffs=sorted(b-a for a,b in zip(window,window[1:]))
        delta=diffs[len(diffs)//2]; current=window[-1]; predictions=[]
        for step in range(1,horizon+1):
            current += delta*(0.8**(step-1)); predictions.append(current)
        return {"ok":True,"model":"damped_median_trend","forecast":predictions,
                "observations":len(series),"horizon":horizon,
                "warning":"Statistical baseline only; evaluate on chronological held-out data."}
