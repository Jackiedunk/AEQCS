"""Partitioned Parquet IO helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_partitioned(df: pd.DataFrame, root: str | Path, partition_cols: list[str]) -> None:
    df.to_parquet(root, partition_cols=partition_cols, engine="pyarrow", index=False)


def read_parquet(path: str | Path, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(path, columns=columns, engine="pyarrow")
