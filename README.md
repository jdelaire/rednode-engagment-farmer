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
```

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

Disclaimer
----------
This project is for educational purposes only. You are responsible for complying with all applicable laws and the platform's policies.

