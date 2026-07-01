import pytest

from scripts.verify_mcp_http_sse import build_http_sse_probe_plan, summarize_probe_results


def test_http_sse_probe_plan_targets_loopback_sse_transport():
    plan = build_http_sse_probe_plan(connections=8)

    assert plan["transport"] == "sse"
    assert plan["endpoint"] == "http://127.0.0.1:8000/sse"
    assert plan["connections"] == 8
    assert [tool["name"] for tool in plan["tools"]] == [
        "system_health",
        "scan_intraday_events",
        "scan_drawdown_risk",
        "scan_portfolio_risk",
        "get_market_data",
    ]


def test_http_sse_probe_plan_rejects_non_loopback_endpoints():
    with pytest.raises(ValueError, match="loopback"):
        build_http_sse_probe_plan(endpoint="http://192.0.2.10:8000/sse", connections=8)


def test_http_sse_probe_summary_requires_every_connection_to_call_every_tool():
    plan = build_http_sse_probe_plan(connections=2)
    report = summarize_probe_results(
        plan,
        [
            {"connection": 0, "tool": "system_health", "ok": True},
            {"connection": 0, "tool": "scan_intraday_events", "ok": True},
            {"connection": 0, "tool": "scan_drawdown_risk", "ok": True},
            {"connection": 0, "tool": "scan_portfolio_risk", "ok": True},
            {"connection": 0, "tool": "get_market_data", "ok": True},
            {"connection": 1, "tool": "system_health", "ok": True},
            {"connection": 1, "tool": "scan_intraday_events", "ok": True},
            {"connection": 1, "tool": "scan_drawdown_risk", "ok": True},
            {"connection": 1, "tool": "scan_portfolio_risk", "ok": True},
            {"connection": 1, "tool": "get_market_data", "ok": True},
        ],
    )

    assert report["status"] == "ok"
    assert report["transport"] == "sse"
    assert report["connections"] == 2
    assert report["calls_per_connection"] == 5
    assert report["total_calls"] == 10
    assert report["failures"] == []
    assert report["tool_counts"]["system_health"] == 2
