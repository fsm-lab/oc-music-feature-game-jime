#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(pwd)}"
PID_FILE="$APP_DIR/cloudflared_quick_tunnel.pid"
LOG_FILE="$APP_DIR/logs/cloudflared_quick_tunnel.log"
URL_FILE="$APP_DIR/cloudflared_quick_tunnel.url"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "running: pid=$(cat "$PID_FILE")"
else
  echo "not running"
fi

if [[ -f "$URL_FILE" ]]; then
  echo "url=$(cat "$URL_FILE")"
else
  grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null | tail -n 1 | sed 's/^/url=/'
fi
