#!/data/data/com.termux/files/usr/bin/bash
set -u

cd "$HOME/jarvis" || exit 1

LOG="$HOME/jarvis/omniroute.log"
PIDFILE="$HOME/jarvis/omniroute.pid"

if [ -f "$PIDFILE" ]; then
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "OmniRoute already running: PID $pid"
        exit 0
    fi
    rm -f "$PIDFILE"
fi

nohup omniroute --no-open >> "$LOG" 2>&1 &
pid=$!

echo "$pid" > "$PIDFILE"
echo "OmniRoute started: PID $pid"
echo "API: http://127.0.0.1:20128"
