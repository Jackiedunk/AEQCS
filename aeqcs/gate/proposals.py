"""Proposal gate primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

ProposalKind = Literal["catalyst", "edge", "signal", "factor", "theme", "correction"]


@dataclass(frozen=True, slots=True)
class Proposal:
    kind: ProposalKind
    payload: dict[str, Any]
    source: str
    confidence: float
    snapshot_id: int | None = None


async def submit_proposal(conn: Any, proposal: Proposal) -> int:
    query = """
    INSERT INTO proposals (created_ts, kind, payload, source, confidence, snapshot_id, status)
    VALUES (CURRENT_TIMESTAMP, $1, $2::jsonb, $3, $4, $5, 'pending')
    RETURNING proposal_id
    """
    return await conn.fetchval(
        query,
        proposal.kind,
        json.dumps(proposal.payload, ensure_ascii=False, default=str),
        proposal.source,
        proposal.confidence,
        proposal.snapshot_id,
    )


async def get_proposal_status(conn: Any, proposal_id: int) -> dict[str, Any]:
    row = await conn.fetchrow(
        "SELECT status, backtest_result FROM proposals WHERE proposal_id=$1",
        proposal_id,
    )
    return {"status": row["status"], "result": row["backtest_result"]} if row else {}
