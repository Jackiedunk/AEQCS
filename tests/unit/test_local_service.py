import json
from datetime import date, datetime

import pandas as pd
import pytest

from aeqcs.core.exceptions import GateStateError, LookAheadViolation
from aeqcs.core.mcp_server import call_local_tool
from aeqcs.core.service import CoreService
from aeqcs.factor.registry import FactorSpec
from aeqcs.gate.proposals import ProposalReview, ProposalStatus
from aeqcs.store.local import LocalStore
from aeqcs.strategy.backtest.engine import BacktestReport


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


def test_local_store_save_daily_rejects_empty_symbol_before_write(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)

    def fail_to_csv(*args, **kwargs):
        raise AssertionError("daily bars should not be written")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(ValueError, match="symbol is required"):
        store.save_daily(
            pd.DataFrame(
                [
                    {
                        "symbol": " ",
                        "date": "2026-01-02",
                        "open": 10,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10,
                        "volume": 1000,
                        "amount": 10000,
                    }
                ]
            )
        )


def test_local_store_save_daily_rejects_invalid_date_before_write(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)

    def fail_to_csv(*args, **kwargs):
        raise AssertionError("daily bars should not be written")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(ValueError, match="date must be a valid date"):
        store.save_daily(
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "date": "not-a-date",
                        "open": 10,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10,
                        "volume": 1000,
                        "amount": 10000,
                    }
                ]
            )
        )


def test_local_store_save_daily_rejects_non_finite_price_before_write(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)

    def fail_to_csv(*args, **kwargs):
        raise AssertionError("daily bars should not be written")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(ValueError, match="close must be finite"):
        store.save_daily(
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "date": "2026-01-02",
                        "open": 10,
                        "high": 10.5,
                        "low": 9.8,
                        "close": float("nan"),
                        "volume": 1000,
                        "amount": 10000,
                    }
                ]
            )
        )


def test_local_store_save_daily_rejects_non_finite_volume_before_write(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)

    def fail_to_csv(*args, **kwargs):
        raise AssertionError("daily bars should not be written")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(ValueError, match="volume must be finite"):
        store.save_daily(
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "date": "2026-01-02",
                        "open": 10,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10,
                        "volume": float("inf"),
                        "amount": 10000,
                    }
                ]
            )
        )


def test_local_store_save_daily_rejects_non_finite_amount_before_write(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)

    def fail_to_csv(*args, **kwargs):
        raise AssertionError("daily bars should not be written")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(ValueError, match="amount must be finite"):
        store.save_daily(
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "date": "2026-01-02",
                        "open": 10,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10,
                        "volume": 1000,
                        "amount": float("-inf"),
                    }
                ]
            )
        )


def test_local_store_save_financials_rejects_empty_period_before_write(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)

    def fail_to_csv(*args, **kwargs):
        raise AssertionError("financial rows should not be written")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(ValueError, match="period is required"):
        store.save_financials(
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "period": " ",
                        "ann_date": "2026-01-01",
                        "vintage": 0,
                        "roe": 0.1,
                    }
                ]
            )
        )


def test_local_store_save_financials_rejects_invalid_ann_date_before_write(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)

    def fail_to_csv(*args, **kwargs):
        raise AssertionError("financial rows should not be written")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(ValueError, match="ann_date must be a valid date"):
        store.save_financials(
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "period": "2025Q4",
                        "ann_date": "not-a-date",
                        "vintage": 0,
                        "roe": 0.1,
                    }
                ]
            )
        )


def test_local_store_save_financials_rejects_non_finite_metric_before_write(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)

    def fail_to_csv(*args, **kwargs):
        raise AssertionError("financial rows should not be written")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(ValueError, match="roe must be finite"):
        store.save_financials(
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "period": "2025Q4",
                        "ann_date": "2026-01-01",
                        "vintage": 0,
                        "roe": float("inf"),
                    }
                ]
            )
        )


def test_local_store_save_financials_rejects_invalid_vintage_before_write(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)

    def fail_to_csv(*args, **kwargs):
        raise AssertionError("financial rows should not be written")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)

    with pytest.raises(ValueError, match="vintage must be a non-negative integer"):
        store.save_financials(
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "period": "2025Q4",
                        "ann_date": "2026-01-01",
                        "vintage": -1,
                        "roe": 0.1,
                    }
                ]
            )
        )


def test_local_market_data_respects_as_of(tmp_path):
    seed_store(tmp_path)

    rows = call_local_tool(
        "get_market_data",
        {"symbol": "000001", "as_of_date": "2026-01-02"},
        root=str(tmp_path),
    )

    assert [row["date"] for row in rows] == ["2026-01-01", "2026-01-02"]
    assert rows[-1]["close"] == 12


def test_local_market_data_returns_hfq_storage_and_qfq_display_prices_when_adj_factor_exists(tmp_path):
    store = LocalStore(tmp_path)
    store.save_daily(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "date": "2026-01-01",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "volume": 1000,
                    "amount": 10000,
                    "adj_factor": 1.0,
                },
                {
                    "symbol": "000001",
                    "date": "2026-01-02",
                    "open": 8,
                    "high": 8.5,
                    "low": 7.5,
                    "close": 8,
                    "volume": 1200,
                    "amount": 9600,
                    "adj_factor": 1.2,
                },
            ]
        )
    )

    rows = store.get_market_data("000001", as_of_date=date(2026, 1, 2))

    assert rows[0]["hfq_close"] == 10.0
    assert rows[1]["hfq_close"] == 9.6
    assert rows[0]["qfq_close"] == 8.333333333333
    assert rows[1]["qfq_close"] == 8.0


def test_local_financials_use_pit_slice(tmp_path):
    seed_store(tmp_path)

    row = call_local_tool(
        "get_financials",
        {"symbol": "000001", "period": "2025Q4", "as_of_date": "2026-01-05"},
        root=str(tmp_path),
    )

    assert row["ann_date"] == "2026-01-01"
    assert row["roe"] == 0.10


def test_core_service_rejects_empty_market_symbol_before_store_call(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    service = CoreService(store)

    def fail_get_market_data(*args, **kwargs):
        raise AssertionError("store should not be queried")

    monkeypatch.setattr(store, "get_market_data", fail_get_market_data)

    with pytest.raises(ValueError, match="symbol is required"):
        service.get_market_data(" ", date(2026, 1, 2))


def test_core_service_rejects_empty_financial_symbol_or_period_before_store_call(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    service = CoreService(store)

    def fail_get_financials(*args, **kwargs):
        raise AssertionError("store should not be queried")

    monkeypatch.setattr(store, "get_financials", fail_get_financials)

    with pytest.raises(ValueError, match="symbol is required"):
        service.get_financials("", "2025Q4", date(2026, 1, 5))

    with pytest.raises(ValueError, match="period is required"):
        service.get_financials("000001", " ", date(2026, 1, 5))


def test_local_tools_reject_empty_market_and_financial_identifiers(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="symbol is required"):
        call_local_tool(
            "get_market_data",
            {"symbol": " ", "as_of_date": "2026-01-02"},
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="period is required"):
        call_local_tool(
            "get_financials",
            {"symbol": "000001", "period": "", "as_of_date": "2026-01-05"},
            root=str(tmp_path),
        )


def test_uploaded_doc_rejects_empty_sha256_before_store_call(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    service = CoreService(store)

    def fail_get_uploaded_doc(*args, **kwargs):
        raise AssertionError("uploaded document store should not be queried")

    monkeypatch.setattr(store, "get_uploaded_doc", fail_get_uploaded_doc)

    with pytest.raises(ValueError, match="sha256 is required"):
        service.get_uploaded_doc(" ")
    with pytest.raises(ValueError, match="sha256 is required"):
        call_local_tool("get_uploaded_doc", {"sha256": ""}, root=str(tmp_path))


def test_local_store_rejects_empty_uploaded_doc_sha256_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.docs_path.write_text("sha256\nabc\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("uploaded documents should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="sha256 is required"):
        store.get_uploaded_doc(" ")


def test_local_index_constituents_require_as_of_and_hide_future_members(tmp_path):
    store = seed_store(tmp_path)
    pd.DataFrame(
        [
            {"index_code": "000300", "symbol": "000001", "in_date": "2026-01-01", "out_date": ""},
            {"index_code": "000300", "symbol": "000002", "in_date": "2026-02-01", "out_date": ""},
            {"index_code": "000300", "symbol": "000003", "in_date": "2025-01-01", "out_date": "2026-01-10"},
        ]
    ).to_csv(store.index_constituents_path, index=False)
    service = CoreService(store)

    rows = service.get_index_constituents("000300", date(2026, 1, 15))

    assert [row["symbol"] for row in rows] == ["000001"]
    with pytest.raises(LookAheadViolation):
        store.get_index_constituents("000300")


def test_local_stock_universe_filters_future_listings_and_delisted_names_as_of_date(tmp_path):
    store = seed_store(tmp_path)
    pd.DataFrame(
        [
            {"symbol": "000001", "name": "Active", "ipo_date": "2020-01-01", "delist_date": "", "status": "listed"},
            {"symbol": "000002", "name": "Future", "ipo_date": "2026-02-01", "delist_date": "", "status": "listed"},
            {"symbol": "000003", "name": "Delisted", "ipo_date": "2020-01-01", "delist_date": "2026-01-10", "status": "delisted"},
        ]
    ).to_csv(store.stock_universe_path, index=False)

    rows = store.get_active_stock_universe(as_of_date=date(2026, 1, 15))

    assert [row["symbol"] for row in rows] == ["000001"]
    with pytest.raises(LookAheadViolation):
        store.get_active_stock_universe()


def test_local_index_constituents_reject_invalid_out_date(tmp_path):
    store = seed_store(tmp_path)
    pd.DataFrame(
        [
            {"index_code": "000300", "symbol": "000001", "in_date": "2026-01-01", "out_date": "not-a-date"},
        ]
    ).to_csv(store.index_constituents_path, index=False)

    with pytest.raises(ValueError, match="out_date must be a valid date"):
        store.get_index_constituents("000300", as_of_date=date(2026, 1, 15))


def test_local_index_constituents_reject_invalid_in_date(tmp_path):
    store = seed_store(tmp_path)
    pd.DataFrame(
        [
            {"index_code": "000300", "symbol": "000001", "in_date": "not-a-date", "out_date": ""},
        ]
    ).to_csv(store.index_constituents_path, index=False)

    with pytest.raises(ValueError, match="in_date must be a valid date"):
        store.get_index_constituents("000300", as_of_date=date(2026, 1, 15))


def test_local_index_constituents_reject_empty_symbol(tmp_path):
    store = seed_store(tmp_path)
    pd.DataFrame(
        [
            {"index_code": "000300", "symbol": " ", "in_date": "2026-01-01", "out_date": ""},
        ]
    ).to_csv(store.index_constituents_path, index=False)

    with pytest.raises(ValueError, match="symbol is required"):
        store.get_index_constituents("000300", as_of_date=date(2026, 1, 15))


def test_core_service_rejects_empty_index_code_before_store_call(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    service = CoreService(store)

    def fail_get_index_constituents(*args, **kwargs):
        raise AssertionError("store should not be queried")

    monkeypatch.setattr(store, "get_index_constituents", fail_get_index_constituents)

    with pytest.raises(ValueError, match="index_code is required"):
        service.get_index_constituents(" ", date(2026, 1, 15))


def test_local_tool_rejects_empty_index_code(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="index_code is required"):
        call_local_tool(
            "get_index_constituents",
            {"index_code": "", "as_of_date": "2026-01-15"},
            root=str(tmp_path),
        )


def test_local_tool_requires_as_of(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="as_of_date is required"):
        call_local_tool("get_market_data", {"symbol": "000001"}, root=str(tmp_path))

    with pytest.raises(ValueError, match="as_of_date must be an ISO date"):
        call_local_tool(
            "get_market_data",
            {"symbol": "000001", "as_of_date": "2026/01/02"},
            root=str(tmp_path),
        )

    with pytest.raises(LookAheadViolation):
        LocalStore(tmp_path).get_market_data("000001")


def test_local_store_rejects_start_date_after_end_date_before_query(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        LocalStore(tmp_path).get_market_data(
            "000001",
            start_date=date(2026, 1, 3),
            end_date=date(2026, 1, 2),
            as_of_date=date(2026, 1, 3),
        )


def test_local_store_rejects_empty_market_symbol_before_loading_daily(tmp_path, monkeypatch):
    store = seed_store(tmp_path)

    def fail_load_daily():
        raise AssertionError("daily data should not be loaded")

    monkeypatch.setattr(store, "load_daily", fail_load_daily)

    with pytest.raises(ValueError, match="symbol is required"):
        store.get_market_data(" ", as_of_date=date(2026, 1, 3))


def test_local_store_rejects_empty_financial_symbol_or_period_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)

    def fail_load_financials():
        raise AssertionError("financials should not be loaded")

    monkeypatch.setattr(store, "load_financials", fail_load_financials)

    with pytest.raises(ValueError, match="symbol is required"):
        store.get_financials("", "2025Q4", as_of_date=date(2026, 1, 5))

    with pytest.raises(ValueError, match="period is required"):
        store.get_financials("000001", " ", as_of_date=date(2026, 1, 5))


def test_local_store_rejects_empty_index_code_before_loading_constituents(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.index_constituents_path.write_text("index_code,symbol,in_date,out_date\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("index constituents should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="index_code is required"):
        store.get_index_constituents(" ", as_of_date=date(2026, 1, 15))


def test_core_service_rejects_empty_universe_parent_before_store_call(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    service = CoreService(store)

    def fail_get_universe_children_as_of(*args, **kwargs):
        raise AssertionError("store should not be queried")

    monkeypatch.setattr(store, "get_universe_children_as_of", fail_get_universe_children_as_of)

    with pytest.raises(ValueError, match="parent_id is required"):
        service.get_universe_children(" ", date(2026, 1, 4))


def test_local_tool_rejects_empty_universe_parent_id(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="parent_id is required"):
        call_local_tool(
            "get_universe_children",
            {"parent_id": "", "as_of_date": "2026-01-04"},
            root=str(tmp_path),
        )


def test_local_store_rejects_empty_universe_parent_before_loading_edges(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.universe_edges_path.write_text(
        "edge_id,parent_id,child_id,relation_type,created_by,as_of_date,verified,verified_by,verified_as_of,valid_to\n",
        encoding="utf-8",
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("semantic edges should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="parent_id is required"):
        store.get_universe_children_as_of(" ", as_of_date=date(2026, 1, 4))


def test_local_store_factor_values_reject_start_date_after_end_date_before_query(tmp_path):
    store = seed_store(tmp_path)
    store.save_factor_values(
        [
            {
                "symbol": "000001",
                "date": date(2026, 1, 2),
                "factor_id": "momentum_1d",
                "version": 1,
                "value": 0.2,
                "calc_timestamp": datetime(2026, 1, 2),
            }
        ]
    )

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        store.get_factor_values(
            ["momentum_1d"],
            date(2026, 1, 3),
            date(2026, 1, 2),
            date(2026, 1, 3),
        )


def test_local_store_save_factor_values_rejects_empty_symbol_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.factor_values_path.write_text("symbol,date,factor_id,version,value,calc_timestamp\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("factor values should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="symbol is required"):
        store.save_factor_values(
            [
                {
                    "symbol": " ",
                    "date": date(2026, 1, 2),
                    "factor_id": "momentum_1d",
                    "version": 1,
                    "value": 0.2,
                    "calc_timestamp": datetime(2026, 1, 2),
                }
            ]
        )


def test_local_store_save_factor_values_rejects_empty_factor_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.factor_values_path.write_text("symbol,date,factor_id,version,value,calc_timestamp\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("factor values should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="factor_id is required"):
        store.save_factor_values(
            [
                {
                    "symbol": "000001",
                    "date": date(2026, 1, 2),
                    "factor_id": " ",
                    "version": 1,
                    "value": 0.2,
                    "calc_timestamp": datetime(2026, 1, 2),
                }
            ]
        )


def test_local_store_save_factor_values_rejects_non_positive_version_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.factor_values_path.write_text("symbol,date,factor_id,version,value,calc_timestamp\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("factor values should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="version must be a positive integer"):
        store.save_factor_values(
            [
                {
                    "symbol": "000001",
                    "date": date(2026, 1, 2),
                    "factor_id": "momentum_1d",
                    "version": 0,
                    "value": 0.2,
                    "calc_timestamp": datetime(2026, 1, 2),
                }
            ]
        )


def test_local_store_save_factor_values_rejects_non_finite_value_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.factor_values_path.write_text("symbol,date,factor_id,version,value,calc_timestamp\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("factor values should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="value must be finite"):
        store.save_factor_values(
            [
                {
                    "symbol": "000001",
                    "date": date(2026, 1, 2),
                    "factor_id": "momentum_1d",
                    "version": 1,
                    "value": float("nan"),
                    "calc_timestamp": datetime(2026, 1, 2),
                }
            ]
        )


def test_local_store_save_factor_values_rejects_invalid_date_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.factor_values_path.write_text("symbol,date,factor_id,version,value,calc_timestamp\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("factor values should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="date must be a valid date"):
        store.save_factor_values(
            [
                {
                    "symbol": "000001",
                    "date": "not-a-date",
                    "factor_id": "momentum_1d",
                    "version": 1,
                    "value": 0.2,
                    "calc_timestamp": datetime(2026, 1, 2),
                }
            ]
        )


def test_local_store_save_factor_values_rejects_invalid_calc_timestamp_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.factor_values_path.write_text("symbol,date,factor_id,version,value,calc_timestamp\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("factor values should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="calc_timestamp must be a valid datetime"):
        store.save_factor_values(
            [
                {
                    "symbol": "000001",
                    "date": date(2026, 1, 2),
                    "factor_id": "momentum_1d",
                    "version": 1,
                    "value": 0.2,
                    "calc_timestamp": "not-a-time",
                }
            ]
        )


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
            "parameters": {
                "symbol": "000001",
                "initial_cash": "10000",
                "fee_rate": "0.001",
                "min_fee": "5",
                "slippage_bps": "10",
            },
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
    assert result["fills"][0]["price"] == "11.011"
    assert result["fills"][0]["fee"] == "9.909900"
    assert result["orders"][0]["status"] == "filled"
    assert result["orders"][0]["execution_date"] == "2026-01-02"
    json.dumps(result)


def test_backtest_result_rejects_empty_id_before_store_call(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    service = CoreService(store)

    def fail_get_backtest_result(*args, **kwargs):
        raise AssertionError("backtest result store should not be queried")

    monkeypatch.setattr(store, "get_backtest_result", fail_get_backtest_result)

    with pytest.raises(ValueError, match="backtest_result_id is required"):
        service.get_backtest_result(" ")
    with pytest.raises(ValueError, match="backtest_result_id is required"):
        call_local_tool("get_backtest_result", {"backtest_result_id": ""}, root=str(tmp_path))


def test_local_store_rejects_empty_backtest_result_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.backtest_results_path.write_text("backtest_result_id\nabc\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("backtest results should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="backtest_result_id is required"):
        store.get_backtest_result(" ")


def test_local_store_save_backtest_result_rejects_empty_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.backtest_results_path.write_text("backtest_result_id\nabc\n", encoding="utf-8")
    report = BacktestReport(
        backtest_result_id=" ",
        strategy_name="buy_and_hold",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        as_of_date=date(2026, 1, 2),
        parameters={},
        fills=[],
        nav=[],
        orders=[],
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("backtest results should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="backtest_result_id is required"):
        store.save_backtest_result(report)


def test_local_store_save_backtest_result_rejects_empty_strategy_name_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.backtest_results_path.write_text("backtest_result_id\nabc\n", encoding="utf-8")
    report = BacktestReport(
        backtest_result_id="result-empty-strategy",
        strategy_name=" ",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        as_of_date=date(2026, 1, 2),
        parameters={},
        fills=[],
        nav=[],
        orders=[],
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("backtest results should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="strategy_name is required"):
        store.save_backtest_result(report)


def test_core_service_rejects_qlib_expression_factor_ids(tmp_path):
    store = seed_store(tmp_path)
    service = CoreService(store)

    with pytest.raises(ValueError, match="unsupported factor ids"):
        service.compute_factors(
            ["qlib_momentum_1d"],
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 1, 2),
        )


def test_core_service_computes_20_day_momentum_via_duckdb(tmp_path):
    store = LocalStore(tmp_path)
    store.save_daily(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "date": f"2026-01-{day:02d}",
                    "open": float(day),
                    "high": float(day),
                    "low": float(day),
                    "close": float(day),
                    "volume": 1000,
                    "amount": 1000 * day,
                }
                for day in range(1, 22)
            ]
        )
    )
    service = CoreService(store)

    rows = service.compute_factors(
        ["momentum_20d"],
        date(2026, 1, 1),
        date(2026, 1, 21),
        date(2026, 1, 21),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 21),
            "factor_id": "momentum_20d",
            "version": 1,
            "value": 20.0,
            "calc_timestamp": datetime(2026, 1, 21),
        }
    ]


def test_core_service_keeps_prior_history_for_strict_lookback_window(tmp_path):
    store = LocalStore(tmp_path)
    store.save_daily(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "date": f"2026-01-{day:02d}",
                    "open": float(day),
                    "high": float(day),
                    "low": float(day),
                    "close": float(day),
                    "volume": 1000,
                    "amount": 1000 * day,
                }
                for day in range(1, 22)
            ]
        )
    )
    service = CoreService(store)

    rows = service.compute_factors(
        ["momentum_20d"],
        date(2026, 1, 21),
        date(2026, 1, 21),
        date(2026, 1, 21),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 21),
            "factor_id": "momentum_20d",
            "version": 1,
            "value": 20.0,
            "calc_timestamp": datetime(2026, 1, 21),
        }
    ]


def test_core_service_bounds_duckdb_history_by_registered_lookback(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)
    store.save_daily(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "date": f"2026-01-{day:02d}",
                    "open": float(day),
                    "high": float(day),
                    "low": float(day),
                    "close": float(day),
                    "volume": 1000,
                    "amount": 1000 * day,
                }
                for day in range(1, 32)
            ]
        )
    )
    captured = {}

    def fake_compute_duckdb_factor_values(frame, **kwargs):
        captured["dates"] = sorted(frame["date"].tolist())
        return []

    monkeypatch.setattr(
        "aeqcs.core.service.compute_duckdb_factor_values",
        fake_compute_duckdb_factor_values,
    )
    service = CoreService(
        store,
        factor_specs={
            "momentum_20d": FactorSpec(
                factor_id="momentum_20d",
                category="technical",
                engine="duckdb",
                compute="close / lag(close, 20) - 1",
                window_type="historical",
                preprocess=[],
                lookback_days=20,
            )
        },
    )

    service.compute_factors(
        ["momentum_20d"],
        date(2026, 1, 31),
        date(2026, 1, 31),
        date(2026, 1, 31),
    )

    assert captured["dates"][0] == date(2026, 1, 11)
    assert captured["dates"][-1] == date(2026, 1, 31)


def test_core_service_never_bounds_duckdb_history_below_factor_window(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)
    store.save_daily(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "date": f"2026-01-{day:02d}",
                    "open": float(day),
                    "high": float(day),
                    "low": float(day),
                    "close": float(day),
                    "volume": 1000,
                    "amount": 1000 * day,
                }
                for day in range(1, 32)
            ]
        )
    )
    captured = {}

    def fake_compute_duckdb_factor_values(frame, **kwargs):
        captured["dates"] = sorted(frame["date"].tolist())
        return []

    monkeypatch.setattr(
        "aeqcs.core.service.compute_duckdb_factor_values",
        fake_compute_duckdb_factor_values,
    )
    service = CoreService(
        store,
        factor_specs={
            "momentum_20d": FactorSpec(
                factor_id="momentum_20d",
                category="technical",
                engine="duckdb",
                compute="close / lag(close, 20) - 1",
                window_type="historical",
                preprocess=[],
                lookback_days=1,
            )
        },
    )

    service.compute_factors(
        ["momentum_20d"],
        date(2026, 1, 31),
        date(2026, 1, 31),
        date(2026, 1, 31),
    )

    assert captured["dates"][0] == date(2026, 1, 11)
    assert captured["dates"][-1] == date(2026, 1, 31)


def test_core_service_computes_roe_quarterly_from_pit_financials(tmp_path):
    store = seed_store(tmp_path)
    service = CoreService(
        store,
        factor_specs={
            "roe_quarterly": FactorSpec(
                factor_id="roe_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.roe",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["roe_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "roe_quarterly",
            "version": 1,
            "value": 0.1,
            "calc_timestamp": datetime(2026, 1, 5),
        }
    ]


def test_core_service_computes_roe_quarterly_without_daily_market_rows(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {"symbol": "000001", "period": "2025Q4", "ann_date": "2026-01-01", "vintage": 0, "roe": 0.10},
            ]
        )
    )
    service = CoreService(store)

    rows = service.compute_factors(
        ["roe_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert [row["factor_id"] for row in rows] == ["roe_quarterly"]


def test_core_service_computes_debt_ratio_quarterly_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "debt_ratio": 0.42,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "debt_ratio": 0.50,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "debt_ratio": 0.35,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "debt_ratio_quarterly": FactorSpec(
                factor_id="debt_ratio_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.debt_ratio",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["debt_ratio_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "debt_ratio_quarterly",
            "version": 1,
            "value": 0.42,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "debt_ratio_quarterly",
            "version": 1,
            "value": 0.35,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_computes_equity_ratio_quarterly_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "debt_ratio": 0.42,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "debt_ratio": 0.50,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "debt_ratio": 0.65,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "equity_ratio_quarterly": FactorSpec(
                factor_id="equity_ratio_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="1 - financials.debt_ratio",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["equity_ratio_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "equity_ratio_quarterly",
            "version": 1,
            "value": 0.58,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "equity_ratio_quarterly",
            "version": 1,
            "value": 0.35,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_computes_debt_to_equity_quarterly_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "debt_ratio": 0.42,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "debt_ratio": 0.50,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "debt_ratio": 0.65,
                },
                {
                    "symbol": "000003",
                    "period": "2025Q4",
                    "ann_date": "2026-01-04",
                    "vintage": 0,
                    "debt_ratio": 1.00,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "debt_to_equity_quarterly": FactorSpec(
                factor_id="debt_to_equity_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.debt_ratio / (1 - financials.debt_ratio)",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["debt_to_equity_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "debt_to_equity_quarterly",
            "version": 1,
            "value": 0.724137931034,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "debt_to_equity_quarterly",
            "version": 1,
            "value": 1.857142857143,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_computes_profit_yoy_quarterly_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "profit_yoy": 0.18,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "profit_yoy": 0.22,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "profit_yoy": -0.05,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "profit_yoy_quarterly": FactorSpec(
                factor_id="profit_yoy_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.profit_yoy",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["profit_yoy_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "profit_yoy_quarterly",
            "version": 1,
            "value": 0.18,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "profit_yoy_quarterly",
            "version": 1,
            "value": -0.05,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_computes_current_ratio_quarterly_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "current_ratio": 1.35,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "current_ratio": 1.50,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "current_ratio": 0.95,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "current_ratio_quarterly": FactorSpec(
                factor_id="current_ratio_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.current_ratio",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["current_ratio_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "current_ratio_quarterly",
            "version": 1,
            "value": 1.35,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "current_ratio_quarterly",
            "version": 1,
            "value": 0.95,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_computes_quick_ratio_quarterly_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "quick_ratio": 1.08,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "quick_ratio": 1.22,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "quick_ratio": 0.81,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "quick_ratio_quarterly": FactorSpec(
                factor_id="quick_ratio_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.quick_ratio",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["quick_ratio_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "quick_ratio_quarterly",
            "version": 1,
            "value": 1.08,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "quick_ratio_quarterly",
            "version": 1,
            "value": 0.81,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_computes_revenue_yoy_quarterly_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "revenue_yoy": 0.12,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "revenue_yoy": 0.16,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "revenue_yoy": -0.03,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "revenue_yoy_quarterly": FactorSpec(
                factor_id="revenue_yoy_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.revenue_yoy",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["revenue_yoy_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "revenue_yoy_quarterly",
            "version": 1,
            "value": 0.12,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "revenue_yoy_quarterly",
            "version": 1,
            "value": -0.03,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_computes_gross_margin_quarterly_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "gross_margin": 0.31,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "gross_margin": 0.36,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "gross_margin": 0.24,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "gross_margin_quarterly": FactorSpec(
                factor_id="gross_margin_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.gross_margin",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["gross_margin_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "gross_margin_quarterly",
            "version": 1,
            "value": 0.31,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "gross_margin_quarterly",
            "version": 1,
            "value": 0.24,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_computes_net_margin_quarterly_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "net_margin": 0.17,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "net_margin": 0.19,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "net_margin": 0.11,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "net_margin_quarterly": FactorSpec(
                factor_id="net_margin_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.net_margin",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["net_margin_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "net_margin_quarterly",
            "version": 1,
            "value": 0.17,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "net_margin_quarterly",
            "version": 1,
            "value": 0.11,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_computes_margin_spread_quarterly_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "gross_margin": 0.31,
                    "net_margin": 0.17,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "gross_margin": 0.36,
                    "net_margin": 0.19,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "gross_margin": 0.24,
                    "net_margin": 0.11,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "margin_spread_quarterly": FactorSpec(
                factor_id="margin_spread_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.gross_margin - financials.net_margin",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    rows = service.compute_factors(
        ["margin_spread_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "margin_spread_quarterly",
            "version": 1,
            "value": 0.14,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "margin_spread_quarterly",
            "version": 1,
            "value": 0.13,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_computes_per_share_quarterly_factors_from_pit_financials(tmp_path):
    store = LocalStore(tmp_path)
    store.save_financials(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-01",
                    "vintage": 0,
                    "eps": 0.88,
                    "bps": 5.10,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": "2026-01-10",
                    "vintage": 1,
                    "eps": 0.92,
                    "bps": 5.30,
                },
                {
                    "symbol": "000002",
                    "period": "2025Q4",
                    "ann_date": "2026-01-03",
                    "vintage": 0,
                    "eps": -0.12,
                    "bps": 2.80,
                },
            ]
        )
    )
    service = CoreService(
        store,
        factor_specs={
            "eps_quarterly": FactorSpec(
                factor_id="eps_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.eps",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            ),
            "bps_quarterly": FactorSpec(
                factor_id="bps_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.bps",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            ),
        },
    )

    rows = service.compute_factors(
        ["eps_quarterly", "bps_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert rows == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "eps_quarterly",
            "version": 1,
            "value": 0.88,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "eps_quarterly",
            "version": 1,
            "value": -0.12,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "bps_quarterly",
            "version": 1,
            "value": 5.1,
            "calc_timestamp": datetime(2026, 1, 5),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 3),
            "factor_id": "bps_quarterly",
            "version": 1,
            "value": 2.8,
            "calc_timestamp": datetime(2026, 1, 5),
        },
    ]


def test_core_service_rejects_missing_industry_for_registry_preprocess(tmp_path):
    store = seed_store(tmp_path)
    service = CoreService(
        store,
        factor_specs={
            "momentum_1d": FactorSpec(
                factor_id="momentum_1d",
                category="technical",
                engine="duckdb",
                compute="close / lag(close, 1) - 1",
                window_type="historical",
                preprocess=["industry_neutralize"],
            )
        },
    )

    with pytest.raises(ValueError, match="industry column is required"):
        service.compute_factors(
            ["momentum_1d"],
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 1, 2),
        )


def test_core_service_rejects_centered_window_factor_specs(tmp_path):
    store = seed_store(tmp_path)
    service = CoreService(
        store,
        factor_specs={
            "momentum_1d": FactorSpec(
                factor_id="momentum_1d",
                category="technical",
                engine="duckdb",
                compute="centered_close_change",
                window_type="centered",
                preprocess=[],
            )
        },
    )

    with pytest.raises(LookAheadViolation, match="centered window"):
        service.compute_factors(
            ["momentum_1d"],
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 1, 2),
        )


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


def test_local_service_rejects_backtest_missing_symbol(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="parameters.symbol is required"):
        call_local_tool(
            "run_backtest",
            {
                "strategy_name": "buy_and_hold",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-02",
                "parameters": {},
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


def test_local_factor_ids_must_be_non_empty_string_list(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="factor_ids must be a list of non-empty strings"):
        call_local_tool(
            "compute_factors",
            {
                "factor_ids": "momentum_1d",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-02",
            },
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="factor_ids must be a list of non-empty strings"):
        call_local_tool(
            "get_factor_values",
            {
                "factor_ids": ["momentum_1d", " "],
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


def test_local_service_rejects_start_date_after_end_date(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        call_local_tool(
            "get_market_data",
            {
                "symbol": "000001",
                "start_date": "2026-01-03",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-03",
            },
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        call_local_tool(
            "compute_factors",
            {
                "factor_ids": ["momentum_1d"],
                "start_date": "2026-01-03",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-03",
            },
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        call_local_tool(
            "get_factor_values",
            {
                "factor_ids": ["momentum_1d"],
                "start_date": "2026-01-03",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-03",
            },
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        call_local_tool(
            "run_backtest",
            {
                "strategy_name": "buy_and_hold",
                "start_date": "2026-01-03",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-03",
                "parameters": {"symbol": "000001"},
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


def test_local_proposal_gate_review_requires_auditable_identity(tmp_path):
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

    with pytest.raises(ValueError, match="reviewed_by is required"):
        call_local_tool(
            "review_proposal",
            {"proposal_id": proposal_id, "status": "approved", "reviewed_by": " "},
            root=str(tmp_path),
        )


def test_local_proposal_tools_reject_invalid_integer_ids(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="proposal_id must be an integer"):
        call_local_tool(
            "get_proposal_status",
            {"proposal_id": "not-an-id"},
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="proposal_id must be an integer"):
        call_local_tool(
            "review_proposal",
            {"proposal_id": "7.5", "status": "approved", "reviewed_by": "tester"},
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="proposal_id must be a positive integer"):
        call_local_tool(
            "approve_proposal",
            {"proposal_id": 0, "approver_id": "risk_officer", "decision": "promote"},
            root=str(tmp_path),
        )


def test_local_store_rejects_non_positive_proposal_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.proposals_path.write_text("proposal_id,status\n1,pending\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("proposals should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="proposal_id must be a positive integer"):
        store.get_proposal_status(0)


def test_local_store_review_proposal_rejects_non_positive_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.proposals_path.write_text("proposal_id,status\n1,pending\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("proposals should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="proposal_id must be a positive integer"):
        store.review_proposal(
            ProposalReview(0, ProposalStatus.APPROVED, reviewed_by="tester")
        )


def test_approve_proposal_promotes_with_auditable_identity(tmp_path):
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
    call_local_tool(
        "review_proposal",
        {"proposal_id": proposal_id, "status": "approved", "reviewed_by": "reviewer"},
        root=str(tmp_path),
    )

    status = call_local_tool(
        "approve_proposal",
        {"proposal_id": proposal_id, "approver_id": "risk_officer", "decision": "promote"},
        root=str(tmp_path),
    )

    assert status["status"] == "promoted"
    assert status["result"]["reviewed_by"] == "risk_officer"


def test_approve_proposal_requires_auditable_identity_before_lookup(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="approver_id is required"):
        call_local_tool(
            "approve_proposal",
            {"proposal_id": 999, "approver_id": " ", "decision": "promote"},
            root=str(tmp_path),
        )


def test_local_store_approve_proposal_rejects_non_positive_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.proposals_path.write_text("proposal_id,status\n1,approved\n", encoding="utf-8")

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("proposals should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="proposal_id must be a positive integer"):
        store.approve_proposal(0, "risk_officer", "promote")


def test_approve_proposal_rejects_unsupported_decision_before_lookup(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    service = CoreService(store)

    def fail_approve_proposal(*args, **kwargs):
        raise AssertionError("proposal store should not be queried")

    monkeypatch.setattr(store, "approve_proposal", fail_approve_proposal)

    with pytest.raises(ValueError, match="unsupported approval decision"):
        service.approve_proposal(999, "risk_officer", "hold")
    with pytest.raises(ValueError, match="unsupported approval decision"):
        call_local_tool(
            "approve_proposal",
            {"proposal_id": 999, "approver_id": "risk_officer", "decision": "hold"},
            root=str(tmp_path),
        )


def test_approve_proposal_rejects_pending_proposal(tmp_path):
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

    with pytest.raises(GateStateError):
        call_local_tool(
            "approve_proposal",
            {"proposal_id": proposal_id, "approver_id": "risk_officer", "decision": "promote"},
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


def test_local_proposal_submission_requires_object_payload_and_valid_confidence(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="proposal payload must be an object"):
        call_local_tool(
            "submit_proposal",
            {
                "kind": "edge",
                "payload": "parent_id=banking",
                "source": "test",
                "confidence": 0.8,
            },
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="proposal confidence must be finite"):
        call_local_tool(
            "submit_proposal",
            {
                "kind": "edge",
                "payload": {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
                "source": "test",
                "confidence": "nan",
            },
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="proposal confidence must be between 0 and 1"):
        call_local_tool(
            "submit_proposal",
            {
                "kind": "edge",
                "payload": {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
                "source": "test",
                "confidence": 1.5,
            },
            root=str(tmp_path),
        )


def test_local_proposal_submission_requires_source_before_store_call(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    service = CoreService(store)

    def fail_submit_proposal(*args, **kwargs):
        raise AssertionError("proposal should not be stored")

    monkeypatch.setattr(store, "submit_proposal", fail_submit_proposal)

    with pytest.raises(ValueError, match="source is required"):
        service.submit_proposal(
            "edge",
            {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
            " ",
            0.8,
        )

    with pytest.raises(ValueError, match="source is required"):
        call_local_tool(
            "submit_proposal",
            {
                "kind": "edge",
                "payload": {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
                "source": "",
                "confidence": 0.8,
            },
            root=str(tmp_path),
        )


def test_local_proposal_submission_requires_kind_before_store_call(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    service = CoreService(store)

    def fail_submit_proposal(*args, **kwargs):
        raise AssertionError("proposal should not be stored")

    monkeypatch.setattr(store, "submit_proposal", fail_submit_proposal)

    with pytest.raises(ValueError, match="kind is required"):
        service.submit_proposal(
            " ",
            {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
            "test",
            0.8,
        )

    with pytest.raises(ValueError, match="kind is required"):
        call_local_tool(
            "submit_proposal",
            {
                "kind": "",
                "payload": {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
                "source": "test",
                "confidence": 0.8,
            },
            root=str(tmp_path),
        )


def test_local_proposal_submission_rejects_invalid_snapshot_id_before_store_call(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    service = CoreService(store)

    def fail_submit_proposal(*args, **kwargs):
        raise AssertionError("proposal should not be stored")

    monkeypatch.setattr(store, "submit_proposal", fail_submit_proposal)

    with pytest.raises(ValueError, match="snapshot_id must be a positive integer"):
        service.submit_proposal(
            "edge",
            {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
            "test",
            0.8,
            snapshot_id=0,
        )

    with pytest.raises(ValueError, match="snapshot_id must be a positive integer"):
        call_local_tool(
            "submit_proposal",
            {
                "kind": "edge",
                "payload": {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
                "source": "test",
                "confidence": 0.8,
                "snapshot_id": "not-an-id",
            },
            root=str(tmp_path),
        )


def test_local_universe_graph_service_and_mcp_tool_flow(tmp_path):
    store = seed_store(tmp_path)
    service = CoreService(store)

    parent = service.create_universe_node("concept.ai", "AI", "concept", "data_steward", date(2026, 1, 1))
    child = call_local_tool(
        "create_universe_node",
        {
            "node_id": "stock.000001",
            "label": "Ping An",
            "level": "stock",
            "created_by": "data_steward",
            "as_of_date": "2026-01-01",
        },
        root=str(tmp_path),
    )
    edge = call_local_tool(
        "create_universe_edge",
        {
            "parent_id": "concept.ai",
            "child_id": "stock.000001",
            "relation_type": "contains",
            "created_by": "data_steward",
            "as_of_date": "2026-01-02",
        },
        root=str(tmp_path),
    )
    call_local_tool(
        "verify_universe_edge",
        {"edge_id": edge["edge_id"], "verified_by": "factor_researcher", "as_of_date": "2026-01-03"},
        root=str(tmp_path),
    )

    children = call_local_tool(
        "get_universe_children",
        {"parent_id": "concept.ai", "as_of_date": "2026-01-04"},
        root=str(tmp_path),
    )

    assert parent["node_id"] == "concept.ai"
    assert child["created_by"] == "data_steward"
    assert edge["verified"] is False
    assert children == ["stock.000001"]


def test_local_universe_edge_audit_identity_is_required(tmp_path):
    store = seed_store(tmp_path)
    service = CoreService(store)
    service.create_universe_node("concept.ai", "AI", "concept", "data_steward", date(2026, 1, 1))
    service.create_universe_node("stock.000001", "Ping An", "stock", "data_steward", date(2026, 1, 1))
    edge = service.create_universe_edge(
        "concept.ai",
        "stock.000001",
        "contains",
        "data_steward",
        date(2026, 1, 2),
    )

    with pytest.raises(ValueError, match="verified_by is required"):
        call_local_tool(
            "verify_universe_edge",
            {"edge_id": edge["edge_id"], "verified_by": " ", "as_of_date": "2026-01-03"},
            root=str(tmp_path),
        )
    with pytest.raises(ValueError, match="retired_by is required"):
        call_local_tool(
            "retire_universe_edge",
            {"edge_id": edge["edge_id"], "retired_by": "", "as_of_date": "2026-01-04"},
            root=str(tmp_path),
        )


def test_local_universe_edge_tools_reject_invalid_integer_ids(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="edge_id must be an integer"):
        call_local_tool(
            "verify_universe_edge",
            {"edge_id": "edge-1", "verified_by": "factor_researcher", "as_of_date": "2026-01-03"},
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="edge_id must be an integer"):
        call_local_tool(
            "retire_universe_edge",
            {"edge_id": "1.5", "retired_by": "risk_officer", "as_of_date": "2026-01-04"},
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="edge_id must be a positive integer"):
        call_local_tool(
            "verify_universe_edge",
            {"edge_id": -1, "verified_by": "factor_researcher", "as_of_date": "2026-01-03"},
            root=str(tmp_path),
        )


def test_local_store_save_universe_edge_rejects_non_positive_explicit_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe storage should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="edge_id must be a positive integer"):
        store.save_universe_edge(
            {
                "edge_id": 0,
                "parent_id": "concept.ai",
                "child_id": "stock.000001",
                "relation_type": "contains",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 2),
            }
        )


def test_local_store_save_universe_edge_rejects_empty_parent_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe storage should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="parent_id is required"):
        store.save_universe_edge(
            {
                "parent_id": " ",
                "child_id": "stock.000001",
                "relation_type": "contains",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 2),
            }
        )


def test_local_store_save_universe_edge_rejects_empty_child_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe storage should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="child_id is required"):
        store.save_universe_edge(
            {
                "parent_id": "concept.ai",
                "child_id": " ",
                "relation_type": "contains",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 2),
            }
        )


def test_local_store_save_universe_edge_rejects_empty_relation_type_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe storage should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="relation_type is required"):
        store.save_universe_edge(
            {
                "parent_id": "concept.ai",
                "child_id": "stock.000001",
                "relation_type": " ",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 2),
            }
        )


def test_local_store_save_universe_edge_rejects_empty_created_by_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe storage should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="created_by is required"):
        store.save_universe_edge(
            {
                "parent_id": "concept.ai",
                "child_id": "stock.000001",
                "relation_type": "contains",
                "created_by": " ",
                "as_of_date": date(2026, 1, 2),
            }
        )


def test_local_store_verify_universe_edge_rejects_non_positive_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.universe_edges_path.write_text(
        "edge_id,parent_id,child_id,relation_type,created_by,verified\n1,p,c,contains,test,false\n",
        encoding="utf-8",
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe edges should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="edge_id must be a positive integer"):
        store.verify_universe_edge(0, "factor_researcher", date(2026, 1, 3))


def test_local_store_verify_universe_edge_rejects_empty_verified_by_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.universe_edges_path.write_text(
        "edge_id,parent_id,child_id,relation_type,created_by,verified\n1,p,c,contains,test,false\n",
        encoding="utf-8",
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe edges should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="verified_by is required"):
        store.verify_universe_edge(1, " ", date(2026, 1, 3))


def test_local_store_retire_universe_edge_rejects_non_positive_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.universe_edges_path.write_text(
        "edge_id,parent_id,child_id,relation_type,created_by,verified\n1,p,c,contains,test,false\n",
        encoding="utf-8",
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe edges should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="edge_id must be a positive integer"):
        store.retire_universe_edge(0, "risk_officer", date(2026, 1, 4))


def test_local_store_retire_universe_edge_rejects_empty_retired_by_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.universe_edges_path.write_text(
        "edge_id,parent_id,child_id,relation_type,created_by,verified\n1,p,c,contains,test,false\n",
        encoding="utf-8",
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe edges should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="retired_by is required"):
        store.retire_universe_edge(1, "", date(2026, 1, 4))


def test_local_universe_graph_rejects_non_string_identity_fields(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="node_id must be a string"):
        call_local_tool(
            "create_universe_node",
            {
                "node_id": 123,
                "label": "AI",
                "level": "concept",
                "created_by": "data_steward",
                "as_of_date": "2026-01-01",
            },
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="relation_type must be a string"):
        call_local_tool(
            "create_universe_edge",
            {
                "parent_id": "concept.ai",
                "child_id": "stock.000001",
                "relation_type": ["contains"],
                "created_by": "data_steward",
                "as_of_date": "2026-01-02",
            },
            root=str(tmp_path),
        )


def test_local_store_save_universe_node_rejects_empty_node_id_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.universe_nodes_path.write_text(
        "node_id,label,level,created_by,as_of_date,status\nconcept.ai,AI,concept,data_steward,2026-01-01,active\n",
        encoding="utf-8",
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe nodes should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="node_id is required"):
        store.save_universe_node(
            {
                "node_id": " ",
                "label": "AI",
                "level": "concept",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 1),
            }
        )


def test_local_store_save_universe_node_rejects_empty_label_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.universe_nodes_path.write_text(
        "node_id,label,level,created_by,as_of_date,status\nconcept.ai,AI,concept,data_steward,2026-01-01,active\n",
        encoding="utf-8",
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe nodes should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="label is required"):
        store.save_universe_node(
            {
                "node_id": "concept.empty",
                "label": " ",
                "level": "concept",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 1),
            }
        )


def test_local_store_save_universe_node_rejects_empty_level_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.universe_nodes_path.write_text(
        "node_id,label,level,created_by,as_of_date,status\nconcept.ai,AI,concept,data_steward,2026-01-01,active\n",
        encoding="utf-8",
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe nodes should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="level is required"):
        store.save_universe_node(
            {
                "node_id": "concept.empty",
                "label": "Empty",
                "level": " ",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 1),
            }
        )


def test_local_store_save_universe_node_rejects_empty_created_by_before_loading(tmp_path, monkeypatch):
    store = seed_store(tmp_path)
    store.universe_nodes_path.write_text(
        "node_id,label,level,created_by,as_of_date,status\nconcept.ai,AI,concept,data_steward,2026-01-01,active\n",
        encoding="utf-8",
    )

    def fail_read_csv(*args, **kwargs):
        raise AssertionError("universe nodes should not be loaded")

    monkeypatch.setattr(pd, "read_csv", fail_read_csv)

    with pytest.raises(ValueError, match="created_by is required"):
        store.save_universe_node(
            {
                "node_id": "concept.empty",
                "label": "Empty",
                "level": "concept",
                "created_by": " ",
                "as_of_date": date(2026, 1, 1),
            }
        )


def test_local_universe_nodes_reject_synonym_duplicate_labels(tmp_path):
    store = seed_store(tmp_path)
    service = CoreService(store)
    service.create_universe_node("concept.ai", "AI 概念", "concept", "data_steward", date(2026, 1, 1))

    with pytest.raises(ValueError, match="synonym duplicate node label"):
        call_local_tool(
            "create_universe_node",
            {
                "node_id": "concept.ai_duplicate",
                "label": "ai-概念",
                "level": "concept",
                "created_by": "data_steward",
                "as_of_date": "2026-01-02",
            },
            root=str(tmp_path),
        )


def test_local_semantic_node_search_is_asof_scoped_and_read_only(tmp_path):
    store = seed_store(tmp_path)
    service = CoreService(store)
    service.create_universe_node("concept.ai", "AI 概念", "concept", "data_steward", date(2026, 1, 1))
    service.create_universe_node("concept.robotics", "机器人", "concept", "data_steward", date(2026, 2, 1))

    rows = call_local_tool(
        "search_semantic_nodes",
        {"query": "AI", "as_of_date": "2026-01-15"},
        root=str(tmp_path),
    )

    assert rows == [
        {
            "node_id": "concept.ai",
            "label": "AI 概念",
            "level": "concept",
            "as_of_date": "2026-01-01",
            "status": "active",
            "score": 1.0,
        }
    ]


def test_local_semantic_node_search_rejects_invalid_query_embedding(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="query must not be empty"):
        call_local_tool(
            "search_semantic_nodes",
            {"query": " ", "as_of_date": "2026-01-15"},
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="query_embedding must be a list of finite numbers"):
        call_local_tool(
            "search_semantic_nodes",
            {"query": "AI", "as_of_date": "2026-01-15", "query_embedding": "0.1,0.2"},
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="query_embedding must be a list of finite numbers"):
        call_local_tool(
            "search_semantic_nodes",
            {"query": "AI", "as_of_date": "2026-01-15", "query_embedding": [0.1, float("nan")]},
            root=str(tmp_path),
        )


def test_local_universe_edges_reject_generic_parent_nodes(tmp_path):
    store = seed_store(tmp_path)
    service = CoreService(store)
    service.create_universe_node("concept.generic", "概念", "generic", "data_steward", date(2026, 1, 1))
    service.create_universe_node("stock.000001", "Ping An", "stock", "data_steward", date(2026, 1, 1))

    with pytest.raises(ValueError, match="parent node is too generic"):
        call_local_tool(
            "create_universe_edge",
            {
                "parent_id": "concept.generic",
                "child_id": "stock.000001",
                "relation_type": "contains",
                "created_by": "data_steward",
                "as_of_date": "2026-01-02",
            },
            root=str(tmp_path),
        )


def test_local_service_and_mcp_scan_intraday_events(tmp_path):
    store = seed_store(tmp_path)
    service = CoreService(store)
    events = [
        {
            "event_id": "m1",
            "event_type": "market",
            "symbol": "000001",
            "close": 10.61,
            "pre_close": 10.0,
            "high_limit": 11.0,
            "tick_status": "TRADE",
        }
    ]

    direct_alerts = service.scan_intraday_events(events)
    mcp_alerts = call_local_tool("scan_intraday_events", {"events": events}, root=str(tmp_path))

    assert direct_alerts == mcp_alerts
    assert mcp_alerts[0]["rule_id"] == "sudden_spike"
    assert mcp_alerts[0]["action"] == "risk_officer.flag_spike"


def test_local_service_and_mcp_scan_strategy_risks(tmp_path):
    service = CoreService(LocalStore(tmp_path))

    drawdown_report = service.scan_drawdown_risk(
        [
            {"date": "2026-01-01", "nav": "100"},
            {"date": "2026-01-02", "nav": "94"},
        ],
        warn_threshold="0.05",
        red_threshold="0.10",
    )
    portfolio_report = service.scan_portfolio_risk(
        cash="0",
        positions={"000001": 80, "000002": 20},
        prices={"000001": "10", "000002": "10"},
        max_gross_exposure="0.80",
        max_single_position_weight="0.50",
    )
    mcp_drawdown = call_local_tool(
        "scan_drawdown_risk",
        {
            "nav": [
                {"date": "2026-01-01", "nav": "100"},
                {"date": "2026-01-02", "nav": "88"},
            ],
            "warn_threshold": "0.05",
            "red_threshold": "0.10",
        },
        root=str(tmp_path),
    )
    mcp_portfolio = call_local_tool(
        "scan_portfolio_risk",
        {
            "cash": "500",
            "positions": {"000001": 50},
            "prices": {"000001": "10"},
            "max_gross_exposure": "0.80",
            "max_single_position_weight": "0.60",
        },
        root=str(tmp_path),
    )

    assert drawdown_report["status"] == "warn"
    assert drawdown_report["alerts"][0]["action"] == "risk_officer.review_drawdown"
    assert portfolio_report["status"] == "red"
    assert [alert["action"] for alert in portfolio_report["alerts"]] == [
        "risk_officer.reduce_exposure",
        "risk_officer.review_concentration",
    ]
    assert mcp_drawdown["status"] == "red"
    assert mcp_drawdown["alerts"][0]["date"] == "2026-01-02"
    assert mcp_portfolio["status"] == "ok"


def test_local_service_rejects_invalid_strategy_risk_inputs(tmp_path):
    service = CoreService(LocalStore(tmp_path))

    with pytest.raises(ValueError, match="nav row requires date"):
        service.scan_drawdown_risk([{"nav": "100"}])

    with pytest.raises(ValueError, match="prices missing symbols: \\['000001'\\]"):
        service.scan_portfolio_risk(
            cash="1000",
            positions={"000001": 10},
            prices={},
        )


def test_strategy_risk_inputs_require_expected_container_shapes(tmp_path):
    service = CoreService(LocalStore(tmp_path))

    with pytest.raises(ValueError, match="nav must be a list of objects"):
        service.scan_drawdown_risk({"date": "2026-01-01", "nav": "100"})

    with pytest.raises(ValueError, match="nav row value must be positive"):
        service.scan_drawdown_risk([{"date": "2026-01-01", "nav": "0"}])

    with pytest.raises(ValueError, match="nav row dates must be strictly increasing"):
        service.scan_drawdown_risk(
            [
                {"date": "2026-01-02", "nav": "100"},
                {"date": "2026-01-01", "nav": "99"},
            ]
        )

    with pytest.raises(ValueError, match="positions must be an object"):
        service.scan_portfolio_risk(cash="0", positions="000001", prices={"000001": "10"})

    with pytest.raises(ValueError, match="prices must be an object"):
        service.scan_portfolio_risk(cash="0", positions={"000001": 1}, prices=["000001"])


def test_strategy_risk_thresholds_must_be_finite_and_non_negative(tmp_path):
    service = CoreService(LocalStore(tmp_path))

    with pytest.raises(ValueError, match="warn_threshold must be non-negative"):
        service.scan_drawdown_risk(
            [{"date": "2026-01-01", "nav": "100"}],
            warn_threshold="-0.01",
        )

    with pytest.raises(ValueError, match="red_threshold must be finite"):
        service.scan_drawdown_risk(
            [{"date": "2026-01-01", "nav": "100"}],
            red_threshold="inf",
        )

    with pytest.raises(ValueError, match="max_gross_exposure must be non-negative"):
        service.scan_portfolio_risk(
            cash="0",
            positions={"000001": 1},
            prices={"000001": "10"},
            max_gross_exposure="-0.1",
        )


def test_local_mcp_strategy_risk_inputs_require_expected_container_shapes(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="nav must be a list of objects"):
        call_local_tool(
            "scan_drawdown_risk",
            {"nav": {"date": "2026-01-01", "nav": "100"}},
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="nav row value must be positive"):
        call_local_tool(
            "scan_drawdown_risk",
            {"nav": [{"date": "2026-01-01", "nav": "-1"}]},
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="nav row dates must be strictly increasing"):
        call_local_tool(
            "scan_drawdown_risk",
            {
                "nav": [
                    {"date": "2026-01-01", "nav": "100"},
                    {"date": "2026-01-01", "nav": "101"},
                ]
            },
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="positions must be an object"):
        call_local_tool(
            "scan_portfolio_risk",
            {"cash": "0", "positions": "000001", "prices": {"000001": "10"}},
            root=str(tmp_path),
        )


def test_local_mcp_strategy_risk_thresholds_must_be_finite_and_non_negative(tmp_path):
    seed_store(tmp_path)

    with pytest.raises(ValueError, match="warn_threshold must be non-negative"):
        call_local_tool(
            "scan_drawdown_risk",
            {"nav": [{"date": "2026-01-01", "nav": "100"}], "warn_threshold": "-0.01"},
            root=str(tmp_path),
        )

    with pytest.raises(ValueError, match="max_single_position_weight must be finite"):
        call_local_tool(
            "scan_portfolio_risk",
            {
                "cash": "0",
                "positions": {"000001": 1},
                "prices": {"000001": "10"},
                "max_single_position_weight": "nan",
            },
            root=str(tmp_path),
        )
