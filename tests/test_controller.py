from __future__ import annotations

from engagebot.adapters.mock import MockAdapter
from engagebot.config import Settings
from engagebot.controller import Controller
from engagebot.strategy import RandomSampleStrategy


def test_run_once_dry_run_no_state_change(monkeypatch):
    settings = Settings(DRY_RUN=True, DISCOVER_LIMIT=5, DEFAULT_TAG="fitness")
    adapter = MockAdapter(settings)
    ctrl = Controller(adapter, settings, sleep_fn=lambda s: None)

    before = adapter.get_state_snapshot()
    ctrl.run_once(RandomSampleStrategy(seed=settings.SEED), dry_run=True)
    after = adapter.get_state_snapshot()

    assert before == after


def test_run_once_respects_delays(monkeypatch):
    calls: list[float] = []

    def fake_sleep(d: float) -> None:
        calls.append(d)

    settings = Settings(
        DRY_RUN=False,
        DISCOVER_LIMIT=3,
        MAX_LIKES_PER_RUN=1,
        MAX_FOLLOWS_PER_RUN=1,
        MAX_COMMENTS_PER_RUN=1,
        LIKE_DELAY_RANGE_S=(1, 1),
        FOLLOW_DELAY_RANGE_S=(2, 2),
        COMMENT_DELAY_RANGE_S=(3, 3),
    )
    adapter = MockAdapter(settings)
    ctrl = Controller(adapter, settings, sleep_fn=fake_sleep)

    ctrl.run_once(RandomSampleStrategy(seed=settings.SEED), dry_run=False)
    # Expect three sleeps with deterministic durations
    assert calls and len(calls) == 3
    assert set(calls) == {1.0, 2.0, 3.0}

