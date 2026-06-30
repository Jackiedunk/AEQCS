"""Token bucket rate limiter for market data providers."""

from __future__ import annotations

import time
from dataclasses import dataclass

from aeqcs.core.exceptions import RateLimitExceeded


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


class RateLimiter:
    def __init__(self, config: dict[str, dict[str, float]]) -> None:
        self.buckets = {
            name: TokenBucket(float(cfg["burst"]), float(cfg["per_second"]))
            for name, cfg in config.items()
        }

    def consume(self, source: str, amount: float = 1.0) -> None:
        self.buckets[source].consume(amount)
