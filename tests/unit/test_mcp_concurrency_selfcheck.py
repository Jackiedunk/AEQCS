import pytest

from scripts.verify_mcp_concurrency import run_mcp_concurrency_selfcheck


@pytest.mark.asyncio
async def test_mcp_concurrency_selfcheck_runs_core_tools_concurrently(tmp_path):
    report = await run_mcp_concurrency_selfcheck(local_root=str(tmp_path), concurrency=8)

    assert report["status"] == "ok"
    assert report["concurrency"] == 8
    assert report["total_calls"] == 40
    assert report["failures"] == []
    assert report["tool_counts"] == {
        "system_health": 8,
        "scan_intraday_events": 8,
        "scan_drawdown_risk": 8,
        "scan_portfolio_risk": 8,
        "get_market_data": 8,
    }
    assert "system_health" in report["observed_tools"]
    assert report["sample_results"]["system_health"]["status"] == "ok"
    assert report["sample_results"]["scan_intraday_events"]["count"] == 1
    assert report["sample_results"]["scan_drawdown_risk"]["status"] == "red"
    assert report["sample_results"]["scan_portfolio_risk"]["status"] == "red"
    assert report["sample_results"]["get_market_data"]["count"] == 0
