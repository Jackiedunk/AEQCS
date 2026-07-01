"""Corporate action normalization and as-of state helpers."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from aeqcs.core.versioning import require_date_value, require_datetime_value, require_non_empty_text


SUPPORTED_ACTION_TYPES = {"st_add", "st_remove", "name_change", "code_change"}


def normalize_corporate_actions(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "effective_date", "action_type", "old_value", "new_value", "knowledge_ts"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing corporate action columns: {sorted(missing)}")
    out = frame.copy()
    out["symbol"] = out["symbol"].map(lambda value: require_non_empty_text(value, "symbol"))
    out["effective_date"] = out["effective_date"].map(lambda value: require_date_value(value, "effective_date"))
    out["action_type"] = out["action_type"].map(lambda value: require_non_empty_text(value, "action_type"))
    unsupported = sorted(set(out["action_type"]) - SUPPORTED_ACTION_TYPES)
    if unsupported:
        raise ValueError(f"unsupported corporate action_type: {unsupported}")
    out["old_value"] = out["old_value"].map(lambda value: "" if value is None or pd.isna(value) else str(value))
    out["new_value"] = out["new_value"].map(lambda value: "" if value is None or pd.isna(value) else str(value))
    out["knowledge_ts"] = out["knowledge_ts"].map(lambda value: require_datetime_value(value, "knowledge_ts"))
    return out.sort_values(["symbol", "effective_date", "knowledge_ts"]).reset_index(drop=True)


def corporate_state_as_of(frame: pd.DataFrame, symbol: str, as_of_date: date) -> dict[str, Any]:
    checked_symbol = require_non_empty_text(symbol, "symbol")
    checked_as_of = require_date_value(as_of_date, "as_of_date")
    normalized = normalize_corporate_actions(frame)
    scoped = normalized[
        (normalized["symbol"] == checked_symbol)
        & (normalized["effective_date"] <= checked_as_of)
    ]
    state: dict[str, Any] = {
        "symbol": checked_symbol,
        "current_symbol": checked_symbol,
        "name": None,
        "is_st": False,
        "as_of_date": checked_as_of,
    }
    for row in scoped.to_dict("records"):
        action_type = row["action_type"]
        if action_type == "st_add":
            state["is_st"] = True
        elif action_type == "st_remove":
            state["is_st"] = False
        elif action_type == "name_change":
            state["name"] = row["new_value"]
        elif action_type == "code_change":
            state["current_symbol"] = row["new_value"]
    return state
