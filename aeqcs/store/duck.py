"""DuckDB session factory with memory-safe defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


def connect_duckdb(
    database: str = ":memory:",
    memory_limit: str = "4GB",
    threads: int = 6,
    temp_directory: str | Path = "/data/aeqcs/duckdb_tmp",
) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(database=database)
    conn.execute(f"SET memory_limit = '{memory_limit}'")
    conn.execute(f"SET threads = {int(threads)}")
    conn.execute(f"SET temp_directory = '{str(temp_directory)}'")
    return conn


def query_parquet(path_glob: str, sql: str, params: dict[str, Any] | None = None):
    conn = connect_duckdb()
    conn.execute("CREATE VIEW source AS SELECT * FROM read_parquet(?)", [path_glob])
    return conn.execute(sql, params or {}).fetch_df()
