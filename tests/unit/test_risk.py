from datetime import date
from decimal import Decimal

import pytest

from aeqcs.strategy import risk


def test_drawdown_tracks_peak_to_trough_loss() -> None:
    values = [Decimal("100"), Decimal("102"), Decimal("99"), Decimal("103")]

    assert risk.drawdown(values) == [
        Decimal("0"),
        Decimal("0"),
        Decimal("-0.0294117647058823529411764706"),
        Decimal("0"),
    ]
    assert risk.max_drawdown_decimal(values) == Decimal("-0.0294117647058823529411764706")


def test_scan_drawdown_risk_emits_warn_and_red_crossing_alerts() -> None:
    assert hasattr(risk, "scan_drawdown_risk")

    report = risk.scan_drawdown_risk(
        [
            (date(2026, 1, 1), Decimal("100")),
            (date(2026, 1, 2), Decimal("96")),
            (date(2026, 1, 3), Decimal("94")),
            (date(2026, 1, 4), Decimal("88")),
        ],
        warn_threshold=Decimal("0.05"),
        red_threshold=Decimal("0.10"),
    )

    assert report == {
        "status": "red",
        "max_drawdown": Decimal("-0.12"),
        "alerts": [
            {
                "date": date(2026, 1, 3),
                "severity": "warn",
                "action": "risk_officer.review_drawdown",
                "drawdown": Decimal("-0.06"),
                "threshold": Decimal("0.05"),
            },
            {
                "date": date(2026, 1, 4),
                "severity": "red",
                "action": "risk_officer.reduce_risk",
                "drawdown": Decimal("-0.12"),
                "threshold": Decimal("0.10"),
            },
        ],
    }


def test_scan_drawdown_risk_stays_ok_below_warn_threshold() -> None:
    assert hasattr(risk, "scan_drawdown_risk")

    report = risk.scan_drawdown_risk(
        [
            (date(2026, 1, 1), Decimal("100")),
            (date(2026, 1, 2), Decimal("98")),
        ],
        warn_threshold=Decimal("0.05"),
        red_threshold=Decimal("0.10"),
    )

    assert report == {
        "status": "ok",
        "max_drawdown": Decimal("-0.02"),
        "alerts": [],
    }


def test_scan_drawdown_risk_rejects_invalid_thresholds() -> None:
    nav = [(date(2026, 1, 1), Decimal("100"))]

    with pytest.raises(ValueError, match="warn_threshold must be finite"):
        risk.scan_drawdown_risk(nav, warn_threshold=Decimal("NaN"))

    with pytest.raises(ValueError, match="warn_threshold must be non-negative"):
        risk.scan_drawdown_risk(nav, warn_threshold=Decimal("-0.01"))

    with pytest.raises(ValueError, match="red_threshold must be finite"):
        risk.scan_drawdown_risk(nav, red_threshold=Decimal("Infinity"))
