from datetime import UTC, datetime, timedelta

from engagebot.config import Settings
from engagebot.domain import Post
from engagebot.strategy import RandomSampleStrategy, RecentFirstStrategy


def _mk_posts(n: int) -> list[Post]:
    now = datetime.now(tz=UTC)
    posts: list[Post] = []
    for i in range(n):
        posts.append(
            Post(
                id=f"p{i}",
                user_id=f"u{i%3}",
                username=f"user{i%3}",
                tags=["fitness"],
                created_at=now - timedelta(minutes=i),
            )
        )
    return posts


essential_caps = Settings(MAX_LIKES_PER_RUN=3, MAX_FOLLOWS_PER_RUN=1, MAX_COMMENTS_PER_RUN=2)


def test_random_strategy_respects_caps():
    strat = RandomSampleStrategy(seed=42)
    plan = strat.plan(_mk_posts(10), essential_caps)
    assert plan.like_count <= 3
    assert plan.follow_count <= 1
    assert plan.comment_count <= 2


def test_recent_strategy_respects_caps_and_order():
    settings = Settings(MAX_LIKES_PER_RUN=2, MAX_FOLLOWS_PER_RUN=1, MAX_COMMENTS_PER_RUN=1)
    strat = RecentFirstStrategy()
    posts = _mk_posts(5)
    plan = strat.plan(posts, settings)
    assert plan.like_count == 2
    assert plan.follow_count == 1
    assert plan.comment_count == 1
