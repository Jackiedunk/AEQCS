"""Tradability filters for A-share execution assumptions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TradabilityInput:
    is_trading: bool
    is_suspend: bool
    is_one_word_limit: bool
    bid_volume: int
    ask_volume: int = 1


def can_buy(snapshot: TradabilityInput) -> bool:
    return (
        snapshot.is_trading
        and not snapshot.is_suspend
        and not snapshot.is_one_word_limit
        and snapshot.ask_volume > 0
    )


def can_sell(snapshot: TradabilityInput) -> bool:
    return (
        snapshot.is_trading
        and not snapshot.is_suspend
        and not snapshot.is_one_word_limit
        and snapshot.bid_volume > 0
    )
