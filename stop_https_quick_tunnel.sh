#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(pwd)}"
PID_FILE="$APP_DIR/cloudflared_quick_tunnel.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "not running: pid file not found"
  exit 0
fi

pid="$(cat "$PID_FILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  echo "stopped: pid=$pid"
else
  echo "not running: pid=$pid"
fi
