#!/usr/bin/env bash
set -euo pipefail

# Resolve repo dir (script location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configurable ENV with defaults (override by exporting before calling or inline: KEYWORD="yoga" ./run.sh)
# Tuned to mimic human behavior by default: slower pace, higher variability, soft session caps.
KEYWORD="${KEYWORD:-crossfit}"
LIMIT="${LIMIT:-200}"
SLOW_MS="${SLOW_MS:-85}"
DELAY_MS="${DELAY_MS:-4800}"
DELAY_JITTER_PCT="${DELAY_JITTER_PCT:-35}"
DELAY_MODEL="${DELAY_MODEL:-gauss}"
LIKE_PROB="${LIKE_PROB:-0.82}"
HOVER_PROB="${HOVER_PROB:-0.68}"
SEARCH_TYPE="${SEARCH_TYPE:-51}"
RAMP_UP_S="${RAMP_UP_S:-45}"
LONG_PAUSE_PROB="${LONG_PAUSE_PROB:-0.24}"
LONG_PAUSE_MIN_S="${LONG_PAUSE_MIN_S:-5.0}"
LONG_PAUSE_MAX_S="${LONG_PAUSE_MAX_S:-14.0}"
SESSION_CAP_MIN="${SESSION_CAP_MIN:-120}"
SESSION_CAP_MAX="${SESSION_CAP_MAX:-180}"
DURATION_MIN="${DURATION_MIN:-210}"
HUMAN_IDLE_PROB="${HUMAN_IDLE_PROB:-0.36}"
HUMAN_IDLE_MIN_S="${HUMAN_IDLE_MIN_S:-1.8}"
HUMAN_IDLE_MAX_S="${HUMAN_IDLE_MAX_S:-5.5}"
MOUSE_WIGGLE_PROB="${MOUSE_WIGGLE_PROB:-0.5}"
USER_DATA="${USER_DATA:-${SCRIPT_DIR}/LoginInfo}"
USER_AGENT="${USER_AGENT:-}"
ACCEPT_LANGUAGE="${ACCEPT_LANGUAGE:-}"
TIMEZONE_ID="${TIMEZONE_ID:-}"
VIEWPORT_W="${VIEWPORT_W:-}"
VIEWPORT_H="${VIEWPORT_H:-}"

# Comment (typing only by default; enabled conservatively; submission disabled unless COMMENT_SUBMIT is set)
COMMENT_PROB="${COMMENT_PROB:-0.08}"
COMMENT_MAX_PER_SESSION="${COMMENT_MAX_PER_SESSION:-10}"
COMMENT_MIN_INTERVAL_S="${COMMENT_MIN_INTERVAL_S:-300}"
COMMENT_TEXT_FILE="${COMMENT_TEXT_FILE:-${SCRIPT_DIR}/models/comments.txt}"
COMMENT_TYPE_DELAY_MIN_MS="${COMMENT_TYPE_DELAY_MIN_MS:-60}"
COMMENT_TYPE_DELAY_MAX_MS="${COMMENT_TYPE_DELAY_MAX_MS:-140}"
COMMENT_SUBMIT="${COMMENT_SUBMIT:-}"

if [[ -z "${KEYWORD// }" ]]; then
  echo "KEYWORD must be set (e.g. KEYWORD=\"yoga\" ./run.sh)" >&2
  exit 1
fi

# Optional flags: set to non-empty to enable; leave empty to omit
HEADLESS="${HEADLESS:-}"
VERBOSE="${VERBOSE:-1}"
NO_RANDOM_UA="${NO_RANDOM_UA:-}"
NO_RANDOM_ORDER="${NO_RANDOM_ORDER:-}"
NO_STEALTH="${NO_STEALTH:-}"

# Check if xhs-bot command exists, if not create and activate virtual environment
if ! command -v xhs-bot &> /dev/null; then
    echo "xhs-bot command not found. Creating and activating virtual environment..."
    python3 -m venv .venv && source .venv/bin/activate
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
  --comment-prob "$COMMENT_PROB" \
  --comment-max-per-session "$COMMENT_MAX_PER_SESSION" \
  --comment-min-interval-s "$COMMENT_MIN_INTERVAL_S" \
  --comment-text-file "$COMMENT_TEXT_FILE" \
  --comment-type-delay-min-ms "$COMMENT_TYPE_DELAY_MIN_MS" \
  --comment-type-delay-max-ms "$COMMENT_TYPE_DELAY_MAX_MS" \
  ${VERBOSE:+--verbose} \
  ${HEADLESS:+--headless} \
  ${NO_RANDOM_UA:+--no-random-ua} \
  ${NO_RANDOM_ORDER:+--no-random-order} \
  ${NO_STEALTH:+--no-stealth} \
  ${COMMENT_SUBMIT:+--comment-submit} \
  ${USER_AGENT:+--user-agent "$USER_AGENT"} \
  ${ACCEPT_LANGUAGE:+--accept-language "$ACCEPT_LANGUAGE"} \
  ${TIMEZONE_ID:+--timezone-id "$TIMEZONE_ID"} \
  ${VIEWPORT_W:+--viewport-w "$VIEWPORT_W"} \
  ${VIEWPORT_H:+--viewport-h "$VIEWPORT_H"} \
  --user-data "$USER_DATA"
