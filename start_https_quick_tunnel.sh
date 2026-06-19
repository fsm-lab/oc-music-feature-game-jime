#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(pwd)}"
LOG_DIR="$APP_DIR/logs"
PID_FILE="$APP_DIR/cloudflared_quick_tunnel.pid"
LOG_FILE="$LOG_DIR/cloudflared_quick_tunnel.log"
LOCAL_URL="${LOCAL_URL:-http://127.0.0.1:18381}"

mkdir -p "$LOG_DIR"
cd "$APP_DIR"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "already running: pid=$(cat "$PID_FILE")"
else
  nohup cloudflared tunnel --no-autoupdate --protocol http2 --url "$LOCAL_URL" > "$LOG_FILE" 2>&1 &
  echo "$!" > "$PID_FILE"
  echo "started: pid=$(cat "$PID_FILE")"
fi

for _ in {1..20}; do
  url="$(grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' "$LOG_FILE" | tail -n 1 || true)"
  if [[ -n "$url" ]]; then
    echo "$url" > "$APP_DIR/cloudflared_quick_tunnel.url"
    echo "url=$url"
    exit 0
  fi
  sleep 1
done

echo "URL not found yet. Check $LOG_FILE" >&2
exit 1
