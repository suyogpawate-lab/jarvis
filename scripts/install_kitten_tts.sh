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

echo "[Kitten] Installing KittenML without its heavyweight optional PyTorch stack..."
python -m pip install --retries 5 --timeout 30 --no-deps --upgrade kittenml

echo "[Kitten] Installing the lightweight ONNX + phonemization dependencies..."
python -m pip install --retries 5 --timeout 30 \
    numpy soundfile huggingface_hub espeakng_loader phonemizer misaki spacy num2words

echo "[Kitten] Checking runtime imports..."
python - <<'PY'
import onnxruntime
import soundfile
from kittenml import KittenTTS
print("KittenTTS import OK")
print("ONNX Runtime:", onnxruntime.__version__)
print("SoundFile:", soundfile.__version__)
PY

echo "[Kitten] Runtime installed. The model downloads on first worker start."
echo "Select it with: jarvis-setup voice"
