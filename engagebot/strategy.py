from __future__ import annotations

import random
from collections.abc import Iterable
from typing import Protocol

from engagebot.config import Settings
from engagebot.domain import ActionItem, ActionPlan, ActionType, Post


class Strategy(Protocol):
    def plan(self, posts: Iterable[Post], settings: Settings) -> ActionPlan:  # pragma: no cover - protocol
        ...


class RandomSampleStrategy:
    """Build a plan by sampling from discovered posts using a seeded RNG."""

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def plan(self, posts: Iterable[Post], settings: Settings) -> ActionPlan:
        posts_list: list[Post] = list(posts)
        self._rng.shuffle(posts_list)

        like_posts = posts_list[: settings.MAX_LIKES_PER_RUN]
        # Unique authors for follows
        unique_users = []
        seen_users = set()
        for p in posts_list:
            if p.user_id not in seen_users:
                unique_users.append(p)
                seen_users.add(p.user_id)
            if len(unique_users) >= settings.MAX_FOLLOWS_PER_RUN:
                break

        comment_posts = posts_list[: settings.MAX_COMMENTS_PER_RUN]

        items: list[ActionItem] = []
        for p in like_posts:
            items.append(ActionItem(type=ActionType.LIKE, post_id=p.id))
        for p in unique_users:
            items.append(ActionItem(type=ActionType.FOLLOW, user_id=p.user_id))
        for p in comment_posts:
            items.append(
                ActionItem(
                    type=ActionType.COMMENT,
                    post_id=p.id,
                    text=settings.DEFAULT_COMMENT_TEXT,
                )
            )

        return ActionPlan(items=items)


class RecentFirstStrategy:
    """Prioritize newest posts first for likes/comments, and newest authors for follows."""

    def plan(self, posts: Iterable[Post], settings: Settings) -> ActionPlan:
        posts_list: list[Post] = list(posts)
        posts_list.sort(key=lambda p: p.created_at, reverse=True)

        like_posts = posts_list[: settings.MAX_LIKES_PER_RUN]
        # Follows by newest author appearances
        unique_users = []
        seen_users = set()
        for p in posts_list:
            if p.user_id not in seen_users:
                unique_users.append(p)
                seen_users.add(p.user_id)
            if len(unique_users) >= settings.MAX_FOLLOWS_PER_RUN:
                break

        comment_posts = posts_list[: settings.MAX_COMMENTS_PER_RUN]

        items: list[ActionItem] = []
        for p in like_posts:
            items.append(ActionItem(type=ActionType.LIKE, post_id=p.id))
        for p in unique_users:
            items.append(ActionItem(type=ActionType.FOLLOW, user_id=p.user_id))
        for p in comment_posts:
            items.append(
                ActionItem(
                    type=ActionType.COMMENT,
                    post_id=p.id,
                    text=settings.DEFAULT_COMMENT_TEXT,
                )
            )
        return ActionPlan(items=items)

