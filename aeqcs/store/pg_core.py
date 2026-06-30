"""PostgreSQL-backed implementation of the core store protocol."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from typing import Any

import pandas as pd

from aeqcs.core.versioning import assert_not_after, require_as_of
from aeqcs.gate.proposals import ProposalReview
from aeqcs.gate.validator import assert_transition
from aeqcs.store.protocols import AsyncCoreStore
from aeqcs.strategy.backtest.engine import BacktestReport


class PgCoreStore(AsyncCoreStore):
    """CoreStore implementation backed by asyncpg connection pools."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def _fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]

    async def _fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
        return dict(row) if row else {}

    async def _fetchval(self, query: str, *args: Any) -> Any:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def load_daily(self) -> pd.DataFrame:
        rows = await self._fetch(
            """
            SELECT symbol, date, open, high, low, close, volume, amount
            FROM stock_daily_origin
            ORDER BY symbol, date
            """
        )
        return pd.DataFrame(rows)

    async def load_financials(self) -> pd.DataFrame:
        rows = await self._fetch(
            """
            SELECT symbol, period, ann_date, vintage, roe, eps, bps,
                   revenue_yoy, profit_yoy, debt_ratio, current_ratio
            FROM financial_indicators
            ORDER BY symbol, period, ann_date, vintage
            """
        )
        return pd.DataFrame(rows)

    async def get_market_data(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
    ) -> list[dict[str, Any]]:
        require_as_of(as_of_date)
        if end_date is not None:
            assert_not_after(end_date, as_of_date)
        return await self._fetch(
            """
            SELECT symbol, date, open, high, low, close, volume, amount
            FROM stock_daily_origin
            WHERE symbol=$1
              AND ($2::date IS NULL OR date >= $2)
              AND ($3::date IS NULL OR date <= $3)
              AND date <= $4
            ORDER BY date
            """,
            symbol,
            start_date,
            end_date,
            as_of_date,
        )

    async def get_financials(
        self,
        symbol: str,
        period: str,
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        require_as_of(as_of_date)
        return await self._fetchrow(
            """
            SELECT symbol, period, ann_date, vintage, roe, eps, bps,
                   revenue_yoy, profit_yoy, debt_ratio, current_ratio
            FROM financial_indicators
            WHERE symbol=$1 AND period=$2 AND ann_date <= $3
            ORDER BY ann_date DESC, vintage DESC
            LIMIT 1
            """,
            symbol,
            period,
            as_of_date,
        )

    async def submit_proposal(self, proposal: Any) -> int:
        payload = asdict(proposal) if hasattr(proposal, "__dataclass_fields__") else dict(proposal)
        return int(
            await self._fetchval(
                """
                INSERT INTO proposals (created_ts, kind, payload, source, confidence, snapshot_id, status)
                VALUES (CURRENT_TIMESTAMP, $1, $2::jsonb, $3, $4, $5, 'pending')
                RETURNING proposal_id
                """,
                payload["kind"],
                json.dumps(payload["payload"], ensure_ascii=False, default=str),
                payload["source"],
                payload["confidence"],
                payload.get("snapshot_id"),
            )
        )

    async def get_proposal_status(self, proposal_id: int) -> dict[str, Any]:
        return await self._fetchrow(
            """
            SELECT status, backtest_result
            FROM proposals
            WHERE proposal_id=$1
            """,
            proposal_id,
        )

    async def review_proposal(self, review: ProposalReview) -> dict[str, Any]:
        current = await self._fetchrow("SELECT status FROM proposals WHERE proposal_id=$1", review.proposal_id)
        if not current:
            return {}
        assert_transition(current["status"], review.status)
        await self._fetchval(
            """
            UPDATE proposals
            SET status=$2,
                reviewed_by=$3,
                reviewed_ts=CURRENT_TIMESTAMP,
                backtest_result=COALESCE($4::jsonb, backtest_result)
            WHERE proposal_id=$1
            RETURNING proposal_id
            """,
            review.proposal_id,
            review.status.value,
            review.reviewed_by,
            json.dumps(review.backtest_result, ensure_ascii=False, default=str)
            if review.backtest_result is not None
            else None,
        )
        return await self.get_proposal_status(review.proposal_id)

    async def save_backtest_result(self, report: BacktestReport) -> str:
        await self._fetchval(
            """
            INSERT INTO backtest_results (
              backtest_result_id, strategy_name, start_date, end_date, as_of_date,
              parameters, fills, nav, created_ts
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (backtest_result_id) DO UPDATE
            SET parameters=EXCLUDED.parameters,
                fills=EXCLUDED.fills,
                nav=EXCLUDED.nav
            RETURNING backtest_result_id
            """,
            report.backtest_result_id,
            report.strategy_name,
            report.start_date,
            report.end_date,
            report.as_of_date,
            json.dumps(report.parameters, ensure_ascii=False, default=str),
            json.dumps([asdict(fill) for fill in report.fills], ensure_ascii=False, default=str),
            json.dumps(report.nav, ensure_ascii=False, default=str),
        )
        return report.backtest_result_id

    async def get_backtest_result(self, backtest_result_id: str) -> dict[str, Any]:
        return await self._fetchrow(
            """
            SELECT backtest_result_id, strategy_name, start_date, end_date, as_of_date,
                   parameters, fills, nav, created_ts
            FROM backtest_results
            WHERE backtest_result_id=$1
            """,
            backtest_result_id,
        )
