# Repository Guidelines

## Project Structure & Module Organization
The automation loop lives in `xhs_bot/cli.py`; it exports a single `like-latest` command that drives Playwright. Packaging metadata sits in `setup.py` and `xhs_bot/__init__.py`. Runtime assets such as cached browser state default to `LoginInfo/` (created via `run.sh`) and should stay untracked. Use `run.sh` for tuned defaults; add new modules under `xhs_bot/` and keep CLI wiring in `main()`.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate`: create an isolated environment.
- `pip install -e . && playwright install chromium`: install editable package and browser deps.
- `xhs-bot like-latest "keyword" --headless --limit 5 --user-data ./LoginInfo`: smoke-test the engagement flow.
- `./run.sh`: orchestrated like-latest run with environment overrides (e.g. `KEYWORD="yoga"`).

## Coding Style & Naming Conventions
Use Python 3.9+ with 4-space indentation, type hints, and dataclasses for configuration objects. Prefer descriptive snake_case for functions/variables and keep CLI argument names kebab-case to match existing flags. Long Playwright selectors should remain readable by grouping heuristics in clearly labelled blocks inside `like_latest_from_search`. Keep user-agent lists and human idle helpers near the top of the module to simplify tuning.

## Testing Guidelines
Automated tests are not yet in the repo; when adding logic, factor pure helpers to enable future `pytest` coverage. Before submitting changes, run `xhs-bot like-latest "smoke" --limit 3 --verbose` in headed mode, use the initial 60-second pause to switch the filter to "最新", and confirm at least one like succeeds. Capture console logs to verify human-idle events, skip reasons, user-agent rotation, and other heuristics. If you modify heuristics, document the manual scenarios exercised (e.g., app-only note skipped, already-liked card detected, cards hitting the `dom-detached` retry path) and attach the JSON summary emitted at the end of the run, highlighting any `error_examples` entries and the final `session_state`.

## Commit & Pull Request Guidelines
Commits typically start with a capitalized type prefix (`Refactor:`, `Fix:`, `feat:`) followed by a concise summary and optional issue tag `(#[n])`. Squash small fixups locally before review. PR descriptions should reiterate the intent, list manual test commands executed, note any selector or timing trade-offs, and link related tickets. Include screenshots or logs when UI behavior changes or when adjusting throttling defaults.

## Security & Configuration Tips
Never commit personal cookies or Playwright profiles; ensure `LoginInfo/` and `.xhs_bot/` stay ignored. When sharing reproduction steps, redact post URLs and comments. For long-running sessions set `USER_DATA` to a safe path outside the repo, and favor headless runs when capturing debug logs.

## Current Status
- Each run writes its JSON summary to `session_logs.jsonl` in the working directory so engagement history can be analyzed later.
- Feed browsing is more varied: sessions now insert occasional dwell pauses, reverse scrolls, and brief note previews without immediate engagement to soften automation fingerprints.
- Comment selection is bucketed: add `low|`, `mid|`, or `high|` prefixes in `models/comments.txt` to steer messaging by the note’s visible like count.
