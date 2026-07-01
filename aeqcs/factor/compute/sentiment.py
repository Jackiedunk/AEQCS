"""Sentiment factor helpers."""

from __future__ import annotations

import pandas as pd


def daily_news_sentiment(news: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "entities", "sentiment"}
    missing = required - set(news.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    rows = []
    for record in news.to_dict("records"):
        for symbol in record.get("entities") or []:
            rows.append(
                {
                    "symbol": symbol,
                    "date": pd.to_datetime(record["timestamp"]).date(),
                    "sentiment": record["sentiment"],
                }
            )
    if not rows:
        return pd.DataFrame(columns=["symbol", "date", "news_sentiment_1d"])
    return (
        pd.DataFrame(rows)
        .groupby(["symbol", "date"], as_index=False)
        .agg(news_sentiment_1d=("sentiment", "mean"))
    )
