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

echo "[Kitten] Installing lightweight ONNX, phonemization and NLTK dependencies..."
python -m pip install --retries 5 --timeout 30 -r requirements-kitten.txt

# KittenML's active English frontend calls Misaki -> nltk.pos_tag().
# Provision the exact NLTK model it requests inside the JARVIS tree so worker
# startup is deterministic and does not depend on a user-global NLTK install.
echo "[Kitten] Provisioning English POS tagger..."
python - <<'PY'
from pathlib import Path
import nltk

root = Path(__file__).resolve().parent
data_dir = root / "cache" / "nltk_data"
data_dir.mkdir(parents=True, exist_ok=True)
nltk.data.path.insert(0, str(data_dir))

resource = "taggers/averaged_perceptron_tagger_eng"
try:
    nltk.data.find(resource, paths=[str(data_dir)])
    print("NLTK English POS tagger already present.")
except LookupError:
    if not nltk.download(
        "averaged_perceptron_tagger_eng",
        download_dir=str(data_dir),
        quiet=False,
    ):
        raise SystemExit("NLTK English POS tagger download failed.")

nltk.data.find(resource, paths=[str(data_dir)])
print("NLTK English POS tagger verified:", data_dir / resource)
PY

echo "[Kitten] Checking runtime imports and package origin..."
python - <<'PY'
from importlib.metadata import version
from pathlib import Path
import kittenml
import nltk
import onnxruntime
import soundfile
from kittenml import KittenTTS

root = Path(__file__).resolve().parent
data_dir = root / "cache" / "nltk_data"
nltk.data.find("taggers/averaged_perceptron_tagger_eng", paths=[str(data_dir)])

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

print("KittenML:", version("kittenml"))
print("KittenML package:", package_path)
print("ONNX Runtime:", onnxruntime.__version__)
print("SoundFile:", soundfile.__version__)
print("NLTK:", nltk.__version__)
print("English POS tagger: present")
print("KittenTTS import OK")
PY

echo "[Kitten] Runtime and English frontend data installed."
echo "[Kitten] The worker preloads the Pico model and runs ONNX warm-up before READY."
echo "Select it with: jarvis-setup voice"
