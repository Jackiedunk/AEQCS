"""Akshare adapter with lazy imports and normalized outputs."""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from aeqcs.core.exceptions import ConfigurationError, DataSourceError
from aeqcs.data.rate_limiter import RateLimiter


class AkshareClient(Protocol):
    def stock_board_concept_cons_ths(self, symbol: str) -> pd.DataFrame:
        ...

    def stock_news_em(self, symbol: str) -> pd.DataFrame:
        ...


class _AkshareModuleClient:
    def __init__(self) -> None:
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:
            raise ConfigurationError("install the data extra to use Akshare") from exc
        self.ak = ak

    def stock_board_concept_cons_ths(self, symbol: str) -> pd.DataFrame:
        return self.ak.stock_board_concept_cons_ths(symbol=symbol)

    def stock_news_em(self, symbol: str) -> pd.DataFrame:
        return self.ak.stock_news_em(symbol=symbol)


class AkshareAdapter:
    def __init__(
        self,
        client: AkshareClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._client = client
        self.rate_limiter = rate_limiter

    @property
    def client(self) -> AkshareClient:
        if self._client is None:
            self._client = _AkshareModuleClient()
        return self._client

    def concept_constituents(self, concept: str) -> pd.DataFrame:
        if self.rate_limiter:
            self.rate_limiter.consume("akshare")
        raw = self.client.stock_board_concept_cons_ths(symbol=concept)
        if raw is None or raw.empty:
            return pd.DataFrame(columns=["concept", "symbol", "name"])
        column_map = {
            "代码": "symbol",
            "名称": "name",
            "code": "symbol",
            "name": "name",
        }
        frame = raw.rename(columns=column_map)
        missing = {"symbol", "name"} - set(frame.columns)
        if missing:
            raise DataSourceError(f"Akshare concept constituents missing columns: {sorted(missing)}")
        out = frame[["symbol", "name"]].copy()
        out["symbol"] = out["symbol"].astype(str).str.zfill(6)
        out.insert(0, "concept", concept)
        return out

    def stock_news(self, symbol: str) -> pd.DataFrame:
        if self.rate_limiter:
            self.rate_limiter.consume("akshare")
        raw = self.client.stock_news_em(symbol=symbol)
        if raw is None or raw.empty:
            return pd.DataFrame(columns=["timestamp", "source", "title", "content", "entities"])
        column_map = {"发布时间": "timestamp", "文章来源": "source", "新闻标题": "title", "新闻内容": "content"}
        frame = raw.rename(columns=column_map)
        missing = {"timestamp", "title"} - set(frame.columns)
        if missing:
            raise DataSourceError(f"Akshare stock news missing columns: {sorted(missing)}")
        out = frame.copy()
        if "source" not in out.columns:
            out["source"] = "akshare"
        if "content" not in out.columns:
            out["content"] = ""
        out["entities"] = [[symbol] for _ in range(len(out))]
        return out[["timestamp", "source", "title", "content", "entities"]]
