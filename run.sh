#!/usr/bin/env bash
set -euo pipefail

# Resolve repo dir (script location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configurable ENV with defaults (override by exporting before calling or inline: KEYWORD="yoga" ./run.sh)
KEYWORD="${KEYWORD:-crossfit}"
LIMIT="${LIMIT:-100}"
SLOW_MS="${SLOW_MS:-50}"
DELAY_MS="${DELAY_MS:-1800}"
DELAY_JITTER_PCT="${DELAY_JITTER_PCT:-40}"
DELAY_MODEL="${DELAY_MODEL:-gauss}"
LIKE_PROB="${LIKE_PROB:-0.8}"
HOVER_PROB="${HOVER_PROB:-0.6}"
SEARCH_TYPE="${SEARCH_TYPE:-51}"
RAMP_UP_S="${RAMP_UP_S:-25}"
LONG_PAUSE_PROB="${LONG_PAUSE_PROB:-0.18}"
LONG_PAUSE_MIN_S="${LONG_PAUSE_MIN_S:-4.0}"
LONG_PAUSE_MAX_S="${LONG_PAUSE_MAX_S:-10.0}"
SESSION_CAP_MIN="${SESSION_CAP_MIN:-0}"
SESSION_CAP_MAX="${SESSION_CAP_MAX:-0}"
DURATION_MIN="${DURATION_MIN:-120}"
HUMAN_IDLE_PROB="${HUMAN_IDLE_PROB:-0.25}"
HUMAN_IDLE_MIN_S="${HUMAN_IDLE_MIN_S:-1.5}"
HUMAN_IDLE_MAX_S="${HUMAN_IDLE_MAX_S:-4.5}"
MOUSE_WIGGLE_PROB="${MOUSE_WIGGLE_PROB:-0.4}"
USER_DATA="${USER_DATA:-${SCRIPT_DIR}/LoginInfo}"
USER_AGENT="${USER_AGENT:-}"
ACCEPT_LANGUAGE="${ACCEPT_LANGUAGE:-}"
TIMEZONE_ID="${TIMEZONE_ID:-}"
VIEWPORT_W="${VIEWPORT_W:-}"
VIEWPORT_H="${VIEWPORT_H:-}"

if [[ -z "${KEYWORD// }" ]]; then
  echo "KEYWORD must be set (e.g. KEYWORD=\"yoga\" ./run.sh)" >&2
  exit 1
fi

# Optional flags: set to non-empty to enable; leave empty to omit
HEADLESS="${HEADLESS:-}"
VERBOSE="${VERBOSE:-1}"
PERSON_DETECTION="${PERSON_DETECTION:-1}"
NO_RANDOM_UA="${NO_RANDOM_UA:-}"
NO_RANDOM_ORDER="${NO_RANDOM_ORDER:-}"
NO_STEALTH="${NO_STEALTH:-}"

# Check if xhs-bot command exists, if not create and activate virtual environment
if ! command -v xhs-bot &> /dev/null; then
    echo "xhs-bot command not found. Creating and activating virtual environment..."
    python3 -m venv .venv && source .venv/bin/activate
    pip3 install opencv-python-headless
fi

xhs-bot like-latest "$KEYWORD" \
  --limit "$LIMIT" \
  --slow "$SLOW_MS" \
  --delay-ms "$DELAY_MS" \
  --delay-jitter-pct "$DELAY_JITTER_PCT" \
  --delay-model "$DELAY_MODEL" \
  --duration-min "$DURATION_MIN" \
  --like-prob "$LIKE_PROB" \
  --hover-prob "$HOVER_PROB" \
  --search-type "$SEARCH_TYPE" \
  --ramp-up-s "$RAMP_UP_S" \
  --long-pause-prob "$LONG_PAUSE_PROB" \
  --long-pause-min-s "$LONG_PAUSE_MIN_S" \
  --long-pause-max-s "$LONG_PAUSE_MAX_S" \
  --session-cap-min "$SESSION_CAP_MIN" \
  --session-cap-max "$SESSION_CAP_MAX" \
  --human-idle-prob "$HUMAN_IDLE_PROB" \
  --human-idle-min-s "$HUMAN_IDLE_MIN_S" \
  --human-idle-max-s "$HUMAN_IDLE_MAX_S" \
  --mouse-wiggle-prob "$MOUSE_WIGGLE_PROB" \
  ${VERBOSE:+--verbose} \
  $( [[ "$PERSON_DETECTION" == "0" ]] && printf '%s' "--no-person-detection" ) \
  ${HEADLESS:+--headless} \
  ${NO_RANDOM_UA:+--no-random-ua} \
  ${NO_RANDOM_ORDER:+--no-random-order} \
  ${NO_STEALTH:+--no-stealth} \
  ${USER_AGENT:+--user-agent "$USER_AGENT"} \
  ${ACCEPT_LANGUAGE:+--accept-language "$ACCEPT_LANGUAGE"} \
  ${TIMEZONE_ID:+--timezone-id "$TIMEZONE_ID"} \
  ${VIEWPORT_W:+--viewport-w "$VIEWPORT_W"} \
  ${VIEWPORT_H:+--viewport-h "$VIEWPORT_H"} \
  --user-data "$USER_DATA"
