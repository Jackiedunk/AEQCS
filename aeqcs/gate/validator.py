"""Validation gate checks before promotion."""

from __future__ import annotations

from typing import Any


def validate_structure(kind: str, payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not kind:
        errors.append("kind is required")
    if not payload:
        errors.append("payload is required")
    if kind == "edge":
        for key in ("parent_id", "child_id", "relation_type"):
            if key not in payload:
                errors.append(f"{key} is required for edge proposals")
    return errors
