from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from engagebot.domain import ActionResult, Post, Session


class ServiceAdapter(ABC):
    """Adapter interface for a target service.

    Implementations must be compliant with the target service's terms of service.
    This PoC ships only with a mock adapter.
    """

    @abstractmethod
    def login(self, username: str, password: str) -> Session:  # pragma: no cover - interface
        ...

    @abstractmethod
    def discover_posts(self, *, tag: str | None, limit: int) -> Iterable[Post]:  # pragma: no cover - interface
        ...

    @abstractmethod
    def like_post(self, session: Session, post_id: str, dry_run: bool) -> ActionResult:  # pragma: no cover - interface
        ...

    @abstractmethod
    def follow_user(
        self, session: Session, user_id: str, dry_run: bool
    ) -> ActionResult:  # pragma: no cover - interface
        ...

    @abstractmethod
    def comment(
        self, session: Session, post_id: str, text: str, dry_run: bool
    ) -> ActionResult:  # pragma: no cover - interface
        ...

