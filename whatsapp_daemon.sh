#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

cd "$(dirname "$0")/whatsapp"

exec node bridge.js
