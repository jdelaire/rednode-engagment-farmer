import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast
import random
import time
from datetime import datetime
import math

from urllib.parse import quote_plus

from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

DEFAULT_USER_DATA_DIR = str(Path.home() / ".xhs_bot" / "user_data")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

COMMON_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.114 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.76 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.118 Safari/537.36",
]


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class BotConfig:
    user_data_dir: str = DEFAULT_USER_DATA_DIR
    headless: bool = False
    slow_mo_ms: int = 50
    locale: str = "en-US"
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
    random_viewport: bool = True
    viewport_min_w: int = 1180
    viewport_max_w: int = 1600
    viewport_min_h: int = 720
    viewport_max_h: int = 1000
    accept_language: Optional[str] = None
    timezone_id: Optional[str] = None
    session_cap_min: int = 0
    session_cap_max: int = 0
    randomize_user_agent: bool = True
    human_idle_prob: float = 0.25
    human_idle_min_s: float = 1.5
    human_idle_max_s: float = 4.5
    mouse_wiggle_prob: float = 0.4


async def create_context(config: BotConfig) -> tuple[Playwright, BrowserContext]:
    pw = await async_playwright().start()
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
        args=["--no-sandbox"],
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
    return (pw, browser)  # type: ignore


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
            box = await element_handle.bounding_box()
            if box:
                target_x = box["x"] + random.uniform(0.2, 0.8) * box["width"]
                target_y = box["y"] + random.uniform(0.2, 0.8) * box["height"]
                await page.mouse.move(target_x, target_y)
            else:
                await element_handle.hover()
            await asyncio.sleep(random.uniform(0.08, 0.25))
    except Exception:
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


async def maybe_idle_like_human(page: Page, config: BotConfig) -> None:
    try:
        prob = max(0.0, min(1.0, config.human_idle_prob))
        if prob <= 0:
            return
        if random.random() > prob:
            return
        sleep_min = max(0.2, config.human_idle_min_s)
        sleep_max = max(sleep_min, config.human_idle_max_s)
        viewport = page.viewport_size
        if viewport:
            wiggle_prob = max(0.0, min(1.0, config.mouse_wiggle_prob))
            if random.random() <= wiggle_prob:
                try:
                    base_x = random.uniform(viewport["width"] * 0.15, viewport["width"] * 0.85)
                    base_y = random.uniform(viewport["height"] * 0.20, viewport["height"] * 0.90)
                    await page.mouse.move(base_x, base_y, steps=random.randint(8, 18))
                    if random.random() < 0.5:
                        drift_x = base_x + random.uniform(-35, 35)
                        drift_y = base_y + random.uniform(-20, 40)
                        await page.mouse.move(drift_x, drift_y, steps=random.randint(4, 10))
                except Exception:
                    pass
        await asyncio.sleep(random.uniform(sleep_min, sleep_max))
    except Exception:
        pass


async def _ensure_note_handle(page: Page, note, info: Dict[str, Any]):
    """Return a fresh note handle if the original became detached."""
    try:
        if note and await page.evaluate("(node) => !!(node && node.isConnected)", note):
            return note
    except Exception:
        pass

    target_url = info.get("exploreHref") or ""
    if not target_url:
        return None
    note_id = target_url.rstrip("/").split("/")[-1]
    if not note_id:
        return None

    try:
        anchor = await page.query_selector(f'section.note-item a[href*="{note_id}"]')
        if not anchor:
            return None
        closest = await anchor.evaluate_handle("el => el.closest('section.note-item')")
        if closest:
            return closest.as_element()
    except Exception:
        return None
    return None


async def _detect_block_state(page: Page) -> str:
    try:
        current_url = page.url
        if current_url and any(
            token in current_url.lower() for token in ["login", "passport", "signin"]
        ):
            return "login-required"
    except Exception:
        pass

    try:
        result = await page.evaluate(  # type: ignore
            """
            () => {
              const bodyText = document.body ? document.body.innerText : '';
              const lower = bodyText.toLowerCase();
              const rateMarkers = ['操作频繁','行为异常','验证','验证码','verify','captcha','限制'];
              const loginMarkers = ['登录','登入','登陆','帳號','账号','sign in','log in','login','手机号','手机登录','手机登錄'];
              let rateHit = false;
              for (const token of rateMarkers) {
                if (!token) continue;
                if (bodyText.includes(token) || lower.includes(token.toLowerCase())) {
                  rateHit = true;
                  break;
                }
              }
              let loginHit = false;
              for (const token of loginMarkers) {
                if (!token) continue;
                if (bodyText.includes(token) || lower.includes(token.toLowerCase())) {
                  loginHit = true;
                  break;
                }
              }
              const hasPassword = !!document.querySelector('input[type="password"], input[name*="password" i]');
              const hasPhone = !!document.querySelector('input[type="tel"], input[name*="phone" i]');
              const hasLoginContainer = !!document.querySelector(
                '.login-container, .login-wrapper, .passport-container, [class*="passport" i], [class*="login" i]'
              );
              return {
                rateHit,
                loginHit,
                hasPassword,
                hasPhone,
                hasLoginContainer,
                bodyLength: bodyText.length,
              };
            }
            """
        )
    except Exception:
        return "none"

    if not result:
        return "none"

    try:
        login_signal = bool(
            result.get("hasPassword")
            or result.get("hasPhone")
            or result.get("hasLoginContainer")
        )
        if result.get("loginHit") and login_signal:
            return "login-required"
        if result.get("rateHit"):
            return "rate-limit"
    except Exception:
        return "none"
    return "none"


async def like_latest_from_search(
    context: BrowserContext,
    config: BotConfig,
    keyword: str,
    limit: int = 10,
    search_type: str = "51",
    duration_sec: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    page = context.pages[0] if context.pages else await context.new_page()
    base_url = "https://www.xiaohongshu.com"
    search_url = f"{base_url}/search_result/?keyword={quote_plus(keyword)}&source=web_explore_feed&type={search_type}"
    await page.goto(search_url, wait_until="domcontentloaded")

    if config.verbose:
        print("Waiting 60 seconds so you can switch filters before automation starts...")
    await asyncio.sleep(60)

    start_ts = time.monotonic()

    liked_items: List[Dict[str, Any]] = []
    skipped_items: List[Dict[str, Any]] = []
    seen_explore_ids: set[str] = set()
    session_state: Dict[str, Any] = {"block_state": "ok"}
    session_expired_logged = False
    session_like_target = limit

    async def extract_note_info(note_handle) -> Dict[str, Any]:
        data = await page.evaluate(
            r"""
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

    idle_rounds = 0
    max_rounds = 120
    last_liked_count = 0

    if config.session_cap_min or config.session_cap_max:
        lo = config.session_cap_min or 1
        hi = config.session_cap_max or max(limit, lo)
        session_like_target = max(1, min(limit, random.randint(lo, hi)))
        if config.verbose:
            print(f"Session like target: {session_like_target}")

    spacing_sec = None
    if duration_sec and session_like_target > 0:
        spacing_sec = max(1.0, duration_sec / float(session_like_target))
    schedule_jitter_frac = 0.2

    while len(liked_items) < session_like_target and idle_rounds < 8 and max_rounds > 0:
        max_rounds -= 1
        block_state = await _detect_block_state(page)
        if block_state == "login-required":
            session_state.update(
                {
                    "block_state": "login-required",
                    "message": "Session appears logged out; reauthenticate.",
                }
            )
            if config.verbose:
                print("Detected logged-out session. Please sign in again.")
            if not session_expired_logged:
                skipped_items.append(
                    {
                        "url": "",
                        "title": "",
                        "reason": "session-expired",
                    }
                )
                session_expired_logged = True
            break
        if block_state == "rate-limit":
            session_state.update(
                {
                    "block_state": "rate-limit",
                    "message": "Rate limit or verification detected.",
                }
            )
            if config.verbose:
                print("Detected potential rate limit or verification. Backing off.")
            await asyncio.sleep(random.uniform(30.0, 90.0))
            break
        note_handles = await page.query_selector_all("section.note-item")
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

        low_like = [
            (n, i)
            for (n, i) in candidates
            if isinstance(i.get("likeCount"), (int, float))
            and i.get("likeCount") is not None
            and i.get("likeCount") < 10
        ]
        others = [(n, i) for (n, i) in candidates if (n, i) not in low_like]
        if config.random_order:
            random.shuffle(low_like)
            random.shuffle(others)
        ordered = low_like + others

        progress = False
        for note, info in ordered:
            if duration_sec and spacing_sec:
                target_time = start_ts + len(liked_items) * spacing_sec
                target_time += random.uniform(-schedule_jitter_frac, schedule_jitter_frac) * spacing_sec
                now = time.monotonic()
                if now < target_time:
                    await asyncio.sleep(target_time - now)
                if now > start_ts + duration_sec:
                    break
            url = info.get("exploreHref") or ""
            if not url or url in seen_explore_ids:
                continue
            seen_explore_ids.add(url)
            if random.random() > max(0.0, min(1.0, config.like_prob)):
                continue
            try:
                note = await _ensure_note_handle(page, note, info) or note
                attempts = 0
                max_attempts = 3
                last_exc: Optional[Exception] = None
                dom_detached_failure = False

                while attempts < max_attempts:
                    like_target = await note.query_selector(
                        "span.like-wrapper, svg.like-icon, .like-wrapper .like-icon"
                    )
                    if like_target is None:
                        note = await _ensure_note_handle(page, note, info) or note
                        attempts += 1
                        await asyncio.sleep(0.1)
                        continue

                    if config.verbose:
                        lc_repr = info.get("likeCount")
                        print(f"Liking: {url} (likes={lc_repr})")

                    try:
                        await note.scroll_into_view_if_needed()
                    except Exception:
                        pass

                    await maybe_idle_like_human(page, config)
                    await maybe_hover_element(page, like_target, config.hover_prob)

                    try:
                        await like_target.click()
                    except Exception as exc:
                        last_exc = exc
                        msg = str(exc).lower()
                        if "not attached" in msg and attempts < max_attempts - 1:
                            note = await _ensure_note_handle(page, note, info) or note
                            dom_detached_failure = True
                            attempts += 1
                            await asyncio.sleep(random.uniform(0.1, 0.3))
                            continue
                        if "not attached" in msg:
                            dom_detached_failure = True
                        raise

                    try:
                        await page.wait_for_function(
                            "(note) => { const u = note.querySelector('svg.like-icon use'); return u && (u.getAttribute('xlink:href')||u.getAttribute('href')||'').includes('liked'); }",
                            arg=note,
                            timeout=2000,
                        )
                    except Exception:
                        pass

                    try:
                        state_changed = await page.evaluate(
                            "(note) => { const u = note.querySelector('svg.like-icon use'); const href = u ? (u.getAttribute('xlink:href')||u.getAttribute('href')||'') : ''; return href.toLowerCase().includes('liked'); }",
                            note,
                        )
                    except Exception:
                        state_changed = False

                    if state_changed:
                        liked_items.append(
                            {
                                "url": url,
                                "title": info.get("title", ""),
                            }
                        )
                        progress = True
                        if config.verbose:
                            print(f"[{now_ts()}] Liked: {url}")
                        break

                    if config.verbose:
                        print(f"Skipped (already-liked or unchanged): {url}")
                    skipped_items.append(
                        {
                            "url": url,
                            "title": info.get("title", ""),
                            "reason": "unchanged",
                        }
                    )

                    if attempts == 0:
                        note = await _ensure_note_handle(page, note, info) or note
                        attempts += 1
                        await asyncio.sleep(0.1)
                        continue

                    break

                if attempts >= max_attempts and (not liked_items or liked_items[-1]["url"] != url):
                    reason = "dom-detached" if dom_detached_failure else "unresolved"
                    skipped_items.append(
                        {
                            "url": url,
                            "title": info.get("title", ""),
                            "reason": reason,
                        }
                    )

                if len(liked_items) >= session_like_target:
                    break

            except Exception as exc:
                err_msg = str(exc)
                if config.verbose:
                    print(
                        f"Error while liking {url}: {exc.__class__.__name__}: {err_msg}"
                    )
                skip_reason = "dom-detached" if "not attached" in err_msg.lower() else "error"
                skipped_items.append(
                    {
                        "url": url,
                        "title": info.get("title", ""),
                        "reason": skip_reason,
                        "error_type": exc.__class__.__name__,
                        "error_message": err_msg[:200],
                    }
                )
                continue
        if len(liked_items) == last_liked_count and not progress:
            idle_rounds += 1
        else:
            idle_rounds = 0
        last_liked_count = len(liked_items)
        if len(liked_items) >= session_like_target:
            break
        try:
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
        if random.random() <= config.long_pause_prob:
            await asyncio.sleep(random.uniform(config.long_pause_min_s, config.long_pause_max_s))
        else:
            await asyncio.sleep(random.uniform(0.4, 1.1))
    return liked_items[:session_like_target], skipped_items, session_state


async def cmd_like_latest(
    config: BotConfig,
    keyword: str,
    limit: int,
    delay_ms: int,
    search_type: str,
    duration_min: int,
) -> int:
    pw, context = await create_context(config)
    start_time = time.time()
    try:
        duration_sec = duration_min * 60 if duration_min > 0 else None
        liked, skipped, session_state = await like_latest_from_search(
            context,
            config,
            keyword,
            limit,
            search_type,
            duration_sec=duration_sec,
        )
        for item in liked:
            url = item.get("url", "")
            print(f"[{now_ts()}] Liked: {url}")
            elapsed = time.monotonic()
            base_delay = delay_ms
            if config.ramp_up_s > 0 and elapsed < config.ramp_up_s:
                ramp_factor = 1.0 + (config.ramp_up_s - elapsed) / config.ramp_up_s
                base_delay = int(base_delay * ramp_factor)
            await asyncio.sleep(
                draw_delay_seconds(base_delay, config.delay_jitter_pct, config.delay_model)
            )
        duration = time.time() - start_time
        total_attempted = len(liked) + len(skipped)
        from collections import Counter

        skip_reasons = Counter(item.get("reason", "unknown") for item in skipped)
        error_examples = [
            {
                "url": item.get("url"),
                "error_type": item.get("error_type"),
                "error_message": item.get("error_message"),
            }
            for item in skipped
            if item.get("reason") == "error"
        ][:5]
        summary = {
            "ts": now_ts(),
            "keyword": keyword,
            "liked": len(liked),
            "skipped": len(skipped),
            "attempted": total_attempted,
            "duration_sec": round(duration, 2),
            "skip_breakdown": dict(skip_reasons),
            "error_examples": error_examples,
            "session_state": session_state,
        }
        print(f"[{summary['ts']}] Summary: {json.dumps(summary, ensure_ascii=False)}")
    finally:
        try:
            await context.close()
        finally:
            try:
                await pw.stop()
            except Exception:
                pass
    if session_state.get("block_state") == "login-required":
        print("Session ended because authentication expired. Sign in manually and rerun.")
        return 1
    return 0


def parse_args(argv: List[str]) -> tuple[BotConfig, Any]:
    import argparse

    parser = argparse.ArgumentParser(
        prog="xhs-bot",
        description="Like the latest Xiaohongshu posts for a keyword.",
    )
    parser.add_argument("keyword", help="Search keyword to target.")
    parser.add_argument("--user-data", dest="user_data_dir", default=DEFAULT_USER_DATA_DIR, help="Persistent user data dir")
    parser.add_argument("--headless", action="store_true", help="Run Chromium headless")
    parser.add_argument("--slow", dest="slow_mo_ms", type=int, default=50, help="Slow motion ms for debugging")
    parser.add_argument("--limit", dest="limit", type=int, default=10, help="Number of posts to like")
    parser.add_argument("--delay-ms", dest="delay_ms", type=int, default=2000, help="Base delay between likes in ms")
    parser.add_argument("--delay-jitter-pct", dest="delay_jitter_pct", type=int, default=30, help="Randomize each delay by ±pct%")
    parser.add_argument("--delay-model", dest="delay_model", choices=["uniform", "gauss", "lognorm"], default="gauss", help="Delay distribution model")
    parser.add_argument("--search-type", dest="search_type", default="51", help="XHS search type parameter (51=notes)")
    parser.add_argument("--duration-min", dest="duration_min", type=int, default=0, help="Spread likes across this many minutes (0=disabled)")
    parser.add_argument("--like-prob", dest="like_prob", type=float, default=0.8, help="Probability to like an eligible card")
    parser.add_argument("--hover-prob", dest="hover_prob", type=float, default=0.6, help="Probability to hover before clicking")
    parser.add_argument("--ramp-up-s", dest="ramp_up_s", type=int, default=30, help="Warm-up seconds with slower pace initially")
    parser.add_argument("--long-pause-prob", dest="long_pause_prob", type=float, default=0.15, help="Chance to insert a long pause between scrolls")
    parser.add_argument("--long-pause-min-s", dest="long_pause_min_s", type=float, default=4.0, help="Minimum long pause seconds")
    parser.add_argument("--long-pause-max-s", dest="long_pause_max_s", type=float, default=10.0, help="Maximum long pause seconds")
    parser.add_argument("--session-cap-min", dest="session_cap_min", type=int, default=0, help="Soft minimum likes per session")
    parser.add_argument("--session-cap-max", dest="session_cap_max", type=int, default=0, help="Soft maximum likes per session")
    parser.add_argument("--user-agent", dest="user_agent", default=DEFAULT_USER_AGENT, help="Override browser User-Agent string")
    parser.add_argument("--accept-language", dest="accept_language", help="Override Accept-Language / navigator.languages")
    parser.add_argument("--timezone-id", dest="timezone_id", help="Override timezone ID (e.g., Asia/Shanghai)")
    parser.add_argument("--viewport-w", dest="viewport_w", type=int, help="Fixed viewport width")
    parser.add_argument("--viewport-h", dest="viewport_h", type=int, help="Fixed viewport height")
    parser.add_argument("--no-stealth", dest="stealth", action="store_false", default=True, help="Disable stealth init scripts")
    parser.add_argument("--no-random-order", dest="random_order", action="store_false", help="Disable randomization of processing order")
    parser.add_argument("--no-random-ua", dest="randomize_user_agent", action="store_false", default=True, help="Disable automatic user-agent rotation")
    parser.add_argument("--human-idle-prob", dest="human_idle_prob", type=float, default=0.25, help="Chance to pause like a human between cards")
    parser.add_argument("--human-idle-min-s", dest="human_idle_min_s", type=float, default=1.5, help="Minimum pause length when idling")
    parser.add_argument("--human-idle-max-s", dest="human_idle_max_s", type=float, default=4.5, help="Maximum pause length when idling")
    parser.add_argument("--mouse-wiggle-prob", dest="mouse_wiggle_prob", type=float, default=0.4, help="Chance to wiggle the cursor during human idle pauses")
    parser.add_argument("--verbose", action="store_true", help="Print verbose progress output")

    ns = parser.parse_args(argv)

    random_viewport = True
    viewport_w = ns.viewport_w or 0
    viewport_h = ns.viewport_h or 0
    if viewport_w and viewport_h:
        random_viewport = False

    user_agent = ns.user_agent
    if ns.randomize_user_agent and not ns.user_agent:
        user_agent = random.choice(COMMON_USER_AGENTS)

    config = BotConfig(
        user_data_dir=ns.user_data_dir,
        headless=ns.headless,
        slow_mo_ms=ns.slow_mo_ms,
        verbose=ns.verbose,
        user_agent=user_agent,
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
        random_viewport=random_viewport,
        viewport_min_w=viewport_w or 1180,
        viewport_max_w=viewport_w or 1600,
        viewport_min_h=viewport_h or 720,
        viewport_max_h=viewport_h or 1000,
        accept_language=ns.accept_language,
        timezone_id=ns.timezone_id,
        session_cap_min=ns.session_cap_min,
        session_cap_max=ns.session_cap_max,
        randomize_user_agent=ns.randomize_user_agent,
        human_idle_prob=ns.human_idle_prob,
        human_idle_min_s=ns.human_idle_min_s,
        human_idle_max_s=ns.human_idle_max_s,
        mouse_wiggle_prob=ns.mouse_wiggle_prob,
    )
    return config, ns


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "like-latest":
        argv = argv[1:]
    if not argv:
        print("Usage: xhs-bot like-latest <keyword> [options]")
        return 2
    config, ns = parse_args(argv)
    return asyncio.run(
        cmd_like_latest(
            config,
            ns.keyword,
            ns.limit,
            ns.delay_ms,
            ns.search_type,
            ns.duration_min,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
