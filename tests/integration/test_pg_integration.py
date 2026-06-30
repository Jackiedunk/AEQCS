import os
from datetime import date, datetime

import asyncpg
import pytest

from aeqcs.gate.proposals import Proposal, ProposalReview, ProposalStatus
from aeqcs.ingest.document_parser import DocumentChunk, ParsedDocument
from aeqcs.store.pg_core import PgCoreStore
from deploy.init_db import SCHEMA_SQL


pytestmark = pytest.mark.integration


def pg_dsn() -> str:
    dsn = os.environ.get("AEQCS_TEST_PG_DSN")
    if not dsn:
        pytest.skip("set AEQCS_TEST_PG_DSN to run PostgreSQL integration tests")
    return dsn


@pytest.fixture
async def pg_pool():
    pool = await asyncpg.create_pool(dsn=pg_dsn(), min_size=1, max_size=2)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.execute(
            """
            DELETE FROM doc_chunks
            USING uploaded_docs
            WHERE doc_chunks.doc_id=uploaded_docs.doc_id
              AND uploaded_docs.filename LIKE 'integration-%';
            DELETE FROM uploaded_docs WHERE filename LIKE 'integration-%';
            DELETE FROM proposals WHERE source LIKE 'integration:%';
            DELETE FROM factor_values WHERE symbol='T00001';
            DELETE FROM financial_indicators WHERE symbol='T00001';
            DELETE FROM stock_daily_origin WHERE symbol='T00001';
            """
        )
    try:
        yield pool
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM doc_chunks
                USING uploaded_docs
                WHERE doc_chunks.doc_id=uploaded_docs.doc_id
                  AND uploaded_docs.filename LIKE 'integration-%';
                DELETE FROM uploaded_docs WHERE filename LIKE 'integration-%';
                DELETE FROM proposals WHERE source LIKE 'integration:%';
                DELETE FROM factor_values WHERE symbol='T00001';
                DELETE FROM financial_indicators WHERE symbol='T00001';
                DELETE FROM stock_daily_origin WHERE symbol='T00001';
                """
            )
        await pool.close()


@pytest.mark.asyncio
async def test_pg_core_store_round_trips_core_paths(pg_pool):
    store = PgCoreStore(pg_pool)
    async with pg_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO stock_daily_origin (symbol, date, open, high, low, close, volume, amount)
            VALUES ('T00001', '2026-01-02', 10.0, 11.0, 9.5, 10.5, 1000, 10500.0)
            """
        )
        await conn.execute(
            """
            INSERT INTO financial_indicators (
              symbol, period, ann_date, vintage, roe, eps, bps,
              revenue_yoy, profit_yoy, debt_ratio, current_ratio
            )
            VALUES ('T00001', '2025Q4', '2026-01-10', 0, 0.12, 0.50, 3.20, 0.20, 0.18, 0.40, 1.80)
            """
        )

    market_rows = await store.get_market_data("T00001", as_of_date=date(2026, 1, 2))
    financials = await store.get_financials("T00001", "2025Q4", as_of_date=date(2026, 1, 10))

    assert len(market_rows) == 1
    assert market_rows[0]["symbol"] == "T00001"
    assert financials["ann_date"] == date(2026, 1, 10)

    document = ParsedDocument(
        filename="integration-note.md",
        path="upload://integration-note.md",
        sha256="integration-sha",
        text="hello integration",
        uploaded_ts=datetime(2026, 1, 1),
    )
    saved = await store.save_uploaded_doc(document, [DocumentChunk("integration-sha", 0, "hello")])
    uploaded = await store.get_uploaded_doc("integration-sha")

    assert saved["chunks"] == 1
    assert uploaded["filename"] == "integration-note.md"
    assert uploaded["chunks"][0]["text"] == "hello"

    proposal_id = await store.submit_proposal(
        Proposal(
            kind="factor",
            payload={"factor_id": "integration_factor", "definition": "close / open - 1"},
            source="integration:test",
            confidence=0.9,
        )
    )
    reviewed = await store.review_proposal(
        ProposalReview(proposal_id, ProposalStatus.APPROVED, reviewed_by="integration")
    )

    assert reviewed["status"] == "approved"
