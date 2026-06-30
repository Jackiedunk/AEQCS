"""Create a tiny local sample dataset for smoke tests and demos."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from aeqcs.data.etl.market_data import write_daily_parquet


def main() -> None:
    root = Path("data/parquet/daily")
    root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {"symbol": "000001", "date": "2026-01-01", "open": 10, "high": 10.5, "low": 9.8, "close": 10, "volume": 1000, "amount": 10000},
            {"symbol": "000001", "date": "2026-01-02", "open": 11, "high": 12.2, "low": 10.8, "close": 12, "volume": 1200, "amount": 13200},
            {"symbol": "000001", "date": "2026-01-05", "open": 12, "high": 12.3, "low": 11.5, "close": 11.8, "volume": 900, "amount": 10800},
        ]
    )
    write_daily_parquet(frame, root)
    print(f"wrote sample data to {root}")


if __name__ == "__main__":
    main()
