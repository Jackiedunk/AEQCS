"""PostgreSQL-backed implementation of the core store protocol."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from typing import Any

import pandas as pd

from aeqcs.core.versioning import (
    assert_not_after,
    require_as_of,
    require_date_value,
    require_datetime_value,
    require_finite_number,
    require_non_empty_text,
    require_valid_date_range,
)
from aeqcs.gate.promote import approve_proposal_decision
from aeqcs.gate.proposals import ProposalReview
from aeqcs.gate.validator import assert_transition
from aeqcs.ingest.document_parser import DocumentChunk, ParsedDocument
from aeqcs.knowledge.universe_builder import is_generic_parent_values, normalize_universe_label
from aeqcs.store.protocols import AsyncCoreStore
from aeqcs.strategy.backtest.engine import BacktestReport


def _date_from_record(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _require_positive_integer_id(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


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
                   revenue_yoy, profit_yoy, debt_ratio, current_ratio, quick_ratio, gross_margin, net_margin
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
        symbol = require_non_empty_text(symbol, "symbol")
        checked_as_of = require_as_of(as_of_date)
        if start_date is not None and end_date is not None:
            require_valid_date_range(start_date, end_date)
        if end_date is not None:
            assert_not_after(end_date, checked_as_of)
        return await self._fetch(
            """
            WITH priced AS (
                SELECT d.symbol, d.date, d.open, d.high, d.low, d.close, d.volume, d.amount,
                       COALESCE(af.factor, 1) AS adj_factor,
                       FIRST_VALUE(COALESCE(af.factor, 1)) OVER (
                           PARTITION BY d.symbol ORDER BY d.date
                       ) AS first_factor,
                       LAST_VALUE(COALESCE(af.factor, 1)) OVER (
                           PARTITION BY d.symbol ORDER BY d.date
                           ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                       ) AS latest_factor
                FROM stock_daily_origin d
                LEFT JOIN adj_factor af ON af.symbol = d.symbol AND af.date = d.date
                WHERE d.symbol=$1
                  AND ($2::date IS NULL OR d.date >= $2)
                  AND ($3::date IS NULL OR d.date <= $3)
                  AND d.date <= $4
            )
            SELECT symbol, date, open, high, low, close, volume, amount, adj_factor,
                   ROUND(open * adj_factor / NULLIF(first_factor, 0), 12) AS hfq_open,
                   ROUND(high * adj_factor / NULLIF(first_factor, 0), 12) AS hfq_high,
                   ROUND(low * adj_factor / NULLIF(first_factor, 0), 12) AS hfq_low,
                   ROUND(close * adj_factor / NULLIF(first_factor, 0), 12) AS hfq_close,
                   ROUND(open * adj_factor / NULLIF(latest_factor, 0), 12) AS qfq_open,
                   ROUND(high * adj_factor / NULLIF(latest_factor, 0), 12) AS qfq_high,
                   ROUND(low * adj_factor / NULLIF(latest_factor, 0), 12) AS qfq_low,
                   ROUND(close * adj_factor / NULLIF(latest_factor, 0), 12) AS qfq_close
            FROM priced
            ORDER BY date
            """,
            symbol,
            start_date,
            end_date,
            checked_as_of,
        )

    async def get_financials(
        self,
        symbol: str,
        period: str,
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        symbol = require_non_empty_text(symbol, "symbol")
        period = require_non_empty_text(period, "period")
        require_as_of(as_of_date)
        return await self._fetchrow(
            """
            SELECT symbol, period, ann_date, vintage, roe, eps, bps,
                   revenue_yoy, profit_yoy, debt_ratio, current_ratio, quick_ratio, gross_margin, net_margin
            FROM financial_indicators
            WHERE symbol=$1 AND period=$2 AND ann_date <= $3
            ORDER BY ann_date DESC, vintage DESC
            LIMIT 1
            """,
            symbol,
            period,
            as_of_date,
        )

    async def get_index_constituents(
        self,
        index_code: str,
        as_of_date: date | None = None,
    ) -> list[dict[str, Any]]:
        index_code = require_non_empty_text(index_code, "index_code")
        checked_as_of = require_as_of(as_of_date)
        return await self._fetch(
            """
            SELECT index_code, symbol, in_date, out_date
            FROM index_constituents
            WHERE index_code=$1
              AND in_date <= $2
              AND (out_date IS NULL OR out_date > $2)
            ORDER BY symbol, in_date
            """,
            index_code,
            checked_as_of,
        )

    async def get_active_stock_universe(self, as_of_date: date | None = None) -> list[dict[str, Any]]:
        checked_as_of = require_as_of(as_of_date)
        return await self._fetch(
            """
            SELECT symbol, name, ipo_date, delist_date, status
            FROM stock_universe
            WHERE ipo_date <= $1
              AND (delist_date IS NULL OR delist_date > $1)
            ORDER BY symbol, ipo_date
            """,
            checked_as_of,
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
        proposal_id = _require_positive_integer_id(proposal_id, "proposal_id")
        return await self._fetchrow(
            """
            SELECT status, backtest_result
            FROM proposals
            WHERE proposal_id=$1
            """,
            proposal_id,
        )

    async def review_proposal(self, review: ProposalReview) -> dict[str, Any]:
        proposal_id = _require_positive_integer_id(review.proposal_id, "proposal_id")
        current = await self._fetchrow("SELECT status FROM proposals WHERE proposal_id=$1", proposal_id)
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
            proposal_id,
            review.status.value,
            review.reviewed_by,
            json.dumps(review.backtest_result, ensure_ascii=False, default=str)
            if review.backtest_result is not None
            else None,
        )
        return await self.get_proposal_status(proposal_id)

    async def approve_proposal(self, proposal_id: int, approver_id: str, decision: str) -> dict[str, Any]:
        proposal_id = _require_positive_integer_id(proposal_id, "proposal_id")
        current = await self._fetchrow("SELECT status FROM proposals WHERE proposal_id=$1", proposal_id)
        if not current:
            return {}
        target = approve_proposal_decision(current["status"], approver_id, decision)
        await self._fetchval(
            """
            UPDATE proposals
            SET status=$2,
                reviewed_by=$3,
                reviewed_ts=CURRENT_TIMESTAMP
            WHERE proposal_id=$1
            RETURNING proposal_id
            """,
            proposal_id,
            target.value,
            approver_id,
        )
        return await self.get_proposal_status(proposal_id)

    async def save_backtest_result(self, report: BacktestReport) -> str:
        backtest_result_id = require_non_empty_text(report.backtest_result_id, "backtest_result_id")
        strategy_name = require_non_empty_text(report.strategy_name, "strategy_name")
        await self._fetchval(
            """
            INSERT INTO backtest_results (
              backtest_result_id, strategy_name, start_date, end_date, as_of_date,
              parameters, fills, nav, orders, created_ts
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (backtest_result_id) DO UPDATE
            SET parameters=EXCLUDED.parameters,
                fills=EXCLUDED.fills,
                nav=EXCLUDED.nav,
                orders=EXCLUDED.orders
            RETURNING backtest_result_id
            """,
            backtest_result_id,
            strategy_name,
            report.start_date,
            report.end_date,
            report.as_of_date,
            json.dumps(report.parameters, ensure_ascii=False, default=str),
            json.dumps([asdict(fill) for fill in report.fills], ensure_ascii=False, default=str),
            json.dumps(report.nav, ensure_ascii=False, default=str),
            json.dumps(report.orders, ensure_ascii=False, default=str),
        )
        return backtest_result_id

    async def get_backtest_result(self, backtest_result_id: str) -> dict[str, Any]:
        backtest_result_id = require_non_empty_text(backtest_result_id, "backtest_result_id")
        return await self._fetchrow(
            """
            SELECT backtest_result_id, strategy_name, start_date, end_date, as_of_date,
                   parameters, fills, nav, orders, created_ts
            FROM backtest_results
            WHERE backtest_result_id=$1
            """,
            backtest_result_id,
        )

    async def save_backtest_task(self, task: dict[str, Any]) -> str:
        task_id = require_non_empty_text(task["task_id"], "task_id")
        status = require_non_empty_text(task["status"], "status")
        return str(
            await self._fetchval(
                """
                INSERT INTO backtest_tasks (
                  task_id, status, strategy_name, start_date, end_date, as_of_date,
                  parameters, result, error, created_ts, updated_ts
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (task_id) DO UPDATE
                SET status=EXCLUDED.status,
                    strategy_name=EXCLUDED.strategy_name,
                    start_date=EXCLUDED.start_date,
                    end_date=EXCLUDED.end_date,
                    as_of_date=EXCLUDED.as_of_date,
                    parameters=EXCLUDED.parameters,
                    result=EXCLUDED.result,
                    error=EXCLUDED.error,
                    updated_ts=CURRENT_TIMESTAMP
                RETURNING task_id
                """,
                task_id,
                status,
                task.get("strategy_name"),
                task.get("start_date"),
                task.get("end_date"),
                task.get("as_of_date"),
                json.dumps(task.get("parameters", {}), ensure_ascii=False, default=str),
                json.dumps(task.get("result"), ensure_ascii=False, default=str),
                task.get("error"),
            )
        )

    async def get_backtest_task(self, task_id: str) -> dict[str, Any]:
        task_id = require_non_empty_text(task_id, "task_id")
        return await self._fetchrow(
            """
            SELECT task_id, status, strategy_name, start_date, end_date, as_of_date,
                   parameters, result, error, created_ts, updated_ts
            FROM backtest_tasks
            WHERE task_id=$1
            """,
            task_id,
        )

    async def save_factor_values(self, values: list[dict[str, Any]]) -> int:
        if not values:
            return 0
        normalized_values = []
        for row in values:
            normalized = dict(row)
            normalized["symbol"] = require_non_empty_text(row["symbol"], "symbol")
            normalized["factor_id"] = require_non_empty_text(row["factor_id"], "factor_id")
            normalized["version"] = _require_positive_integer_id(row.get("version", 1), "version")
            normalized["value"] = require_finite_number(row["value"], "value")
            normalized["date"] = require_date_value(row["date"], "date")
            normalized["calc_timestamp"] = require_datetime_value(row["calc_timestamp"], "calc_timestamp")
            normalized_values.append(normalized)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for row in normalized_values:
                    await conn.execute(
                        """
                        INSERT INTO factor_values (
                          symbol, date, factor_id, version, value, calc_timestamp
                        )
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (symbol, date, factor_id, version) DO UPDATE
                        SET value=EXCLUDED.value,
                            calc_timestamp=EXCLUDED.calc_timestamp
                        """,
                        row["symbol"],
                        row["date"],
                        row["factor_id"],
                        row.get("version", 1),
                        row["value"],
                        row["calc_timestamp"],
                    )
        return len(values)

    async def get_factor_values(
        self,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        require_as_of(as_of_date)
        require_valid_date_range(start_date, end_date)
        assert_not_after(end_date, as_of_date)
        return await self._fetch(
            """
            SELECT symbol, date, factor_id, version, value, calc_timestamp
            FROM factor_values
            WHERE factor_id = ANY($1)
              AND date >= $2
              AND date <= $3
              AND date <= $4
            ORDER BY factor_id, symbol, date
            """,
            factor_ids,
            start_date,
            end_date,
            as_of_date,
        )

    async def save_uploaded_doc(self, document: ParsedDocument, chunks: list[DocumentChunk]) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                doc_id = await conn.fetchval(
                    """
                    INSERT INTO uploaded_docs (uploaded_ts, filename, doc_type, path, sha256, status, meta)
                    VALUES ($1, $2, $3, $4, $5, 'parsed', '{}'::jsonb)
                    ON CONFLICT (sha256) DO UPDATE
                    SET filename=EXCLUDED.filename,
                        doc_type=EXCLUDED.doc_type,
                        path=EXCLUDED.path,
                        status='parsed'
                    RETURNING doc_id
                    """,
                    document.uploaded_ts,
                    document.filename,
                    document.doc_type,
                    document.path,
                    document.sha256,
                )
                await conn.execute("DELETE FROM doc_chunks WHERE doc_id=$1", doc_id)
                for chunk in chunks:
                    await conn.execute(
                        """
                        INSERT INTO doc_chunks (doc_id, seq, text, embed_model)
                        VALUES ($1, $2, $3, NULL)
                        ON CONFLICT (doc_id, seq) DO UPDATE
                        SET text=EXCLUDED.text,
                            embed_model=EXCLUDED.embed_model
                        """,
                        doc_id,
                        chunk.seq,
                        chunk.text,
                    )
        return {"doc_id": int(doc_id), "sha256": document.sha256, "chunks": len(chunks)}

    async def get_uploaded_doc(self, sha256: str) -> dict[str, Any]:
        sha256 = require_non_empty_text(sha256, "sha256")
        doc = await self._fetchrow(
            """
            SELECT doc_id, uploaded_ts, filename, doc_type, path, sha256, status, meta
            FROM uploaded_docs
            WHERE sha256=$1
            """,
            sha256,
        )
        if not doc:
            return {}
        chunks = await self._fetch(
            """
            SELECT seq, text
            FROM doc_chunks
            WHERE doc_id=$1
            ORDER BY seq
            """,
            doc["doc_id"],
        )
        doc["chunks"] = chunks
        return doc

    async def save_universe_node(self, node: dict[str, Any]) -> str:
        node_id = require_non_empty_text(node["node_id"], "node_id")
        label = require_non_empty_text(node["label"], "label")
        level = require_non_empty_text(node["level"], "level")
        created_by = require_non_empty_text(node["created_by"], "created_by")
        await self._reject_duplicate_universe_label(node_id, label)
        return str(
            await self._fetchval(
                """
                INSERT INTO semantic_nodes (
                  node_id, label, level, created_by, as_of_date, status, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
                ON CONFLICT (node_id) DO UPDATE
                SET label=EXCLUDED.label,
                    level=EXCLUDED.level,
                    created_by=EXCLUDED.created_by,
                    as_of_date=EXCLUDED.as_of_date,
                    status=EXCLUDED.status
                RETURNING node_id
                """,
                node_id,
                label,
                level,
                created_by,
                _date_from_record(node["as_of_date"]),
                node.get("status", "active"),
            )
        )

    async def save_universe_edge(self, edge: dict[str, Any]) -> int:
        edge_id = (
            _require_positive_integer_id(edge["edge_id"], "edge_id")
            if edge.get("edge_id") is not None
            else None
        )
        parent_id = require_non_empty_text(edge["parent_id"], "parent_id")
        child_id = require_non_empty_text(edge["child_id"], "child_id")
        relation_type = require_non_empty_text(edge["relation_type"], "relation_type")
        created_by = require_non_empty_text(edge["created_by"], "created_by")
        await self._reject_generic_universe_parent(parent_id)
        args = (
            parent_id,
            child_id,
            relation_type,
            created_by,
            edge.get("verified", False),
            edge.get("verified_by"),
            _date_from_record(edge["verified_as_of"]) if edge.get("verified_as_of") else None,
            edge.get("retired_by"),
            _date_from_record(edge["as_of_date"]),
            _date_from_record(edge["valid_to"]) if edge.get("valid_to") else None,
        )
        if edge_id is None:
            return int(
                await self._fetchval(
                    """
                    INSERT INTO semantic_edges (
                      parent_id, child_id, relation_type, created_by,
                      verified, verified_by, verified_as_of, retired_by, valid_from, valid_to
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    RETURNING edge_id
                    """,
                    *args,
                )
            )
        return int(
            await self._fetchval(
                """
                INSERT INTO semantic_edges (
                  edge_id, parent_id, child_id, relation_type, created_by,
                  verified, verified_by, verified_as_of, retired_by, valid_from, valid_to
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (edge_id) DO UPDATE
                SET parent_id=EXCLUDED.parent_id,
                    child_id=EXCLUDED.child_id,
                    relation_type=EXCLUDED.relation_type,
                    created_by=EXCLUDED.created_by,
                    verified=EXCLUDED.verified,
                    verified_by=EXCLUDED.verified_by,
                    verified_as_of=EXCLUDED.verified_as_of,
                    retired_by=EXCLUDED.retired_by,
                    valid_from=EXCLUDED.valid_from,
                    valid_to=EXCLUDED.valid_to
                RETURNING edge_id
                """,
                edge_id,
                *args,
            )
        )

    async def verify_universe_edge(self, edge_id: int, verified_by: str, as_of_date: date) -> dict[str, Any]:
        edge_id = _require_positive_integer_id(edge_id, "edge_id")
        verified_by = require_non_empty_text(verified_by, "verified_by")
        return await self._fetchrow(
            """
            UPDATE semantic_edges
            SET verified=TRUE,
                verified_by=$2,
                verified_as_of=$3
            WHERE edge_id=$1
            RETURNING edge_id, parent_id, child_id, relation_type, created_by,
                      verified, verified_by, verified_as_of, retired_by, valid_from, valid_to
            """,
            edge_id,
            verified_by,
            as_of_date,
        )

    async def retire_universe_edge(self, edge_id: int, retired_by: str, as_of_date: date) -> dict[str, Any]:
        edge_id = _require_positive_integer_id(edge_id, "edge_id")
        retired_by = require_non_empty_text(retired_by, "retired_by")
        return await self._fetchrow(
            """
            UPDATE semantic_edges
            SET retired_by=$2,
                valid_to=$3
            WHERE edge_id=$1
            RETURNING edge_id, parent_id, child_id, relation_type, created_by,
                      verified, verified_by, verified_as_of, retired_by, valid_from, valid_to
            """,
            edge_id,
            retired_by,
            as_of_date,
        )

    async def get_universe_children_as_of(self, parent_id: str, as_of_date: date) -> list[str]:
        parent_id = require_non_empty_text(parent_id, "parent_id")
        rows = await self._fetch(
            """
            SELECT child_id
            FROM semantic_edges
            WHERE parent_id=$1
              AND verified
              AND verified_as_of <= $2
              AND (valid_to IS NULL OR valid_to > $2)
            ORDER BY child_id, edge_id
            """,
            parent_id,
            as_of_date,
        )
        return [str(row["child_id"]) for row in rows]

    async def search_semantic_nodes(
        self,
        query: str,
        as_of_date: date,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("query must not be empty")
        vector_literal = None if query_embedding is None else "[" + ",".join(str(value) for value in query_embedding) + "]"
        return await self._fetch(
            """
            SELECT node_id, label, level, as_of_date, status,
                   CASE
                     WHEN $3::vector IS NOT NULL AND embedding IS NOT NULL
                       THEN 1 - (embedding <=> $3::vector)
                     WHEN label ILIKE '%' || $1 || '%' OR node_id ILIKE '%' || $1 || '%'
                       THEN 1.0
                     ELSE 0.0
                   END AS score
            FROM semantic_nodes
            WHERE as_of_date <= $2
              AND status = 'active'
              AND (
                ($3::vector IS NOT NULL AND embedding IS NOT NULL)
                OR label ILIKE '%' || $1 || '%'
                OR node_id ILIKE '%' || $1 || '%'
              )
            ORDER BY score DESC, label, node_id
            """,
            query,
            as_of_date,
            vector_literal,
        )

    async def _reject_duplicate_universe_label(self, node_id: str, label: str) -> None:
        normalized_label = normalize_universe_label(label)
        rows = await self._fetch(
            """
            SELECT node_id, label
            FROM semantic_nodes
            WHERE node_id <> $1
            """,
            node_id,
        )
        for row in rows:
            if normalize_universe_label(str(row["label"])) == normalized_label:
                raise ValueError(f"synonym duplicate node label: {label}")

    async def _reject_generic_universe_parent(self, node_id: str) -> None:
        row = await self._fetchrow(
            """
            SELECT label, level
            FROM semantic_nodes
            WHERE node_id=$1
            """,
            node_id,
        )
        if row and is_generic_parent_values(str(row["label"]), str(row["level"])):
            raise ValueError("parent node is too generic")
