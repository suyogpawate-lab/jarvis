#!/data/data/com.termux/files/usr/bin/bash
# JARVIS installer for Termux.
#
#   bash install.sh                  core install, then the guided setup
#   bash install.sh --with-voice     also build whisper.cpp + wake-word packages (heavy)
#   bash install.sh --skip-osint     skip the OSINT tools
#   bash install.sh --skip-setup     don't launch `python setup.py` at the end
#
# Safe to re-run: it only installs what is missing and never touches your
# .env, WhatsApp session, contacts or memory.

echo "[*] Checking Device Environment..."

# Read the native Android build property
ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)

if [ -n "$ANDROID_API_LEVEL" ]; then
    
    export ANDROID_API_LEVEL
    echo "[+] Found Android API Level: $ANDROID_API_LEVEL"
else
    # Fallback option if getprop fails or if you're testing inside a container
    export ANDROID_API_LEVEL=24
    echo "[-] Warning: Could not resolve Android API level natively. FALLBACK TO 24"
fi

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

WITH_VOICE=0
WITH_OSINT=1
RUN_SETUP=1
for arg in "$@"; do
    case "$arg" in
        --with-voice) WITH_VOICE=1 ;;
        --skip-osint) WITH_OSINT=0 ;;
        --skip-setup) RUN_SETUP=0 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "[ERROR] Unknown option: $arg"; exit 2 ;;
    esac
done

info() { printf '\n[INFO] %s\n' "$*"; }
ok()   { printf '[OK] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }

if ! command -v pkg >/dev/null 2>&1; then
    echo "[ERROR] Termux 'pkg' was not found. Run this installer inside Termux."
    exit 1
fi

if [ "$ROOT" != "$HOME/jarvis" ]; then
    warn "JARVIS is designed to live in ~/jarvis (currently: $ROOT)."
fi

# ───────────────────────── system packages ─────────────────────────
info "Installing system packages..."
pkg update -y
pkg install -y python git curl jq tmux termux-api nodejs mpv ollama python-onnxruntime libjpeg-turbo rust binutils \
    python-numpy libxml2 libxslt clang make pkg-config

if [ "$WITH_VOICE" -eq 1 ]; then
    pkg install -y cmake portaudio
fi

# ───────────────────────── python packages ─────────────────────────
info "Installing Python packages..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ "$WITH_OSINT" -eq 1 ]; then
    python -m pip install -r requirements-osint.txt \
        || warn "Some OSINT packages failed to install (lxml needs libxml2/libxslt, installed above)."
fi

if [ "$WITH_VOICE" -eq 1 ]; then
    python -m pip install -r requirements-voice.txt \
        || warn "Voice packages failed; wake-word support may be unavailable on this device."
fi

# ───────────────────────── folders ─────────────────────────
mkdir -p data logs voice/models
ok "Runtime folders ready (data/, logs/)."

# ───────────────────────── WhatsApp bridge ─────────────────────────
info "Installing WhatsApp bridge packages..."
if [ -d whatsapp/node_modules/@whiskeysockets/baileys ] && [ -d whatsapp/node_modules/qrcode-terminal ]; then
    ok "WhatsApp packages already present."
else
    (
        cd whatsapp
        if [ -f package-lock.json ]; then
            npm ci --omit=dev || npm install --omit=dev
        else
            npm install --omit=dev
        fi
    ) || warn "WhatsApp packages failed to install. Retry: cd whatsapp && npm install"
fi

# ───────────────────────── OmniRoute (optional model router) ─────────────────────────
info "Setting up OmniRoute..."
if command -v omniroute >/dev/null 2>&1; then
    ok "OmniRoute already installed."
else
    npm install -g omniroute || warn "OmniRoute install failed; JARVIS still works with Groq keys."
fi
if command -v omniroute >/dev/null 2>&1; then
    bash omniroute_daemon.sh || warn "Could not start OmniRoute."
fi

# ───────────────────────── OSINT tools ─────────────────────────
if [ "$WITH_OSINT" -eq 1 ]; then
    info "Fetching OSINT tools..."
    mkdir -p osint/data
    clone_tool() {
        local name="$1" url="$2"
        if [ -d "osint/data/$name" ]; then
            ok "$name already present."
        else
            git clone --depth 1 "$url" "osint/data/$name" || warn "Could not clone $name."
        fi
    }
    clone_tool sigit  https://github.com/orthodoxenthusiastic/SIGIT.git
    clone_tool x-osint https://github.com/TermuxHackz/X-osint.git
fi

# ───────────────────────── voice (optional) ─────────────────────────
if [ "$WITH_VOICE" -eq 1 ]; then
    info "Setting up speech recognition (whisper.cpp)..."
    WHISPER="$HOME/whisper.cpp"       # voice/listener.py looks here
    if [ ! -d "$WHISPER" ]; then
        git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$WHISPER"
    fi
    if [ ! -x "$WHISPER/build/bin/whisper-cli" ]; then
        (cd "$WHISPER" && cmake -B build && cmake --build build -j2 --config Release) \
            || warn "whisper.cpp build failed."
    else
        ok "whisper-cli already built."
    fi
    MODEL="voice/models/ggml-tiny.en.bin"
    if [ ! -f "$MODEL" ]; then
        curl -L --fail -o "$MODEL" \
            https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin \
            || warn "Could not download the whisper model."
    else
        ok "Whisper model already present."
    fi
fi

# ───────────────────────── report ─────────────────────────
info "Checking optional components..."
if command -v ollama >/dev/null 2>&1; then
    ok "Ollama: $(ollama --version 2>/dev/null | head -n1 || echo installed)"
else
    warn "Ollama not installed; local-model support is unavailable."
fi
if curl -fsS http://127.0.0.1:20128/v1/models >/dev/null 2>&1; then
    ok "OmniRoute is responding on port 20128."
else
    warn "OmniRoute is not responding on port 20128 (optional)."
fi
warn "For notifications, contacts and battery info install the 'Termux:API' app (F-Droid) and grant it permissions."

# ───────────────────────── guided setup ─────────────────────────
if [ "$RUN_SETUP" -eq 1 ] && [ -t 0 ]; then
    info "Starting guided setup (API keys, Gmail, WhatsApp, contacts)..."
    python setup.py
else
    info "Install finished. Run the guided setup with:  python setup.py"
fi

echo
ok "Done. Start JARVIS with:  python jarvis_ui.py"
