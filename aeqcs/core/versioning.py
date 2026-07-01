"""Point-in-time guards and decision snapshot helpers."""

from __future__ import annotations

import hashlib
import json
import math
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


def require_valid_date_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")


def require_non_empty_text(value: str, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def require_finite_number(value: Any, field: str) -> Any:
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{field} must be finite")
    return value


def require_date_value(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be a valid date") from exc
    raise ValueError(f"{field} must be a valid date")


def require_datetime_value(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be a valid datetime") from exc
    raise ValueError(f"{field} must be a valid datetime")


def stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    role: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    embed_model: str | None = None
    output_model: str | None = None

    @property
    def input_hash(self) -> str:
        return stable_hash(self.input)


async def write_snapshot(conn: Any, snapshot: DecisionSnapshot) -> int:
    query = """
    INSERT INTO decision_snapshot (decision_ts, role, input_hash, input, output_model, output, embed_model)
    VALUES (CURRENT_TIMESTAMP, $1, $2, $3::jsonb, $4, $5::jsonb, $6)
    RETURNING snapshot_id
    """
    return await conn.fetchval(
        query,
        snapshot.role,
        snapshot.input_hash,
        json.dumps(snapshot.input, ensure_ascii=False, default=str),
        snapshot.output_model,
        json.dumps(snapshot.output, ensure_ascii=False, default=str)
        if snapshot.output is not None
        else None,
        snapshot.embed_model,
    )


async def replay_snapshot_output(conn: Any, input_payload: dict[str, Any]) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "SELECT output FROM decision_snapshot WHERE input_hash=$1 ORDER BY decision_ts DESC LIMIT 1",
        stable_hash(input_payload),
    )
    return dict(row["output"]) if row and row["output"] else None
