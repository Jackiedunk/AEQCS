"""Import external adapter outputs into stores."""

from __future__ import annotations

from datetime import date

import pandas as pd

from aeqcs.data.etl.financial_data import normalize_financial_frame
from aeqcs.data.etl.market_data import normalize_daily_frame, validate_daily_frame
from aeqcs.store.local import LocalStore


def import_daily_to_local(adapter, store: LocalStore, symbol: str, start: date, end: date) -> int:
    incoming = normalize_daily_frame(adapter.daily(symbol, start, end))
    errors = validate_daily_frame(incoming)
    if errors:
        raise ValueError("; ".join(errors))
    existing = store.load_daily()
    merged = pd.concat([existing, incoming], ignore_index=True)
    merged = merged.drop_duplicates(["symbol", "date"], keep="last")
    store.save_daily(merged)
    return len(incoming)


def import_financials_to_local(adapter, store: LocalStore, symbol: str) -> int:
    incoming = normalize_financial_frame(adapter.fina_indicator(symbol))
    existing = store.load_financials()
    merged = pd.concat([existing, incoming], ignore_index=True)
    merged = merged.drop_duplicates(["symbol", "period", "ann_date", "vintage"], keep="last")
    store.save_financials(merged)
    return len(incoming)
