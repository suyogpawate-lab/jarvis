#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

if [ -z "${PREFIX:-}" ] || [ ! -d "$PREFIX" ]; then
  echo "Run this installer inside Termux." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_DIR="$ROOT/models/kokoro82m"
MODEL_V1="$MODEL_DIR/kokoro-v1.0.fp16.onnx"
VOICES_V1="$MODEL_DIR/voices-v1.0.bin"
VOICES_ZH="$MODEL_DIR/voices-v1.1-zh.bin"
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

# The 103 Chinese embeddings are retained on disk for the full 157-voice
# setup catalogue only. The English worker never opens this archive.
if [ ! -s "$VOICES_ZH" ] || [ "$(wc -c < "$VOICES_ZH")" -lt 50000000 ] || \
   ! python - "$VOICES_ZH" <<'PY'
import sys, zipfile
try:
    with zipfile.ZipFile(sys.argv[1]) as archive:
        names = [name for name in archive.namelist() if name.endswith(".npy")]
        valid = len(names) == 103 and archive.testzip() is None
except Exception:
    valid = False
raise SystemExit(0 if valid else 1)
PY
then
  rm -f "$VOICES_ZH.part"
  echo "Downloading Chinese voice catalogue (catalogue only; not loaded by JARVIS)..."
  curl --fail --location --retry 3 --retry-delay 2 "$BASE/voices-v1.1-zh.bin" -o "$VOICES_ZH.part"
  [ "$(wc -c < "$VOICES_ZH.part")" -ge 50000000 ] || {
    echo "Chinese voice catalogue download is incomplete." >&2
    rm -f "$VOICES_ZH.part"
    exit 1
  }
  python - "$VOICES_ZH.part" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    names = [name for name in archive.namelist() if name.endswith(".npy")]
    if len(names) != 103 or archive.testzip() is not None:
        raise SystemExit("Expected a valid archive containing exactly 103 Chinese voice embeddings.")
PY
  mv "$VOICES_ZH.part" "$VOICES_ZH"
fi

python - "$VOICES_V1" "$VOICES_ZH" <<'PY'
import sys
import numpy as np
import zipfile

with np.load(sys.argv[1], allow_pickle=False) as archive:
    english = list(archive.files)
if len(english) != 54 or any(not name.startswith(("a", "b")) for name in english):
    raise SystemExit("Expected exactly 54 English voice embeddings.")
with zipfile.ZipFile(sys.argv[2]) as archive:
    chinese = [name for name in archive.namelist() if name.endswith(".npy")]
    if len(chinese) != 103 or archive.testzip() is not None:
        raise SystemExit("Expected exactly 103 valid Chinese catalogue embeddings.")
print(f"Verified 157 voice IDs: {len(english)} English + {len(chinese)} Chinese.")
print("Only the English archive is opened by the runtime; one selected English embedding is copied into RAM.")
PY

echo
echo "Kokoro installation verified: 157-voice setup catalogue."
echo "Only the English v1.0 ONNX model is installed for synthesis."
echo "The Chinese voice archive is stored on disk for catalogue display and is never loaded by the English worker."
echo "At startup, only the selected English speaker embedding and its derived whisper style are resident."
echo "This installation does not modify your current TTS provider."
