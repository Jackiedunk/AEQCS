"""Market data normalization and persistence helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from aeqcs.data.models import DailyBar
from aeqcs.data.quality.validator import validate_daily_bar


REQUIRED_DAILY_COLUMNS = {"symbol", "date", "open", "high", "low", "close", "volume", "amount"}


def normalize_daily_frame(df: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_DAILY_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing daily columns: {sorted(missing)}")
    out = df.copy()
    out["symbol"] = out["symbol"].astype(str)
    out["date"] = pd.to_datetime(out["date"]).dt.date
    for col in ("open", "high", "low", "close", "amount"):
        out[col] = pd.to_numeric(out[col])
    out["volume"] = pd.to_numeric(out["volume"]).astype("int64")
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def validate_daily_frame(df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    for row in normalize_daily_frame(df).to_dict("records"):
        bar = DailyBar.from_mapping(row)
        errors.extend(f"{bar.symbol} {bar.date}: {err}" for err in validate_daily_bar(bar))
    return errors


def bars_to_frame(bars: Iterable[DailyBar]) -> pd.DataFrame:
    return pd.DataFrame([asdict(bar) for bar in bars])


def write_daily_parquet(df: pd.DataFrame, root: str | Path) -> None:
    normalized = normalize_daily_frame(df)
    normalized["year"] = pd.to_datetime(normalized["date"]).dt.year
    normalized.to_parquet(root, partition_cols=["year"], index=False)
