"""Point-in-time guards and decision snapshot helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from aeqcs.core.exceptions import LookAheadViolation


def require_as_of(as_of_date: date | datetime | None) -> date | datetime:
    if as_of_date is None:
        raise LookAheadViolation("as_of_date is required for point-in-time reads")
    return as_of_date


def assert_not_after(known_at: date | datetime, as_of_date: date | datetime) -> None:
    if known_at > as_of_date:
        raise LookAheadViolation(f"data known at {known_at!s} is after as_of {as_of_date!s}")


def stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    role: str
    input: dict[str, Any]
    llm_output: dict[str, Any] | None = None
    embed_model: str | None = None
    llm_model: str | None = None

    @property
    def input_hash(self) -> str:
        return stable_hash(self.input)


async def write_snapshot(conn: Any, snapshot: DecisionSnapshot) -> int:
    query = """
    INSERT INTO decision_snapshot (decision_ts, role, input_hash, input, llm_model, llm_output, embed_model)
    VALUES (CURRENT_TIMESTAMP, $1, $2, $3::jsonb, $4, $5::jsonb, $6)
    RETURNING snapshot_id
    """
    return await conn.fetchval(
        query,
        snapshot.role,
        snapshot.input_hash,
        json.dumps(snapshot.input, ensure_ascii=False, default=str),
        snapshot.llm_model,
        json.dumps(snapshot.llm_output, ensure_ascii=False, default=str)
        if snapshot.llm_output is not None
        else None,
        snapshot.embed_model,
    )


async def replay_llm(conn: Any, input_payload: dict[str, Any]) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "SELECT llm_output FROM decision_snapshot WHERE input_hash=$1 ORDER BY decision_ts DESC LIMIT 1",
        stable_hash(input_payload),
    )
    return dict(row["llm_output"]) if row and row["llm_output"] else None
