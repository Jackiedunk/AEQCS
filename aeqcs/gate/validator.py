"""Validation gate checks before promotion."""

from __future__ import annotations

from typing import Any

from aeqcs.core.exceptions import GateStateError
from aeqcs.gate.proposals import ProposalStatus, normalize_status


REQUIRED_BY_KIND: dict[str, set[str]] = {
    "catalyst": {"concept", "affected_stocks"},
    "edge": {"parent_id", "child_id", "relation_type"},
    "signal": {"strategy_id", "symbol", "score"},
    "factor": {"factor_id", "definition"},
    "theme": {"theme_id", "name"},
    "correction": {"target", "corrected"},
}

ALLOWED_TRANSITIONS: dict[ProposalStatus, set[ProposalStatus]] = {
    ProposalStatus.PENDING: {ProposalStatus.BACKTESTED, ProposalStatus.APPROVED, ProposalStatus.REJECTED},
    ProposalStatus.BACKTESTED: {ProposalStatus.APPROVED, ProposalStatus.REJECTED},
    ProposalStatus.APPROVED: {ProposalStatus.PROMOTED},
    ProposalStatus.REJECTED: set(),
    ProposalStatus.PROMOTED: set(),
}


def validate_structure(kind: str, payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not kind:
        errors.append("kind is required")
    elif kind not in REQUIRED_BY_KIND:
        errors.append(f"unsupported proposal kind: {kind}")
    if not payload:
        errors.append("payload is required")
    if kind in REQUIRED_BY_KIND and payload:
        for key in sorted(REQUIRED_BY_KIND[kind] - set(payload)):
            if key not in payload:
                errors.append(f"{key} is required for {kind} proposals")
    return errors


def assert_transition(current: str | ProposalStatus, target: str | ProposalStatus) -> None:
    current_status = normalize_status(current)
    target_status = normalize_status(target)
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise GateStateError(f"invalid proposal transition: {current_status} -> {target_status}")
