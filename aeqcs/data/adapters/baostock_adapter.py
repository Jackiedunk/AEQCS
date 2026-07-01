"""Baostock market data adapter with canonical AEQCS outputs."""

from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Any, Callable, Protocol

import pandas as pd

from aeqcs.core.exceptions import ConfigurationError, DataSourceError
from aeqcs.core.versioning import require_non_empty_text
from aeqcs.data.etl.market_data import normalize_daily_frame
from aeqcs.data.rate_limiter import RateLimiter


class BaostockResult(Protocol):
    error_code: str
    error_msg: str

    def get_data(self) -> pd.DataFrame:
        ...


class BaostockClient(Protocol):
    def login(self) -> Any:
        ...

    def query_history_k_data_plus(
        self,
        code: str,
        fields: str,
        start_date: str,
        end_date: str,
        frequency: str,
        adjustflag: str,
    ) -> BaostockResult:
        ...


_BAOSTOCK_LOCK = threading.Lock()


def _fmt_day(day: date) -> str:
    return day.isoformat()


def _valid_symbol(symbol: str) -> str:
    return require_non_empty_text(symbol, "symbol")


def _assert_date_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start must be on or before end")


def _result_error_code(result: Any) -> str:
    return str(getattr(result, "error_code", "0"))


def _result_error_message(result: Any) -> str:
    return str(getattr(result, "error_msg", ""))


def _is_session_error(result: Any) -> bool:
    message = _result_error_message(result).lower()
    return _result_error_code(result) != "0" and (
        "login" in message or "session" in message or "timeout" in message
    )


def _assert_success(result: Any, source: str) -> None:
    if _result_error_code(result) != "0":
        raise DataSourceError(f"{source} failed: {_result_error_message(result)}")


def _frame_from_result(result: BaostockResult) -> pd.DataFrame:
    if all(hasattr(result, attr) for attr in ("fields", "next", "get_row_data")):
        rows = []
        while result.next():  # type: ignore[attr-defined]
            rows.append(result.get_row_data())  # type: ignore[attr-defined]
        return pd.DataFrame(rows, columns=result.fields)  # type: ignore[attr-defined]
    frame = result.get_data()
    if frame is None:
        return pd.DataFrame()
    return frame


def _parse_minute_timestamps(frame: pd.DataFrame) -> pd.Series:
    time_text = frame["time"].astype(str).str.strip()
    clock_text = time_text.where(~time_text.str.match(r"^\d{14,}$"), time_text.str.slice(8, 14))
    clock_text = clock_text.str.zfill(6).str.slice(0, 6)
    return pd.to_datetime(
        frame["date"].astype(str) + " " + clock_text,
        format="%Y-%m-%d %H%M%S",
    )


class BaostockAdapter:
    """Baostock adapter for raw market data only.

    Baostock is intentionally not a financial fundamentals provider in AEQCS.
    """

    def __init__(
        self,
        client: BaostockClient | None = None,
        rate_limiter: RateLimiter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self.rate_limiter = rate_limiter
        self._clock = clock or datetime.utcnow
        self._logged_in = False

    @property
    def client(self) -> BaostockClient:
        if self._client is not None:
            return self._client
        try:
            import baostock as bs  # type: ignore
        except ImportError as exc:
            raise ConfigurationError("install the data extra to use baostock") from exc
        self._client = bs
        return self._client

    def _login(self) -> None:
        result = self.client.login()
        _assert_success(result, "baostock login")
        self._logged_in = True

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self._login()

    def _query_history(
        self,
        *,
        symbol: str,
        start: date,
        end: date,
        fields: tuple[str, ...],
        frequency: str,
    ) -> pd.DataFrame:
        checked_symbol = _valid_symbol(symbol)
        _assert_date_range(start, end)
        if self.rate_limiter:
            self.rate_limiter.consume("baostock")
        with _BAOSTOCK_LOCK:
            self._ensure_login()
            result = self.client.query_history_k_data_plus(
                checked_symbol,
                ",".join(fields),
                start_date=_fmt_day(start),
                end_date=_fmt_day(end),
                frequency=frequency,
                adjustflag="3",
            )
            if _is_session_error(result):
                self._logged_in = False
                self._login()
                result = self.client.query_history_k_data_plus(
                    checked_symbol,
                    ",".join(fields),
                    start_date=_fmt_day(start),
                    end_date=_fmt_day(end),
                    frequency=frequency,
                    adjustflag="3",
                )
            _assert_success(result, "baostock query_history_k_data_plus")
            return _frame_from_result(result)

    def daily(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        fields = (
            "date",
            "code",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "pctChg",
            "peTTM",
        )
        raw = self._query_history(symbol=symbol, start=start, end=end, fields=fields, frequency="d")
        columns = [
            "symbol",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "timestamp",
            "knowledge_ts",
            "pct_chg",
            "pe_ttm",
        ]
        if raw.empty:
            return pd.DataFrame(columns=columns)
        frame = raw.rename(columns={"code": "symbol", "pctChg": "pct_chg", "peTTM": "pe_ttm"})
        missing = {"symbol", "date", "open", "high", "low", "close", "volume", "amount"} - set(frame.columns)
        if missing:
            raise DataSourceError(f"baostock daily missing columns: {sorted(missing)}")
        frame["timestamp"] = pd.to_datetime(frame["date"])
        frame["knowledge_ts"] = self._clock()
        for column in ("pct_chg", "pe_ttm"):
            if column not in frame.columns:
                frame[column] = None
            else:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        normalized = normalize_daily_frame(
            frame[["symbol", "date", "open", "high", "low", "close", "volume", "amount"]]
        )
        for column in ("timestamp", "knowledge_ts", "pct_chg", "pe_ttm"):
            normalized[column] = frame.reset_index(drop=True)[column]
        return normalized[columns]

    def minute(self, symbol: str, start: date, end: date, *, frequency: str = "1") -> pd.DataFrame:
        fields = ("date", "time", "code", "open", "high", "low", "close", "volume", "amount")
        raw = self._query_history(symbol=symbol, start=start, end=end, fields=fields, frequency=frequency)
        columns = ["symbol", "timestamp", "knowledge_ts", "open", "high", "low", "close", "volume", "amount"]
        if raw.empty:
            return pd.DataFrame(columns=columns)
        frame = raw.rename(columns={"code": "symbol"})
        missing = {"symbol", "date", "time", "open", "high", "low", "close", "volume", "amount"} - set(frame.columns)
        if missing:
            raise DataSourceError(f"baostock minute missing columns: {sorted(missing)}")
        frame["timestamp"] = _parse_minute_timestamps(frame)
        frame["knowledge_ts"] = self._clock()
        for column in ("open", "high", "low", "close", "amount", "volume"):
            frame[column] = pd.to_numeric(frame[column])
        frame["volume"] = frame["volume"].astype("int64")
        return frame[columns].sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    def estimate_minute_history_request_count(self, symbol: str, start: date, end: date) -> int:
        _valid_symbol(symbol)
        _assert_date_range(start, end)
        return 1
