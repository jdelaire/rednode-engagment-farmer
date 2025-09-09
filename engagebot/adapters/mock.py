from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from engagebot.adapters.base import ServiceAdapter
from engagebot.config import Settings
from engagebot.domain import ActionResult, ActionType, Post, Session, User
from engagebot.logging_setup import get_logger


@dataclass
class _RateBucket:
    window_start_minute: int
    count: int


class MockAdapter(ServiceAdapter):
    """In-memory mock adapter loading from example_data.

    - Simulates latency per settings.MOCK_LATENCY_MS_RANGE
    - Enforces simple per-minute rate limits from settings
    - Deterministic outcomes by seeding random with settings.SEED
    """

    def __init__(self, settings: Settings, data_dir: Path | None = None) -> None:
        self.settings = settings
        self._rng = random.Random(settings.SEED)
        self._logger = get_logger(self.__class__.__name__)

        self._data_dir = data_dir or (Path(__file__).resolve().parents[2] / "example_data")
        self._users: dict[str, User] = {}
        self._posts: dict[str, Post] = {}

        # Adapter state (mutated only when dry_run is False)
        self._liked_post_ids: set[str] = set()
        self._followed_user_ids: set[str] = set()
        self._comments_by_post_id: dict[str, list[str]] = {}

        # Per-minute rate buckets
        self._like_bucket = _RateBucket(window_start_minute=-1, count=0)
        self._follow_bucket = _RateBucket(window_start_minute=-1, count=0)
        self._comment_bucket = _RateBucket(window_start_minute=-1, count=0)

        self._load_data()

    # Public API -----------------------------------------------------------------
    def login(self, username: str, password: str) -> Session:
        self._simulate_latency()
        # For mock: any username/password works, associate with a mock user if present
        user = next((u for u in self._users.values() if u.username == username), None)
        user_id = user.id if user else f"mock-{abs(hash(username)) % 10000}"
        return Session(user_id=user_id, username=username, token="mock-token", adapter_name="mock")

    def discover_posts(self, *, tag: str | None, limit: int):
        self._simulate_latency()
        posts = list(self._posts.values())
        if tag:
            posts = [p for p in posts if tag in p.tags]
        # Recent-first default ordering for discovery
        posts.sort(key=lambda p: p.created_at, reverse=True)
        return posts[: max(0, int(limit))]

    def like_post(self, session: Session, post_id: str, dry_run: bool) -> ActionResult:
        self._simulate_latency()
        if not self._check_rate(self._like_bucket, self.settings.MOCK_MAX_LIKES_PER_MIN):
            return ActionResult(
                ok=False,
                action=ActionType.LIKE,
                target_id=post_id,
                message="rate limit exceeded",
                rate_limited=True,
                dry_run=dry_run,
            )

        if post_id not in self._posts:
            return ActionResult(
                ok=False,
                action=ActionType.LIKE,
                target_id=post_id,
                message="post not found",
                dry_run=dry_run,
            )

        if not dry_run:
            self._liked_post_ids.add(post_id)
        return ActionResult(ok=True, action=ActionType.LIKE, target_id=post_id, dry_run=dry_run)

    def follow_user(self, session: Session, user_id: str, dry_run: bool) -> ActionResult:
        self._simulate_latency()
        if not self._check_rate(self._follow_bucket, self.settings.MOCK_MAX_FOLLOWS_PER_MIN):
            return ActionResult(
                ok=False,
                action=ActionType.FOLLOW,
                target_id=user_id,
                message="rate limit exceeded",
                rate_limited=True,
                dry_run=dry_run,
            )

        if user_id not in self._users:
            return ActionResult(
                ok=False,
                action=ActionType.FOLLOW,
                target_id=user_id,
                message="user not found",
                dry_run=dry_run,
            )

        if not dry_run:
            self._followed_user_ids.add(user_id)
        return ActionResult(ok=True, action=ActionType.FOLLOW, target_id=user_id, dry_run=dry_run)

    def comment(self, session: Session, post_id: str, text: str, dry_run: bool) -> ActionResult:
        self._simulate_latency()
        if not self._check_rate(self._comment_bucket, self.settings.MOCK_MAX_COMMENTS_PER_MIN):
            return ActionResult(
                ok=False,
                action=ActionType.COMMENT,
                target_id=post_id,
                message="rate limit exceeded",
                rate_limited=True,
                dry_run=dry_run,
            )

        if post_id not in self._posts:
            return ActionResult(
                ok=False,
                action=ActionType.COMMENT,
                target_id=post_id,
                message="post not found",
                dry_run=dry_run,
            )

        if not dry_run:
            self._comments_by_post_id.setdefault(post_id, []).append(text)
        return ActionResult(ok=True, action=ActionType.COMMENT, target_id=post_id, dry_run=dry_run)

    # Introspection helpers for tests -------------------------------------------
    def get_state_snapshot(self) -> dict[str, int]:
        return {
            "likes": len(self._liked_post_ids),
            "follows": len(self._followed_user_ids),
            "comments": sum(len(v) for v in self._comments_by_post_id.values()),
        }

    # Internals -----------------------------------------------------------------
    def _load_data(self) -> None:
        users_path = self._data_dir / "users.json"
        posts_path = self._data_dir / "posts.json"
        if not users_path.exists() or not posts_path.exists():
            self._logger.warning("example_data not found at %s", self._data_dir)
            return

        users_raw = json.loads(users_path.read_text(encoding="utf-8"))
        for u in users_raw:
            user = User(**u)
            self._users[user.id] = user

        posts_raw = json.loads(posts_path.read_text(encoding="utf-8"))
        for p in posts_raw:
            # Ensure created_at parsed
            created_at = _parse_datetime(p.get("created_at"))
            post = Post(
                id=p["id"],
                user_id=p["user_id"],
                username=p.get("username", ""),
                tags=p.get("tags", []),
                created_at=created_at,
                has_liked=False,
            )
            self._posts[post.id] = post

        self._logger.info(
            "Loaded %d users and %d posts from %s",
            len(self._users),
            len(self._posts),
            self._data_dir,
        )

    def _check_rate(self, bucket: _RateBucket, limit_per_minute: int) -> bool:
        now_minute = int(time.time() // 60)
        if bucket.window_start_minute != now_minute:
            bucket.window_start_minute = now_minute
            bucket.count = 0
        bucket.count += 1
        return bucket.count <= max(0, int(limit_per_minute))

    def _simulate_latency(self) -> None:
        low_ms, high_ms = self.settings.MOCK_LATENCY_MS_RANGE
        if high_ms <= 0:
            return
        delay_s = self._rng.uniform(low_ms / 1000.0, high_ms / 1000.0)
        time.sleep(delay_s)


def _parse_datetime(value: str) -> datetime:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).astimezone(UTC)
    except Exception:
        return datetime.now(tz=UTC)

