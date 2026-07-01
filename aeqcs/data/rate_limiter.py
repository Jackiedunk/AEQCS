"""Rate limiter for market data providers."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable

from aeqcs.core.exceptions import RateLimitExceeded


LOGGER = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    burst: float
    per_second: float
    tokens: float | None = None
    updated_at: float | None = None

    def __post_init__(self) -> None:
        self.tokens = self.burst
        self.updated_at = time.monotonic()

    def consume(self, amount: float = 1.0) -> None:
        now = time.monotonic()
        assert self.tokens is not None and self.updated_at is not None
        elapsed = now - self.updated_at
        self.tokens = min(self.burst, self.tokens + elapsed * self.per_second)
        self.updated_at = now
        if self.tokens < amount:
            raise RateLimitExceeded("rate limit exceeded")
        self.tokens -= amount


@dataclass
class DailyQuota:
    quota: float
    used: float = 0.0
    day: date | None = None
    warn_ratio: float = 0.9

    def consume(self, source: str, amount: float, current_day: date) -> None:
        if self.day != current_day:
            self.day = current_day
            self.used = 0.0
        if self.used + amount > self.quota:
            LOGGER.warning(
                "daily quota exceeded for data source",
                extra={"source": source, "quota": self.quota, "used": self.used, "amount": amount},
            )
            raise RateLimitExceeded(f"{source} daily quota exceeded")
        self.used += amount
        if self.used >= self.quota * self.warn_ratio:
            LOGGER.warning(
                "daily quota near limit for data source",
                extra={"source": source, "quota": self.quota, "used": self.used},
            )


class RateLimiter:
    def __init__(
        self,
        config: dict[str, dict[str, float | int | bool]],
        *,
        day_fn: Callable[[], date] | None = None,
    ) -> None:
        self._day_fn = day_fn or date.today
        self.buckets = {
            name: TokenBucket(float(cfg["burst"]), float(cfg["per_second"]))
            for name, cfg in config.items()
            if "burst" in cfg and "per_second" in cfg
        }
        self.daily_quotas = {
            name: DailyQuota(float(cfg.get("daily_quota", cfg.get("max_daily"))))
            for name, cfg in config.items()
            if "daily_quota" in cfg or "max_daily" in cfg
        }

    def consume(self, source: str, amount: float = 1.0) -> None:
        if source not in self.buckets and source not in self.daily_quotas:
            raise KeyError(source)
        if source in self.daily_quotas:
            self.daily_quotas[source].consume(source, amount, self._day_fn())
        if source in self.buckets:
            self.buckets[source].consume(amount)
