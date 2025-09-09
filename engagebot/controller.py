from __future__ import annotations

import random
import time
from collections.abc import Callable

from engagebot.adapters.base import ServiceAdapter
from engagebot.config import Settings
from engagebot.domain import ActionItem, ActionPlan, ActionType, Session
from engagebot.logging_setup import get_logger


class Controller:
    """Orchestrates an engagement run using an adapter and a strategy."""

    def __init__(
        self,
        adapter: ServiceAdapter,
        settings: Settings,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.adapter = adapter
        self.settings = settings
        self._sleep = sleep_fn or time.sleep
        self._rng = random.Random(settings.SEED)
        self._logger = get_logger(self.__class__.__name__)

    def run_once(
        self,
        strategy,
        *,
        tag: str | None = None,
        dry_run: bool | None = None,
        discover_limit: int | None = None,
    ) -> ActionPlan:
        dry = self.settings.DRY_RUN if dry_run is None else dry_run

        session = self.adapter.login(self.settings.USERNAME, self.settings.PASSWORD)
        posts = self.adapter.discover_posts(
            tag=tag if tag is not None else self.settings.DEFAULT_TAG,
            limit=discover_limit if discover_limit is not None else self.settings.DISCOVER_LIMIT,
        )
        plan = strategy.plan(posts, self.settings)
        self._logger.info("Plan: %s", plan.summary())
        print(plan.summary())  # explicit print for CLI acceptance criteria

        if dry:
            self._logger.info("Dry-run enabled; not executing actions.")
            return plan

        for item in plan.items:
            self._execute_action(session, item)
            self._maybe_delay(item)
        return plan

    # Internals -----------------------------------------------------------------
    def _execute_action(self, session: Session, item: ActionItem) -> None:
        if item.type == ActionType.LIKE and item.post_id:
            result = self.adapter.like_post(session, item.post_id, dry_run=False)
        elif item.type == ActionType.FOLLOW and item.user_id:
            result = self.adapter.follow_user(session, item.user_id, dry_run=False)
        elif item.type == ActionType.COMMENT and item.post_id:
            result = self.adapter.comment(
                session, item.post_id, text=item.text or self.settings.DEFAULT_COMMENT_TEXT, dry_run=False
            )
        else:
            self._logger.error("Invalid action item: %s", item)
            return

        if result.rate_limited:
            self._logger.warning("Rate limited on %s -> %s", item.type, item)
        elif not result.ok:
            self._logger.error("Action failed: %s -> %s", item, result.message)
        else:
            self._logger.info("Action ok: %s", item)

    def _maybe_delay(self, item: ActionItem) -> None:
        if item.type == ActionType.LIKE:
            low, high = self.settings.LIKE_DELAY_RANGE_S
        elif item.type == ActionType.FOLLOW:
            low, high = self.settings.FOLLOW_DELAY_RANGE_S
        elif item.type == ActionType.COMMENT:
            low, high = self.settings.COMMENT_DELAY_RANGE_S
        else:
            return

        if high <= 0:
            return
        delay = self._rng.uniform(low, high)
        self._sleep(delay)

