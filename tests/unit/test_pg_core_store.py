from datetime import date, datetime

import pytest

from aeqcs.core.exceptions import LookAheadViolation
from aeqcs.gate.proposals import ProposalReview, ProposalStatus
from aeqcs.ingest.document_parser import DocumentChunk, ParsedDocument
from aeqcs.store.pg_core import PgCoreStore
from aeqcs.strategy.backtest.engine import BacktestReport


class FakeConn:
    def __init__(self):
        self.calls = []

    async def fetch(self, query, *args):
        self.calls.append(("fetch", query, args))
        return []

    async def fetchrow(self, query, *args):
        self.calls.append(("fetchrow", query, args))
        if "SELECT status FROM proposals" in query:
            return {"status": "pending"}
        return None

    async def fetchval(self, query, *args):
        self.calls.append(("fetchval", query, args))
        return 1

    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))
        return "OK"

    def transaction(self):
        return AcquireContext(self)


class AcquireContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self):
        self.conn = FakeConn()

    def acquire(self):
        return AcquireContext(self.conn)


@pytest.mark.asyncio
async def test_pg_market_data_requires_as_of():
    store = PgCoreStore(FakePool())

    with pytest.raises(LookAheadViolation):
        await store.get_market_data("000001")


@pytest.mark.asyncio
async def test_pg_market_data_binds_as_of_date():
    pool = FakePool()
    store = PgCoreStore(pool)

    await store.get_market_data("000001", as_of_date=date(2026, 1, 2))

    kind, query, args = pool.conn.calls[-1]
    assert kind == "fetch"
    assert "date <= $4" in query
    assert args == ("000001", None, None, date(2026, 1, 2))


@pytest.mark.asyncio
async def test_pg_market_data_rejects_end_after_as_of():
    store = PgCoreStore(FakePool())

    with pytest.raises(LookAheadViolation):
        await store.get_market_data(
            "000001",
            end_date=date(2026, 1, 3),
            as_of_date=date(2026, 1, 2),
        )


@pytest.mark.asyncio
async def test_pg_review_proposal_updates_status():
    pool = FakePool()
    store = PgCoreStore(pool)

    await store.review_proposal(
        ProposalReview(1, ProposalStatus.APPROVED, reviewed_by="tester", reason="ok")
    )

    calls = [call for call in pool.conn.calls if call[0] == "fetchval"]
    assert calls
    assert calls[-1][2][0:3] == (1, "approved", "tester")


@pytest.mark.asyncio
async def test_pg_save_backtest_result_upserts_report():
    pool = FakePool()
    store = PgCoreStore(pool)

    report = BacktestReport(
        backtest_result_id="abc",
        strategy_name="buy_and_hold",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        as_of_date=date(2026, 1, 2),
        parameters={"symbol": "000001"},
        fills=[],
        nav=[],
    )
    result_id = await store.save_backtest_result(report)

    assert result_id == "abc"
    kind, query, args = pool.conn.calls[-1]
    assert kind == "fetchval"
    assert "INSERT INTO backtest_results" in query
    assert args[0] == "abc"


@pytest.mark.asyncio
async def test_pg_factor_values_upsert_and_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    count = await store.save_factor_values(
        [
            {
                "symbol": "000001",
                "date": date(2026, 1, 2),
                "factor_id": "momentum_1d",
                "version": 1,
                "value": 0.1,
                "calc_timestamp": date(2026, 1, 2),
            }
        ]
    )
    await store.get_factor_values(
        ["momentum_1d"],
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 2),
    )

    assert count == 1
    assert any(call[0] == "execute" and "INSERT INTO factor_values" in call[1] for call in pool.conn.calls)
    assert pool.conn.calls[-1][2] == (
        ["momentum_1d"],
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 2),
    )


@pytest.mark.asyncio
async def test_pg_save_uploaded_doc_replaces_chunks():
    pool = FakePool()
    store = PgCoreStore(pool)
    document = ParsedDocument(
        filename="note.md",
        path="/tmp/note.md",
        sha256="abc",
        text="hello",
        uploaded_ts=datetime(2026, 1, 1),
    )

    result = await store.save_uploaded_doc(document, [DocumentChunk("abc", 0, "hello")])

    assert result == {"doc_id": 1, "sha256": "abc", "chunks": 1}
    assert any(call[0] == "execute" and "DELETE FROM doc_chunks" in call[1] for call in pool.conn.calls)
