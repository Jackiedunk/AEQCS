from datetime import date, datetime
from decimal import Decimal
from importlib import import_module
from typing import Any

import pytest

from aeqcs.core.events import RiskAlert


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, RiskAlert]] = []

    async def publish(self, channel: str, event: RiskAlert) -> None:
        self.published.append((channel, event))


def _publisher() -> Any:
    try:
        return import_module("aeqcs.runtime.risk_alerts").publish_strategy_risk_alerts
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing strategy risk alert publisher: {exc}")


@pytest.mark.asyncio
async def test_publish_strategy_risk_alerts_emits_deterministic_risk_events() -> None:
    report = {
        "alerts": [
            {
                "date": date(2026, 1, 3),
                "severity": "warn",
                "action": "risk_officer.review_drawdown",
                "drawdown": Decimal("-0.06"),
                "threshold": Decimal("0.05"),
            },
            {
                "severity": "red",
                "action": "risk_officer.reduce_exposure",
                "metric": "gross_exposure",
                "value": Decimal("1.2"),
                "threshold": Decimal("1"),
            },
        ],
    }
    bus = FakeBus()

    await _publisher()(bus, report, source="strategy", timestamp=datetime(2026, 1, 3, 15, 0))

    assert [channel for channel, _event in bus.published] == ["risk_alerts", "risk_alerts"]
    assert [event.event_id for _channel, event in bus.published] == [
        "risk_alert:strategy:risk_officer.review_drawdown:2026-01-03",
        "risk_alert:strategy:risk_officer.reduce_exposure:gross_exposure",
    ]
    assert [event.type for _channel, event in bus.published] == [
        "risk_officer.review_drawdown",
        "risk_officer.reduce_exposure",
    ]
    assert [event.severity for _channel, event in bus.published] == ["warn", "red"]
    assert bus.published[0][1].message == (
        "strategy: risk_officer.review_drawdown date=2026-01-03 "
        "drawdown=-0.06 threshold=0.05"
    )
    assert bus.published[1][1].message == (
        "strategy: risk_officer.reduce_exposure metric=gross_exposure "
        "value=1.2 threshold=1"
    )


@pytest.mark.asyncio
async def test_publish_strategy_risk_alerts_rejects_non_risk_officer_actions() -> None:
    report = {
        "alerts": [
            {
                "severity": "red",
                "action": "market_observer.inspect",
                "metric": "gross_exposure",
                "value": Decimal("1.2"),
                "threshold": Decimal("1"),
            }
        ],
    }

    with pytest.raises(ValueError, match="unsupported risk alert action"):
        await _publisher()(FakeBus(), report, source="strategy", timestamp=datetime(2026, 1, 3, 15, 0))
