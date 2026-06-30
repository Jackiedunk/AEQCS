from datetime import date

import pandas as pd
import pytest

from aeqcs.core.exceptions import LookAheadViolation
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

    assert row["date"] == date(2026, 1, 2)
    assert row["close"] == 12


def test_local_financials_use_pit_slice(tmp_path):
    seed_store(tmp_path)

    row = call_local_tool(
        "get_financials",
        {"symbol": "000001", "period": "2025Q4", "as_of_date": "2026-01-05"},
        root=str(tmp_path),
    )

    assert row["ann_date"] == date(2026, 1, 1)
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
    result = call_local_tool(
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

    assert factor_rows
    assert result["fills"][0]["date"] == date(2026, 1, 2)
