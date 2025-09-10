import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


DEFAULT_USER_DATA_DIR = str(Path.home() / ".xhs_bot" / "user_data")


@dataclass
class BotConfig:
    user_data_dir: str = DEFAULT_USER_DATA_DIR
    headless: bool = False
    slow_mo_ms: int = 50
    locale: str = "en-US"
    timeout_ms: int = 30000


async def create_context(config: BotConfig) -> tuple[Browser, BrowserContext]:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch_persistent_context(
        user_data_dir=config.user_data_dir,
        headless=config.headless,
        slow_mo=config.slow_mo_ms,
        locale=config.locale,
        args=[
            "--no-sandbox",
        ],
        viewport={"width": 1280, "height": 800},
    )
    # launch_persistent_context returns BrowserContext (as browser)
    # For unified return, expose context as ctx and the underlying browser via _browser
    # but Playwright's persistent returns context-like; we just return (None, context)
    return (None, browser)  # type: ignore


async def goto_home(page: Page) -> None:
    await page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")


async def ensure_logged_in(context: BrowserContext) -> Page:
    page = context.pages[0] if context.pages else await context.new_page()
    await goto_home(page)
    return page


async def like_post(context: BrowserContext, url: str) -> None:
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(url, wait_until="domcontentloaded")
    # Try multiple selectors for like button
    candidate_selectors = [
        "button[aria-label='like']",
        "[data-testid='like']",
        "button:has(svg[aria-label='like'])",
        "button:has-text('赞')",
    ]
    for selector in candidate_selectors:
        try:
            el = await page.wait_for_selector(selector, timeout=3000)
            if el:
                await el.click()
                return
        except Exception:
            continue
    raise RuntimeError("Unable to find like button. UI may have changed or requires login.")


async def comment_post(context: BrowserContext, url: str, comment: str) -> None:
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(url, wait_until="domcontentloaded")
    # Find comment input textarea
    candidate_inputs = [
        "textarea",
        "[contenteditable='true']",
        "textarea[placeholder*='评论']",
    ]
    input_found = None
    for selector in candidate_inputs:
        try:
            input_found = await page.wait_for_selector(selector, timeout=4000)
            if input_found:
                break
        except Exception:
            continue
    if not input_found:
        raise RuntimeError("Unable to find comment input. UI may have changed or requires login.")
    await input_found.click()
    await page.keyboard.type(comment, delay=30)
    # Try to submit comment
    candidate_submit = [
        "button:has-text('发布')",
        "button:has-text('发送')",
        "button:has-text('评论')",
    ]
    for selector in candidate_submit:
        try:
            el = await page.wait_for_selector(selector, timeout=3000)
            if el:
                await el.click()
                return
        except Exception:
            continue
    # If no explicit button worked, press Enter
    await page.keyboard.press("Enter")


def parse_common_args(argv: List[str]) -> tuple[BotConfig, List[str]]:
    import argparse

    parser = argparse.ArgumentParser(prog="xhs-bot", description="Xiaohongshu engagement CLI")
    parser.add_argument("command", choices=["login", "like", "comment", "batch"], help="Action")
    parser.add_argument("args", nargs="*", help="Command args")
    parser.add_argument("--user-data", dest="user_data_dir", default=DEFAULT_USER_DATA_DIR, help="Persistent user data dir")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--slow", dest="slow_mo_ms", type=int, default=50, help="Slow motion ms for debugging")
    parser.add_argument("--timeout", dest="timeout_ms", type=int, default=30000, help="Default timeout ms")
    ns = parser.parse_args(argv)
    config = BotConfig(
        user_data_dir=ns.user_data_dir,
        headless=ns.headless,
        slow_mo_ms=ns.slow_mo_ms,
        timeout_ms=ns.timeout_ms,
    )
    return config, [ns.command] + ns.args


async def cmd_login(config: BotConfig) -> int:
    _, context = await create_context(config)
    page = context.pages[0] if context.pages else await context.new_page()
    await goto_home(page)
    print("A browser window will open. Log in manually; your session will persist.")
    print("Press Ctrl+C here to stop when done. The context will be saved.")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    await context.close()
    return 0


async def cmd_like(config: BotConfig, url: str) -> int:
    _, context = await create_context(config)
    try:
        await like_post(context, url)
        print("Liked:", url)
    finally:
        await context.close()
    return 0


async def cmd_comment(config: BotConfig, url: str, comment: str) -> int:
    _, context = await create_context(config)
    try:
        await comment_post(context, url, comment)
        print("Commented on:", url)
    finally:
        await context.close()
    return 0


async def cmd_batch(config: BotConfig, manifest_path: str) -> int:
    # Manifest JSON: {"actions": [{"type": "like"|"comment", "url": "...", "comment": "..."}], "delay_ms": 2000}
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    actions = manifest.get("actions", [])
    delay_ms = int(manifest.get("delay_ms", 2000))
    _, context = await create_context(config)
    try:
        for action in actions:
            action_type = action.get("type")
            url = action.get("url")
            if not url:
                continue
            if action_type == "like":
                await like_post(context, url)
                print("Liked:", url)
            elif action_type == "comment":
                comment = action.get("comment", "")
                if not comment:
                    print("Skipping comment with empty text for", url)
                else:
                    await comment_post(context, url, comment)
                    print("Commented:", url)
            else:
                print("Unknown action type:", action_type)
            await asyncio.sleep(delay_ms / 1000.0)
    finally:
        await context.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    config, args = parse_common_args(argv)
    command = args[0]
    if command == "login":
        return asyncio.run(cmd_login(config))
    if command == "like":
        if len(args) < 2:
            print("Usage: xhs-bot like <post_url>")
            return 2
        return asyncio.run(cmd_like(config, args[1]))
    if command == "comment":
        if len(args) < 3:
            print("Usage: xhs-bot comment <post_url> <comment_text>")
            return 2
        return asyncio.run(cmd_comment(config, args[1], " ".join(args[2:])))
    if command == "batch":
        if len(args) < 2:
            print("Usage: xhs-bot batch <manifest.json>")
            return 2
        return asyncio.run(cmd_batch(config, args[1]))
    print("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

