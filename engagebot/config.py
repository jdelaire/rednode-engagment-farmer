from __future__ import annotations

from typing import tuple

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_range(value: str | tuple[int, int]) -> tuple[int, int]:
    if isinstance(value, tuple):
        return value
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    if len(parts) != 2:
        raise ValueError("Expected a 'min,max' range string, e.g., '2,5'")
    low, high = int(parts[0]), int(parts[1])
    if low > high:
        low, high = high, low
    return (low, high)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # Adapter + credentials (mock only in this PoC)
    ADAPTER: str = Field(default="mock")
    USERNAME: str = Field(default="")
    PASSWORD: str = Field(default="")

    # Discovery defaults
    DEFAULT_TAG: str = Field(default="fitness")
    DISCOVER_LIMIT: int = Field(default=20)

    # Per-run caps
    MAX_LIKES_PER_RUN: int = Field(default=5)
    MAX_FOLLOWS_PER_RUN: int = Field(default=1)
    MAX_COMMENTS_PER_RUN: int = Field(default=1)

    # Delay ranges (seconds) as "min,max"
    LIKE_DELAY_RANGE_S: tuple[int, int] = Field(default=(2, 5))
    FOLLOW_DELAY_RANGE_S: tuple[int, int] = Field(default=(5, 10))
    COMMENT_DELAY_RANGE_S: tuple[int, int] = Field(default=(8, 12))

    # Global behavior
    DRY_RUN: bool = Field(default=True)
    LOG_JSON: bool = Field(default=False)
    SEED: int = Field(default=12345)
    DEFAULT_COMMENT_TEXT: str = Field(default="Nice work!")

    # Mock adapter simple rate limits (per minute)
    MOCK_MAX_LIKES_PER_MIN: int = Field(default=10)
    MOCK_MAX_FOLLOWS_PER_MIN: int = Field(default=5)
    MOCK_MAX_COMMENTS_PER_MIN: int = Field(default=5)

    # Mock adapter latency in milliseconds (min,max)
    MOCK_LATENCY_MS_RANGE: tuple[int, int] = Field(default=(0, 0))

    SCHEDULE_CRON: str = Field(default="*/30 * * * *")

    @field_validator("LIKE_DELAY_RANGE_S", mode="before")
    @classmethod
    def _validate_like(cls, v):  # type: ignore[override]
        return _parse_range(v)

    @field_validator("FOLLOW_DELAY_RANGE_S", mode="before")
    @classmethod
    def _validate_follow(cls, v):  # type: ignore[override]
        return _parse_range(v)

    @field_validator("COMMENT_DELAY_RANGE_S", mode="before")
    @classmethod
    def _validate_comment(cls, v):  # type: ignore[override]
        return _parse_range(v)

    @field_validator("MOCK_LATENCY_MS_RANGE", mode="before")
    @classmethod
    def _validate_latency(cls, v):  # type: ignore[override]
        return _parse_range(v)


def load_settings() -> Settings:
    return Settings()

