import os
import asyncio
import json
from datetime import date, datetime

import asyncpg
import pytest

from aeqcs.core.event_bus import EventBus
from aeqcs.core.events import NewsEvent
from aeqcs.gate.proposals import Proposal, ProposalReview, ProposalStatus
from aeqcs.ingest.document_parser import DocumentChunk, ParsedDocument
from aeqcs.knowledge.universe_builder import UniverseBuilder
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
            DELETE FROM semantic_edges
            WHERE parent_id LIKE 'integration.%'
               OR child_id LIKE 'integration.%';
            DELETE FROM semantic_nodes WHERE node_id LIKE 'integration.%';
            DELETE FROM event_log
            WHERE event_id LIKE 'integration.%'
               OR channel='integration_events';
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
                DELETE FROM semantic_edges
                WHERE parent_id LIKE 'integration.%'
                   OR child_id LIKE 'integration.%';
                DELETE FROM semantic_nodes WHERE node_id LIKE 'integration.%';
                DELETE FROM event_log
                WHERE event_id LIKE 'integration.%'
                   OR channel='integration_events';
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


@pytest.mark.asyncio
async def test_pg_universe_graph_round_trips_lifecycle_asof(pg_pool):
    store = PgCoreStore(pg_pool)
    builder = UniverseBuilder()
    parent = builder.add_node(
        "integration.concept.ai",
        "Integration AI Theme",
        "concept",
        "data_steward",
        date(2026, 1, 1),
    )
    child = builder.add_node(
        "integration.stock.000001",
        "Integration Stock One",
        "stock",
        "data_steward",
        date(2026, 1, 1),
    )
    edge = builder.add_edge(
        "integration.concept.ai",
        "integration.stock.000001",
        "contains",
        "data_steward",
        date(2026, 1, 2),
    )
    edge.pop("edge_id")

    assert await store.save_universe_node(parent) == "integration.concept.ai"
    assert await store.save_universe_node(child) == "integration.stock.000001"
    edge_id = await store.save_universe_edge(edge)
    before_verify = await store.get_universe_children_as_of(
        "integration.concept.ai",
        as_of_date=date(2026, 1, 2),
    )
    verified = await store.verify_universe_edge(
        edge_id,
        verified_by="factor_researcher",
        as_of_date=date(2026, 1, 3),
    )
    active_children = await store.get_universe_children_as_of(
        "integration.concept.ai",
        as_of_date=date(2026, 1, 4),
    )
    retired = await store.retire_universe_edge(
        edge_id,
        retired_by="risk_officer",
        as_of_date=date(2026, 1, 5),
    )
    retired_children = await store.get_universe_children_as_of(
        "integration.concept.ai",
        as_of_date=date(2026, 1, 5),
    )

    assert before_verify == []
    assert verified["verified"] is True
    assert verified["verified_by"] == "factor_researcher"
    assert active_children == ["integration.stock.000001"]
    assert retired["retired_by"] == "risk_officer"
    assert retired_children == []


@pytest.mark.asyncio
async def test_pg_event_bus_round_trips_lightweight_notify_and_full_payload(pg_pool):
    bus = EventBus(pg_pool)
    received_notification = asyncio.get_running_loop().create_future()
    listener_conn = await pg_pool.acquire()

    def on_notify(_connection, _pid, channel, payload):
        if not received_notification.done():
            received_notification.set_result((channel, payload))

    try:
        await listener_conn.add_listener("integration_events", on_notify)
        event = NewsEvent(
            event_id="integration.news.1",
            timestamp=datetime(2026, 1, 1, 9, 30),
            knowledge_ts=datetime(2026, 1, 1, 9, 30),
            source="integration",
            level="A",
            title="integration event bus",
            content="x" * 9000,
        )

        await bus.publish("integration_events", event)
        channel, notify_payload = await asyncio.wait_for(received_notification, timeout=3)
    finally:
        await listener_conn.remove_listener("integration_events", on_notify)
        await pg_pool.release(listener_conn)

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT channel, payload
            FROM event_log
            WHERE event_id=$1
            """,
            "integration.news.1",
        )
    handled = []

    async def handler(event_payload):
        handled.append(event_payload)

    await bus.dispatch_notification(notify_payload, handler)
    await bus.dispatch_notification(notify_payload, handler)
    stored_payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else dict(row["payload"])
    notify_reference = json.loads(notify_payload)

    assert channel == "integration_events"
    assert notify_reference == {"event_id": "integration.news.1", "channel": "integration_events"}
    assert len(notify_payload.encode("utf-8")) < 8000
    assert row["channel"] == "integration_events"
    assert stored_payload["content"] == "x" * 9000
    assert handled == [stored_payload]
