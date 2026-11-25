#!/data/data/com.termux/files/usr/bin/bash
# Install the lightweight ONNX-only KittenTTS path; reuse all existing assets.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v pkg >/dev/null 2>&1; then
    echo "[ERROR] Run this installer inside Termux."
    exit 1
fi

# Xet is an optional transfer accelerator and is not needed by the runtime.
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"

echo "[Kitten] Checking Termux packages..."
missing_apt=()
for package in python python-onnxruntime espeak; do
    if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "install ok installed"; then
        missing_apt+=("$package")
    else
        echo "[Kitten] Reusing installed Termux package: $package"
    fi
done
if (("${#missing_apt[@]}" )); then
    echo "[Kitten] Installing missing Termux packages: ${missing_apt[*]}"
    pkg install -y "${missing_apt[@]}"
else
    echo "[Kitten] All required Termux packages already exist; skipping pkg install."
fi

echo "[Kitten] Checking Python distributions..."
python - <<'PY'
from importlib.metadata import PackageNotFoundError, distribution
from packaging.requirements import Requirement
from packaging.version import Version
from pathlib import Path
import subprocess
import sys

root = Path.cwd()
requirements_file = root / "requirements-kitten.txt"
requirements = []
for raw in requirements_file.read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    requirements.append(Requirement(line))

def is_satisfied(req):
    if req.marker and not req.marker.evaluate():
        return True
    try:
        installed = distribution(req.name)
    except PackageNotFoundError:
        return False
    return not req.specifier or Version(installed.version) in req.specifier

missing = [req for req in requirements if not is_satisfied(req)]
misaki_missing = any(req.name.lower() == "misaki" for req in missing)
regular_missing = [req for req in missing if req.name.lower() != "misaki"]
kitten_missing = False

# The PyPI 0.9.7 wheel does not contain the kittentts2_tiny frontend used by
# JARVIS. Install the matching upstream source revision when absent.
KITTEN_SOURCE = (
    "git+https://github.com/KittenML/KittenTTS.git@"
    "5802f6b956844919ecf210f4e55f4750a6ad7c6f"
)
try:
    kitten = distribution("kittenml")
    import kittenml.kittentts2_tiny
    if Version(kitten.version) != Version("0.9.7"):
        kitten_missing = True
    else:
        print("[Kitten] Reusing KittenML 0.9.7 with tiny ONNX frontend")
except (PackageNotFoundError, ImportError):
    kitten_missing = True

if regular_missing:
    print("[Kitten] Installing missing Python packages with their required dependencies:")
    for req in regular_missing:
        print("  -", req)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--retries", "5",
         "--timeout", "30", *[str(req) for req in regular_missing]],
        check=True,
    )
else:
    print("[Kitten] All non-Misaki Python dependencies are already satisfied.")

if misaki_missing:
    print("[Kitten] Installing lightweight Misaki 0.9.4 without optional spaCy/torch extras.")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--retries", "5",
         "--timeout", "30", "--no-deps", "--ignore-requires-python", "misaki==0.9.4"],
        check=True,
    )
else:
    print("[Kitten] Reusing Misaki 0.9.4.")

if kitten_missing:
    print("[Kitten] Installing KittenML source with the Pico/Nano ONNX frontend.")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--retries", "5",
         "--timeout", "30", "--no-deps", KITTEN_SOURCE],
        check=True,
    )

PY

# JARVIS's Misaki adapter uses NLTK's English POS tagger. Keep the small
# tagger corpus repository-local and download it only when absent.
echo "[Kitten] Checking English POS tagger..."
python - <<'PY'
from pathlib import Path
import nltk

data_dir = Path.cwd() / "cache" / "nltk_data"
data_dir.mkdir(parents=True, exist_ok=True)
if str(data_dir) not in nltk.data.path:
    nltk.data.path.insert(0, str(data_dir))

resource = "taggers/averaged_perceptron_tagger_eng"
try:
    nltk.data.find(resource, paths=[str(data_dir)])
    print("[Kitten] Reusing existing NLTK English POS tagger.")
except LookupError:
    print("[Kitten] English POS tagger missing; downloading it once...")
    if not nltk.download("averaged_perceptron_tagger_eng", download_dir=str(data_dir), quiet=False):
        raise SystemExit("NLTK English POS tagger download failed.")
    nltk.data.find(resource, paths=[str(data_dir)])

print("[Kitten] English POS tagger verified.")
PY

echo "[Kitten] Verifying runtime imports..."
python - <<'PY'
from importlib.metadata import version
from pathlib import Path
import kittenml
import nltk
import onnxruntime
import soundfile
from kittenml import KittenTTS
from voice.kitten_misaki import nltk_misaki_class

root = Path.cwd()
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
g2p = nltk_misaki_class()()
phonemes, _tokens = g2p("Hello from JARVIS.", preprocess=False)
if not phonemes:
    raise SystemExit("Misaki + NLTK produced no English phonemes.")
print("Misaki + NLTK English G2P:", phonemes)
print("KittenTTS import OK")
PY

echo "[Kitten] Installer checks complete. Existing packages and NLTK data were reused."
echo "[Kitten] The worker's Hugging Face cache is also reused automatically when present."
echo "Select it with: jarvis-setup voice"
