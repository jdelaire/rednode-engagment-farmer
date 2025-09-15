#!/usr/bin/env bash
set -euo pipefail

# Resolve repo dir (script location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configurable ENV with defaults (override by exporting before calling or inline: KEYWORD="yoga" ./run.sh)
KEYWORD="${KEYWORD:-crossfit}"
LIMIT="${LIMIT:-60}"
DELAY_MS="${DELAY_MS:-1800}"
DELAY_JITTER_PCT="${DELAY_JITTER_PCT:-40}"
DELAY_MODEL="${DELAY_MODEL:-gauss}"
LIKE_PROB="${LIKE_PROB:-0.8}"
RAMP_UP_S="${RAMP_UP_S:-25}"
LONG_PAUSE_PROB="${LONG_PAUSE_PROB:-0.18}"
OPEN_NOTE_PROB="${OPEN_NOTE_PROB:-0.0}"
OPEN_AUTHOR_PROB="${OPEN_AUTHOR_PROB:-0.00}"
TOGGLE_TAB_PROB="${TOGGLE_TAB_PROB:-0.2}"
USER_DATA="${USER_DATA:-${SCRIPT_DIR}/LoginInfo}"

# Optional flags: set to non-empty to enable; leave empty to omit
HEADLESS="${HEADLESS:-}"
VERBOSE="${VERBOSE:-1}"

# Check if xhs-bot command exists, if not create and activate virtual environment
if ! command -v xhs-bot &> /dev/null; then
    echo "xhs-bot command not found. Creating and activating virtual environment..."
    python3 -m venv .venv && source .venv/bin/activate
fi

xhs-bot like-latest "$KEYWORD" \
  --limit "$LIMIT" \
  --delay-ms "$DELAY_MS" \
  --delay-jitter-pct "$DELAY_JITTER_PCT" \
  --delay-model "$DELAY_MODEL" \
  --duration-min 120 \
  --like-prob "$LIKE_PROB" \
  --ramp-up-s "$RAMP_UP_S" \
  --long-pause-prob "$LONG_PAUSE_PROB" \
  --open-note-prob "$OPEN_NOTE_PROB" \
  --open-author-prob "$OPEN_AUTHOR_PROB" \
  --toggle-tab-prob "$TOGGLE_TAB_PROB" \
  ${VERBOSE:+--verbose} \
  ${HEADLESS:+--headless} \
  --user-data "$USER_DATA"