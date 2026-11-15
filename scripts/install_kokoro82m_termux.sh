#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

if [ -z "${PREFIX:-}" ] || [ ! -d "$PREFIX" ]; then
  echo "Run this installer inside Termux." >&2
  exit 1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_DIR="$ROOT/models/kokoro82m"
MODEL="$MODEL_DIR/kokoro-v1.0.fp16.onnx"
VOICES="$MODEL_DIR/voices-v1.0.bin"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
mkdir -p "$MODEL_DIR"

for cmd in curl python espeak-ng sox; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "Missing $cmd. Install Termux packages with: pkg install python curl espeak-ng sox" >&2
    exit 1
  }
done
python - <<'PY'
import numpy, onnxruntime
print("NumPy:", numpy.__version__)
print("ONNX Runtime:", onnxruntime.__version__)
if "CPUExecutionProvider" not in onnxruntime.get_available_providers():
    raise SystemExit("ONNX Runtime CPUExecutionProvider is unavailable.")
PY

fetch() {
  local url="$1" dest="$2" min="$3" sha="$4"
  if [ -s "$dest" ] && [ "$(wc -c < "$dest")" -ge "$min" ]; then
    local got
    got="$(sha256sum "$dest" | awk '{print $1}')"
    if [ "$got" = "$sha" ]; then
      echo "Verified existing $(basename "$dest")"
      return
    fi
    echo "Existing $(basename "$dest") has a different checksum; replacing it."
  fi
  rm -f "$dest.part"
  echo "Downloading $(basename "$dest") (this is a large model file)..."
  curl --fail --location --retry 3 --retry-delay 2 "$url" -o "$dest.part"
  [ "$(wc -c < "$dest.part")" -ge "$min" ] || { echo "Download too small: $dest" >&2; rm -f "$dest.part"; exit 1; }
  echo "$sha  $dest.part" | sha256sum -c -
  mv "$dest.part" "$dest"
}
fetch "$BASE/kokoro-v1.0.fp16.onnx" "$MODEL" 150000000 "f3a290d384fbb27966d462905c71a46cef9e5fd00516b40df32a0b4afe77ac96"
fetch "$BASE/voices-v1.0.bin" "$VOICES" 25000000 "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"

echo
echo "Kokoro FP16 model and 54-voice archive verified."
echo "The model loads into RAM only when JARVIS starts with JARVIS_TTS_PROVIDER=kokoro."
echo "This installation does not modify your current TTS provider."
