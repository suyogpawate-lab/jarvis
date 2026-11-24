#!/data/data/com.termux/files/usr/bin/bash
# Install the lightweight ONNX-only KittenTTS path; do not pull the full
# PyTorch/CUDA-oriented dependency set from kittenml.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v pkg >/dev/null 2>&1; then
    echo "[ERROR] Run this installer inside Termux."
    exit 1
fi

echo "[Kitten] Installing Android ONNX Runtime and eSpeak..."
pkg install -y python python-onnxruntime espeak-ng

echo "[Kitten] Installing KittenML 0.9.7 without its heavyweight PyTorch stack..."
python -m pip install --retries 5 --timeout 30 --no-deps --upgrade "kittenml==0.9.7"

# Misaki's English POS tagger invokes NLTK's averaged_perceptron_tagger_eng.
# That dataset is not part of the lightweight Pico Termux path: KittenML 0.9.7
# can use its eSpeak NG fallback instead. Remove any Misaki copy left by an
# earlier install so it cannot hijack frontend initialization.
echo "[Kitten] Removing optional Misaki frontend (Pico uses eSpeak NG on Termux)..."
python -m pip uninstall -y misaki >/dev/null 2>&1 || true

echo "[Kitten] Installing lightweight ONNX + phonemization dependencies..."
python -m pip install --retries 5 --timeout 30 -r requirements-kitten.txt

echo "[Kitten] Checking runtime imports and package origin..."
python - <<'PY'
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path
import kittenml
import onnxruntime
import soundfile
from kittenml import KittenTTS

package_path = Path(kittenml.__file__).resolve()
legacy_checkout = (Path.home() / "KittenTTS").resolve()
try:
    package_path.relative_to(legacy_checkout)
except ValueError:
    pass
else:
    raise SystemExit(
        "KittenML is importing from ~/KittenTTS. Install it into the active "
        "Termux Python environment rather than using that checkout on PYTHONPATH."
    )

if find_spec("misaki") is not None:
    raise SystemExit(
        "Misaki is still importable after cleanup. Remove it with "
        "'python -m pip uninstall -y misaki' before starting the KittenTTS worker."
    )

print("KittenML:", version("kittenml"))
print("KittenML package:", package_path)
print("ONNX Runtime:", onnxruntime.__version__)
print("SoundFile:", soundfile.__version__)
print("Misaki frontend: absent (eSpeak NG fallback)")
print("KittenTTS import OK")
PY

echo "[Kitten] Runtime installed. The Pico model downloads on first worker start."
echo "[Kitten] The worker preloads the model and runs an ONNX warm-up before reporting READY."
echo "Select it with: jarvis-setup voice"
