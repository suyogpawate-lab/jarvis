#!/data/data/com.termux/files/usr/bin/bash
# JARVIS installer for Termux.
#
#   bash install.sh                  core install, then the guided setup
#   bash install.sh --with-voice     install Needle + Whistle STT and wake-word packages
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
    pkg install -y portaudio
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
mkdir -p data logs voice/models lib/piper models/piper voice/data cache/piper
chmod +x "$ROOT/voice-config" 2>/dev/null || true
info "Preparing repository-local Piper assets..."
python scripts/prepare_piper_assets.py || warn "Could not migrate existing Piper assets; run python scripts/prepare_piper_assets.py to retry."
ok "Runtime and voice folders ready inside $ROOT."

# ───────────────────────── installed apps index ─────────────────────────
info "Capturing installed apps (data/installed_apps.json)..."
pkg install -y aapt >/dev/null 2>&1 || warn "aapt unavailable; app names will be derived from package IDs."
python scripts/capture_apps.py || warn "Could not capture installed apps. Retry: python scripts/capture_apps.py"

# ───────────────────────── shell aliases ─────────────────────────
info "Configuring JARVIS shell aliases..."
BASHRC="$HOME/.bashrc"
ALIAS_START="# >>> JARVIS aliases (managed by install.sh) >>>"
ALIAS_END="# <<< JARVIS aliases (managed by install.sh) <<<"
# Refresh only the installer-managed block, preserving all unrelated shell config.
mkdir -p "$(dirname "$BASHRC")"
touch "$BASHRC"
ALIAS_TMP="$(mktemp "${BASHRC}.jarvis.XXXXXX")"
awk -v start="$ALIAS_START" -v end="$ALIAS_END" '
    $0 == start { inside=1; found_start=1; next }
    $0 == end { inside=0; found_end=1; next }
    !inside { print }
    END { if (inside || (found_start && !found_end)) exit 2 }
' "$BASHRC" > "$ALIAS_TMP" || {
    rm -f "$ALIAS_TMP"
    warn "Could not safely refresh the managed alias block; leaving $BASHRC unchanged."
    exit 1
}
cat >> "$ALIAS_TMP" <<EOF

$ALIAS_START
alias jarvis='python "$ROOT/jarvis_ui.py"'
alias jarvis-cli='python "$ROOT/jarvis.py"'
alias olser='nohup ollama serve > /dev/null 2>&1 &'
alias wa='nohup bash "$ROOT/whatsapp_daemon.sh" > /dev/null 2>&1 &'
alias omni='bash "$ROOT/omniroute_daemon.sh"'
alias rag='nohup python "$ROOT/knowledge_hub/app.py" > /dev/null 2>&1 &'
$ALIAS_END
EOF
chmod --reference="$BASHRC" "$ALIAS_TMP" 2>/dev/null || true
mv "$ALIAS_TMP" "$BASHRC"
ok "Refreshed JARVIS aliases in $BASHRC."
# This loads aliases in the installer's shell. A child script cannot modify
# its parent interactive shell, so users may need to run: source ~/.bashrc
if [ -r "$BASHRC" ]; then
    # shellcheck disable=SC1090
    source "$BASHRC"
fi

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

# ───────────────────────── sqlmap (core runtime only) ─────────────────────────
info "Setting up sqlmap core files..."
SQLMAP_DIR="$ROOT/security/sqlmap-dev"
SQLMAP_SPARSE_PATHS=(/sqlmap.py /LICENSE /lib/ /plugins/ /data/ /thirdparty/ /tamper/)
if git -C "$SQLMAP_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$SQLMAP_DIR" pull --ff-only || warn "sqlmap update failed; keeping the existing checkout."
    git -C "$SQLMAP_DIR" sparse-checkout set --no-cone "${SQLMAP_SPARSE_PATHS[@]}" \
        || warn "Could not refresh sqlmap's core-only sparse checkout."
elif [ -e "$SQLMAP_DIR" ]; then
    warn "$SQLMAP_DIR exists but is not a Git checkout; leaving it untouched."
else
    mkdir -p "$(dirname "$SQLMAP_DIR")"
    if git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/sqlmapproject/sqlmap.git "$SQLMAP_DIR"; then
        git -C "$SQLMAP_DIR" sparse-checkout set --no-cone "${SQLMAP_SPARSE_PATHS[@]}" \
            || warn "sqlmap cloned, but core-only sparse checkout failed."
        ok "sqlmap core runtime installed at security/sqlmap-dev."
    else
        warn "Could not fetch sqlmap. Retry: bash install.sh --skip-setup"
    fi
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
    info "Setting up local speech recognition (Needle + Whistle)..."
    # Install Needle and prepare the Android ARM64 runtime directory.
    python -m pip install --upgrade cactus-needle \
        || warn "Could not install the Needle downloader; check Python/pip."
    mkdir -p "$ROOT/android-arm64"
    if command -v needle >/dev/null 2>&1; then
        needle download android-arm64 --out "$ROOT" \
            || warn "Could not download the Android ARM64 Needle runner."
        needle download whistle --out "$ROOT" \
            || warn "Could not download Whistle speech weights."
    else
        warn "Needle CLI is unavailable. Install cactus-needle, then run: needle download android-arm64 --out \"$ROOT\" && needle download whistle --out \"$ROOT\""
    fi
    # Some Needle distributions provide a static library; build its shared
    # companion when present. The normal executable-based STT path still works
    # if the optional library is not included in the download.
    if [ -f "$ROOT/android-arm64/libneedle.a" ]; then
        if command -v clang++ >/dev/null 2>&1; then
            if clang++ -shared -o "$ROOT/libneedle.so" \
                -Wl,--whole-archive "$ROOT/android-arm64/libneedle.a" \
                -Wl,--no-whole-archive; then
                ok "Built optional libneedle.so."
            else
                warn "Could not build libneedle.so; continuing with the Needle executable."
            fi
        else
            warn "clang++ unavailable; skipping optional libneedle.so build."
        fi
    fi

    if [ -x "$ROOT/android-arm64/needle" ] && [ -f "$ROOT/whistle.cact" ]; then
        ok "Whistle STT ready: android-arm64/needle + whistle.cact."
    else
        warn "Whistle files are incomplete. Retry: bash install.sh --with-voice --skip-setup"
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
    info "Starting guided setup (API keys, Gmail, WhatsApp, contacts, speech output)..."
    python setup.py
else
    info "Install finished. Run the guided setup with:  python setup.py"
fi

echo
ok "Done. Start JARVIS with:  python jarvis_ui.py"
