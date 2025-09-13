import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, cast
import re
import random
import time
from datetime import datetime
import math

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
    like_prob: float = 0.8
    random_order: bool = True
    delay_model: str = "gauss"  # uniform|gauss|lognorm
    ramp_up_s: int = 30
    long_pause_prob: float = 0.15
    long_pause_min_s: float = 4.0
    long_pause_max_s: float = 10.0
    open_note_prob: float = 0.12
    open_author_prob: float = 0.0
    toggle_tab_prob: float = 0.2
    random_viewport: bool = True
    viewport_min_w: int = 1180
    viewport_max_w: int = 1600
    viewport_min_h: int = 720
    viewport_max_h: int = 1000
    accept_language: Optional[str] = None
    timezone_id: Optional[str] = None
    session_cap_min: int = 0
    session_cap_max: int = 0
    daily_cap: int = 0


class AppOnlyNoteError(RuntimeError):
    pass


async def create_context(config: BotConfig) -> tuple[Playwright, BrowserContext]:
    pw = await async_playwright().start()
    # Randomize viewport if enabled
    viewport = {"width": 1280, "height": 800}
    if config.random_viewport:
        viewport = {
            "width": random.randint(config.viewport_min_w, config.viewport_max_w),
            "height": random.randint(config.viewport_min_h, config.viewport_max_h),
        }
    browser = await pw.chromium.launch_persistent_context(
        user_data_dir=config.user_data_dir,
        headless=config.headless,
        slow_mo=config.slow_mo_ms,
        locale=config.locale,
        user_agent=config.user_agent,
        args=[
            "--no-sandbox",
        ],
        viewport=viewport,
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
    # Accept-Language and timezone as best-effort context emulation
    try:
        if config.accept_language:
            for page in browser.pages:
                await page.add_init_script(
                    f"""
                    () => {{
                      try {{ Object.defineProperty(navigator, 'language', {{ get: () => '{config.accept_language.split(',')[0].strip()}' }}); }} catch (e) {{}}
                      try {{ Object.defineProperty(navigator, 'languages', {{ get: () => {json.dumps([p.strip() for p in (config.accept_language.split(',') if config.accept_language else [])])} }}); }} catch (e) {{}}
                    }}
                    """
                )
        if config.timezone_id:
            await browser.grant_permissions([], time_zone_id=config.timezone_id)  # type: ignore
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
        text_locator = page.get_by_text(re.compile(r"^\s*(赞|点赞)\s*$"))
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
    parser.add_argument("--like-prob", dest="like_prob", type=float, default=0.8, help="Probability to like a given card")
    parser.add_argument("--no-random-order", dest="random_order", action="store_false", help="Disable randomization of processing order")
    parser.add_argument("--delay-model", dest="delay_model", default="gauss", choices=["uniform","gauss","lognorm"], help="Delay distribution model")
    parser.add_argument("--ramp-up-s", dest="ramp_up_s", type=int, default=30, help="Warm-up seconds with slower pace initially")
    parser.add_argument("--long-pause-prob", dest="long_pause_prob", type=float, default=0.15, help="Chance to insert long think pause")
    parser.add_argument("--long-pause-min-s", dest="long_pause_min_s", type=float, default=4.0, help="Min long pause seconds")
    parser.add_argument("--long-pause-max-s", dest="long_pause_max_s", type=float, default=10.0, help="Max long pause seconds")
    parser.add_argument("--open-note-prob", dest="open_note_prob", type=float, default=0.12, help="Chance to open a note briefly")
    parser.add_argument("--open-author-prob", dest="open_author_prob", type=float, default=0.0, help="Chance to open an author profile briefly")
    parser.add_argument("--toggle-tab-prob", dest="toggle_tab_prob", type=float, default=0.2, help="Chance to toggle tabs and back")
    parser.add_argument("--random-viewport", dest="random_viewport", action="store_true", default=True, help="Enable random viewport size")
    parser.add_argument("--viewport-w", dest="viewport_w", type=int, help="Fixed viewport width (overrides random)")
    parser.add_argument("--viewport-h", dest="viewport_h", type=int, help="Fixed viewport height (overrides random)")
    parser.add_argument("--accept-language", dest="accept_language", help="Override Accept-Language / navigator.languages")
    parser.add_argument("--timezone-id", dest="timezone_id", help="Override timezone ID (e.g., Asia/Shanghai)")
    parser.add_argument("--session-cap-min", dest="session_cap_min", type=int, default=0, help="Soft min likes per session")
    parser.add_argument("--session-cap-max", dest="session_cap_max", type=int, default=0, help="Soft max likes per session")
    parser.add_argument("--daily-cap", dest="daily_cap", type=int, default=0, help="Max likes per day (not persisted)")
    parser.add_argument("--duration-min", dest="duration_min", type=int, default=0, help="Spread likes across this many minutes (0=disabled)")
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
        like_prob=ns.like_prob,
        random_order=ns.random_order,
        delay_model=ns.delay_model,
        ramp_up_s=ns.ramp_up_s,
        long_pause_prob=ns.long_pause_prob,
        long_pause_min_s=ns.long_pause_min_s,
        long_pause_max_s=ns.long_pause_max_s,
        open_note_prob=ns.open_note_prob,
        open_author_prob=ns.open_author_prob,
        toggle_tab_prob=ns.toggle_tab_prob,
        random_viewport=(False if (ns.viewport_w and ns.viewport_h) else ns.random_viewport),
        viewport_min_w=ns.viewport_w or 1180,
        viewport_max_w=ns.viewport_w or 1600,
        viewport_min_h=ns.viewport_h or 720,
        viewport_max_h=ns.viewport_h or 1000,
        accept_language=ns.accept_language,
        timezone_id=ns.timezone_id,
        session_cap_min=ns.session_cap_min,
        session_cap_max=ns.session_cap_max,
        daily_cap=ns.daily_cap,
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


def draw_delay_seconds(base_delay_ms: int, jitter_pct: int, model: str) -> float:
    base_s = base_delay_ms / 1000.0
    if model == "uniform":
        return compute_jittered_delay_seconds(base_delay_ms, jitter_pct)
    if model == "gauss":
        sigma = base_s * max(0.05, min(jitter_pct, 95) / 150.0)
        val = random.gauss(mu=base_s, sigma=sigma)
        return max(0.05, val)
    if model == "lognorm":
        sigma = max(0.05, min(jitter_pct, 95) / 100.0)
        mu = max(0.01, math.log(base_s) - 0.5 * sigma * sigma)
        val = random.lognormvariate(mu, sigma)
        return max(0.05, val)
    return compute_jittered_delay_seconds(base_delay_ms, jitter_pct)


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
    config: BotConfig,
    keyword: str,
    limit: int = 10,
    search_type: str = "51",
    duration_sec: Optional[int] = None,
) -> List[Dict[str, Any]]:
    page = context.pages[0] if context.pages else await context.new_page()
    base_url = "https://www.xiaohongshu.com"
    search_url = f"{base_url}/search_result/?keyword={quote_plus(keyword)}&source=web_explore_feed&type={search_type}"
    await page.goto(search_url, wait_until="domcontentloaded")
    await _maybe_select_latest_tab(page)

    start_ts = time.monotonic()

    liked_items: List[Dict[str, Any]] = []
    seen_explore_ids: set[str] = set()
    session_like_target = limit

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
              const countEl = note.querySelector('.like-wrapper .count');
              let likeCount = null;
              if (countEl) {
                const raw = (countEl.textContent || '').trim();
                const mW = raw.match(/^(\d+(?:\.\d+)?)\s*[wW]$/);
                if (mW) {
                  likeCount = Math.round(parseFloat(mW[1]) * 10000);
                } else {
                  const m = raw.match(/\d+/);
                  if (m) likeCount = parseInt(m[0], 10);
                }
              }
              return { exploreHref, title, alreadyLiked, likeCount };
            }
            """,
            note_handle,
        )
        return cast(Dict[str, Any], data)  # type: ignore

    from typing import cast

    idle_rounds = 0
    max_rounds = 120
    last_liked_count = 0

    # Soft session cap
    if config.session_cap_min or config.session_cap_max:
        lo = config.session_cap_min or 1
        hi = config.session_cap_max or max(limit, lo)
        session_like_target = max(1, min(limit, random.randint(lo, hi)))
        if config.verbose:
            print(f"Session like target: {session_like_target}")

    async def _maybe_toggle_tabs() -> None:
        try:
            if random.random() <= config.toggle_tab_prob:
                tabs = await page.query_selector_all("button.tab, .tab")
                if tabs:
                    random_tab = random.choice(tabs)
                    await random_tab.click()
                    await asyncio.sleep(random.uniform(0.5, 1.2))
                    # Try to re-select Latest if available
                    await _maybe_select_latest_tab(page)
        except Exception:
            pass

    async def _maybe_mouse_wiggle() -> None:
        try:
            # Small wiggle around current mouse position
            for _ in range(random.randint(1, 3)):
                dx = random.randint(-20, 20)
                dy = random.randint(-10, 10)
                await page.mouse.move(max(1, dx), max(1, dy))
                await asyncio.sleep(random.uniform(0.03, 0.09))
        except Exception:
            pass

    async def _maybe_open_note_or_author(note) -> bool:
        try:
            r = random.random()
            if r <= config.open_note_prob:
                a = await note.query_selector('a[href^="/search_result/"]')
                if a:
                    await a.click()
                    await asyncio.sleep(random.uniform(1.2, 3.5))
                    # random wheel scroll a bit
                    try:
                        await page.mouse.wheel(0, random.randint(150, 500))
                        await asyncio.sleep(random.uniform(0.2, 0.6))
                    except Exception:
                        pass
                    await page.go_back()
                    await asyncio.sleep(random.uniform(0.4, 1.0))
                    return True
            elif r <= config.open_note_prob + config.open_author_prob:
                author = await note.query_selector('a.author')
                if author:
                    await author.click()
                    await asyncio.sleep(random.uniform(1.0, 3.0))
                    try:
                        await page.mouse.wheel(0, random.randint(200, 600))
                        await asyncio.sleep(random.uniform(0.2, 0.6))
                    except Exception:
                        pass
                    await page.go_back()
                    await asyncio.sleep(random.uniform(0.4, 1.0))
                    return True
        except Exception:
            pass
        return False

    async def _is_rate_limited() -> bool:
        try:
            txt = await page.evaluate("() => document.body ? document.body.innerText : ''")
            if not txt:
                return False
            patterns = ["操作频繁", "行为异常", "验证", "验证码", "verify", "captcha", "限制"]
            return any(p in txt for p in patterns)
        except Exception:
            return False

    # If a duration is provided, compute per-like spacing with a bit of jitter
    spacing_sec = None
    if duration_sec and session_like_target > 0:
        spacing_sec = max(1.0, duration_sec / float(session_like_target))
    schedule_jitter_frac = 0.2

    while len(liked_items) < session_like_target and idle_rounds < 8 and max_rounds > 0:
        max_rounds -= 1
        note_handles = await page.query_selector_all("section.note-item")
        # Build candidate list with extracted info
        candidates: List[tuple[Any, Dict[str, Any]]] = []
        for note in note_handles:
            try:
                info = await extract_note_info(note)
            except Exception:
                continue
            url = info.get("exploreHref") or ""
            if not url:
                continue
            if url in seen_explore_ids:
                continue
            if info.get("alreadyLiked"):
                continue
            candidates.append((note, info))

        # Prioritize low-like cards (< 10), then the rest
        low_like = [(n, i) for (n, i) in candidates if isinstance(i.get("likeCount"), (int, float)) and i.get("likeCount") is not None and i.get("likeCount") < 10]
        others = [(n, i) for (n, i) in candidates if (n, i) not in low_like]
        if config.random_order:
            random.shuffle(low_like)
            random.shuffle(others)
        ordered = low_like + others

        progress = False
        for note, info in ordered:
            # Enforce run duration and spacing schedule if provided
            if duration_sec and spacing_sec:
                target_time = start_ts + len(liked_items) * spacing_sec
                target_time += random.uniform(-schedule_jitter_frac, schedule_jitter_frac) * spacing_sec
                now = time.monotonic()
                if now < target_time:
                    await asyncio.sleep(target_time - now)
                # hard stop if overall duration exceeded
                if now > start_ts + duration_sec:
                    break
            url = info.get("exploreHref") or ""
            if not url or url in seen_explore_ids:
                continue
            seen_explore_ids.add(url)
            # Randomly skip this card
            if random.random() > max(0.0, min(1.0, config.like_prob)):
                continue
            try:
                like_target = await note.query_selector("span.like-wrapper, svg.like-icon, .like-wrapper .like-icon")
                if like_target is None:
                    continue
                if config.verbose:
                    lc_repr = info.get("likeCount")
                    print(f"Liking: {url} (likes={lc_repr})")
                await maybe_hover_element(page, like_target, config.hover_prob)
                await _maybe_mouse_wiggle()
                await like_target.click()
                try:
                    await page.wait_for_function(
                        "(note) => { const u = note.querySelector('svg.like-icon use'); return u && (u.getAttribute('xlink:href')||u.getAttribute('href')||'').includes('liked'); }",
                        arg=note,
                        timeout=2000,
                    )
                except Exception:
                    pass
                liked_items.append({"url": url, "title": info.get("title", "")})
                progress = True
                if config.verbose:
                    print("Liked:", url)
                if len(liked_items) >= session_like_target:
                    break
            except Exception:
                continue
        if len(liked_items) == last_liked_count and not progress:
            idle_rounds += 1
        else:
            idle_rounds = 0
        last_liked_count = len(liked_items)
        if len(liked_items) >= session_like_target:
            break
        # Scroll to load more with randomization
        try:
            await _maybe_toggle_tabs()
            scroll_y = random.randint(int(0.6 * 800), int(1.3 * 800))
            if random.random() < 0.6:
                await page.mouse.wheel(0, scroll_y)
            else:
                await page.evaluate("(y) => window.scrollBy(0, y)", scroll_y)
                if random.random() < 0.25:
                    await asyncio.sleep(random.uniform(0.2, 0.6))
                    await page.mouse.wheel(0, -random.randint(50, 200))
        except Exception:
            pass
        # Long think pause sometimes
        if random.random() <= config.long_pause_prob:
            await asyncio.sleep(random.uniform(config.long_pause_min_s, config.long_pause_max_s))
        else:
            await asyncio.sleep(random.uniform(0.4, 1.1))
        # Basic rate limit detection
        if await _is_rate_limited():
            if config.verbose:
                print("Detected potential rate limit or verification. Backing off.")
            await asyncio.sleep(random.uniform(30.0, 90.0))
            break

    return liked_items[:session_like_target]


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
        duration_sec = None
        # ns is not directly available here; use environment variable override if needed or pass via args
        # We parsed duration_min in parse_common_args, but did not store it in config.
        # As a simple approach, derive from argv or set via env XHS_DURATION_MIN; else 0.
        try:
            # Try to infer from sys.argv
            if "--duration-min" in sys.argv:
                idx = sys.argv.index("--duration-min")
                duration_min = int(sys.argv[idx + 1])
                if duration_min > 0:
                    duration_sec = duration_min * 60
        except Exception:
            pass
        if duration_sec is None:
            env_min = os.environ.get("XHS_DURATION_MIN")
            if env_min:
                try:
                    em = int(env_min)
                    if em > 0:
                        duration_sec = em * 60
                except Exception:
                    pass
        liked = await like_latest_from_search(context, config, keyword, limit, search_type, duration_sec=duration_sec)
        for i, item in enumerate(liked, start=1):
            print("Liked:", item.get("url", ""))
            # Ramp-up slower at the beginning of the session
            elapsed = time.monotonic()  # monotonic seconds since process start
            base_delay = delay_ms
            if config.ramp_up_s > 0 and elapsed < config.ramp_up_s:
                ramp_factor = 1.0 + (config.ramp_up_s - elapsed) / config.ramp_up_s
                base_delay = int(base_delay * ramp_factor)
            await asyncio.sleep(draw_delay_seconds(base_delay, config.delay_jitter_pct, config.delay_model))
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

