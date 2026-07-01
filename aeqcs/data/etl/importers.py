"""Import external adapter outputs into stores."""

from __future__ import annotations

from datetime import date
from typing import Callable

import pandas as pd

from aeqcs.core.exceptions import DataSourceError
from aeqcs.core.versioning import require_non_empty_text
from aeqcs.data.etl.financial_data import normalize_financial_frame
from aeqcs.data.etl.market_data import normalize_daily_frame, validate_daily_frame
from aeqcs.store.local import LocalStore


def _append_to_existing(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing.empty:
        return incoming.copy()
    if incoming.empty:
        return existing.copy()
    return pd.concat([existing, incoming], ignore_index=True)


def _assert_date_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start must be on or before end")


def _normalize_adapter_output(
    frame: pd.DataFrame,
    source: str,
    normalize_fn: Callable[[pd.DataFrame], pd.DataFrame],
) -> pd.DataFrame:
    try:
        return normalize_fn(frame)
    except ValueError as exc:
        raise DataSourceError(f"{source} invalid row: {exc}") from exc


def import_daily_to_local(adapter, store: LocalStore, symbol: str, start: date, end: date) -> int:
    checked_symbol = require_non_empty_text(symbol, "symbol")
    _assert_date_range(start, end)
    incoming = _normalize_adapter_output(
        adapter.daily(checked_symbol, start, end),
        "daily import",
        normalize_daily_frame,
    )
    errors = validate_daily_frame(incoming)
    if errors:
        raise DataSourceError(f"daily import invalid bar: {'; '.join(errors)}")
    existing = store.load_daily()
    merged = _append_to_existing(existing, incoming)
    merged = merged.drop_duplicates(["symbol", "date"], keep="last")
    store.save_daily(merged)
    return len(incoming)


def import_financials_to_local(adapter, store: LocalStore, symbol: str) -> int:
    checked_symbol = require_non_empty_text(symbol, "symbol")
    incoming = _normalize_adapter_output(
        adapter.fina_indicator(checked_symbol),
        "financial import",
        normalize_financial_frame,
    )
    existing = store.load_financials()
    incoming = assign_financial_vintages(existing, incoming)
    merged = _append_to_existing(existing, incoming)
    merged = merged.drop_duplicates(["symbol", "period", "ann_date", "vintage"], keep="last")
    store.save_financials(merged)
    return len(incoming)


def assign_financial_vintages(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    normalized_incoming = normalize_financial_frame(incoming)
    if normalized_incoming.empty:
        return normalized_incoming
    normalized_existing = normalize_financial_frame(existing) if not existing.empty else existing
    working_existing = normalized_existing.copy()
    assigned_rows = []
    for row in normalized_incoming.to_dict("records"):
        row_group = _financial_period_group(working_existing, str(row["symbol"]), str(row["period"]))
        matching_vintage = _matching_financial_vintage(row_group, row)
        if matching_vintage is not None:
            row["vintage"] = matching_vintage
        elif row_group.empty:
            row["vintage"] = 0
        else:
            row["vintage"] = int(row_group["vintage"].max()) + 1
        assigned_rows.append(row)
        new_existing_row = pd.DataFrame([row])
        if working_existing.empty:
            working_existing = normalize_financial_frame(new_existing_row)
            continue
        working_existing = normalize_financial_frame(
            pd.concat([working_existing, new_existing_row], ignore_index=True)
        )
    return normalize_financial_frame(pd.DataFrame(assigned_rows))


def _financial_period_group(existing: pd.DataFrame, symbol: str, period: str) -> pd.DataFrame:
    if existing.empty:
        return existing
    return existing[(existing["symbol"] == symbol) & (existing["period"] == period)]


def _matching_financial_vintage(existing_group: pd.DataFrame, incoming_row: dict) -> int | None:
    if existing_group.empty:
        return None
    comparable_columns = [column for column in existing_group.columns if column != "vintage"]
    for existing_row in existing_group.to_dict("records"):
        if all(_financial_values_equal(existing_row.get(column), incoming_row.get(column)) for column in comparable_columns):
            return int(existing_row["vintage"])
    return None


def _financial_values_equal(left, right) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    return left == right
