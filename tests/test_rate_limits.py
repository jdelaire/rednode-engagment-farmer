from engagebot.adapters.mock import MockAdapter
from engagebot.config import Settings


def test_rate_limits_enforced():
    settings = Settings(
        DRY_RUN=False,
        MOCK_MAX_LIKES_PER_MIN=1,
        MOCK_MAX_FOLLOWS_PER_MIN=1,
        MOCK_MAX_COMMENTS_PER_MIN=1,
        MOCK_LATENCY_MS_RANGE=(0, 0),
    )
    adapter = MockAdapter(settings)
    session = adapter.login("demo", "demo")

    r1 = adapter.like_post(session, "p1", dry_run=False)
    r2 = adapter.like_post(session, "p2", dry_run=False)
    assert r1.ok is True
    assert r2.rate_limited is True

    r3 = adapter.follow_user(session, "u1", dry_run=False)
    r4 = adapter.follow_user(session, "u2", dry_run=False)
    assert r3.ok is True
    assert r4.rate_limited is True

    r5 = adapter.comment(session, "p1", text="hi", dry_run=False)
    r6 = adapter.comment(session, "p2", text="hi", dry_run=False)
    assert r5.ok is True
    assert r6.rate_limited is True

