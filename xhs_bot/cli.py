import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from urllib.parse import quote_plus, urljoin

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


def parse_common_args(argv: List[str]) -> tuple[BotConfig, List[str], Any]:
    import argparse

    parser = argparse.ArgumentParser(prog="xhs-bot", description="Xiaohongshu engagement CLI")
    parser.add_argument(
        "command",
        choices=["login", "like", "comment", "batch", "search", "like-latest"],
        help="Action",
    )
    parser.add_argument("args", nargs="*", help="Command args")
    parser.add_argument("--user-data", dest="user_data_dir", default=DEFAULT_USER_DATA_DIR, help="Persistent user data dir")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--slow", dest="slow_mo_ms", type=int, default=50, help="Slow motion ms for debugging")
    parser.add_argument("--timeout", dest="timeout_ms", type=int, default=30000, help="Default timeout ms")
    parser.add_argument("--limit", dest="limit", type=int, default=10, help="Number of posts to process for search/like-latest")
    parser.add_argument("--delay-ms", dest="delay_ms", type=int, default=2000, help="Delay between actions in like-latest")
    parser.add_argument("--search-type", dest="search_type", default="51", help="XHS search type parameter (51=notes)")
    ns = parser.parse_args(argv)
    config = BotConfig(
        user_data_dir=ns.user_data_dir,
        headless=ns.headless,
        slow_mo_ms=ns.slow_mo_ms,
        timeout_ms=ns.timeout_ms,
    )
    return config, [ns.command] + ns.args, ns


async def _maybe_select_latest_tab(page: Page) -> None:
    candidate_selectors = [
        "button:has-text('最新')",
        "a:has-text('最新')",
        "[role='tab']:has-text('最新')",
        "span:has-text('最新')",
        "div[role='tab']:has-text('最新')",
        "button:has-text('Latest')",
        "a:has-text('Latest')",
    ]
    for selector in candidate_selectors:
        try:
            el = await page.wait_for_selector(selector, timeout=1500)
            if el:
                await el.click()
                await page.wait_for_timeout(600)
                return
        except Exception:
            continue


async def search_latest_posts(
    context: BrowserContext,
    keyword: str,
    limit: int = 10,
    search_type: str = "51",
) -> List[Dict[str, Any]]:
    page = context.pages[0] if context.pages else await context.new_page()
    base_url = "https://www.xiaohongshu.com"
    search_url = f"{base_url}/search_result/?keyword={quote_plus(keyword)}&source=web_explore_feed&type={search_type}"
    await page.goto(search_url, wait_until="domcontentloaded")

    await _maybe_select_latest_tab(page)

    collected: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    async def harvest() -> List[Dict[str, Any]]:
        return await page.evaluate(
            """
            () => {
              const anchors = Array.from(document.querySelectorAll('a[href*="/explore/"]'));
              const items = [];
              for (const a of anchors) {
                let href = a.getAttribute('href') || '';
                if (!href) continue;
                if (!href.startsWith('http')) {
                  href = new URL(href, 'https://www.xiaohongshu.com').toString();
                }
                try {
                  const u = new URL(href);
                  if (!u.pathname.startsWith('/explore/')) continue;
                } catch (e) {
                  continue;
                }
                const card = a.closest('li, div');
                let title = '';
                if (card) {
                  const titleEl = card.querySelector('[class*="title"], h3, p, span');
                  if (titleEl && titleEl.textContent) {
                    title = titleEl.textContent.trim();
                  }
                }
                if (!title && a.title) title = a.title.trim();
                const imgEl = (card ? card.querySelector('img') : (a.querySelector && a.querySelector('img')));
                const image = imgEl ? (imgEl.getAttribute('src') || imgEl.getAttribute('data-src') || '') : '';
                items.push({ href, title, image });
              }
              const uniq = [];
              const seen = new Set();
              for (const it of items) {
                if (seen.has(it.href)) continue;
                seen.add(it.href);
                uniq.push(it);
              }
              return uniq;
            }
            """
        )

    idle_rounds = 0
    max_rounds = 60
    last_count = 0
    while len(collected) < limit and idle_rounds < 5 and max_rounds > 0:
        max_rounds -= 1
        try:
            new_items = await harvest()
        except Exception:
            new_items = []
        for item in new_items:
            url = item.get("href") or item.get("url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            collected.append({
                "url": url,
                "title": (item.get("title") or "").strip(),
                "image": (item.get("image") or "").strip(),
            })
            if len(collected) >= limit:
                break
        if len(collected) == last_count:
            idle_rounds += 1
        else:
            idle_rounds = 0
        last_count = len(collected)
        if len(collected) >= limit:
            break
        try:
            await page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
        except Exception:
            pass
        await asyncio.sleep(0.8)

    return collected[:limit]


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


async def cmd_search(config: BotConfig, keyword: str, limit: int, search_type: str) -> int:
    _, context = await create_context(config)
    try:
        posts = await search_latest_posts(context, keyword, limit, search_type)
        print(json.dumps(posts, ensure_ascii=False, indent=2))
    finally:
        await context.close()
    return 0


async def cmd_like_latest(
    config: BotConfig,
    keyword: str,
    limit: int,
    delay_ms: int,
    search_type: str,
) -> int:
    _, context = await create_context(config)
    try:
        posts = await search_latest_posts(context, keyword, limit, search_type)
        for post in posts:
            url = post.get("url", "")
            if not url:
                continue
            await like_post(context, url)
            print("Liked:", url)
            await asyncio.sleep(delay_ms / 1000.0)
    finally:
        await context.close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    config, args, ns = parse_common_args(argv)
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
    if command == "search":
        if len(args) < 2:
            print("Usage: xhs-bot search <keyword> [--limit N] [--search-type 51]")
            return 2
        keyword = args[1]
        return asyncio.run(cmd_search(config, keyword, ns.limit, ns.search_type))
    if command == "like-latest":
        if len(args) < 2:
            print("Usage: xhs-bot like-latest <keyword> [--limit N] [--delay-ms MS] [--search-type 51]")
            return 2
        keyword = args[1]
        return asyncio.run(cmd_like_latest(config, keyword, ns.limit, ns.delay_ms, ns.search_type))
    print("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

