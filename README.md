xhs-bot
=======

A minimal Playwright-based CLI to like the latest Xiaohongshu (小红书) posts.

Important: Using automation on third-party sites may violate their Terms of Service and could result in account restrictions. Use at your own risk.

Requirements
-----------
- Python 3.9+
- Playwright browsers installed

Install
-------

```bash
python -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e .
playwright install chromium
```

Usage
-----

```bash
# Launch headed Chromium, hover the filter panel, select "最新", then let the loop run
xhs-bot like-latest "crossfit" --limit 20 --delay-ms 1800 --user-data ./LoginInfo

# The shorthand omits the command name; both forms are supported
xhs-bot "crossfit" --limit 5 --headless --delay-ms 1200
```

`like-latest` is the only supported command. When the browser opens, manually toggle the
filter to "最新" (Latest) before the automation starts scrolling.

Global flags
------------

- `--user-data <path>`: Persistent browser profile directory (keeps login session)
- `--headless`: Run without displaying a window
- `--slow <ms>`: Slow motion delay between actions (useful for debugging)
- `--limit <n>`: Number of posts to attempt per session (default 10)
- `--delay-ms <ms>`: Base delay between likes (default 2000)
- `--delay-jitter-pct <pct>` / `--delay-model`: Randomize the spacing between likes (default gauss ±30%)
- `--duration-min <minutes>`: Spread the session across a wider time window (0 disables)
- `--search-type <type>`: XHS search type (default `51` = notes)
- `--like-prob <0..1>` / `--hover-prob <0..1>`: Control how many cards are liked and whether to hover before clicking
- `--ramp-up-s`, `--long-pause-prob`, `--long-pause-min-s`, `--long-pause-max-s`: Pace controls for slow starts and occasional breaks
- `--session-cap-min`, `--session-cap-max`: Soft range for the number of likes in a run
- `--user-agent`, `--accept-language`, `--timezone-id`: Browser fingerprint overrides
- `--viewport-w`, `--viewport-h`: Fix viewport size; omit to keep random sizing
- `--no-stealth`: Disable stealth tweaks (Playwright exposes `navigator.webdriver`)
- `--no-random-order`: Process cards in the order they appear
- `--verbose`: Print progress logs for each like

Notes
-----
- The first time, run in headed mode and complete login; cookies persist in the user-data directory.
- Selectors are best-effort and may require updates if site UI changes.
- Use `--slow 150` for debugging to see interactions.
- The like loop navigates to `https://www.xiaohongshu.com/search_result/?keyword=<kw>&type=51`. Select the "最新" filter manually; the automation does not toggle it.
- If a note is already liked or Playwright cannot find the icon, the entry is skipped and the script continues.
- Some notes are app-only on web and show an overlay like "当前笔记暂时无法浏览". These are detected and skipped automatically.
- The bot prioritizes cards with fewer than 10 likes first (based on the count shown on each card), then processes the rest according to your randomization settings.

Contributing
------------
New contributors should review the [Repository Guidelines](AGENTS.md) before opening PRs; it summarizes the project layout, manual smoke-test expectations, and commit conventions referenced in this README.

Disclaimer
----------
This project is for educational purposes only. You are responsible for complying with all applicable laws and the platform's policies.
