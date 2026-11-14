#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

if [ -z "${PREFIX:-}" ] || [ ! -d "$PREFIX" ]; then
  echo "Run this installer inside Termux." >&2
  exit 1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_DIR="$ROOT/models/vision"
TMP_DIR="$MODEL_DIR/.mobileclip-install"
BASE="https://huggingface.co/usama99athar/multilingual-embedders-onnx-coreml/resolve/main/models/mobileclip-s0"
mkdir -p "$MODEL_DIR" "$TMP_DIR"

for cmd in curl python; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing command: $cmd" >&2; exit 1; }
done
python - <<'PY'
mods=("numpy","PIL","onnxruntime")
missing=[]
for m in mods:
    try: __import__(m)
    except Exception: missing.append(m)
if missing:
    raise SystemExit("Missing Python modules: "+", ".join(missing)+"; install Termux packages python-numpy python-pillow python-onnxruntime.")
PY

fetch() {
  local url="$1" dest="$2" min="$3"
  if [ -s "$dest" ] && [ "$(wc -c < "$dest")" -ge "$min" ]; then
    echo "Already downloaded: $(basename "$dest")"
    return
  fi
  rm -f "$dest.part"
  echo "Downloading $(basename "$dest") ..."
  curl --fail --location --retry 3 --retry-delay 2 "$url" -o "$dest.part"
  [ "$(wc -c < "$dest.part")" -ge "$min" ] || { echo "Download too small: $dest" >&2; rm -f "$dest.part"; exit 1; }
  mv "$dest.part" "$dest"
}

fetch "$BASE/ort/Fixed/image_encoder_fp16.ort" "$MODEL_DIR/mobileclip_s0_image_fp16.ort" 30000000
fetch "$BASE/ort/Fixed/text_encoder_fp16.ort" "$TMP_DIR/text_encoder_fp16.ort" 80000000
fetch "$BASE/tokenizer/bpe_simple_vocab_16e6.txt.gz" "$TMP_DIR/bpe_simple_vocab_16e6.txt.gz" 1000000

python "$ROOT/scripts/build_mobileclip_s0_prototypes.py" \
  --text-model "$TMP_DIR/text_encoder_fp16.ort" \
  --vocab "$TMP_DIR/bpe_simple_vocab_16e6.txt.gz" \
  --output "$MODEL_DIR/mobileclip_s0_prototypes.json"

python - "$MODEL_DIR/mobileclip_s0_image_fp16.ort" "$MODEL_DIR/mobileclip_s0_prototypes.json" <<'PY'
import sys, json, onnxruntime as ort
model, manifest = sys.argv[1:]
s=ort.InferenceSession(model, providers=["CPUExecutionProvider"])
assert s.get_inputs()[0].name == "pixel_values"
assert "image_embedding" in [x.name for x in s.get_outputs()]
m=json.load(open(manifest, encoding="utf-8"))
assert m["model"] == "MobileCLIP-S0" and len(m["labels"]) >= 30
assert all(len(x["embedding"]) == 512 for x in m["labels"])
print("MobileCLIP-S0 image encoder and matching text prototypes verified.")
PY

rm -rf "$TMP_DIR"
echo "Installed. JARVIS will load the image encoder lazily on the next screen request."
