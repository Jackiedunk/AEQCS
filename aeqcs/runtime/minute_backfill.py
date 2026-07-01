"""Checkpointed baostock minute-bar backfill worker."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import asyncpg
import pandas as pd

from aeqcs.core.exceptions import RateLimitExceeded
from aeqcs.core.versioning import require_non_empty_text


class MinuteAdapter(Protocol):
    def minute(self, symbol: str, start: date, end: date, *, frequency: str = "5") -> pd.DataFrame:
        ...


class MinuteWriter(Protocol):
    def write(self, frame: pd.DataFrame) -> int:
        ...


@dataclass(frozen=True)
class MinuteBackfillResult:
    status: str
    source: str
    checkpoint_path: str
    symbols_total: int
    symbols_completed: int
    requests_used: int
    rows_written: int


def _load_checkpoint(path: Path, *, source: str, today: date) -> dict[str, Any]:
    if not path.exists():
        return {
            "source": source,
            "quota_day": today.isoformat(),
            "used_today": 0,
            "completed_symbols": [],
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("quota_day") != today.isoformat():
        payload["quota_day"] = today.isoformat()
        payload["used_today"] = 0
    payload.setdefault("source", source)
    payload.setdefault("completed_symbols", [])
    payload.setdefault("used_today", 0)
    return payload


def _save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_minute_backfill_resume(
    *,
    adapter: MinuteAdapter,
    writer: MinuteWriter,
    symbols: tuple[str, ...],
    start: date,
    end: date,
    checkpoint_path: str | Path,
    daily_quota: int,
    today: date | None = None,
    source: str = "baostock",
    frequency: str = "5",
) -> MinuteBackfillResult:
    if not symbols:
        raise ValueError("symbols is required")
    if start > end:
        raise ValueError("start must be on or before end")
    if daily_quota < 1:
        raise ValueError("daily_quota must be positive")
    checked_symbols = tuple(require_non_empty_text(symbol, "symbol") for symbol in symbols)
    run_day = today or date.today()
    path = Path(checkpoint_path)
    checkpoint = _load_checkpoint(path, source=source, today=run_day)
    completed = set(str(symbol) for symbol in checkpoint.get("completed_symbols", []))
    used_today = int(checkpoint.get("used_today", 0))
    requests_used = 0
    rows_written = 0

    for symbol in checked_symbols:
        if symbol in completed:
            continue
        if used_today >= daily_quota:
            _save_checkpoint(path, checkpoint)
            return MinuteBackfillResult(
                status="daily_quota_reached",
                source=source,
                checkpoint_path=str(path),
                symbols_total=len(checked_symbols),
                symbols_completed=len(completed),
                requests_used=requests_used,
                rows_written=rows_written,
            )
        try:
            frame = adapter.minute(symbol, start, end, frequency=frequency)
        except RateLimitExceeded:
            _save_checkpoint(path, checkpoint)
            return MinuteBackfillResult(
                status="daily_quota_reached",
                source=source,
                checkpoint_path=str(path),
                symbols_total=len(checked_symbols),
                symbols_completed=len(completed),
                requests_used=requests_used,
                rows_written=rows_written,
            )
        used_today += 1
        requests_used += 1
        rows_written += writer.write(frame)
        completed.add(symbol)
        checkpoint["quota_day"] = run_day.isoformat()
        checkpoint["used_today"] = used_today
        checkpoint["completed_symbols"] = sorted(completed)
        _save_checkpoint(path, checkpoint)

    return MinuteBackfillResult(
        status="completed",
        source=source,
        checkpoint_path=str(path),
        symbols_total=len(checked_symbols),
        symbols_completed=len(completed),
        requests_used=requests_used,
        rows_written=rows_written,
    )


def _minute_records(frame: pd.DataFrame) -> list[tuple[Any, ...]]:
    if frame.empty:
        return []
    required = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"minute frame missing columns: {sorted(missing)}")
    records: list[tuple[Any, ...]] = []
    for row in frame.to_dict("records"):
        timestamp = pd.Timestamp(row["timestamp"]).to_pydatetime()
        records.append(
            (
                str(row["symbol"]),
                timestamp,
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                int(row["volume"]),
                None,
                None,
                None,
                None,
                None,
            )
        )
    return records


class PgMinuteBarWriter:
    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("dsn is required")
        self.dsn = dsn

    def write(self, frame: pd.DataFrame) -> int:
        return asyncio.run(self.write_async(frame))

    async def write_async(self, frame: pd.DataFrame) -> int:
        records = _minute_records(frame)
        if not records:
            return 0
        conn = await asyncpg.connect(self.dsn)
        try:
            await conn.executemany(
                """
                INSERT INTO minute_bar_hot (
                  symbol, ts, open, high, low, close, volume,
                  pre_close, high_limit, low_limit, bid_volume, is_one_word_limit
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (symbol, ts) DO UPDATE SET
                  open=EXCLUDED.open,
                  high=EXCLUDED.high,
                  low=EXCLUDED.low,
                  close=EXCLUDED.close,
                  volume=EXCLUDED.volume,
                  pre_close=EXCLUDED.pre_close,
                  high_limit=EXCLUDED.high_limit,
                  low_limit=EXCLUDED.low_limit,
                  bid_volume=EXCLUDED.bid_volume,
                  is_one_word_limit=EXCLUDED.is_one_word_limit
                """,
                records,
            )
        finally:
            await conn.close()
        return len(records)


def result_to_dict(result: MinuteBackfillResult) -> dict[str, Any]:
    return asdict(result)
