"""Trading calendar and timestamp helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")


def now_shanghai() -> datetime:
    return datetime.now(tz=SHANGHAI)


def to_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=SHANGHAI)
    return ts.astimezone(UTC)


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5


def prev_trading_day(day: date) -> date:
    current = day - timedelta(days=1)
    while not is_trading_day(current):
        current -= timedelta(days=1)
    return current


def next_trading_day(day: date) -> date:
    current = day + timedelta(days=1)
    while not is_trading_day(current):
        current += timedelta(days=1)
    return current


def trading_minutes(day: date) -> list[datetime]:
    minutes: list[datetime] = []
    for start, end in ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0))):
        cursor = datetime.combine(day, start, tzinfo=SHANGHAI)
        stop = datetime.combine(day, end, tzinfo=SHANGHAI)
        while cursor <= stop:
            minutes.append(cursor)
            cursor += timedelta(minutes=1)
    return minutes
