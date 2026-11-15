#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

if [ -z "\${PREFIX:-}" ] || [ ! -d "$PREFIX" ]; then
  echo "Run this installer inside Termux." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_DIR="$ROOT/models/kokoro82m"
MODEL_V1="$MODEL_DIR/kokoro-v1.0.fp16.onnx"
VOICES_V1="$MODEL_DIR/voices-v1.0.bin"
MODEL_V11="$MODEL_DIR/kokoro-v1.1-zh.fp16.onnx"
VOICES_V11="$MODEL_DIR/voices-v1.1-zh.bin"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
mkdir -p "$MODEL_DIR"

for cmd in curl python sha256sum; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "Missing $cmd. Install with: pkg install python curl coreutils" >&2
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
  echo "Downloading $(basename "$dest")..."
  curl --fail --location --retry 3 --retry-delay 2 "$url" -o "$dest.part"
  [ "$(wc -c < "$dest.part")" -ge "$min" ] || {
    echo "Download too small: $dest" >&2
    rm -f "$dest.part"
    exit 1
  }
  echo "$sha  $dest.part" | sha256sum -c -
  mv "$dest.part" "$dest"
}

fetch "$BASE/kokoro-v1.0.fp16.onnx" "$MODEL_V1" 150000000 "f3a290d384fbb27966d462905c71a46cef9e5fd00516b40df32a0b4afe77ac96"
fetch "$BASE/voices-v1.0.bin" "$VOICES_V1" 25000000 "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
fetch "$BASE/kokoro-v1.1-zh.fp16.onnx" "$MODEL_V11" 150000000 "a628ea5d6fbde96d1a85f691a6a00847829937f9e488021ba2c5359bc6ea08b5"
fetch "$BASE/voices-v1.1-zh.bin" "$VOICES_V11" 50000000 "14cb6186c99e4f6016871405f62046c5df863ae27465cbdc4ee08be7dd703acd"

python - "$VOICES_V1" "$VOICES_V11" <<'PY'
import sys
import numpy as np

counts = []
catalog = {}
for path, expected in ((sys.argv[1], 54), (sys.argv[2], 103)):
    with np.load(path, allow_pickle=False) as archive:
        names = list(archive.files)
    if len(names) != expected:
        raise SystemExit(f"{path}: expected {expected} voices, found {len(names)}")
    counts.append(len(names))
    for name in names:
        if name in catalog:
            raise SystemExit(f"Duplicate voice ID across Kokoro packs: {name}")
        catalog[name] = path
if len(catalog) != 157:
    raise SystemExit(f"Expected 157 unique Kokoro voices, found {len(catalog)}")
print(f"Verified voice catalog: {counts[0]} v1.0 + {counts[1]} v1.1-zh = {len(catalog)} unique voices.")
PY

echo
echo "Kokoro 157-voice installation verified."
echo "Both model packs are stored on disk; JARVIS loads only the model for the selected voice."
echo "The selected voice's normal and matching LPC-whisper styles are preloaded when JARVIS starts."
echo "This installation does not modify your current TTS provider."
