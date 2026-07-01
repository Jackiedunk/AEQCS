"""Validation gate checks before promotion."""

from __future__ import annotations

from typing import Any

import pandas as pd

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


def _positive_int(config: dict[str, Any], key: str) -> int:
    value = int(config[key])
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def backtest_check(metrics: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    required = {"date", "annualized_return", "max_drawdown"}
    missing = required - set(metrics.columns)
    if missing:
        raise ValueError(f"backtest metrics missing columns: {sorted(missing)}")

    train_window = _positive_int(config, "train_window_days")
    test_window = _positive_int(config, "test_window_days")
    step = _positive_int(config, "step_days")
    embargo = int(config.get("embargo_days", 0))
    if embargo < 0:
        raise ValueError("embargo_days must be non-negative")
    min_return = float(config["min_annualized_return"])
    max_drawdown = float(config["max_drawdown"])

    frame = metrics.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.sort_values("date").reset_index(drop=True)
    dates = list(frame["date"])
    folds: list[dict[str, Any]] = []
    start = 0
    while start + train_window + embargo + test_window <= len(dates):
        train_start = dates[start]
        train_end = dates[start + train_window - 1]
        test_start_index = start + train_window + embargo
        test_end_index = test_start_index + test_window - 1
        test_start = dates[test_start_index]
        test_end = dates[test_end_index]
        test_slice = frame.iloc[test_start_index : test_end_index + 1]
        annualized_return = float(test_slice["annualized_return"].mean())
        observed_drawdown = float(test_slice["max_drawdown"].min())
        passed = annualized_return >= min_return and observed_drawdown >= -max_drawdown
        folds.append(
            {
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "annualized_return": annualized_return,
                "max_drawdown": observed_drawdown,
                "passed": passed,
            }
        )
        start += step

    if not folds:
        raise ValueError("not enough metrics to build rolling validation folds")
    passed_folds = sum(1 for fold in folds if fold["passed"])
    return {
        "passed": passed_folds > len(folds) / 2,
        "passed_folds": passed_folds,
        "total_folds": len(folds),
        "folds": folds,
    }
