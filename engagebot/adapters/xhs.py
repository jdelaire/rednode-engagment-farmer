from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from engagebot.adapters.base import ServiceAdapter
from engagebot.domain import ActionResult, ActionType, Post, Session


@dataclass
class _XhsConfig:
    base_url: str
    user_agent: str
    cookie: str


class XhsAdapter(ServiceAdapter):
    """Stub Xiaohongshu adapter.

    NOTE: This is a non-networking placeholder to fit EngageBot's interface.
    It does not call xiaohongshu.com. Replace internals with compliant API calls later.
    """

    def __init__(self, *, base_url: str, user_agent: str, cookie: str) -> None:
        self._cfg = _XhsConfig(base_url=base_url, user_agent=user_agent, cookie=cookie)

    # Public API -----------------------------------------------------------------
    def login(self, username: str, password: str) -> Session:
        # Placeholder session. Real impl should authenticate or set cookies.
        return Session(user_id="xhs-guest", username=username, token="xhs-cookie", adapter_name="xhs")

    def discover_posts(self, *, tag: str | None, limit: int) -> Iterable[Post]:
        # Return an empty iterable for now. Real impl should fetch search/tag feed.
        now = datetime.now(tz=UTC)
        # Provide a tiny synthetic sample so strategies can run in demos
        sample: list[Post] = []
        for i in range(max(0, int(min(limit, 3)))):
            sample.append(
                Post(
                    id=f"xhs_post_{i}",
                    user_id=f"xhs_user_{i}",
                    username=f"xhsuser{i}",
                    tags=[tag] if tag else [],
                    created_at=now,
                    has_liked=False,
                )
            )
        return sample

    def like_post(self, session: Session, post_id: str, dry_run: bool) -> ActionResult:
        return ActionResult(ok=True, action=ActionType.LIKE, target_id=post_id, dry_run=dry_run)

    def follow_user(self, session: Session, user_id: str, dry_run: bool) -> ActionResult:
        return ActionResult(ok=True, action=ActionType.FOLLOW, target_id=user_id, dry_run=dry_run)

    def comment(self, session: Session, post_id: str, text: str, dry_run: bool) -> ActionResult:
        return ActionResult(ok=True, action=ActionType.COMMENT, target_id=post_id, dry_run=dry_run)

