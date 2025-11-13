#!/usr/bin/env bash
set -euo pipefail

# Resolve repo dir (script location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Optional: host/port and auto-open control
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
XHS_WEB_AUTO_OPEN="${XHS_WEB_AUTO_OPEN:-1}"

# Ensure venv exists and is activated
if [[ ! -d "${SCRIPT_DIR}/.venv" ]]; then
  echo "Creating virtual environment in .venv..."
  python3 -m venv "${SCRIPT_DIR}/.venv"
fi
source "${SCRIPT_DIR}/.venv/bin/activate"

# Install web extras if FastAPI is missing
if ! python3 -c "import fastapi" >/dev/null 2>&1; then
  echo "Installing package and web extras..."
  pip install -U pip setuptools wheel >/dev/null
  pip install -e .[web]
fi

# Ensure Playwright browser installed (no-op if already present)
python3 -m playwright install chromium >/dev/null || true

export XHS_WEB_AUTO_OPEN

echo "Starting XHS web UI on http://${HOST}:${PORT} ..."
# Note: host/port are currently defined in the server. This script keeps envs for future overrides.
exec python -m xhs_bot.web_server
