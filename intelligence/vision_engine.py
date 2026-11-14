"""RAM-only MobileCLIP-S0 image encoder + precomputed text prototypes.

The image encoder and prototypes must come from the same MobileCLIP-S0 checkpoint.
This is a vector classifier, not a captioning model or object detector.
"""
from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path


class VisionEngine:
    def __init__(self, model_path=None, prototypes_path=None, providers=None):
        root = Path(__file__).resolve().parents[1]
        self.model_path = Path(model_path or os.getenv(
            "JARVIS_VISION_ONNX", root / "models/vision/mobileclip_s0_image.onnx"
        ))
        self.prototypes_path = Path(prototypes_path or os.getenv(
            "JARVIS_VISION_PROTOTYPES", root / "models/vision/mobileclip_s0_prototypes.json"
        ))
        self.providers = providers
        self._session = self._prototypes = self._labels = None
        self.last_error = None

    def status(self):
        return {
            "enabled": self.model_path.is_file() and self.prototypes_path.is_file(),
            "model": str(self.model_path),
            "prototypes": str(self.prototypes_path),
            "loaded": self._session is not None,
            "last_error": self.last_error,
        }

    def _load(self):
        if self._session is not None:
            return
        if not self.model_path.is_file() or not self.prototypes_path.is_file():
            raise RuntimeError(
                "MobileCLIP-S0 ONNX model/prototypes are missing; see intelligence/README.md."
            )
        import numpy as np
        import onnxruntime as ort
        from PIL import Image

        manifest = json.loads(self.prototypes_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("labels"), list):
            raise ValueError("Unsupported MobileCLIP prototype manifest.")
        vectors, labels = [], []
        for item in manifest["labels"]:
            if not isinstance(item, dict) or not isinstance(item.get("label"), str):
                continue
            vector = np.asarray(item.get("embedding"), dtype=np.float32)
            norm = float(np.linalg.norm(vector))
            if vector.ndim != 1 or not norm:
                continue
            vectors.append(vector / norm)
            labels.append(item["label"][:100])
        if not vectors:
            raise ValueError("No valid MobileCLIP text prototypes.")
        matrix = np.stack(vectors)
        session = ort.InferenceSession(
            str(self.model_path),
            providers=self.providers or ["CPUExecutionProvider"],
        )
        inputs = session.get_inputs()
        if len(inputs) != 1:
            raise ValueError("Expected a single-input MobileCLIP image encoder.")
        self._np, self._Image = np, Image
        self._prototypes, self._labels, self._session = matrix, labels, session
        self._input_name = inputs[0].name
        self._size = tuple(manifest.get("input_size", [256, 256]))
        self._mean = np.asarray(manifest["mean"], dtype=np.float32)
        self._std = np.asarray(manifest["std"], dtype=np.float32)
        if len(self._size) != 2 or self._mean.shape != (3,) or self._std.shape != (3,) or np.any(self._std == 0):
            raise ValueError("Invalid MobileCLIP preprocessing metadata.")
        if matrix.shape[1] <= 0:
            raise ValueError("Invalid MobileCLIP embedding dimension.")

    def classify_bytes(self, image_bytes: bytes, top_k=5):
        """Classify one in-memory JPEG/PNG frame; never writes the frame to disk."""
        started = time.monotonic()
        try:
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
                raise ValueError("No image bytes supplied.")
            self._load()
            np = self._np
            with self._Image.open(io.BytesIO(image_bytes)) as image:
                image = image.convert("RGB")
                target_h, target_w = self._size
                if target_h <= 0 or target_w <= 0:
                    raise ValueError("Invalid MobileCLIP input dimensions.")
                # MobileCLIP-S0 uses bicubic shortest-edge resize then a center crop.
                width, height = image.size
                scale = max(target_w / width, target_h / height)
                resized_w = max(target_w, int(round(width * scale)))
                resized_h = max(target_h, int(round(height * scale)))
                resampling = getattr(self._Image, "Resampling", self._Image)
                image = image.resize(
                    (resized_w, resized_h),
                    resample=getattr(resampling, "BICUBIC", 3),
                )
                left = (resized_w - target_w) // 2
                top = (resized_h - target_h) // 2
                image = image.crop((left, top, left + target_w, top + target_h))
                array = np.asarray(image, dtype=np.float32) / 255.0
            tensor = (((array - self._mean) / self._std).transpose(2, 0, 1)[None, ...]).astype(np.float32)
            output = self._session.run(None, {self._input_name: tensor})
            if not output:
                raise RuntimeError("MobileCLIP returned no image embedding.")
            vector = np.asarray(output[0], dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(vector))
            if not norm:
                raise RuntimeError("MobileCLIP returned a zero embedding.")
            vector /= norm
            if vector.shape[0] != self._prototypes.shape[1]:
                raise RuntimeError("Image/text embedding dimensions do not match.")
            scores = self._prototypes @ vector
            order = np.argsort(scores)[::-1][:max(1, min(int(top_k), len(scores)))]
            self.last_error = None
            return {
                "ok": True,
                "labels": [
                    {"label": self._labels[int(index)], "score": float(scores[index])}
                    for index in order
                ],
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "model": "MobileCLIP-S0",
            }
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "error": self.last_error, "labels": []}

    def classify(self, image_path, top_k=5):
        """Compatibility helper for offline tests; live screen path uses classify_bytes."""
        try:
            data = Path(image_path).read_bytes()
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "error": self.last_error, "labels": []}
        return self.classify_bytes(data, top_k=top_k)
