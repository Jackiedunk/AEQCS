from datetime import datetime

import pytest

from aeqcs.core.events import RiskAlert
from aeqcs.runtime.intraday import load_cep_rules, publish_cep_alerts, scan_cep_events


class FakeEventBus:
    def __init__(self):
        self.published = []

    async def publish(self, channel, event):
        self.published.append((channel, event))


def test_cep_rules_with_absolute_limit_prices_must_declare_raw_price_basis(tmp_path):
    path = tmp_path / "cep_rules.yaml"
    path.write_text(
        """
rules:
  - id: limit_up_open
    condition: "e.tick_status=='OPEN' and abs(e.close-e.high_limit)<1e-3"
    action: risk_officer.flag_limit_open
    priority: important
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="price_basis: raw"):
        load_cep_rules(path)


def test_scan_cep_events_flags_market_spike_and_limit_open():
    events = [
        {
            "event_id": "m1",
            "event_type": "market",
            "symbol": "000001",
            "timestamp": datetime(2026, 1, 2, 9, 31),
            "close": 10.61,
            "pre_close": 10.00,
            "high_limit": 11.00,
            "tick_status": "TRADE",
            "volume": 1000,
        },
        {
            "event_id": "m2",
            "event_type": "market",
            "symbol": "000002",
            "timestamp": datetime(2026, 1, 2, 9, 32),
            "close": 22.0,
            "pre_close": 20.0,
            "high_limit": 22.0,
            "tick_status": "OPEN",
            "volume": 1000,
        },
    ]

    alerts = scan_cep_events(events, load_cep_rules())

    assert [alert["rule_id"] for alert in alerts] == [
        "sudden_spike",
        "sudden_spike",
        "limit_up_open",
    ]
    assert alerts[0]["symbol"] == "000001"
    assert alerts[0]["action"] == "risk_officer.flag_spike"
    assert alerts[0]["priority"] == "urgent"
    assert alerts[2]["symbol"] == "000002"
    assert alerts[2]["action"] == "risk_officer.flag_limit_open"


def test_scan_cep_events_flags_s_level_news_without_llm_or_market_observer():
    events = [
        {
            "event_id": "n1",
            "event_type": "news",
            "timestamp": datetime(2026, 1, 2, 10, 0),
            "source": "akshare",
            "level": "S",
            "title": "重大确定性政策",
            "entities": ["新能源"],
        }
    ]

    alerts = scan_cep_events(events, load_cep_rules())

    assert alerts == [
        {
            "alert_id": "cep:n1:s_level_news",
            "event_id": "n1",
            "rule_id": "s_level_news",
            "event_type": "news",
            "symbol": None,
            "priority": "urgent",
            "action": "data_steward.queue_news_reference",
            "message": "S-level news requires deterministic reference queueing",
        }
    ]
    assert "llm" not in str(alerts).lower()
    assert "market_observer" not in str(alerts)


def test_scan_cep_events_rejects_invalid_event_payloads():
    rules = load_cep_rules()

    with pytest.raises(ValueError, match="CEP event requires event_id"):
        scan_cep_events(
            [
                {
                    "event_type": "market",
                    "symbol": "000001",
                    "close": 10.61,
                    "pre_close": 10.0,
                }
            ],
            rules,
        )

    with pytest.raises(ValueError, match="CEP event m1 requires close"):
        scan_cep_events(
            [
                {
                    "event_id": "m1",
                    "event_type": "market",
                    "symbol": "000001",
                    "pre_close": 10.0,
                }
            ],
            rules,
        )


def test_scan_cep_events_supports_all_configured_deterministic_rules():
    events = [
        {
            "event_id": "m1",
            "event_type": "market",
            "symbol": "000001",
            "timestamp": datetime(2026, 1, 2, 9, 31),
            "concept": "新能源",
            "change_pct": 0.031,
            "close": 10.31,
            "pre_close": 10.00,
            "high_limit": 11.00,
            "tick_status": "TRADE",
            "volume": 1000,
        },
        {
            "event_id": "m2",
            "event_type": "market",
            "symbol": "000002",
            "timestamp": datetime(2026, 1, 2, 9, 32),
            "concept": "新能源",
            "change_pct": 0.035,
            "close": 20.70,
            "pre_close": 20.00,
            "high_limit": 22.00,
            "tick_status": "TRADE",
            "volume": 1000,
        },
        {
            "event_id": "m3",
            "event_type": "market",
            "symbol": "000003",
            "timestamp": datetime(2026, 1, 2, 9, 34),
            "concept": "新能源",
            "change_pct": 0.04,
            "close": 31.20,
            "pre_close": 30.00,
            "high_limit": 33.00,
            "tick_status": "TRADE",
            "volume": 1000,
        },
        {
            "event_id": "m4",
            "event_type": "market",
            "symbol": "000004",
            "timestamp": datetime(2026, 1, 2, 9, 35),
            "close": 40.00,
            "pre_close": 40.00,
            "high_limit": 44.00,
            "tick_status": "TRADE",
            "volume": 4000,
            "volume_mean_20": 1000,
        },
        {
            "event_id": "p1",
            "event_type": "portfolio",
            "timestamp": datetime(2026, 1, 2, 9, 36),
            "drawdown": 0.06,
        },
    ]

    alerts = scan_cep_events(events, load_cep_rules())

    assert [alert["rule_id"] for alert in alerts] == [
        "sector_linkage",
        "sector_linkage",
        "sector_linkage",
        "volume_breakout",
        "portfolio_drawdown",
    ]
    assert [alert["action"] for alert in alerts] == [
        "risk_officer.flag_sector_linkage",
        "risk_officer.flag_sector_linkage",
        "risk_officer.flag_sector_linkage",
        "risk_officer.flag_volume_breakout",
        "risk_officer.analyze_drawdown",
    ]


@pytest.mark.asyncio
async def test_publish_cep_alerts_emits_risk_alert_events():
    alerts = [
        {
            "alert_id": "cep:m1:sudden_spike",
            "event_id": "m1",
            "rule_id": "sudden_spike",
            "event_type": "market",
            "symbol": "000001",
            "priority": "urgent",
            "action": "risk_officer.flag_spike",
            "message": "Market price moved beyond the configured spike threshold",
        }
    ]
    bus = FakeEventBus()

    await publish_cep_alerts(bus, alerts, timestamp=datetime(2026, 1, 2, 9, 31))

    assert len(bus.published) == 1
    channel, event = bus.published[0]
    assert channel == "risk_alerts"
    assert isinstance(event, RiskAlert)
    assert event.event_id == "risk_alert:cep:m1:sudden_spike"
    assert event.type == "sudden_spike"
    assert event.severity == "urgent"
    assert event.message == "000001: Market price moved beyond the configured spike threshold"
    assert event.timestamp == datetime(2026, 1, 2, 9, 31)
