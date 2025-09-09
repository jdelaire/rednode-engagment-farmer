from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Session(BaseModel):
    """Represents an authenticated session with a service via an adapter."""

    user_id: str
    username: str
    token: str
    adapter_name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(BaseModel):
    """Represents a user in the target service domain."""

    id: str
    username: str
    followers_count: int | None = None
    following_count: int | None = None


class Post(BaseModel):
    """Represents a post that can be liked or commented on."""

    id: str
    user_id: str
    username: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    has_liked: bool = False


class ActionType(str, Enum):
    LIKE = "like"
    FOLLOW = "follow"
    COMMENT = "comment"


class ActionItem(BaseModel):
    """A single action to perform during an engagement run."""

    type: ActionType
    post_id: str | None = None
    user_id: str | None = None
    text: str | None = None


class ActionPlan(BaseModel):
    """A sequence of actions that a strategy proposes to execute."""

    items: list[ActionItem] = Field(default_factory=list)

    @property
    def like_count(self) -> int:
        return sum(1 for a in self.items if a.type == ActionType.LIKE)

    @property
    def follow_count(self) -> int:
        return sum(1 for a in self.items if a.type == ActionType.FOLLOW)

    @property
    def comment_count(self) -> int:
        return sum(1 for a in self.items if a.type == ActionType.COMMENT)

    def summary(self) -> str:
        return (
            f"would like {self.like_count} posts, "
            f"follow {self.follow_count} users, "
            f"comment {self.comment_count} time(s)"
        )


class ActionResult(BaseModel):
    """Outcome of an attempted action."""

    ok: bool
    action: ActionType
    target_id: str
    message: str = ""
    rate_limited: bool = False
    dry_run: bool = False
    executed_at: datetime = Field(default_factory=datetime.utcnow)

