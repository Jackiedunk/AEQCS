from datetime import date

import pytest

from aeqcs.core.exceptions import RateLimitExceeded
from aeqcs.data.rate_limiter import RateLimiter


def test_rate_limiter_rejects_when_daily_quota_is_exhausted_without_waiting():
    limiter = RateLimiter({"baostock": {"daily_quota": 2}}, day_fn=lambda: date(2026, 1, 2))

    limiter.consume("baostock")
    limiter.consume("baostock")

    with pytest.raises(RateLimitExceeded, match="daily quota exceeded"):
        limiter.consume("baostock")


def test_rate_limiter_tracks_daily_quota_per_source_and_resets_by_day():
    current_day = date(2026, 1, 2)
    limiter = RateLimiter(
        {
            "baostock": {"daily_quota": 1},
            "tushare": {"daily_quota": 1},
        },
        day_fn=lambda: current_day,
    )

    limiter.consume("baostock")
    limiter.consume("tushare")

    with pytest.raises(RateLimitExceeded):
        limiter.consume("baostock")

    current_day = date(2026, 1, 3)
    limiter.consume("baostock")


def test_rate_limiter_keeps_token_bucket_behavior_when_configured():
    limiter = RateLimiter({"tushare": {"burst": 1, "per_second": 0}})

    limiter.consume("tushare")

    with pytest.raises(RateLimitExceeded, match="rate limit exceeded"):
        limiter.consume("tushare")
