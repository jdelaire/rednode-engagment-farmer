from __future__ import annotations

import asyncio
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple
import json
import re
from glob import glob

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os
import threading
import webbrowser
from datetime import datetime

from .cli import (
    BotConfig,
    cmd_like_latest,
    DEFAULT_USER_DATA_DIR,
    load_comment_library,
    DEFAULT_USER_AGENT,
    SESSION_LOG_PATH,
    create_context,
    apply_latest_filter,
    _detect_block_state,
)
from urllib.parse import quote_plus


@dataclass
class RunParams:
    keyword: str = "crossfit"
    limit: int = 200
    search_type: str = "51"
    duration_min: int = 210
    user_data_dir: str = str(Path(__file__).resolve().parent.parent / "LoginInfo")
    headless: bool = False  # HEADED=1
    like_prob: float = 0.82
    delay_ms: int = 4800
    delay_jitter_pct: int = 35
    delay_model: str = "gauss"
    hover_prob: float = 0.68
    slow_mo_ms: int = 85
    ramp_up_s: int = 45
    long_pause_prob: float = 0.24
    long_pause_min_s: float = 5.0
    long_pause_max_s: float = 14.0
    session_cap_min: int = 120
    session_cap_max: int = 180
    human_idle_prob: float = 0.36
    human_idle_min_s: float = 1.8
    human_idle_max_s: float = 5.5
    mouse_wiggle_prob: float = 0.5
    random_order: bool = True
    stealth: bool = True
    randomize_user_agent: bool = False
    user_agent: Optional[str] = DEFAULT_USER_AGENT
    accept_language: Optional[str] = None
    timezone_id: Optional[str] = "Asia/Bangkok"
    comment_prob: float = 0.08
    comment_max_per_session: int = 10
    comment_min_interval_s: float = 300.0
    comment_type_delay_min_ms: int = 60
    comment_type_delay_max_ms: int = 140
    comment_submit: bool = True  # crossfit.sh sets COMMENT_SUBMIT=1
    comment_text_file: str = str(Path(__file__).resolve().parent.parent / "models" / "comments.txt")
    verbose: bool = True


@dataclass
class RunStatus:
    running: bool = False
    stopping: bool = False
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    liked: int = 0
    skipped: int = 0
    params: Optional[RunParams] = None
    last_liked_url: Optional[str] = None
    last_liked_title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "stopping": self.stopping,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_sec": (time.time() - self.started_at) if self.running and self.started_at else None,
            "exit_code": self.exit_code,
            "error": self.error,
            "liked": self.liked,
            "skipped": self.skipped,
            "params": self.params.__dict__ if self.params else None,
            "last_liked_url": self.last_liked_url,
            "last_liked_title": self.last_liked_title,
        }


class _StreamWriter:
    """A simple stdout proxy that captures lines per run while forwarding to original stdout."""

    def __init__(self, append_line_cb):
        self._buf = ""
        self._append = append_line_cb
        self._orig = sys.stdout

    def write(self, s: str) -> int:
        # Forward to original stdout
        try:
            self._orig.write(s)
        except Exception:
            pass
        # Buffer and split lines to capture discrete entries
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            try:
                self._append(line)
            except Exception:
                pass
        return len(s)

    def flush(self) -> None:
        try:
            self._orig.flush()
        except Exception:
            pass


class RunManager:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._cancel_event = asyncio.Event()
        self._logs: Deque[Tuple[int, str]] = deque(maxlen=2000)
        self._log_index: int = 0
        self._status: RunStatus = RunStatus()
        self._lock = asyncio.Lock()

    def _append_log(self, line: str) -> None:
        self._log_index += 1
        idx = self._log_index
        # lightweight counters based on common prefixes in cli.py output
        l = line.strip()
        if l.startswith("[") and "] Liked:" in l:
            self._status.liked += 1
            # extract URL and optional title if present
            try:
                # formats like: [ts] Liked: URL
                after = l.split("Liked:", 1)[1].strip()
                url = after.split()[0]
                self._status.last_liked_url = url
            except Exception:
                pass
        elif l.startswith("Skipped ") or l.startswith("[") and "] Skipped" in l:
            self._status.skipped += 1
        self._logs.append((idx, line))

    async def start(self, params: RunParams) -> None:
        async with self._lock:
            if self._task and not self._task.done():
                raise RuntimeError("A run is already in progress")
            self._cancel_event = asyncio.Event()
            self._status = RunStatus(running=True, stopping=False, started_at=time.time(), params=params)
            self._logs.clear()
            self._log_index = 0

            async def runner() -> None:
                # Prepare config from params
                # Resolve user agent with rotation if requested
                ua = params.user_agent
                if params.randomize_user_agent and not ua:
                    from .cli import COMMON_USER_AGENTS  # lazy import to avoid cycles
                    import random as _random
                    ua = _random.choice(COMMON_USER_AGENTS)
                if not ua:
                    ua = DEFAULT_USER_AGENT
                # Resolve locale/timezone defaults from host if not provided
                from .cli import guess_default_accept_language, guess_default_timezone_id
                accept_lang = params.accept_language or guess_default_accept_language()
                tzid = params.timezone_id or os.getenv("XHS_TIMEZONE_ID") or "Asia/Bangkok" or guess_default_timezone_id()
                cfg = BotConfig(
                    user_data_dir=params.user_data_dir,
                    headless=params.headless,
                    slow_mo_ms=params.slow_mo_ms,
                    verbose=params.verbose,
                    user_agent=ua,
                    delay_ms=max(0, params.delay_ms),
                    delay_jitter_pct=params.delay_jitter_pct,
                    hover_prob=params.hover_prob,
                    stealth=params.stealth,
                    like_prob=params.like_prob,
                    random_order=params.random_order,
                    delay_model=params.delay_model,
                    ramp_up_s=params.ramp_up_s,
                    long_pause_prob=params.long_pause_prob,
                    long_pause_min_s=params.long_pause_min_s,
                    long_pause_max_s=params.long_pause_max_s,
                    accept_language=accept_lang,
                    timezone_id=tzid,
                    session_cap_min=params.session_cap_min,
                    session_cap_max=params.session_cap_max,
                    randomize_user_agent=params.randomize_user_agent,
                    human_idle_prob=params.human_idle_prob,
                    human_idle_min_s=params.human_idle_min_s,
                    human_idle_max_s=params.human_idle_max_s,
                    mouse_wiggle_prob=params.mouse_wiggle_prob,
                )
                # Load comments library similar to CLI
                comment_texts, comment_buckets = load_comment_library(params.comment_text_file)
                cfg.comment_prob = params.comment_prob
                cfg.comment_max_per_session = params.comment_max_per_session
                cfg.comment_min_interval_s = params.comment_min_interval_s
                cfg.comment_type_delay_min_ms = params.comment_type_delay_min_ms
                cfg.comment_type_delay_max_ms = params.comment_type_delay_max_ms
                cfg.comment_texts = comment_texts
                cfg.comment_buckets = comment_buckets
                cfg.comment_submit = params.comment_submit
                # Capture stdout for this task
                orig_stdout = sys.stdout
                sys.stdout = _StreamWriter(self._append_log)  # type: ignore
                exit_code: Optional[int] = None
                try:
                    exit_code = await cmd_like_latest(
                        cfg,
                        keyword=params.keyword,
                        limit=params.limit,
                        search_type=params.search_type,
                        duration_min=params.duration_min,
                    )
                except asyncio.CancelledError:
                    self._append_log("[web] Run cancelled by user.")
                    raise
                except Exception as exc:  # unexpected
                    self._status.error = f"{exc.__class__.__name__}: {exc}"
                    self._append_log(f"[web] Error: {self._status.error}")
                finally:
                    try:
                        sys.stdout = orig_stdout  # type: ignore
                    except Exception:
                        pass
                    self._status.exit_code = exit_code
                    self._status.finished_at = time.time()
                    self._status.running = False
                    self._status.stopping = False

            self._task = asyncio.create_task(runner())

    async def stop(self) -> None:
        async with self._lock:
            if not self._task or self._task.done():
                return
            self._status.stopping = True
            self._task.cancel()
        # allow cancellation to propagate
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            async with self._lock:
                self._status.running = False
                self._status.stopping = False
                self._status.finished_at = time.time()

    async def status(self) -> RunStatus:
        async with self._lock:
            return self._status

    async def logs_since(self, from_index: int = 0) -> Tuple[int, List[str]]:
        async with self._lock:
            lines: List[str] = []
            next_index = self._log_index
            for idx, line in self._logs:
                if idx > from_index:
                    lines.append(line)
            return next_index, lines


RUNNER = RunManager()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _collect_known_keywords() -> List[str]:
    def _sanitize_kw(raw: str) -> Optional[str]:
        if not raw:
            return None
        kw = raw.strip()
        # strip wrapping quotes
        if (kw.startswith('"') and kw.endswith('"')) or (kw.startswith("'") and kw.endswith("'")):
            kw = kw[1:-1].strip()
        # ignore shell substitution or suspicious tokens
        bad_tokens = ['${', '}', '$(', ')', '`', ':-', '\\', '\n', '\r']
        if any(t in kw for t in bad_tokens):
            return None
        # collapse surrounding whitespace
        kw = kw.strip()
        # reject obviously placeholder-like values
        if kw.lower().startswith('keyword') or kw.lower().startswith('$(keyword'):
            return None
        return kw or None
    seen: Dict[str, int] = {}
    latest_case: Dict[str, str] = {}
    # From session logs
    try:
        if SESSION_LOG_PATH.exists():
            for raw in SESSION_LOG_PATH.read_text("utf-8", errors="ignore").splitlines()[-2000:]:
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                kw = _sanitize_kw(str(obj.get("keyword", ""))) or ""
                if not kw:
                    continue
                k = kw.lower()
                seen[k] = seen.get(k, 0) + 1
                latest_case[k] = kw
    except Exception:
        pass
    # From shell scripts in repo root
    try:
        for path in glob(str(Path(__file__).resolve().parent.parent / "*.sh")):
            try:
                txt = Path(path).read_text("utf-8", errors="ignore")
            except Exception:
                continue
            m = re.findall(r"\bKEYWORD\s*=\s*([^\n\r]+)", txt)
            for val in m:
                # take first token on the line
                first = val.strip().split()[0]
                kw = _sanitize_kw(first) or ""
                if not kw:
                    continue
                k = kw.lower()
                seen[k] = seen.get(k, 0) + 1
                latest_case[k] = kw
            # Also use filename as hint
            base = Path(path).stem
            if base and base != 'run' and len(base) <= 24:
                k = base.lower()
                seen[k] = seen.get(k, 0) + 1
                latest_case[k] = base
    except Exception:
        pass
    # Curated defaults
    curated = ["crossfit", "CrossFit训练", "fitnessgirl", "功能性训练", "力量训练"]
    for kw in curated:
        if kw.lower() not in latest_case:
            latest_case[kw.lower()] = kw
            seen[kw.lower()] = 1

    # Sort curated first in order, then by frequency desc, then alpha
    def sort_key(item):
        k, v = item
        try:
            pin = curated.index(v)
        except ValueError:
            pin = len(curated)
        return (pin, -seen.get(k, 0), v)

    ordered = sorted(latest_case.items(), key=sort_key)
    items = []
    for _, v in ordered:
        if v not in items:
            items.append(v)
    return items


class PopularityManager:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self.running = False
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.progress: int = 0
        self.total: int = 0
        self.error: Optional[str] = None
        self.cache_path = Path.cwd() / ".xhs_bot" / "keyword_popularity.json"
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            if self.cache_path.exists():
                return json.loads(self.cache_path.read_text("utf-8", errors="ignore"))
        except Exception:
            pass
        return {"updated_ts": None, "keywords": {}}

    def _save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    async def _sample_popularity(self, keywords: List[str], user_data_dir: str) -> None:
        self.running = True
        self.error = None
        self.started_at = _now_iso()
        self.progress = 0
        self.total = len(keywords)
        self.finished_at = None
        # One Playwright context for all keywords
        cfg = BotConfig(
            user_data_dir=user_data_dir,
            headless=True,
            slow_mo_ms=0,
            verbose=False,
            user_agent=DEFAULT_USER_AGENT,
            delay_ms=0,
        )
        pw, context = await create_context(cfg)  # reuse browser context
        try:
            page = await context.new_page()
            for kw in keywords:
                try:
                    url = f"https://www.xiaohongshu.com/search_result/?keyword={quote_plus(kw)}&type=51"
                    await page.goto(url, wait_until="domcontentloaded")
                    # Give the page time to render cards
                    await asyncio.sleep(1.5)
                    # Quick block/state check
                    try:
                        state = await _detect_block_state(page)  # type: ignore
                    except Exception:
                        state = None
                    if state in {"login-required", "rate-limit"}:
                        self.data.setdefault("keywords", {})[kw] = {
                            "ts": _now_iso(),
                            "sample_n": 0,
                            "median": 0,
                            "p75": 0,
                            "error": str(state),
                        }
                        self.progress += 1
                        await asyncio.sleep(0.5)
                        continue
                    # Try ensure filter panel isn't blocking and cards are visible
                    try:
                        await page.wait_for_selector('section.note-item', timeout=4000)
                    except Exception:
                        # light scroll to trigger lazy load
                        try:
                            for _ in range(3):
                                await page.mouse.wheel(0, 1400)
                                await asyncio.sleep(0.6)
                        except Exception:
                            pass
                    # As a last resort, attempt to hover filter area and select 最新
                    try:
                        await apply_latest_filter(page, cfg)  # type: ignore
                    except Exception:
                        pass
                    # collect like counts from visible cards
                    counts = await page.evaluate(
                        r"""
                        () => {
                          const nodes = Array.from(document.querySelectorAll('section.note-item'));
                          const parseCount = (raw) => {
                            if (!raw) return null;
                            const t = String(raw).trim();
                            const mW = t.match(/^(\d+(?:\.\d+)?)\s*[wW]$/);
                            if (mW) return Math.round(parseFloat(mW[1]) * 10000);
                            const d = t.match(/\d+/g);
                            if (d && d.length) return parseInt(d[0], 10);
                            return null;
                          };
                          const likes = [];
                          for (const n of nodes.slice(0, 40)) {
                            const c = n.querySelector('.like-wrapper .count');
                            let v = null;
                            if (c) v = parseCount(c.textContent || '');
                            if (v == null) v = parseCount(n.getAttribute('data-like-count'));
                            if (v == null) v = parseCount((n.getAttribute('aria-label') || ''));
                            if (v != null && !Number.isNaN(v)) likes.push(v);
                          }
                          return likes;
                        }
                        """
                    )
                    likes = [int(x) for x in (counts or []) if isinstance(x, (int, float))]
                    likes = likes[:40]
                    score = None
                    med = None
                    if likes:
                        s = sorted(likes)
                        n = len(s)
                        med = int(s[n//2])
                        p75 = int(s[int(0.75 * (n-1))]) if n > 1 else int(s[0])
                        score = p75
                    self.data.setdefault("keywords", {})[kw] = {
                        "ts": _now_iso(),
                        "sample_n": len(likes),
                        "median": med if med is not None else 0,
                        "p75": score if score is not None else 0,
                    }
                    self.progress += 1
                    await asyncio.sleep(0.8)
                except Exception as e:
                    self.data.setdefault("keywords", {})[kw] = {
                        "ts": _now_iso(),
                        "sample_n": 0,
                        "median": 0,
                        "p75": 0,
                        "error": f"{e.__class__.__name__}"
                    }
                    self.progress += 1
            self.data["updated_ts"] = _now_iso()
            self._save()
        finally:
            try:
                await context.close()
            finally:
                try:
                    await pw.stop()
                except Exception:
                    pass
            self.finished_at = _now_iso()
            self.running = False

    async def start(self, keywords: Optional[List[str]], user_data_dir: str) -> None:
        async with self._lock:
            if self._task and not self._task.done():
                raise RuntimeError("Popularity refresh already in progress")
            if not keywords:
                keywords = _collect_known_keywords()
            self._task = asyncio.create_task(self._sample_popularity(keywords, user_data_dir))

    async def status(self) -> Dict[str, Any]:
        async with self._lock:
            return {
                "running": self.running,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "progress": self.progress,
                "total": self.total,
                "updated_ts": self.data.get("updated_ts"),
            }


POPULARITY = PopularityManager()

app = FastAPI(title="XHS Engagement Bot (Local UI)")


# Static UI
_STATIC_DIR = Path(__file__).with_name("web_static")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    # Serve the simple HTML UI
    return HTMLResponse(_STATIC_DIR.joinpath("index.html").read_text("utf-8"))


@app.post("/start")
async def start_run(payload: Dict[str, Any]) -> JSONResponse:
    try:
        params = RunParams(
            keyword=str(payload.get("keyword", RunParams.keyword)).strip() or RunParams.keyword,
            limit=int(payload.get("limit", RunParams.limit)),
            search_type=str(payload.get("search_type", RunParams.search_type)),
            duration_min=int(payload.get("duration_min", RunParams.duration_min)),
            user_data_dir=str(payload.get("user_data_dir", RunParams.user_data_dir)),
            headless=bool(payload.get("headless", RunParams.headless)),
            like_prob=float(payload.get("like_prob", RunParams.like_prob)),
            delay_ms=int(payload.get("delay_ms", RunParams.delay_ms)),
            delay_jitter_pct=int(payload.get("delay_jitter_pct", RunParams.delay_jitter_pct)),
            delay_model=str(payload.get("delay_model", RunParams.delay_model)),
            hover_prob=float(payload.get("hover_prob", RunParams.hover_prob)),
            slow_mo_ms=int(payload.get("slow_mo_ms", RunParams.slow_mo_ms)),
            ramp_up_s=int(payload.get("ramp_up_s", RunParams.ramp_up_s)),
            long_pause_prob=float(payload.get("long_pause_prob", RunParams.long_pause_prob)),
            long_pause_min_s=float(payload.get("long_pause_min_s", RunParams.long_pause_min_s)),
            long_pause_max_s=float(payload.get("long_pause_max_s", RunParams.long_pause_max_s)),
            session_cap_min=int(payload.get("session_cap_min", RunParams.session_cap_min)),
            session_cap_max=int(payload.get("session_cap_max", RunParams.session_cap_max)),
            human_idle_prob=float(payload.get("human_idle_prob", RunParams.human_idle_prob)),
            human_idle_min_s=float(payload.get("human_idle_min_s", RunParams.human_idle_min_s)),
            human_idle_max_s=float(payload.get("human_idle_max_s", RunParams.human_idle_max_s)),
            mouse_wiggle_prob=float(payload.get("mouse_wiggle_prob", RunParams.mouse_wiggle_prob)),
            random_order=bool(payload.get("random_order", RunParams.random_order)),
            stealth=bool(payload.get("stealth", RunParams.stealth)),
            randomize_user_agent=bool(payload.get("randomize_user_agent", RunParams.randomize_user_agent)),
            user_agent=(str(payload.get("user_agent")) if payload.get("user_agent") is not None else None),
            accept_language=(str(payload.get("accept_language")) if payload.get("accept_language") is not None else None),
            timezone_id=(str(payload.get("timezone_id")) if payload.get("timezone_id") is not None else None),
            comment_prob=float(payload.get("comment_prob", RunParams.comment_prob)),
            comment_max_per_session=int(payload.get("comment_max_per_session", RunParams.comment_max_per_session)),
            comment_min_interval_s=float(payload.get("comment_min_interval_s", RunParams.comment_min_interval_s)),
            comment_type_delay_min_ms=int(payload.get("comment_type_delay_min_ms", RunParams.comment_type_delay_min_ms)),
            comment_type_delay_max_ms=int(payload.get("comment_type_delay_max_ms", RunParams.comment_type_delay_max_ms)),
            comment_submit=bool(payload.get("comment_submit", RunParams.comment_submit)),
            comment_text_file=str(payload.get("comment_text_file", RunParams.comment_text_file)),
            verbose=bool(payload.get("verbose", RunParams.verbose)),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid params: {exc}")
    if not params.keyword:
        raise HTTPException(status_code=400, detail="keyword is required")
    try:
        await RUNNER.start(params)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse({"ok": True})


@app.post("/stop")
async def stop_run() -> JSONResponse:
    await RUNNER.stop()
    return JSONResponse({"ok": True})


@app.get("/status")
async def get_status() -> JSONResponse:
    st = await RUNNER.status()
    return JSONResponse(st.to_dict())


@app.get("/logs")
async def get_logs(from_index: int = 0) -> JSONResponse:
    next_idx, lines = await RUNNER.logs_since(from_index)
    return JSONResponse({"next": next_idx, "lines": lines})


@app.get("/keywords")
async def get_keywords(sort: Optional[str] = None) -> JSONResponse:
    items = _collect_known_keywords()
    scores = POPULARITY.data.get("keywords", {}) if isinstance(POPULARITY.data, dict) else {}
    if sort == "pop":
        def pop_score(kw: str) -> int:
            rec = scores.get(kw, {}) if isinstance(scores, dict) else {}
            return int(rec.get("p75", 0) or 0)
        items = sorted(items, key=lambda kw: (-pop_score(kw), kw.lower()))
    return JSONResponse({
        "keywords": items,
        "scores": scores,
        "updated_ts": POPULARITY.data.get("updated_ts"),
    })


@app.post("/keywords/refresh")
async def refresh_keywords(payload: Optional[Dict[str, Any]] = None) -> JSONResponse:
    payload = payload or {}
    kws = payload.get("keywords")
    if kws and isinstance(kws, list):
        keywords = [str(x) for x in kws if str(x).strip()]
    else:
        keywords = None
    try:
        # use default LoginInfo as profile for access
        user_data_dir = str(Path(__file__).resolve().parent.parent / "LoginInfo")
        await POPULARITY.start(keywords, user_data_dir)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse({"started": True})


@app.get("/keywords/refresh/status")
async def refresh_status() -> JSONResponse:
    st = await POPULARITY.status()
    return JSONResponse(st)


def main() -> None:
    # Allow running via: python -m xhs_bot.web_server
    import uvicorn

    # Optionally auto-open a browser tab on startup
    host = "127.0.0.1"
    port = 8000
    auto_open_env = os.getenv("XHS_WEB_AUTO_OPEN", "1").lower()
    auto_open = auto_open_env not in {"0", "false", "no", "off"}
    if auto_open:
        def _open():
            try:
                webbrowser.open_new_tab(f"http://{host}:{port}/")
            except Exception:
                pass
        # Give the server a moment to bind before opening
        threading.Timer(0.8, _open).start()

    uvicorn.run(
        "xhs_bot.web_server:app",
        host=host,
        port=port,
        reload=False,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
