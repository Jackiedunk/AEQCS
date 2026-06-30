from datetime import date
import json

import pandas as pd
import pytest

from aeqcs.core.exceptions import GateStateError, LookAheadViolation
from aeqcs.core.mcp_server import call_local_tool
from aeqcs.store.local import LocalStore


def seed_store(tmp_path):
    store = LocalStore(tmp_path)
    store.save_daily(
        pd.DataFrame(
            [
                {"symbol": "000001", "date": "2026-01-01", "open": 10, "high": 10.5, "low": 9.8, "close": 10, "volume": 1000, "amount": 10000},
                {"symbol": "000001", "date": "2026-01-02", "open": 11, "high": 12.2, "low": 10.8, "close": 12, "volume": 1200, "amount": 13200},
                {"symbol": "000001", "date": "2026-01-05", "open": 12, "high": 12.3, "low": 11.5, "close": 11.8, "volume": 900, "amount": 10800},
            ]
        )
    )
    store.save_financials(
        pd.DataFrame(
            [
                {"symbol": "000001", "period": "2025Q4", "ann_date": "2026-01-01", "vintage": 0, "roe": 0.10},
                {"symbol": "000001", "period": "2025Q4", "ann_date": "2026-01-10", "vintage": 1, "roe": 0.12},
            ]
        )
    )
    return store


def test_local_market_data_respects_as_of(tmp_path):
    seed_store(tmp_path)

    row = call_local_tool(
        "get_market_data",
        {"symbol": "000001", "as_of_date": "2026-01-02"},
        root=str(tmp_path),
    )

    assert row["date"] == "2026-01-02"
    assert row["close"] == 12


def test_local_financials_use_pit_slice(tmp_path):
    seed_store(tmp_path)

    row = call_local_tool(
        "get_financials",
        {"symbol": "000001", "period": "2025Q4", "as_of_date": "2026-01-05"},
        root=str(tmp_path),
    )

    assert row["ann_date"] == "2026-01-01"
    assert row["roe"] == 0.10


def test_local_tool_requires_as_of(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(KeyError):
        call_local_tool("get_market_data", {"symbol": "000001"}, root=str(tmp_path))

    with pytest.raises(LookAheadViolation):
        LocalStore(tmp_path).get_market_data("000001")


def test_local_backtest_and_factor_tools(tmp_path):
    seed_store(tmp_path)

    factor_rows = call_local_tool(
        "compute_factors",
        {
            "factor_ids": ["momentum_1d"],
            "start_date": "2026-01-01",
            "end_date": "2026-01-05",
            "as_of_date": "2026-01-05",
        },
        root=str(tmp_path),
    )
    stored_factor_rows = call_local_tool(
        "get_factor_values",
        {
            "factor_ids": ["momentum_1d"],
            "start_date": "2026-01-01",
            "end_date": "2026-01-05",
            "as_of_date": "2026-01-05",
        },
        root=str(tmp_path),
    )
    run_result = call_local_tool(
        "run_backtest",
        {
            "strategy_name": "buy_and_hold",
            "start_date": "2026-01-01",
            "end_date": "2026-01-05",
            "as_of_date": "2026-01-05",
            "parameters": {"symbol": "000001", "initial_cash": "10000"},
        },
        root=str(tmp_path),
    )
    result = call_local_tool(
        "get_backtest_result",
        {"backtest_result_id": run_result["backtest_result_id"]},
        root=str(tmp_path),
    )

    assert factor_rows
    assert stored_factor_rows
    assert stored_factor_rows[0]["factor_id"] == "momentum_1d"
    assert stored_factor_rows[0]["date"] == "2026-01-02"
    assert result["fills"][0]["date"] == "2026-01-02"
    json.dumps(result)


def test_local_service_rejects_end_date_after_as_of(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(LookAheadViolation):
        call_local_tool(
            "run_backtest",
            {
                "strategy_name": "buy_and_hold",
                "start_date": "2026-01-01",
                "end_date": "2026-01-05",
                "as_of_date": "2026-01-02",
                "parameters": {"symbol": "000001"},
            },
            root=str(tmp_path),
        )


def test_local_service_rejects_unknown_factor(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError):
        call_local_tool(
            "compute_factors",
            {
                "factor_ids": ["unknown_factor"],
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-02",
            },
            root=str(tmp_path),
        )


def test_local_factor_values_reject_end_date_after_as_of(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(LookAheadViolation):
        call_local_tool(
            "get_factor_values",
            {
                "factor_ids": ["momentum_1d"],
                "start_date": "2026-01-01",
                "end_date": "2026-01-05",
                "as_of_date": "2026-01-02",
            },
            root=str(tmp_path),
        )


def test_local_proposal_gate_review_flow(tmp_path):
    seed_store(tmp_path)

    proposal_id = call_local_tool(
        "submit_proposal",
        {
            "kind": "edge",
            "payload": {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
            "source": "test",
            "confidence": 0.8,
        },
        root=str(tmp_path),
    )
    status = call_local_tool(
        "review_proposal",
        {"proposal_id": proposal_id, "status": "approved", "reviewed_by": "tester"},
        root=str(tmp_path),
    )

    assert status["status"] == "approved"

    with pytest.raises(GateStateError):
        call_local_tool(
            "review_proposal",
            {"proposal_id": proposal_id, "status": "rejected", "reviewed_by": "tester"},
            root=str(tmp_path),
        )


def test_local_proposal_gate_rejects_invalid_payload(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError):
        call_local_tool(
            "submit_proposal",
            {
                "kind": "edge",
                "payload": {"parent_id": "banking"},
                "source": "test",
                "confidence": 0.8,
            },
            root=str(tmp_path),
        )
