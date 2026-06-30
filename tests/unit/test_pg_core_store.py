from datetime import date

import pytest

from aeqcs.core.exceptions import LookAheadViolation
from aeqcs.gate.proposals import ProposalReview, ProposalStatus
from aeqcs.store.pg_core import PgCoreStore


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
