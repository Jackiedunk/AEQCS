from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from aeqcs.runtime.minute_backfill import run_minute_backfill_resume


class FakeMinuteAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date, date, str]] = []

    def minute(self, symbol: str, start: date, end: date, *, frequency: str = "5") -> pd.DataFrame:
        self.calls.append((symbol, start, end, frequency))
        return pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "timestamp": datetime(2026, 6, 30, 9, 35),
                    "knowledge_ts": datetime(2026, 7, 1, 20, 0),
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1000,
                    "amount": 10100.0,
                }
            ]
        )


class FakeMinuteWriter:
    def __init__(self) -> None:
        self.frames: list[pd.DataFrame] = []

    def write(self, frame: pd.DataFrame) -> int:
        self.frames.append(frame.copy())
        return len(frame)


def test_minute_backfill_writes_checkpoint_and_skips_completed_symbol(tmp_path: Path):
    checkpoint = tmp_path / "minute_checkpoint.json"
    adapter = FakeMinuteAdapter()
    writer = FakeMinuteWriter()

    first = run_minute_backfill_resume(
        adapter=adapter,
        writer=writer,
        symbols=("sh.600000",),
        start=date(2026, 6, 30),
        end=date(2026, 6, 30),
        checkpoint_path=checkpoint,
        daily_quota=10,
        today=date(2026, 7, 1),
    )
    second = run_minute_backfill_resume(
        adapter=adapter,
        writer=writer,
        symbols=("sh.600000",),
        start=date(2026, 6, 30),
        end=date(2026, 6, 30),
        checkpoint_path=checkpoint,
        daily_quota=10,
        today=date(2026, 7, 1),
    )

    assert first.status == "completed"
    assert first.requests_used == 1
    assert first.rows_written == 1
    assert second.status == "completed"
    assert second.requests_used == 0
    assert len(adapter.calls) == 1
    assert len(writer.frames) == 1


def test_minute_backfill_stops_before_request_when_daily_quota_is_exhausted(tmp_path: Path):
    checkpoint = tmp_path / "minute_checkpoint.json"
    checkpoint.write_text(
        """
        {
          "source": "baostock",
          "quota_day": "2026-07-01",
          "used_today": 1,
          "completed_symbols": []
        }
        """,
        encoding="utf-8",
    )
    adapter = FakeMinuteAdapter()
    writer = FakeMinuteWriter()

    result = run_minute_backfill_resume(
        adapter=adapter,
        writer=writer,
        symbols=("sh.600000",),
        start=date(2026, 6, 30),
        end=date(2026, 6, 30),
        checkpoint_path=checkpoint,
        daily_quota=1,
        today=date(2026, 7, 1),
    )

    assert result.status == "daily_quota_reached"
    assert result.requests_used == 0
    assert result.rows_written == 0
    assert adapter.calls == []
    assert writer.frames == []


def test_minute_backfill_resets_completed_symbols_when_job_range_changes(tmp_path: Path):
    checkpoint = tmp_path / "minute_checkpoint.json"
    adapter = FakeMinuteAdapter()
    writer = FakeMinuteWriter()

    run_minute_backfill_resume(
        adapter=adapter,
        writer=writer,
        symbols=("sh.600000",),
        start=date(2026, 6, 1),
        end=date(2026, 6, 30),
        checkpoint_path=checkpoint,
        daily_quota=10,
        today=date(2026, 7, 1),
    )
    result = run_minute_backfill_resume(
        adapter=adapter,
        writer=writer,
        symbols=("sh.600000",),
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        checkpoint_path=checkpoint,
        daily_quota=10,
        today=date(2026, 7, 1),
    )

    assert result.status == "completed"
    assert result.requests_used == 1
    assert len(adapter.calls) == 2
    assert adapter.calls[-1][1:] == (date(2026, 7, 1), date(2026, 7, 31), "5")
