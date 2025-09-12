import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import re
import random

from urllib.parse import quote_plus, urljoin

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


DEFAULT_USER_DATA_DIR = str(Path.home() / ".xhs_bot" / "user_data")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


@dataclass
class BotConfig:
    user_data_dir: str = DEFAULT_USER_DATA_DIR
    headless: bool = False
    slow_mo_ms: int = 50
    locale: str = "en-US"
    timeout_ms: int = 30000
    verbose: bool = False
    user_agent: str = DEFAULT_USER_AGENT
    delay_jitter_pct: int = 30
    hover_prob: float = 0.6
    stealth: bool = True


class AppOnlyNoteError(RuntimeError):
    pass


async def create_context(config: BotConfig) -> tuple[Playwright, BrowserContext]:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch_persistent_context(
        user_data_dir=config.user_data_dir,
        headless=config.headless,
        slow_mo=config.slow_mo_ms,
        locale=config.locale,
        user_agent=config.user_agent,
        args=[
            "--no-sandbox",
        ],
        viewport={"width": 1280, "height": 800},
    )
    if config.stealth:
        try:
            await browser.add_init_script(
                """
                () => {
                  try {
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                  } catch (e) {}
                }
                """
            )
        except Exception:
            pass
    # launch_persistent_context returns BrowserContext (as browser)
    # For unified return, expose context as ctx and the underlying browser via _browser
    # but Playwright's persistent returns context-like; we just return (None, context)
    return (pw, browser)  # type: ignore


async def goto_home(page: Page) -> None:
    await page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")


async def ensure_logged_in(context: BrowserContext) -> Page:
    page = context.pages[0] if context.pages else await context.new_page()
    await goto_home(page)
    return page


async def _is_app_only_note(page: Page) -> bool:
    app_only_phrases = [
        "当前笔记暂时无法浏览",
        "请打开小红书App扫码查看",
        "请使用小红书App扫码查看",
        "返回首页",
        "小红书如何扫码",
        "问题反馈",
    ]
    for phrase in app_only_phrases:
        try:
            loc = page.get_by_text(phrase)
            await loc.first.wait_for(timeout=800)
            return True
        except Exception:
            continue
    try:
        body_text = await page.evaluate("() => document.body ? document.body.innerText || '' : ''")
        if body_text and ("无法浏览" in body_text and "小红书" in body_text):
            return True
    except Exception:
        pass
    return False


async def like_post(context: BrowserContext, url: str) -> None:
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(url, wait_until="domcontentloaded")
    # Give the page a moment to render interactive elements
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass

    if await _is_app_only_note(page):
        raise AppOnlyNoteError("Note is app-only; skipping")

    # 1) Role-based selector with text matching (robust across markup changes)
    try:
        role_locator = page.get_by_role("button", name=re.compile("赞|点赞|Like|喜欢", re.I))
        if await role_locator.count() > 0:
            await role_locator.first.click()
            return
    except Exception:
        pass

    # 2) Common CSS-based heuristics
    candidate_selectors = [
        "button[aria-label='like']",
        "button[aria-label*='like' i]",
        "[role='button'][aria-label*='like' i]",
        "[data-testid='like']",
        "[data-testid*='like' i]",
        "button:has(svg[aria-label='like'])",
        "button:has(svg[aria-label*='like' i])",
        "[role='button']:has(svg[aria-label*='like' i])",
        "button:has-text('赞')",
        "button:has-text('点赞')",
        "[role='button']:has-text('赞')",
        "[role='button']:has-text('点赞')",
        "[class*='like' i][role='button']",
        "[class*='Like' i][role='button']",
        "[class*='zan' i][role='button']",
        "[class*='dianzan' i][role='button']",
        "[class*='like' i]:has(svg)",
        "[class*='zan' i]:has(svg)",
    ]
    for selector in candidate_selectors:
        try:
            el = await page.wait_for_selector(selector, timeout=1500)
            if el:
                await el.click()
                return
        except Exception:
            continue

    # 3) Text-based locator fallback
    try:
        text_locator = page.get_by_text(re.compile("^\s*(赞|点赞)\s*$"))
        if await text_locator.count() > 0:
            target = text_locator.first
            # Click the nearest clickable ancestor if needed
            # Try direct click first
            try:
                await target.click()
                return
            except Exception:
                pass
            # Fallback: traverse DOM to find a clickable ancestor
            el_handle = await target.element_handle()
            if el_handle:
                ancestor = await page.evaluate_handle(
                    """
                    (el) => {
                      function isClickable(n) {
                        if (!n) return false;
                        const tag = (n.tagName || '').toLowerCase();
                        if (tag === 'button') return true;
                        if (n.getAttribute && (n.getAttribute('role') === 'button')) return true;
                        if (n.onclick) return true;
                        return false;
                      }
                      let cur = el;
                      for (let i = 0; i < 5 && cur; i++) {
                        if (isClickable(cur)) return cur;
                        cur = cur.parentElement;
                      }
                      return el;
                    }
                    """,
                    el_handle,
                )
                clickable = await ancestor.as_element()
                if clickable:
                    await clickable.click()
                    return
    except Exception:
        pass

    # 4) Scripted heuristic: look for visible elements with like-related hints
    try:
        candidate = await page.evaluate_handle(
            """
            () => {
              const HINT_RE = /(like|zan|dianzan|heart)/i;
              const TEXTS = ['赞','点赞','Like','喜欢'];
              function isVisible(el) {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                if (s && (s.visibility === 'hidden' || s.display === 'none')) return false;
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
              }
              const nodes = Array.from(document.querySelectorAll('button, [role="button"], a, div, span'));
              for (const el of nodes) {
                if (!isVisible(el)) continue;
                const txt = (el.innerText || el.textContent || '').trim();
                const hasText = TEXTS.some(t => txt.includes(t));
                const cls = (el.className || '').toString();
                const hint = HINT_RE.test(cls);
                if (hasText || hint) return el;
              }
              return null;
            }
            """
        )
        el = await candidate.as_element()
        if el:
            await el.click()
            return
    except Exception:
        pass

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
    parser.add_argument("--verbose", action="store_true", help="Print verbose progress output")
    parser.add_argument("--user-agent", dest="user_agent", default=DEFAULT_USER_AGENT, help="Override browser User-Agent string")
    parser.add_argument("--delay-jitter-pct", dest="delay_jitter_pct", type=int, default=30, help="Randomize each delay by ±pct%")
    parser.add_argument("--hover-prob", dest="hover_prob", type=float, default=0.6, help="Probability to hover an element before clicking")
    parser.add_argument("--no-stealth", dest="stealth", action="store_false", default=True, help="Disable stealth init scripts")
    ns = parser.parse_args(argv)
    config = BotConfig(
        user_data_dir=ns.user_data_dir,
        headless=ns.headless,
        slow_mo_ms=ns.slow_mo_ms,
        timeout_ms=ns.timeout_ms,
        verbose=ns.verbose,
        user_agent=ns.user_agent,
        delay_jitter_pct=ns.delay_jitter_pct,
        hover_prob=ns.hover_prob,
        stealth=ns.stealth,
    )
    return config, [ns.command] + ns.args, ns


def compute_jittered_delay_seconds(base_delay_ms: int, jitter_pct: int) -> float:
    if base_delay_ms <= 0:
        return 0.0
    jitter_fraction = max(0, min(jitter_pct, 95)) / 100.0
    min_factor = 1.0 - jitter_fraction
    max_factor = 1.0 + jitter_fraction
    factor = random.uniform(min_factor, max_factor)
    total_ms = max(50, int(base_delay_ms * factor))
    return total_ms / 1000.0


async def maybe_hover_element(page: Page, element_handle, hover_probability: float) -> None:
    try:
        if random.random() <= max(0.0, min(1.0, hover_probability)):
            # Prefer realistic mouse move to a random point within element bounds
            box = await element_handle.bounding_box()
            if box:
                target_x = box["x"] + random.uniform(0.2, 0.8) * box["width"]
                target_y = box["y"] + random.uniform(0.2, 0.8) * box["height"]
                await page.mouse.move(target_x, target_y)
            else:
                await element_handle.hover()
            await asyncio.sleep(random.uniform(0.08, 0.25))
    except Exception:
        # Hover is a best-effort nicety; ignore failures
        pass


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


async def like_latest_from_search(
    context: BrowserContext,
    keyword: str,
    limit: int = 10,
    search_type: str = "51",
    verbose: bool = False,
) -> List[Dict[str, Any]]:
    page = context.pages[0] if context.pages else await context.new_page()
    base_url = "https://www.xiaohongshu.com"
    search_url = f"{base_url}/search_result/?keyword={quote_plus(keyword)}&source=web_explore_feed&type={search_type}"
    await page.goto(search_url, wait_until="domcontentloaded")
    await _maybe_select_latest_tab(page)

    liked_items: List[Dict[str, Any]] = []
    seen_explore_ids: set[str] = set()

    async def extract_note_info(note_handle) -> Dict[str, Any]:
        data = await page.evaluate(
            """
            (note) => {
              const exploreA = note.querySelector('a[href^="/explore/"]');
              const searchA = note.querySelector('a[href^="/search_result/"]');
              const hrefRaw = (exploreA && exploreA.getAttribute('href')) || (searchA && searchA.getAttribute('href')) || '';
              let exploreHref = '';
              if (hrefRaw.startsWith('/explore/')) {
                exploreHref = new URL(hrefRaw, 'https://www.xiaohongshu.com').toString();
              } else if (hrefRaw.startsWith('/search_result/')) {
                const id = hrefRaw.split('/').pop()?.split('?')[0] || '';
                if (id) {
                  exploreHref = new URL('/explore/' + id, 'https://www.xiaohongshu.com').toString();
                }
              }
              const titleEl = note.querySelector('.footer .title');
              const title = titleEl ? (titleEl.textContent || '').trim() : '';
              const useEl = note.querySelector('svg.like-icon use');
              const likeHref = useEl ? useEl.getAttribute('xlink:href') || useEl.getAttribute('href') || '' : '';
              const alreadyLiked = likeHref.includes('liked');
              return { exploreHref, title, alreadyLiked };
            }
            """,
            note_handle,
        )
        return cast(Dict[str, Any], data)  # type: ignore

    from typing import cast

    idle_rounds = 0
    max_rounds = 120
    last_liked_count = 0
    while len(liked_items) < limit and idle_rounds < 8 and max_rounds > 0:
        max_rounds -= 1
        note_handles = await page.query_selector_all("section.note-item")
        progress = False
        for note in note_handles:
            info = await extract_note_info(note)
            url = info.get("exploreHref") or ""
            if not url:
                continue
            if url in seen_explore_ids:
                continue
            seen_explore_ids.add(url)
            if info.get("alreadyLiked"):
                continue
            # Try clicking like in this card
            try:
                like_target = await note.query_selector("span.like-wrapper, svg.like-icon, .like-wrapper .like-icon")
                if like_target is None:
                    continue
                if verbose:
                    print("Liking:", url)
                await maybe_hover_element(page, like_target, 0.6)
                await like_target.click()
                try:
                    await page.wait_for_function(
                        "(note) => { const u = note.querySelector('svg.like-icon use'); return u && (u.getAttribute('xlink:href')||u.getAttribute('href')||'').includes('liked'); }",
                        arg=note,
                        timeout=2000,
                    )
                except Exception:
                    # If we cannot confirm state change quickly, still proceed
                    pass
                liked_items.append({"url": url, "title": info.get("title", "")})
                progress = True
                if verbose:
                    print("Liked:", url)
                if len(liked_items) >= limit:
                    break
            except Exception:
                continue
        if len(liked_items) == last_liked_count and not progress:
            idle_rounds += 1
        else:
            idle_rounds = 0
        last_liked_count = len(liked_items)
        if len(liked_items) >= limit:
            break
        # Scroll to load more
        try:
            # Randomized scroll distance and micro-pauses
            scroll_y = random.randint(int(0.6 * 800), int(1.3 * 800))
            await page.evaluate("(y) => window.scrollBy(0, y)", scroll_y)
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.4, 1.1))

    return liked_items[:limit]


async def cmd_login(config: BotConfig) -> int:
    pw, context = await create_context(config)
    page = context.pages[0] if context.pages else await context.new_page()
    await goto_home(page)
    print("A browser window will open. Log in manually; your session will persist.")
    print("Press Ctrl+C here to stop when done. The context will be saved.")
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Exiting and saving session...")
    finally:
        try:
            await context.close()
        finally:
            try:
                await pw.stop()
            except Exception:
                pass
    return 0


async def cmd_like(config: BotConfig, url: str) -> int:
    pw, context = await create_context(config)
    try:
        if config.verbose:
            print("Liking:", url)
        try:
            await like_post(context, url)
            print("Liked:", url)
        except AppOnlyNoteError as e:
            print("Skipped (app-only):", url)
    finally:
        try:
            await context.close()
        finally:
            try:
                await pw.stop()
            except Exception:
                pass
    return 0


async def cmd_comment(config: BotConfig, url: str, comment: str) -> int:
    pw, context = await create_context(config)
    try:
        await comment_post(context, url, comment)
        print("Commented on:", url)
    finally:
        try:
            await context.close()
        finally:
            try:
                await pw.stop()
            except Exception:
                pass
    return 0


async def cmd_batch(config: BotConfig, manifest_path: str) -> int:
    # Manifest JSON: {"actions": [{"type": "like"|"comment", "url": "...", "comment": "..."}], "delay_ms": 2000}
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    actions = manifest.get("actions", [])
    delay_ms = int(manifest.get("delay_ms", 2000))
    pw, context = await create_context(config)
    try:
        for action in actions:
            action_type = action.get("type")
            url = action.get("url")
            if not url:
                continue
            if action_type == "like":
                if config.verbose:
                    print("Liking:", url)
                try:
                    await like_post(context, url)
                    print("Liked:", url)
                except AppOnlyNoteError:
                    print("Skipped (app-only):", url)
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
        try:
            await context.close()
        finally:
            try:
                await pw.stop()
            except Exception:
                pass
    return 0


async def cmd_search(config: BotConfig, keyword: str, limit: int, search_type: str) -> int:
    pw, context = await create_context(config)
    try:
        posts = await search_latest_posts(context, keyword, limit, search_type)
        print(json.dumps(posts, ensure_ascii=False, indent=2))
    finally:
        try:
            await context.close()
        finally:
            try:
                await pw.stop()
            except Exception:
                pass
    return 0


async def cmd_like_latest(
    config: BotConfig,
    keyword: str,
    limit: int,
    delay_ms: int,
    search_type: str,
) -> int:
    pw, context = await create_context(config)
    try:
        liked = await like_latest_from_search(context, keyword, limit, search_type, verbose=config.verbose)
        for item in liked:
            print("Liked:", item.get("url", ""))
            await asyncio.sleep(compute_jittered_delay_seconds(delay_ms, config.delay_jitter_pct))
    finally:
        try:
            await context.close()
        finally:
            try:
                await pw.stop()
            except Exception:
                pass
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

