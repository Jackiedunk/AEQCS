"""Immutable event schemas for deterministic core workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


def new_event_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    timestamp: datetime
    knowledge_ts: datetime

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MarketEvent(Event):
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_trading: bool
    tick_status: str
    pre_close: float
    high_limit: float
    low_limit: float
    bid_volume: int = 0
    is_one_word_limit: bool = False


@dataclass(frozen=True, slots=True)
class NewsEvent(Event):
    source: str
    level: str
    title: str
    content: str
    entities: list[str] = field(default_factory=list)
    sentiment: float | None = None


@dataclass(frozen=True, slots=True)
class FinancialEvent(Event):
    symbol: str
    period: str
    ann_date: datetime
    indicators: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CatalystDetected(Event):
    news_id: str
    concept: str
    affected_stocks: list[str]
    confidence: float


@dataclass(frozen=True, slots=True)
class SignalEvent(Event):
    strategy_id: str
    symbol: str
    score: float
    source_tags: list[str]


@dataclass(frozen=True, slots=True)
class RiskAlert(Event):
    type: str
    message: str
    severity: str
