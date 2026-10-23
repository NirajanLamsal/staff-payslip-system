#!/usr/bin/env bash
# Starts Payslip Manager on this computer only (http://127.0.0.1:8501) and opens the browser.
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
APP_DIR="$(pwd)"
mkdir -p logs output config
PIDFILE="$APP_DIR/.payslip.pid"; PORTFILE="$APP_DIR/.payslip.port"

open_browser() { (xdg-open "$1" >/dev/null 2>&1 || sensible-browser "$1" >/dev/null 2>&1 || true) & }

# Already running? Just open it again.
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null && [ -f "$PORTFILE" ]; then
  URL="http://127.0.0.1:$(cat "$PORTFILE")"
  echo "Payslip Manager is already running at $URL"; open_browser "$URL"; exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. On Ubuntu/Debian run:  sudo apt install python3 python3-venv python3-pip"; exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  echo "Python 3.10 or newer is required (found $(python3 --version))."; exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First start: creating the private Python environment (needs internet once)..."
  rm -rf .venv
  if ! python3 -m venv .venv; then
    echo "Could not create a virtual environment. On Ubuntu/Debian run:  sudo apt install python3-venv python3-pip"
    rm -rf .venv; exit 1
  fi
fi

WANT="$(sha256sum requirements.txt | cut -d' ' -f1)"
if [ ! -f .venv/.req_hash ] || [ "$(cat .venv/.req_hash)" != "$WANT" ]; then
  echo "Installing required libraries (needs internet once, a few minutes)..."
  if ! .venv/bin/python -m pip install --quiet --upgrade pip || ! .venv/bin/python -m pip install --quiet -r requirements.txt; then
    echo "Installing the libraries failed. Check your internet connection and run ./start.sh again."
    echo "Other Linux: install python3, python3-venv and pip with your package manager first."; exit 1
  fi
  echo "$WANT" > .venv/.req_hash
fi

# The app stays locked until an admin account exists - create it now (interactive).
if [ ! -f config/admin.json ] && [ -z "${PAYSLIP_ADMIN_HASH:-}" ]; then
  if [ -t 0 ]; then
    echo "No admin account yet - let's create one."
    .venv/bin/python scripts/set_admin.py || exit 1
  else
    echo "No admin account yet. Run:  .venv/bin/python scripts/set_admin.py"
  fi
fi

# Pick a free port starting at 8501
PORT=8501
while .venv/bin/python - "$PORT" <<'PY'
import socket, sys
s = socket.socket(); s.settimeout(0.5)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
do PORT=$((PORT+1)); [ "$PORT" -gt 8520 ] && { echo "No free port between 8501 and 8520."; exit 1; }; done
[ "$PORT" != "8501" ] && echo "Port 8501 is busy, using $PORT instead."

STREAMLIT_BROWSER_GATHER_USAGE_STATS=false nohup .venv/bin/python -m streamlit run app.py \
  --server.address 127.0.0.1 --server.port "$PORT" --server.headless true \
  --browser.gatherUsageStats false >> logs/server.log 2>&1 &
echo $! > "$PIDFILE"; echo "$PORT" > "$PORTFILE"

URL="http://127.0.0.1:$PORT"
for _ in $(seq 1 40); do
  if .venv/bin/python -c "import urllib.request,sys; urllib.request.urlopen('$URL', timeout=1)" 2>/dev/null; then
    echo "Payslip Manager is running at $URL"; echo "To stop it later run ./stop.sh"
    open_browser "$URL"; exit 0
  fi
  kill -0 "$(cat "$PIDFILE")" 2>/dev/null || { echo "The app stopped unexpectedly. See logs/server.log"; rm -f "$PIDFILE" "$PORTFILE"; exit 1; }
  sleep 0.5
done
echo "Started, but the page did not answer yet. Open $URL in your browser."
