"""Import Tushare daily and financial data into a LocalStore.

Example:
    python scripts/import_tushare_local.py --symbol 000001.SZ --start 2026-01-01 --end 2026-01-31 --token %TUSHARE_TOKEN%
"""

from __future__ import annotations

import argparse
import os
from datetime import date

from aeqcs.data.adapters.tushare_adapter import TushareAdapter
from aeqcs.data.etl.importers import import_daily_to_local, import_financials_to_local
from aeqcs.store.local import LocalStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--root", default="data/local")
    parser.add_argument("--token", default=os.environ.get("TUSHARE_TOKEN"))
    parser.add_argument("--skip-financials", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    adapter = TushareAdapter(token=args.token)
    store = LocalStore(args.root)
    daily_count = import_daily_to_local(
        adapter,
        store,
        args.symbol,
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
    )
    financial_count = 0
    if not args.skip_financials:
        financial_count = import_financials_to_local(adapter, store, args.symbol)
    print({"daily_rows": daily_count, "financial_rows": financial_count, "root": args.root})


if __name__ == "__main__":
    main()
