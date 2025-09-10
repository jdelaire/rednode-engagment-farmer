xhs-bot
=======

A minimal Playwright-based CLI to like and comment on Xiaohongshu (小红书) posts.

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
xhs-bot login [--headless] [--user-data ~/.xhs_bot/user_data]
# A browser launches. Complete login manually; session persists in user data dir.

xhs-bot like <post_url> [--headless] [--user-data ~/.xhs_bot/user_data]

xhs-bot comment <post_url> <comment text...> [--headless] [--user-data ~/.xhs_bot/user_data]

xhs-bot batch manifest.json [--headless] [--user-data ~/.xhs_bot/user_data]

# Search latest posts by keyword (prints JSON)
xhs-bot search "crossfit" --limit 10 [--search-type 51] [--headless]

# Like latest N posts for a keyword
xhs-bot like-latest "crossfit" --limit 10 --delay-ms 1500 [--search-type 51] [--headless]
```

Global flags
------------

- `--user-data <path>`: Persistent browser profile directory (keeps login session)
- `--headless`: Run without displaying a window
- `--slow <ms>`: Slow motion delay between actions (useful for debugging)
- `--timeout <ms>`: Default operation timeout
- `--search-type <type>`: XHS search type (default `51` = notes)
- `--limit <n>`: Number of items to fetch/process for search/like-latest (default 10)
- `--delay-ms <ms>`: Delay between likes in like-latest (default 2000)

Batch manifest format
---------------------

```json
{
  "delay_ms": 2000,
  "actions": [
    { "type": "like", "url": "https://www.xiaohongshu.com/explore/XXXXXXXX" },
    { "type": "comment", "url": "https://www.xiaohongshu.com/explore/YYYYYYYY", "comment": "Nice post!" }
  ]
}
```

Notes
-----
- The first time, run `xhs-bot login` without `--headless` and complete login; cookies persist.
- Selectors are best-effort and may require updates if site UI changes.
- Use `--slow 150` for debugging to see interactions.
- The `search`/`like-latest` commands navigate to `https://www.xiaohongshu.com/search_result/?keyword=<kw>&type=51` and attempt to select the "最新" (Latest) tab, then harvest visible posts. Adjust `--search-type` if needed.
- The like action uses multiple robust heuristics (role-based, CSS, text, and DOM evaluation). If one URL fails, `like-latest` logs the error and continues with the next.

Sample search output
--------------------

```json
[
  {
    "url": "https://www.xiaohongshu.com/explore/XXXXXXXX",
    "title": "Crossfit WOD ...",
    "image": "https://.../cover.jpg"
  },
  {
    "url": "https://www.xiaohongshu.com/explore/YYYYYYYY",
    "title": "My first crossfit class",
    "image": ""
  }
]
```

Disclaimer
----------
This project is for educational purposes only. You are responsible for complying with all applicable laws and the platform's policies.

