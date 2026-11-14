#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

if [ -z "${PREFIX:-}" ] || [ ! -d "$PREFIX" ]; then
  echo "Run this installer inside Termux." >&2
  exit 1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_DIR="$ROOT/models/kokoro82m"
VOICE_DIR="$MODEL_DIR/voices"
MODEL="$MODEL_DIR/model_q8f16.onnx"
BASE="https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main"
mkdir -p "$VOICE_DIR"

for cmd in curl cargo rustc python; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd" >&2; exit 1; }
done

fetch() {
  local url="$1" dest="$2" minimum="$3"
  if [ -s "$dest" ] && [ "$(wc -c < "$dest")" -ge "$minimum" ]; then
    echo "Present: $(basename "$dest")"
    return
  fi
  rm -f "$dest.part"
  echo "Downloading $(basename "$dest") ..."
  curl --fail --location --retry 3 --retry-delay 2 "$url" -o "$dest.part"
  [ "$(wc -c < "$dest.part")" -ge "$minimum" ] || { echo "Download too small: $dest" >&2; rm -f "$dest.part"; exit 1; }
  mv "$dest.part" "$dest"
}

fetch "$BASE/onnx/model_q8f16.onnx" "$MODEL" 80000000

VOICES=(
  af_alloy af_aoede af_bella af_heart af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky
  am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa
  bf_alice bf_emma bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis
  ef_dora em_alex em_santa ff_siwis
  hf_alpha hf_beta hm_omega hm_psi
  if_sara im_nicola
  jf_alpha jf_gongitsune jf_nezumi jf_tebukuro jm_kumo
  pf_dora pm_alex pm_santa
  zf_xiaobei zf_xiaoni zf_xiaoxiao zf_xiaoyi zm_yunjian zm_yunxi zm_yunxia zm_yunyang
)
echo "Installing ${#VOICES[@]} Kokoro voices..."
for voice in "${VOICES[@]}"; do
  fetch "$BASE/voices/$voice.bin" "$VOICE_DIR/$voice.bin" 500000
done

python "$ROOT/scripts/build_kokoro_voice_blend.py" --voices "$VOICE_DIR" --base am_onyx --donor af_nicole --weight 0.30 --output jarvis_nicole30

# Reuse Termux's installed ONNX Runtime shared library instead of downloading
# a second runtime copy during the Rust build.
ORT_LIB="$(python - <<'PY'
from pathlib import Path
try:
    import onnxruntime
    root = Path(onnxruntime.__file__).resolve().parent
    candidates = [root / "capi" / "libonnxruntime.so", root.parent.parent / "lib" / "libonnxruntime.so"]
    for candidate in candidates:
        if candidate.is_file():
            print(candidate)
            break
except Exception:
    pass
PY
)"
if [ -z "$ORT_LIB" ] || [ ! -f "$ORT_LIB" ]; then
  echo "Could not locate Termux libonnxruntime.so. Install python-onnxruntime first." >&2
  exit 1
fi
export ORT_STRATEGY=system
export ORT_DYLIB_PATH="$ORT_LIB"

echo "Building persistent Android/Termux Kokoro worker against $ORT_LIB ..."
cargo build --release --manifest-path "$ROOT/voice/kokoro_worker/Cargo.toml"

echo
echo "Kokoro-82M assets and worker installed."
echo "Model: $MODEL"
echo "Voices: ${#VOICES[@]} original + jarvis_nicole30 blend"
echo "Select it with: JARVIS_TTS_PROVIDER=kokoro"
