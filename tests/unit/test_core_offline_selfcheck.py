from datetime import date

import pytest

from scripts.verify_core_offline import run_offline_core_selfcheck


@pytest.mark.asyncio
async def test_core_offline_selfcheck_covers_health_batch_and_intraday(tmp_path, monkeypatch):
    monkeypatch.setenv("AEQCS_HERMES_URL", "http://127.0.0.1:9/unavailable")

    report = await run_offline_core_selfcheck(
        local_root=str(tmp_path),
        today=date(2026, 6, 30),
    )

    assert report["status"] == "ok"
    assert report["system_health"]["status"] == "ok"
    assert report["system_health"]["backend"] == "local"
    assert "system_health" in report["system_health"]["tools"]
    assert report["batch_night"]["dag"] == "batch-night-retain-3m"
    assert report["batch_night"]["tasks"] == [
        "backup_snapshot",
        "archive_minute_bar_hot",
        "vacuum_full_window",
        "vacuum_analyze_hot_tables",
        "reindex_hnsw",
        "parse_upload_inbox",
    ]
    assert report["intraday_cep"]["alerts"][0]["rule_id"] == "sudden_spike"
    assert report["resource_budget"]["memory"]["within_limit"] is True
    assert report["resource_budget"]["memory"]["total_planned_mb"] == 5120
    assert report["resource_budget"]["postgresql_connections"]["within_limit"] is True
    assert report["resource_budget"]["postgresql_connections"]["total_planned_connections"] == 20
    assert report["offline_boundary"]["used_external_cognitive_service"] is False


@pytest.mark.asyncio
async def test_core_offline_selfcheck_covers_strategy_risk_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("AEQCS_HERMES_URL", "http://127.0.0.1:9/unavailable")

    report = await run_offline_core_selfcheck(
        local_root=str(tmp_path),
        today=date(2026, 6, 30),
    )

    assert report["strategy_risk"]["drawdown"]["status"] == "red"
    assert [alert["action"] for alert in report["strategy_risk"]["drawdown"]["alerts"]] == [
        "risk_officer.review_drawdown",
        "risk_officer.reduce_risk",
    ]
    assert report["strategy_risk"]["portfolio"]["status"] == "red"
    assert [alert["action"] for alert in report["strategy_risk"]["portfolio"]["alerts"]] == [
        "risk_officer.reduce_exposure",
        "risk_officer.review_concentration",
    ]
    assert report["offline_boundary"]["used_external_cognitive_service"] is False
