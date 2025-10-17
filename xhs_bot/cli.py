import asyncio
import json
import sys
from dataclasses import dataclass, field
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

SESSION_LOG_PATH = Path("session_logs.jsonl")

STEALTH_INIT_SCRIPT = r"""
(() => {
  const redefine = (object, property, value) => {
    try {
      Object.defineProperty(object, property, { get: () => value, configurable: true });
    } catch (e) {
      try {
        object[property] = value;
      } catch (e2) {}
    }
  };

  redefine(Navigator.prototype, 'webdriver', undefined);
  redefine(Navigator.prototype, 'hardwareConcurrency', Math.max(4, navigator.hardwareConcurrency || 4));
  redefine(Navigator.prototype, 'deviceMemory', navigator.deviceMemory || 8);
  if (!navigator.languages || navigator.languages.length === 0) {
    redefine(Navigator.prototype, 'languages', ['en-US', 'en']);
  }
  if (!navigator.language) {
    redefine(Navigator.prototype, 'language', 'en-US');
  }
  redefine(Navigator.prototype, 'maxTouchPoints', navigator.maxTouchPoints || 1);
  redefine(Navigator.prototype, 'platform', navigator.platform || 'MacIntel');

  if (!window.chrome) {
    redefine(window, 'chrome', { runtime: {} });
  }

  try {
    const originalQuery = navigator.permissions && navigator.permissions.query;
    if (originalQuery) {
      navigator.permissions.query = parameters => {
        const name = parameters && parameters.name;
        if (name === 'notifications') {
          const state = typeof Notification !== 'undefined' ? Notification.permission : 'default';
          return Promise.resolve({ state });
        }
        return originalQuery(parameters);
      };
    }
  } catch (e) {}

  try {
    const pluginArray = () => {
      const plugins = [
        { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      ];
      plugins.forEach(plugin => {
        plugin.length = 1;
        plugin[0] = {
          type: 'application/pdf',
          suffixes: 'pdf',
          description: 'Portable Document Format',
        };
      });
      plugins.length = plugins.length;
      return plugins;
    };
    redefine(navigator, 'plugins', pluginArray());
    redefine(navigator, 'mimeTypes', [{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' }]);
  } catch (e) {}

  try {
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
      get: function () {
        return window;
      },
    });
  } catch (e) {}

  try {
    const getParameter = WebGLRenderingContext && WebGLRenderingContext.prototype.getParameter;
    if (getParameter) {
      WebGLRenderingContext.prototype.getParameter = function (parameter) {
        if (parameter === 37445) {
          return 'Intel Inc.';
        }
        if (parameter === 37446) {
          return 'Intel Iris OpenGL Engine';
        }
        return getParameter.apply(this, arguments);
      };
    }
  } catch (e) {}
})();
"""

DEFAULT_COMMENT_BUCKETS = {
    "low": [
        "Keep showing up and momentum builds",
        "One more rep makes a difference",
        "Great to see the early grind",
        "Fresh start, strong finish ahead",
    ],
    "mid": [
        "Energy here feels unstoppable",
        "Loving the discipline in this set",
        "Dialed in and focused - keep it up",
        "Consistency is clearly paying off",
    ],
    "high": [
        "This level of effort really inspires",
        "You are setting a high bar for everyone",
        "That is championship commitment on display",
        "Outstanding intensity all the way through",
    ],
    "general": [
        "Always impressed by the dedication",
        "Hard work today fuels tomorrow",
        "Strong work - thanks for sharing",
        "Love seeing this routine locked in",
    ],
}


def load_comment_library(custom_path: Optional[str]) -> tuple[List[str], Dict[str, List[str]]]:
    """Load comments grouped by buckets; supports optional `bucket|text` lines."""
    buckets: Dict[str, List[str]] = {k: list(v) for k, v in DEFAULT_COMMENT_BUCKETS.items()}
    flat: List[str] = [text for values in buckets.values() for text in values]
    seen: set[str] = set(flat)
    valid_buckets = set(buckets.keys())

    candidate_paths: List[Path] = []
    if custom_path:
        candidate_paths.append(Path(custom_path))
    candidate_paths.append(Path("models/comments.txt"))
    fallback_path = Path(__file__).resolve().parent.parent / "models" / "comments.txt"
    if fallback_path not in candidate_paths:
        candidate_paths.append(fallback_path)

    def add_text(bucket: str, text: str) -> None:
        if not text or text in seen:
            return
        buckets.setdefault(bucket, []).append(text)
        flat.append(text)
        seen.add(text)

    for path in candidate_paths:
        try:
            if not path.exists() or not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                raw = (line or "").strip()
                if not raw or raw.startswith("#"):
                    continue
                bucket = "general"
                text = raw
                if "|" in raw:
                    prefix, rest = raw.split("|", 1)
                    bucket = prefix.strip().lower() or "general"
                    text = rest.strip()
                elif raw.startswith("[") and "]" in raw:
                    closing = raw.find("]")
                    prefix = raw[1:closing].strip().lower()
                    remainder = raw[closing + 1 :].strip()
                    if remainder:
                        bucket = prefix or "general"
                        text = remainder
                if bucket not in valid_buckets:
                    bucket = "general"
                add_text(bucket, text)
        except Exception:
            continue

    return flat, buckets

DEFAULT_DWELL_PROB = 0.3
DEFAULT_DWELL_MIN_S = 3.5
DEFAULT_DWELL_MAX_S = 9.0
DEFAULT_REVISIT_SCROLL_PROB = 0.25
DEFAULT_REVISIT_SCROLL_MIN = 120
DEFAULT_REVISIT_SCROLL_MAX = 420
DEFAULT_PREVIEW_NOTE_PROB = 0.18
DEFAULT_PREVIEW_NOTE_MIN_S = 1.4
DEFAULT_PREVIEW_NOTE_MAX_S = 4.0


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_session_log(summary: Dict[str, Any]) -> None:
    try:
        with SESSION_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary, ensure_ascii=False))
            fh.write("\n")
    except Exception:
        pass


async def apply_latest_filter(page: Page, config: "BotConfig") -> bool:
    """Hover filter control and click the 最新 tag if it becomes available."""
    if config.verbose:
        print("Attempting to select 最新 filter automatically...")
    filter_locator = page.locator("div.filter").first
    try:
        await filter_locator.wait_for(state="visible", timeout=8000)
    except Exception as exc:
        if config.verbose:
            print(f"Filter button not found; fallback to manual selection. ({exc.__class__.__name__})")
        return False
    try:
        await filter_locator.scroll_into_view_if_needed()
    except Exception:
        pass

    hover_attempts = 0
    hovered = False
    while hover_attempts < 2 and not hovered:
        hover_attempts += 1
        try:
            await filter_locator.hover()
            hovered = True
        except Exception as exc:
            if config.verbose:
                print(f"Hover attempt {hover_attempts} failed ({exc.__class__.__name__}).")
            await asyncio.sleep(random.uniform(0.25, 0.4))
    if hovered:
        try:
            bbox = await filter_locator.bounding_box()
        except Exception:
            bbox = None
        if bbox:
            await page.mouse.move(
                bbox["x"] + bbox["width"] / 2,
                bbox["y"] + bbox["height"] / 2,
            )
            await asyncio.sleep(random.uniform(0.15, 0.25))
    else:
        if config.verbose:
            print("Failed to hover filter button after retries; fallback to manual selection.")
        return False

    await asyncio.sleep(random.uniform(0.35, 0.75))
    wrapper_locator = page.locator(".filters-wrapper").first

    async def wait_for_wrapper(timeout: float) -> bool:
        try:
            await page.wait_for_selector(
                ".filters-wrapper",
                state="visible",
                timeout=timeout,
            )
            return True
        except Exception as exc_inner:
            if config.verbose:
                print(f"filters-wrapper not visible yet ({exc_inner.__class__.__name__}).")
            return False

    if not await wait_for_wrapper(4000):
        if config.verbose:
            print("Filter options did not appear after hover; trying click.")
        try:
            await filter_locator.click()
            await asyncio.sleep(random.uniform(0.2, 0.4))
        except Exception as click_exc:
            if config.verbose:
                print(f"Filter click fallback failed ({click_exc.__class__.__name__}).")
        if not await wait_for_wrapper(3000):
            try:
                dispatched = await page.evaluate(
                    """
                    () => {
                      const el = document.querySelector('div.filter');
                      if (!el) return false;
                      const rect = el.getBoundingClientRect();
                      const opts = {bubbles: true, cancelable: true, clientX: rect.left + rect.width/2, clientY: rect.top + rect.height/2};
                      el.dispatchEvent(new MouseEvent('mouseover', opts));
                      el.dispatchEvent(new MouseEvent('mouseenter', opts));
                      el.dispatchEvent(new MouseEvent('mousemove', opts));
                      return true;
                    }
                    """
                )
                if config.verbose:
                    print(f"Dispatched synthetic hover events: {dispatched}")
                await asyncio.sleep(random.uniform(0.25, 0.45))
            except Exception as synthetic_exc:
                if config.verbose:
                    print(
                        f"Synthetic hover dispatch failed ({synthetic_exc.__class__.__name__})."
                    )
            if not await wait_for_wrapper(2500):
                if config.verbose:
                    try:
                        top_html = await page.inner_html(".search-layout__top")
                        print(f"search-layout__top snippet: {top_html[:200]}")
                    except Exception:
                        pass
                return False

    options_locator = wrapper_locator.locator(
        ":scope .tags, :scope .tag, :scope .filter-tag, :scope [class*='tag'], :scope button, :scope span, :scope div"
    )
    latest_locator = wrapper_locator.locator(
        ".tags",
        has=page.locator("span", has_text="最新"),
    ).first
    try:
        await latest_locator.wait_for(state="visible", timeout=2500)
    except Exception as exc:
        if config.verbose:
            try:
                texts = await wrapper_locator.all_inner_texts()
            except Exception:
                texts = []
            readable = ", ".join(t.strip() for t in texts if t and t.strip())
            print(f"最新 filter option not found; fallback to manual selection. ({exc.__class__.__name__}) options=[{readable}]")
        return False
    try:
        await latest_locator.click()
        await asyncio.sleep(random.uniform(0.25, 0.45))
        activated = False
        try:
            await page.wait_for_function(
                """
                () => {
                  const active = document.querySelector('.filters-wrapper .tags.active span');
                  return !!(active && active.textContent && active.textContent.includes('最新'));
                }
                """,
                timeout=3000,
            )
            activated = True
        except Exception:
            try:
                await page.wait_for_function(
                    """
                    () => {
                      const top = document.querySelector('.search-layout__top');
                      if (!top) return false;
                      const actives = Array.from(top.querySelectorAll('.tags.active span'));
                      return actives.some(el => (el.textContent || '').includes('最新'));
                    }
                    """,
                    timeout=2000,
                )
                activated = True
            except Exception:
                activated = False
        if activated:
            if config.verbose:
                print("Selected 最新 filter via automation.")
            # small move upward to collapse panel if it remains open
            try:
                bbox = await filter_locator.bounding_box()
            except Exception:
                bbox = None
            if bbox:
                await page.mouse.move(bbox["x"] + bbox["width"] / 2, max(0, bbox["y"] - 60))
            return True
    except Exception as click_exc:
        if config.verbose:
            print(f"Click on 最新 failed; fallback to manual selection. ({click_exc.__class__.__name__})")
    return False


@dataclass
class BotConfig:
    user_data_dir: str = DEFAULT_USER_DATA_DIR
    headless: bool = True
    slow_mo_ms: int = 50
    locale: str = "en-US"
    verbose: bool = False
    user_agent: str = DEFAULT_USER_AGENT
    delay_ms: int = 2000
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
    # Commenting (type-only by default)
    comment_prob: float = 0.1
    comment_max_per_session: int = 10
    comment_min_interval_s: float = 300.0
    comment_type_delay_min_ms: int = 60
    comment_type_delay_max_ms: int = 140
    comment_texts: Optional[List[str]] = None
    comment_submit: bool = False  # default dry-run: type only, do not submit
    comment_after_like_only: bool = True
    comment_buckets: Dict[str, List[str]] = field(default_factory=dict)
    dwell_prob: float = DEFAULT_DWELL_PROB
    dwell_min_s: float = DEFAULT_DWELL_MIN_S
    dwell_max_s: float = DEFAULT_DWELL_MAX_S
    revisit_scroll_prob: float = DEFAULT_REVISIT_SCROLL_PROB
    revisit_scroll_min: int = DEFAULT_REVISIT_SCROLL_MIN
    revisit_scroll_max: int = DEFAULT_REVISIT_SCROLL_MAX
    preview_note_prob: float = DEFAULT_PREVIEW_NOTE_PROB
    preview_note_min_s: float = DEFAULT_PREVIEW_NOTE_MIN_S
    preview_note_max_s: float = DEFAULT_PREVIEW_NOTE_MAX_S


async def create_context(config: BotConfig) -> tuple[Playwright, BrowserContext]:
    pw = await async_playwright().start()
    viewport = {"width": 1280, "height": 800}
    if config.random_viewport:
        viewport = {
            "width": random.randint(config.viewport_min_w, config.viewport_max_w),
            "height": random.randint(config.viewport_min_h, config.viewport_max_h),
        }
    launch_args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    browser = await pw.chromium.launch_persistent_context(
        user_data_dir=config.user_data_dir,
        headless=config.headless,
        slow_mo=config.slow_mo_ms,
        locale=config.locale,
        user_agent=config.user_agent,
        args=launch_args,
        viewport=viewport,
    )
    if config.stealth:
        try:
            await browser.add_init_script(STEALTH_INIT_SCRIPT)
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


async def maybe_take_feed_break(page: Page, config: BotConfig) -> None:
    try:
        prob = max(0.0, min(1.0, config.dwell_prob))
        if prob <= 0 or random.random() > prob:
            return
        sleep_min = max(0.5, config.dwell_min_s)
        sleep_max = max(sleep_min, config.dwell_max_s)
        # Small cursor drift before pausing to mimic reading
        viewport = page.viewport_size
        if viewport and random.random() < 0.4:
            try:
                base_x = random.uniform(viewport["width"] * 0.2, viewport["width"] * 0.8)
                base_y = random.uniform(viewport["height"] * 0.25, viewport["height"] * 0.9)
                await page.mouse.move(base_x, base_y, steps=random.randint(6, 15))
            except Exception:
                pass
        await asyncio.sleep(random.uniform(sleep_min, sleep_max))
    except Exception:
        pass


async def maybe_revisit_feed(page: Page, config: BotConfig) -> None:
    try:
        prob = max(0.0, min(1.0, config.revisit_scroll_prob))
        if prob <= 0 or config.revisit_scroll_max <= 0 or random.random() > prob:
            return
        lower = max(40, min(config.revisit_scroll_min, config.revisit_scroll_max))
        upper = max(lower, config.revisit_scroll_max)
        delta = random.randint(lower, upper)
        if random.random() < 0.6:
            await page.mouse.wheel(0, -delta)
        else:
            await page.evaluate("(y) => window.scrollBy(0, -y)", delta)
        await asyncio.sleep(random.uniform(0.4, 1.2))
        if random.random() < 0.7:
            rebound = random.randint(int(delta * 0.3), delta)
            try:
                await page.mouse.wheel(0, rebound)
            except Exception:
                await page.evaluate("(y) => window.scrollBy(0, y)", rebound)
    except Exception:
        pass


async def preview_note_detail(page: Page, note_handle, config: BotConfig) -> bool:
    try:
        cover = None
        for sel in ['a.cover.mask.ld', 'a.cover.mask', 'a.cover', 'a[href^="/explore/"]']:
            try:
                el = await note_handle.query_selector(sel)
            except Exception:
                el = None
            if el:
                cover = el
                break
        if not cover:
            return False
        try:
            await cover.scroll_into_view_if_needed()
        except Exception:
            pass
        await maybe_hover_element(page, cover, hover_probability=0.45)
        await cover.click()
        opened = False
        try:
            await page.wait_for_selector(
                '.interactions.engage-bar, .note-container, #noteContainer', timeout=2500
            )
            opened = True
        except Exception:
            pass
        dwell_min = max(0.8, config.preview_note_min_s)
        dwell_max = max(dwell_min, config.preview_note_max_s)
        await asyncio.sleep(random.uniform(dwell_min, dwell_max))
        if opened:
            await _close_note_overlay(page)
        else:
            try:
                await page.wait_for_timeout(200)
            except Exception:
                pass
        return True
    except Exception:
        return False


async def maybe_preview_note_detail(page: Page, note_handle, info: Dict[str, Any], config: BotConfig) -> bool:
    try:
        prob = max(0.0, min(1.0, config.preview_note_prob))
        if prob <= 0 or random.random() > prob:
            return False
        refreshed = await _ensure_note_handle(page, note_handle, info)
        target = refreshed or note_handle
        if target is None:
            return False
        viewed = await preview_note_detail(page, target, config)
        if viewed:
            await maybe_take_feed_break(page, config)
        return viewed
    except Exception:
        return False


def choose_comment_text(info: Dict[str, Any], config: BotConfig) -> Optional[str]:
    buckets = getattr(config, "comment_buckets", {}) or {}
    pool: List[str] = []
    like_count = info.get("likeCount")
    bucket_key = "general"
    if isinstance(like_count, (int, float)):
        if like_count < 20:
            bucket_key = "low"
        elif like_count < 120:
            bucket_key = "mid"
        else:
            bucket_key = "high"
    specific = buckets.get(bucket_key)
    if specific:
        pool.extend(specific)
    general = buckets.get("general")
    if general:
        pool.extend(general)
    if not pool:
        fallback = config.comment_texts or []
        pool.extend(fallback)
    pool = [text for text in pool if text]
    if not pool:
        return None
    return random.choice(pool)


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


async def _is_handle_connected(handle) -> bool:
    """Best-effort check that an element handle is still attached."""
    if handle is None:
        return False
    try:
        return await handle.evaluate("node => !!(node && node.isConnected)")
    except Exception:
        return False


async def _resolve_like_target(note_handle) -> Optional[Any]:
    selectors = [
        "span.like-wrapper button",
        "span.like-wrapper",
        "button:has-text(\"点赞\")",
        "button:has-text(\"Like\")",
        "button:has-text(\"喜欢\")",
        "[aria-label*='like' i]",
        "[aria-label*='喜欢' i]",
        "[data-role*='like' i]",
        "svg.like-icon",
        ".like-wrapper .like-icon",
        "button.like-btn",
    ]
    for sel in selectors:
        candidate = None
        try:
            candidate = await note_handle.query_selector(sel)
        except Exception:
            candidate = None
        if not candidate:
            continue
        try:
            if await _is_handle_connected(candidate):
                return candidate
        except Exception:
            continue
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

    liked_items: List[Dict[str, Any]] = []
    skipped_items: List[Dict[str, Any]] = []
    seen_explore_ids: set[str] = set()
    session_state: Dict[str, Any] = {"block_state": "ok"}
    session_state.setdefault("resilience_events", [])
    session_expired_logged = False
    session_like_target = limit
    # comment session tracking (type-only by default)
    comments_typed = 0
    comment_attempts = 0
    last_comment_time = 0.0
    dom_detached_recent = []
    empty_candidate_rounds = 0
    max_reload_attempts = 3
    reload_attempts = 0

    async def record_resilience_event(event_type: str, reason: str) -> None:
        entry = {
            "ts": now_ts(),
            "event": event_type,
            "reason": reason,
            "reloads": reload_attempts,
        }
        try:
            session_state.setdefault("resilience_events", []).append(entry)
        except Exception:
            pass
        if config.verbose:
            print(f"[{entry['ts']}] Resilience: {event_type} ({reason})")

    async def navigate_with_retries(label: str, url: str, attempts: int = 3) -> bool:
        for attempt in range(1, max(1, attempts) + 1):
            try:
                await page.goto(url, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                return True
            except Exception as exc:
                await record_resilience_event(
                    "nav-retry",
                    f"{label}:{exc.__class__.__name__}:attempt={attempt}",
                )
                if attempt >= attempts:
                    raise
                await asyncio.sleep(random.uniform(2.0, 4.0) * attempt)
        return False

    await navigate_with_retries("initial-load", search_url, attempts=3)

    filter_selected = await apply_latest_filter(page, config)
    if filter_selected:
        await asyncio.sleep(random.uniform(2.5, 4.5))
    else:
        if config.verbose:
            print("Waiting 60 seconds so you can switch filters before automation starts...")
        await asyncio.sleep(60)

    start_ts = time.monotonic()
    session_start_monotonic = start_ts

    async def sleep_after_like() -> None:
        delay_ms = max(0, getattr(config, "delay_ms", 0))
        if delay_ms <= 0:
            return
        base_delay = delay_ms
        elapsed = max(0.0, time.monotonic() - session_start_monotonic)
        ramp_up_s = max(0, getattr(config, "ramp_up_s", 0))
        if ramp_up_s > 0 and elapsed < ramp_up_s:
            ramp_factor = 1.0 + (ramp_up_s - elapsed) / ramp_up_s
            base_delay = int(base_delay * ramp_factor)
        await asyncio.sleep(
            draw_delay_seconds(base_delay, config.delay_jitter_pct, config.delay_model)
        )

    async def reload_feed(reason: str) -> bool:
        nonlocal reload_attempts, empty_candidate_rounds, dom_detached_recent
        if reload_attempts >= max_reload_attempts:
            return False
        reload_attempts += 1
        try:
            await record_resilience_event("reload", reason)
            await navigate_with_retries(f"reload:{reason}", search_url, attempts=2)
            await asyncio.sleep(random.uniform(4.0, 6.0))
            filter_refreshed = await apply_latest_filter(page, config)
            if filter_refreshed:
                await asyncio.sleep(random.uniform(2.0, 3.5))
            else:
                await record_resilience_event("filter-manual", f"reload:{reason}")
            seen_explore_ids.clear()
            empty_candidate_rounds = 0
            dom_detached_recent = []
            return True
        except Exception:
            return False

    async def extract_note_info(note_handle) -> Dict[str, Any]:
        data = await page.evaluate(
            r"""
            (note) => {
              const dataset = note.dataset || {};
              const exploreA = note.querySelector('a[href^="/explore/"]');
              const searchA = note.querySelector('a[href^="/search_result/"]');
              let hrefRaw = (exploreA && exploreA.getAttribute('href')) || (searchA && searchA.getAttribute('href')) || '';
              if (!hrefRaw) {
                const fallbackAnchor = note.querySelector('a[href*="/explore/"]');
                hrefRaw = fallbackAnchor ? fallbackAnchor.getAttribute('href') || '' : '';
              }
              const datasetLink = note.getAttribute('data-note-url') || note.getAttribute('data-link') || dataset.noteUrl || dataset.link || '';
              const datasetId = note.getAttribute('data-note-id') || note.getAttribute('data-noteid') || dataset.noteId || dataset.id || '';
              const normalizeExplore = (href) => {
                if (!href) return '';
                try {
                  if (href.startsWith('/explore/')) {
                    return new URL(href, 'https://www.xiaohongshu.com').toString();
                  }
                  const url = new URL(href, 'https://www.xiaohongshu.com');
                  if (url.pathname && url.pathname.startsWith('/explore/')) {
                    return url.toString();
                  }
                } catch (e) {
                  return '';
                }
                if (href.startsWith('/search_result/')) {
                  const id = href.split('/').pop()?.split('?')[0] || '';
                  if (id) {
                    return new URL('/explore/' + id, 'https://www.xiaohongshu.com').toString();
                  }
                }
                return '';
              };
              let exploreHref = normalizeExplore(hrefRaw);
              if (!exploreHref) {
                exploreHref = normalizeExplore(datasetLink);
              }
              if (!exploreHref && datasetId) {
                try {
                  exploreHref = new URL('/explore/' + datasetId, 'https://www.xiaohongshu.com').toString();
                } catch (e) {
                  exploreHref = '';
                }
              }
              const titleEl = note.querySelector('.footer .title');
              let title = titleEl ? (titleEl.textContent || '').trim() : '';
              if (!title) {
                const datasetTitle = note.getAttribute('data-title') || dataset.title || dataset.noteTitle || '';
                if (datasetTitle) {
                  title = datasetTitle.trim();
                }
              }
              if (!title) {
                const aria = note.getAttribute('aria-label') || '';
                if (aria) {
                  title = aria.trim();
                }
              }
              const useEl = note.querySelector('svg.like-icon use');
              const likeHref = useEl ? useEl.getAttribute('xlink:href') || useEl.getAttribute('href') || '' : '';
              const className = (note.className || '').toString().toLowerCase();
              const alreadyLiked = likeHref.includes('liked') || className.includes('liked');
              const countEl = note.querySelector('.like-wrapper .count');
              let likeCount = null;
              const parseCount = (raw) => {
                if (!raw) return null;
                const trimmed = String(raw).trim();
                if (!trimmed) return null;
                const mW = trimmed.match(/^(\d+(?:\.\d+)?)\s*[wW]$/);
                if (mW) {
                  return Math.round(parseFloat(mW[1]) * 10000);
                }
                const digits = trimmed.match(/\d+/g);
                if (digits && digits.length) {
                  return parseInt(digits[0], 10);
                }
                return null;
              };
              if (countEl) {
                likeCount = parseCount(countEl.textContent || '');
              }
              if (likeCount === null) {
                likeCount = parseCount(note.getAttribute('data-like-count') || dataset.likeCount || dataset.likes || '');
              }
              if (likeCount === null) {
                likeCount = parseCount(note.getAttribute('aria-label') || '');
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

    max_rounds = max(120, session_like_target * 4 if session_like_target else 120)

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

        if not ordered:
            empty_candidate_rounds += 1
            if empty_candidate_rounds >= 3:
                if await reload_feed("no-candidates"):
                    continue
            await asyncio.sleep(random.uniform(1.0, 2.0))
            continue
        else:
            empty_candidate_rounds = 0

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
                await maybe_preview_note_detail(page, note, info, config)
                await maybe_take_feed_break(page, config)
                continue
            try:
                note = await _ensure_note_handle(page, note, info) or note
                attempts = 0
                max_attempts = 3
                last_exc: Optional[Exception] = None
                dom_detached_failure = False

                while attempts < max_attempts:
                    like_target = await _resolve_like_target(note)
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

                    if not await _is_handle_connected(like_target):
                        dom_detached_failure = True
                        attempts += 1
                        if attempts >= max_attempts:
                            break
                        note = await _ensure_note_handle(page, note, info) or note
                        await asyncio.sleep(random.uniform(0.1, 0.3))
                        continue

                    try:
                        try:
                            await like_target.wait_for_element_state("stable")
                        except Exception:
                            pass
                        await like_target.click()
                    except Exception as exc:
                        last_exc = exc
                        msg = str(exc).lower()
                        if "not attached" in msg:
                            dom_detached_failure = True
                            attempts += 1
                            if attempts >= max_attempts:
                                break
                            note = await _ensure_note_handle(page, note, info) or note
                            await asyncio.sleep(random.uniform(0.1, 0.3))
                            continue
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
                        # Maybe type a comment after like (dry-run by default)
                        comment_was_attempted = False
                        if (
                            config.comment_texts
                            and len(config.comment_texts) > 0
                            and comments_typed < max(0, config.comment_max_per_session)
                        ):
                            should_comment = random.random() <= max(0.0, min(1.0, config.comment_prob))
                            now_t = time.monotonic()
                            interval_ok = (now_t - last_comment_time) >= max(0.0, config.comment_min_interval_s)
                            if should_comment and interval_ok:
                                comment_was_attempted = True
                                comment_text = choose_comment_text(info, config)
                                if not comment_text:
                                    comment_was_attempted = False
                                else:
                                    comment_attempts += 1
                                    if config.verbose:
                                        preview = comment_text if len(comment_text) <= 160 else (comment_text[:160] + "...")
                                        action = "submit" if config.comment_submit else "type (dry-run)"
                                        print(f"[{now_ts()}] Preparing to {action} comment on {url}: {preview}")
                                    # Prefer opening via card cover click to preserve SPA context and tokens
                                    ok, reason = await try_open_and_type_comment_from_card(
                                        context, page, note, url, comment_text, config
                                    )
                                    if ok:
                                        comments_typed += 1
                                        last_comment_time = time.monotonic()
                                        if config.verbose:
                                            preview2 = comment_text if len(comment_text) <= 160 else (comment_text[:160] + "...")
                                            label = "Submitted" if config.comment_submit else "Typed (dry-run)"
                                            print(f"[{now_ts()}] {label} comment on {url}: {preview2}")
                                    else:
                                        if config.verbose:
                                            print(f"[{now_ts()}] Comment skipped on {url}: {reason}")
                        if not comment_was_attempted:
                            await maybe_preview_note_detail(page, note, info, config)
                        await maybe_take_feed_break(page, config)
                        await sleep_after_like()
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
                    await maybe_take_feed_break(page, config)
                    await maybe_preview_note_detail(page, note, info, config)

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
                    if reason == "dom-detached":
                        dom_detached_recent.append(time.monotonic())
                        dom_detached_recent = [t for t in dom_detached_recent if time.monotonic() - t <= 180.0]
                        if len(dom_detached_recent) >= 8:
                            if await reload_feed("dom-detached-spike"):
                                break

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
                if skip_reason == "dom-detached":
                    dom_detached_recent.append(time.monotonic())
                    dom_detached_recent = [t for t in dom_detached_recent if time.monotonic() - t <= 180.0]
                    if len(dom_detached_recent) >= 8:
                        if await reload_feed("dom-detached-spike"):
                            continue
                await maybe_take_feed_break(page, config)
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
        await maybe_revisit_feed(page, config)
        if random.random() <= config.long_pause_prob:
            await asyncio.sleep(random.uniform(config.long_pause_min_s, config.long_pause_max_s))
        else:
            await asyncio.sleep(random.uniform(0.4, 1.1))
        await maybe_take_feed_break(page, config)
    # record comment metrics
    try:
        session_state.setdefault("comments", {})
        session_state["comments"].update(
            {
                "typed": comments_typed,
                "attempts": comment_attempts,
            }
        )
    except Exception:
        pass
    return liked_items[:session_like_target], skipped_items, session_state


async def _find_comment_input(page: Page):
    # Scope strictly within the engage bar to avoid typing into global search bars
    try:
        engage = await page.query_selector('.interactions.engage-bar')
    except Exception:
        engage = None
    if not engage:
        return None
    selectors = [
        '#content-textarea.content-input[contenteditable="true"]',
        'p#content-textarea[contenteditable="true"]',
        '.input-box .content-edit #content-textarea',
        '.content-edit [contenteditable="true"]',
    ]
    for sel in selectors:
        try:
            el = await engage.query_selector(sel)  # type: ignore
            if el:
                box = await el.bounding_box()
                if box and box.get("width") and box.get("height"):
                    return el
        except Exception:
            continue
    return None


async def _activate_comment_bar(page: Page) -> bool:
    try:
        eb = await page.query_selector('.interactions.engage-bar')
        if not eb:
            return False
        try:
            await eb.scroll_into_view_if_needed()
        except Exception:
            pass
        # Prefer clicking the placeholder overlay if present
        try:
            placeholder = await eb.query_selector('.inner-when-not-active .inner')
        except Exception:
            placeholder = None
        if placeholder:
            try:
                await maybe_hover_element(page, placeholder, hover_probability=0.4)
                try:
                    await placeholder.click()
                except Exception:
                    await placeholder.click(force=True)
            except Exception:
                pass
        else:
            # Click the content-edit area
            try:
                area = await eb.query_selector('.input-box .content-edit')
            except Exception:
                area = None
            if area:
                try:
                    await maybe_hover_element(page, area, hover_probability=0.4)
                    try:
                        await area.click()
                    except Exception:
                        await area.click(force=True)
                except Exception:
                    pass
            else:
                # Try the chat icon wrapper as a last resort
                try:
                    chat = await eb.query_selector('.chat-wrapper')
                    if chat:
                        await maybe_hover_element(page, chat, hover_probability=0.3)
                        await chat.click()
                except Exception:
                    pass
        # Wait briefly for the right button area to appear
        try:
            await page.wait_for_selector('.interactions.engage-bar .right-btn-area', state='visible', timeout=1200)
        except Exception:
            pass
        # Consider activation successful if input can be found or right-btn-area is visible
        try:
            rba = await page.query_selector('.interactions.engage-bar .right-btn-area')
            if rba:
                box = await rba.bounding_box()
                if box and box.get('width') and box.get('height'):
                    return True
        except Exception:
            pass
        input_el = await _find_comment_input(page)
        return input_el is not None
    except Exception:
        return False


async def try_type_comment_on_note(
    context: BrowserContext,
    note_url: str,
    text: str,
    config: BotConfig,
) -> Tuple[bool, str]:
    page = await context.new_page()
    try:
        await page.goto(note_url, wait_until="domcontentloaded")
        # quick block/state check
        state = await _detect_block_state(page)
        if state in {"login-required", "rate-limit"}:
            return False, state
        # Wait a bit for UI to settle
        await asyncio.sleep(random.uniform(0.6, 1.6))
        # Detect app-only or missing engage UI early
        try:
            flags = await page.evaluate(
                """
                () => {
                  const bodyText = document.body ? document.body.innerText : '';
                  const lower = bodyText.toLowerCase();
                  const tokens = ['当前笔记暂时无法浏览','暂时无法浏览','打开app','去app','app内打开','下载app','open in app'];
                  let appOnly = false;
                  for (const t of tokens) {
                    if (!t) continue;
                    if (bodyText.includes(t) || lower.includes(t.toLowerCase())) { appOnly = true; break; }
                  }
                  const hasEngage = !!document.querySelector('.interactions.engage-bar');
                  return { appOnly, hasEngage };
                }
                """
            )
        except Exception:
            flags = {"appOnly": False, "hasEngage": False}
        if (flags and (flags.get("appOnly") or not flags.get("hasEngage"))):
            return False, "app-only"
        # Activate the comment bar so buttons appear
        if not await _activate_comment_bar(page):
            return False, "no-activate"
        # Try to find comment input
        input_el = None
        for _ in range(6):
            input_el = await _find_comment_input(page)
            if input_el:
                break
            await asyncio.sleep(0.5)
        if not input_el:
            return False, "no-input"
        try:
            await input_el.scroll_into_view_if_needed()
        except Exception:
            pass
        await maybe_hover_element(page, input_el, hover_probability=0.7)
        try:
            await input_el.click()
        except Exception:
            try:
                await input_el.click(force=True)
            except Exception:
                pass
        # Ensure focus and reveal of submit/cancel controls
        try:
            await page.evaluate("el => el.focus()", input_el)
        except Exception:
            pass
        try:
            await page.wait_for_selector('.interactions.engage-bar .right-btn-area', state='visible', timeout=1500)
        except Exception:
            pass
        ok, treason = await _type_into_comment_input(page, config, text)
        if not ok:
            return False, treason
        # Submit if requested
        if config.comment_submit:
            await _submit_comment(page, input_el)
        # Small pause to observe typed content
        await asyncio.sleep(random.uniform(0.3, 0.8))
        return True, "ok"
    except Exception as exc:
        return False, f"error:{exc.__class__.__name__}"
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def try_open_and_type_comment_from_card(
    context: BrowserContext,
    page: Page,
    note_handle,
    note_url: str,
    text: str,
    config: BotConfig,
) -> Tuple[bool, str]:
    # Try clicking the cover image anchor inside the card to open the SPA overlay.
    # Fall back to direct navigation if we cannot open from card.
    try:
        cover = None
        for sel in [
            'a.cover.mask.ld',
            'a.cover.mask',
            'a.cover',
            'a[href^="/explore/"]',
        ]:
            try:
                el = await note_handle.query_selector(sel)
            except Exception:
                el = None
            if el:
                cover = el
                break
        if cover:
            try:
                await cover.scroll_into_view_if_needed()
            except Exception:
                pass
            await maybe_hover_element(page, cover, hover_probability=0.5)
            # Simple click (SPA may open overlay). If it navigates, we handle below.
            await cover.click()
            # Wait briefly for overlay or navigation.
            opened = False
            try:
                await page.wait_for_selector('.interactions.engage-bar, .note-container, #noteContainer', timeout=3000)
                opened = True
            except Exception:
                # maybe navigated; check url change and re-detect
                pass
            if not opened:
                try:
                    await page.wait_for_load_state('domcontentloaded', timeout=2500)
                except Exception:
                    pass
                # Re-check engage bar on current page
                try:
                    eb = await page.query_selector('.interactions.engage-bar')
                    opened = bool(eb)
                except Exception:
                    opened = False
            if opened:
                # Now type comment within the same page (overlay)
                # Reuse the scoped finder
                input_el = None
                for _ in range(8):
                    input_el = await _find_comment_input(page)
                    if input_el:
                        break
                    await asyncio.sleep(0.4)
                if not input_el:
                    # try clicking the content area to activate, then retry once more
                    try:
                        area = await page.query_selector('.interactions.engage-bar .input-box .content-edit')
                        if area:
                            await area.click()
                    except Exception:
                        pass
                    input_el = await _find_comment_input(page)
                if not input_el:
                    # Attempt to close overlay to restore state
                    try:
                        await page.keyboard.press('Escape')
                    except Exception:
                        pass
                    return False, 'no-input'
                try:
                    await input_el.scroll_into_view_if_needed()
                except Exception:
                    pass
                await maybe_hover_element(page, input_el, hover_probability=0.6)
                try:
                    await input_el.click()
                except Exception:
                    try:
                        await input_el.click(force=True)
                    except Exception:
                        pass
                try:
                    await page.evaluate("el => el.focus()", input_el)
                except Exception:
                    pass
                try:
                    await page.wait_for_selector('.interactions.engage-bar .right-btn-area', state='visible', timeout=1500)
                except Exception:
                    pass
                ok2, treason2 = await _type_into_comment_input(page, config, text)
                if not ok2:
                    # Close overlay if present
                    try:
                        await page.keyboard.press('Escape')
                    except Exception:
                        pass
                    return False, treason2
                # observation pause
                await asyncio.sleep(random.uniform(0.3, 0.8))
                # Submit if requested (within overlay)
                if config.comment_submit:
                    await _submit_comment(page, input_el)
                    await asyncio.sleep(random.uniform(0.3, 0.8))
                # Close overlay or go back
                closed = await _close_note_overlay(page)
                if not closed:
                    try:
                        await page.go_back()
                    except Exception:
                        pass
                return True, 'ok'
        # Fallback: navigate to note URL in a new page and type
        return await try_type_comment_on_note(context, note_url, text, config)
    except Exception as exc:
        return False, f'error:{exc.__class__.__name__}'


async def _close_note_overlay(page: Page) -> bool:
    # Try to close overlay using Escape, then close buttons, then background click.
    def overlay_present() -> bool:
        return False  # stub for type checker
    try:
        present = await page.query_selector('.interactions.engage-bar, .note-container, #noteContainer')
        if not present:
            return True
    except Exception:
        return False
    # Press Escape up to 3 times, waiting briefly for the overlay to disappear
    for _ in range(3):
        try:
            await page.keyboard.press('Escape')
        except Exception:
            pass
        try:
            await page.wait_for_selector('.interactions.engage-bar, .note-container, #noteContainer', state='detached', timeout=800)
            return True
        except Exception:
            await asyncio.sleep(0.2)
    # Try clicking a close control
    for sel in [
        'button.close',
        '[aria-label*="close" i]',
        '.close',
        '.icon-close',
        'svg[class*="close" i]'
    ]:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await maybe_hover_element(page, btn, hover_probability=0.4)
                await btn.click()
                try:
                    await page.wait_for_selector('.interactions.engage-bar, .note-container, #noteContainer', state='detached', timeout=800)
                    return True
                except Exception:
                    pass
        except Exception:
            continue
    # As a last resort, click near a corner to dismiss
    try:
        vs = page.viewport_size
        if vs:
            await page.mouse.click(5, 5)
            try:
                await page.wait_for_selector('.interactions.engage-bar, .note-container, #noteContainer', state='detached', timeout=800)
                return True
            except Exception:
                pass
    except Exception:
        pass
    return False


async def _submit_comment(page: Page, input_el) -> None:
    # Try to find the enabled submit button near the engage bar and click it.
    # Prefer the specific submit button in the right-btn-area.
    selectors_enabled = [
        '.interactions.engage-bar .right-btn-area button.btn.submit:not([disabled])',
        'button.btn.submit:not([disabled])',
        'button:has-text("发送"):not([disabled])',
        'button:has-text("发表"):not([disabled])',
        'button:has-text("Send"):not([disabled])',
        'button:has-text("Post"):not([disabled])',
    ]
    btn = None
    for sel in selectors_enabled:
        try:
            btn = await page.query_selector(sel)
            if btn:
                break
        except Exception:
            btn = None
    # If not found enabled, wait shortly for it to become enabled after typing
    if not btn:
        try:
            btn = await page.wait_for_selector(
                '.interactions.engage-bar .right-btn-area button.btn.submit:not([disabled])', timeout=2000
            )
        except Exception:
            btn = None
    # As a fallback, click generic submit and hope it's enabled
    if not btn:
        try:
            btn = await page.query_selector('.interactions.engage-bar .right-btn-area button.btn.submit')
        except Exception:
            btn = None
    if btn:
        try:
            await maybe_hover_element(page, btn, hover_probability=0.4)
        except Exception:
            pass
        try:
            await btn.click()
        except Exception:
            # try pressing Enter if click fails and input is focused
            try:
                await input_el.press('Enter')
            except Exception:
                pass
        # Best-effort: wait for input to clear or button to disable again
        try:
            await page.wait_for_selector('.interactions.engage-bar .right-btn-area button.btn.submit[disabled], .interactions.engage-bar .right-btn-area button.btn.submit.gray', timeout=1500)
        except Exception:
            pass


async def _type_into_comment_input(page: Page, config: BotConfig, text: str) -> Tuple[bool, str]:
    # re-resolve input after activation in case DOM changed
    input_el = await _find_comment_input(page)
    if not input_el:
        return False, 'no-input'
    # Focus and type with per-char delay
    try:
        await page.evaluate("el => el.focus()", input_el)
    except Exception:
        pass
    delay = random.randint(
        max(0, config.comment_type_delay_min_ms),
        max(config.comment_type_delay_min_ms, config.comment_type_delay_max_ms),
    )
    try:
        # typing directly into the element
        await input_el.type(text, delay=delay)
    except Exception as e:
        # handle potential detachment by re-querying and trying again
        try:
            input_el = await _find_comment_input(page)
            if input_el:
                await page.evaluate("el => el.focus()", input_el)
                await input_el.type(text, delay=delay)
            else:
                raise e
        except Exception:
            # fallback: if the active element is inside the engage bar, use page.keyboard.type
            try:
                active_ok = await page.evaluate(
                    "() => { const ae = document.activeElement; return !!(ae && ae.closest && ae.closest('.interactions.engage-bar')); }"
                )
            except Exception:
                active_ok = False
            if active_ok:
                try:
                    await page.keyboard.type(text, delay=delay)
                except Exception as e2:
                    return False, f'type-failed:{e2.__class__.__name__}'
            else:
                # last resort: programmatic insert to contenteditable
                try:
                    inserted = await page.evaluate(
                        """
                        (txt) => {
                          const el = document.querySelector('.interactions.engage-bar #content-textarea.content-input[contenteditable="true"], .interactions.engage-bar p#content-textarea[contenteditable="true"]');
                          if (!el) return false;
                          el.focus();
                          try { document.execCommand('insertText', false, txt); } catch (e) {}
                          const ev = new InputEvent('input', {bubbles: true, cancelable: true, inputType: 'insertText', data: txt});
                          el.dispatchEvent(ev);
                          return !!(el.innerText && el.innerText.length);
                        }
                        """,
                        text,
                    )
                    if not inserted:
                        return False, f'type-failed:{e.__class__.__name__}'
                except Exception:
                    return False, f'type-failed:{e.__class__.__name__}'
    # Verify content present
    try:
        has_text = await page.evaluate(
            """
            () => {
              const el = document.querySelector('.interactions.engage-bar #content-textarea.content-input[contenteditable="true"], .interactions.engage-bar p#content-textarea[contenteditable="true"]');
              if (!el) return false;
              const t = (el.innerText || el.textContent || '').trim();
              return t.length > 0;
            }
            """
        )
        if not has_text:
            return False, 'type-failed:empty'
    except Exception:
        pass
    return True, 'ok'


async def cmd_like_latest(
    config: BotConfig,
    keyword: str,
    limit: int,
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
        # attach comment metrics if present
        comments_info = session_state.get("comments") if isinstance(session_state, dict) else None
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
        append_session_log(summary)
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
    parser.add_argument("--headless", dest="headless", action="store_true", help="Run Chromium headless")
    parser.add_argument("--headed", dest="headless", action="store_false", help="Run Chromium headed (disable headless)")
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
    parser.add_argument(
        "--user-agent",
        dest="user_agent",
        default=None,
        help="Override browser User-Agent string (defaults to rotation when enabled)",
    )
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
    # Comment-related (type-only by default; will not submit unless --comment-submit is set)
    parser.add_argument("--comment-prob", dest="comment_prob", type=float, default=0.1, help="Chance to type a comment after a like (dry-run)")
    parser.add_argument("--comment-max-per-session", dest="comment_max_per_session", type=int, default=10, help="Maximum comments to type in a session")
    parser.add_argument("--comment-min-interval-s", dest="comment_min_interval_s", type=float, default=300.0, help="Minimum seconds between comments")
    parser.add_argument("--comment-text-file", dest="comment_text_file", default="models/comments.txt", help="Path to comments file (one per line)")
    parser.add_argument("--comment-type-delay-min-ms", dest="comment_type_delay_min_ms", type=int, default=60, help="Minimum per-character typing delay (ms)")
    parser.add_argument("--comment-type-delay-max-ms", dest="comment_type_delay_max_ms", type=int, default=140, help="Maximum per-character typing delay (ms)")
    parser.add_argument("--comment-submit", dest="comment_submit", action="store_true", default=False, help="Submit the comment instead of dry-run typing only")
    parser.add_argument("--verbose", action="store_true", help="Print verbose progress output")

    parser.set_defaults(headless=True)

    ns = parser.parse_args(argv)

    random_viewport = True
    viewport_w = ns.viewport_w or 0
    viewport_h = ns.viewport_h or 0
    if viewport_w and viewport_h:
        random_viewport = False

    user_agent = ns.user_agent
    if ns.randomize_user_agent and not ns.user_agent:
        user_agent = random.choice(COMMON_USER_AGENTS)
    if not user_agent:
        user_agent = DEFAULT_USER_AGENT

    comment_texts, comment_buckets = load_comment_library((ns.comment_text_file or "").strip() or None)

    config = BotConfig(
        user_data_dir=ns.user_data_dir,
        headless=ns.headless,
        slow_mo_ms=ns.slow_mo_ms,
        verbose=ns.verbose,
        user_agent=user_agent,
        delay_ms=max(0, ns.delay_ms),
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
        comment_prob=ns.comment_prob,
        comment_max_per_session=ns.comment_max_per_session,
        comment_min_interval_s=ns.comment_min_interval_s,
        comment_type_delay_min_ms=ns.comment_type_delay_min_ms,
        comment_type_delay_max_ms=ns.comment_type_delay_max_ms,
        comment_texts=comment_texts,
        comment_submit=ns.comment_submit,
        comment_buckets=comment_buckets,
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
            ns.search_type,
            ns.duration_min,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
