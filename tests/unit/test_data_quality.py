from datetime import date
from decimal import Decimal

import pandas as pd

from aeqcs.data.models import DailyBar
from aeqcs.data.quality.cross_check import compare_daily_bars
from aeqcs.data.quality.health_checker import check_baostock_health
from aeqcs.data.quality.outlier_detector import detect_daily_outliers
from aeqcs.data.quality.source_policy import decide_source_health_action
from aeqcs.data.quality.validator import validate_daily_bar


def test_validate_daily_bar_rejects_bad_ohlc():
    bar = DailyBar(
        symbol="000001",
        date=date(2026, 1, 1),
        open=Decimal("10"),
        high=Decimal("9"),
        low=Decimal("8"),
        close=Decimal("10"),
        volume=1,
        amount=Decimal("10"),
    )

    assert validate_daily_bar(bar)


class HealthyBaostockAdapter:
    def daily(self, symbol, start, end):
        return pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "date": start,
                    "open": 10,
                    "high": 10,
                    "low": 10,
                    "close": 10,
                    "volume": 100,
                    "amount": 1000,
                    "timestamp": pd.Timestamp(start),
                    "knowledge_ts": pd.Timestamp("2026-01-02 16:00:00"),
                }
            ]
        )


def test_baostock_health_checker_reports_alive_for_fixture_adapter():
    report = check_baostock_health(
        HealthyBaostockAdapter(),
        symbol="sh.000001",
        day=date(2026, 1, 2),
    )

    assert report["source"] == "baostock"
    assert report["status"] == "ok"
    assert report["rows"] == 1


def test_daily_cross_check_emits_data_quality_alerts_for_close_and_volume_drift():
    tushare = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": date(2026, 1, 2),
                "close": 10.00,
                "volume": 1000,
            }
        ]
    )
    baostock = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": date(2026, 1, 2),
                "close": 10.20,
                "volume": 1120,
            }
        ]
    )

    alerts = compare_daily_bars(
        primary=tushare,
        cross_check=baostock,
        primary_source="tushare",
        cross_check_source="baostock",
        close_tolerance=0.001,
        volume_tolerance=0.01,
    )

    assert [alert["metric"] for alert in alerts] == ["close", "volume"]
    assert alerts[0]["alert_type"] == "daily_cross_check_mismatch"
    assert alerts[0]["severity"] == "warning"
    assert alerts[0]["symbol"] == "000001.SZ"


def test_daily_outlier_detector_flags_implausible_price_move():
    frame = pd.DataFrame(
        [
            {"symbol": "000001.SZ", "date": date(2026, 1, 2), "open": 10, "close": 10, "volume": 100},
            {"symbol": "000001.SZ", "date": date(2026, 1, 3), "open": 10, "close": 20, "volume": 100},
        ]
    )

    alerts = detect_daily_outliers(frame, max_abs_return=0.2)

    assert alerts == [
        {
            "alert_type": "daily_outlier",
            "severity": "warning",
            "symbol": "000001.SZ",
            "date": date(2026, 1, 3),
            "metric": "close_return",
            "value": 1.0,
            "threshold": 0.2,
        }
    ]


def test_source_health_policy_stops_primary_source_and_alerts_cross_check_source():
    assert decide_source_health_action({"source": "tushare", "status": "error"}, role="financial") == {
        "action": "stop_calculation",
        "severity": "red",
        "reason": "primary financial data source is unhealthy",
    }
    assert decide_source_health_action({"source": "baostock", "status": "error"}, role="daily_cross_check") == {
        "action": "emit_alert",
        "severity": "warning",
        "reason": "cross-check data source is unhealthy",
    }
