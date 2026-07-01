"""Promotion boundary for approved proposals."""

from __future__ import annotations

from typing import Any

from aeqcs.core.exceptions import GateBypassError
from aeqcs.gate.proposals import ProposalStatus
from aeqcs.gate.validator import assert_transition


def approve_proposal_decision(
    current_status: str | ProposalStatus,
    approver_id: str,
    decision: str,
) -> ProposalStatus:
    if not approver_id.strip():
        raise ValueError("approver_id is required")
    if decision != "promote":
        raise ValueError(f"unsupported approval decision: {decision}")
    assert_transition(current_status, ProposalStatus.PROMOTED)
    return ProposalStatus.PROMOTED


async def promote(conn: Any, proposal_id: int, reviewed_by: str) -> None:
    row = await conn.fetchrow("SELECT status FROM proposals WHERE proposal_id=$1", proposal_id)
    if not row or row["status"] != ProposalStatus.APPROVED:
        raise GateBypassError("only approved proposals can be promoted")
    await conn.execute(
        """
        UPDATE proposals
        SET reviewed_by=$2, reviewed_ts=CURRENT_TIMESTAMP
        WHERE proposal_id=$1
        """,
        proposal_id,
        reviewed_by,
    )
