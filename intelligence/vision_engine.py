"""Optional vector-only visual classifier backed by an exported image ONNX model.

The image encoder must share an embedding space with the precomputed text
prototypes. Arbitrary SmolVLM vision features are not assumed to be CLIP-compatible.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path

class VisionEngine:
    def __init__(self, model_path=None, prototypes_path=None, providers=None):
        root = Path(__file__).resolve().parents[1]
        self.model_path = Path(model_path or os.getenv("JARVIS_VISION_ONNX", root / "models/vision/mobileclip_image.onnx"))
        self.prototypes_path = Path(prototypes_path or os.getenv("JARVIS_VISION_PROTOTYPES", root / "models/vision/prototypes.json"))
        self.providers, self._session, self._prototypes = providers, None, None
        self.last_error = None

    def status(self):
        return {"enabled": self.model_path.is_file() and self.prototypes_path.is_file(),
                "model": str(self.model_path), "prototypes": str(self.prototypes_path),
                "loaded": self._session is not None, "last_error": self.last_error}

    def _load(self):
        if self._session is not None: return
        if not self.model_path.is_file() or not self.prototypes_path.is_file():
            raise RuntimeError("Install the matching image ONNX model and text prototypes; see intelligence/README.md.")
        import numpy as np
        import onnxruntime as ort
        from PIL import Image
        meta = json.loads(self.prototypes_path.read_text(encoding="utf-8"))
        if meta.get("schema_version") != 1 or not isinstance(meta.get("labels"), list):
            raise ValueError("Unsupported vision prototype manifest.")
        vectors, labels = [], []
        for item in meta["labels"]:
            if not isinstance(item, dict) or not isinstance(item.get("label"), str): continue
            vector = np.asarray(item.get("embedding"), dtype=np.float32)
            norm = float(np.linalg.norm(vector))
            if vector.ndim != 1 or not norm: continue
            vectors.append(vector / norm); labels.append(item["label"])
        if not vectors: raise ValueError("No valid text prototypes.")
        matrix = np.stack(vectors)
        session = ort.InferenceSession(str(self.model_path), providers=self.providers)
        self._np, self._prototypes, self._labels, self._session = np, matrix, labels, session
        self._image = Image
        self._size = tuple(meta.get("input_size", [256, 256]))
        self._mean = np.asarray(meta.get("mean", [0.485,0.456,0.406]), dtype=np.float32)
        self._std = np.asarray(meta.get("std", [0.229,0.224,0.225]), dtype=np.float32)

    def classify(self, image_path, top_k=5):
        started = time.monotonic()
        try:
            self._load(); np = self._np
            with self._image.open(image_path) as im:
                arr = np.asarray(im.convert("RGB").resize((self._size[1],self._size[0])),dtype=np.float32)/255.0
            tensor = (((arr-self._mean)/self._std).transpose(2,0,1)[None,...]).astype(np.float32)
            inputs = self._session.get_inputs()
            if not inputs: raise RuntimeError("ONNX model has no inputs.")
            vector = np.asarray(self._session.run(None,{inputs[0].name:tensor})[0],dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(vector))
            if not norm: raise RuntimeError("Image encoder returned zero embedding.")
            vector /= norm
            if vector.shape[0] != self._prototypes.shape[1]:
                raise RuntimeError("Image/text embedding dimensions do not match.")
            scores = self._prototypes @ vector
            order = np.argsort(scores)[::-1][:max(1,min(int(top_k),len(scores)))]
            self.last_error = None
            return {"ok":True,"labels":[{"label":self._labels[int(i)],"score":float(scores[i])} for i in order],
                    "latency_ms":round((time.monotonic()-started)*1000,1),"model":self.model_path.name}
        except Exception as exc:
            self.last_error=f"{type(exc).__name__}: {exc}"
            return {"ok":False,"error":self.last_error,"labels":[]}
