""""RAM-only MobileCLIP-S0 image encoder + matching text prototypes."""
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
            "JARVIS_VISION_ONNX", root / "models/vision/mobileclip_s0_image_fp16.ort"
        ))
        self.prototypes_path = Path(prototypes_path or os.getenv(
            "JARVIS_VISION_PROTOTYPES", root / "models/vision/mobileclip_s0_prototypes.json"
        ))
        self.providers = providers or ["CPUExecutionProvider"]
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
                "Community MobileCLIP-S0 .ort model/prototypes are missing; run "
                "scripts/install_mobileclip_s0_termux.sh."
            )
        import numpy as np
        import onnxruntime as ort
        from PIL import Image

        manifest = json.loads(self.prototypes_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 2 or manifest.get("model") != "MobileCLIP-S0":
            raise ValueError("Unsupported MobileCLIP-S0 prototype manifest.")
        vectors, labels = [], []
        for item in manifest.get("labels", []):
            if not isinstance(item, dict) or not isinstance(item.get("label"), str):
                continue
            vector = np.asarray(item.get("embedding"), dtype=np.float32)
            norm = float(np.linalg.norm(vector))
            if vector.shape != (512,) or not norm:
                continue
            vectors.append(vector / norm)
            labels.append(item["label"][:100])
        if not vectors:
            raise ValueError("No valid 512-dimensional MobileCLIP text prototypes.")
        matrix = np.stack(vectors)
        session = ort.InferenceSession(
            str(self.model_path), providers=self.providers
        )
        inputs = session.get_inputs()
        if len(inputs) != 1 or inputs[0].name != "pixel_values":
            raise ValueError("Unexpected MobileCLIP image encoder input contract.")
        shape = inputs[0].shape
        if len(shape) != 4 or shape[1:] != [3, 256, 256]:
            raise ValueError(f"Unexpected MobileCLIP image input shape: {shape}")
        outputs = session.get_outputs()
        output_name = "image_embedding"
        if output_name not in [item.name for item in outputs]:
            raise ValueError("MobileCLIP image_embedding output is missing.")
        self._np, self._Image = np, Image
        self._prototypes, self._labels, self._session = matrix, labels, session
        self._input_name, self._output_name = inputs[0].name, output_name

    def classify_bytes(self, image_bytes: bytes, top_k=5):
        """Classify an in-memory JPEG/PNG frame; never writes the frame to disk."""
        started = time.monotonic()
        try:
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
                raise ValueError("No image bytes supplied.")
            self._load()
            np = self._np
            with self._Image.open(io.BytesIO(image_bytes)) as image:
                image = image.convert("RGB")
                width, height = image.size
                scale = 256.0 / min(width, height)
                resized = (max(256, int(round(width * scale))),
                           max(256, int(round(height * scale))))
                resampling = getattr(self._Image, "Resampling", self._Image)
                image = image.resize(resized, resample=getattr(resampling, "BILINEAR", 2))
                left, top = (resized[0] - 256) // 2, (resized[1] - 256) // 2
                image = image.crop((left, top, left + 256, top + 256))
                array = np.asarray(image, dtype=np.float32) / 255.0
            tensor = array.transpose(2, 0, 1)[None, ...].astype(np.float32)
            output = self._session.run(
                [self._output_name], {self._input_name: tensor}
            )[0]
            vector = np.asarray(output, dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(vector))
            if vector.shape != (512,) or not norm:
                raise RuntimeError("MobileCLIP returned an invalid image embedding.")
            vector /= norm
            scores = self._prototypes @ vector
            order = np.argsort(scores)[::-1][:max(1, min(int(top_k), len(scores)))]
            self.last_error = None
            return {
                "ok": True,
                "labels": [
                    {"label": self._labels[int(i)], "score": float(scores[i])}
                    for i in order
                ],
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "model": "MobileCLIP-S0-community-ORT-FP16",
            }
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "error": self.last_error, "labels": []}

    def classify(self, image_path, top_k=5):
        try:
            data = Path(image_path).read_bytes()
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "error": self.last_error, "labels": []}
        return self.classify_bytes(data, top_k=top_k)
