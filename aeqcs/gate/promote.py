"""Promotion boundary for approved proposals."""

from __future__ import annotations

from typing import Any

from aeqcs.core.exceptions import GateBypassError


async def promote(conn: Any, proposal_id: int, reviewed_by: str) -> None:
    row = await conn.fetchrow("SELECT status FROM proposals WHERE proposal_id=$1", proposal_id)
    if not row or row["status"] != "approved":
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
