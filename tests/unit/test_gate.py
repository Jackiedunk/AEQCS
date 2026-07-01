import pytest
import pandas as pd

from aeqcs.core.exceptions import GateStateError
from aeqcs.gate.promote import approve_proposal_decision
from aeqcs.gate.proposals import ProposalStatus
from aeqcs.gate.validator import assert_transition, backtest_check, validate_structure


def test_validate_structure_requires_kind_specific_fields():
    errors = validate_structure("edge", {"parent_id": "a"})

    assert "child_id is required for edge proposals" in errors
    assert "relation_type is required for edge proposals" in errors


def test_validate_structure_rejects_unknown_kind():
    assert validate_structure("unknown", {"x": 1}) == ["unsupported proposal kind: unknown"]


def test_proposal_transition_rules():
    assert_transition(ProposalStatus.PENDING, ProposalStatus.APPROVED)

    with pytest.raises(GateStateError):
        assert_transition(ProposalStatus.APPROVED, ProposalStatus.REJECTED)


def test_approve_proposal_decision_promotes_only_approved_proposals():
    assert approve_proposal_decision(ProposalStatus.APPROVED, "alice", "promote") == ProposalStatus.PROMOTED

    with pytest.raises(GateStateError):
        approve_proposal_decision(ProposalStatus.PENDING, "alice", "promote")


def test_approve_proposal_decision_requires_auditable_identity():
    with pytest.raises(ValueError, match="approver_id is required"):
        approve_proposal_decision(ProposalStatus.APPROVED, "", "promote")


def test_approve_proposal_decision_rejects_unknown_decision():
    with pytest.raises(ValueError, match="unsupported approval decision"):
        approve_proposal_decision(ProposalStatus.APPROVED, "alice", "maybe")


def test_backtest_check_uses_rolling_out_of_sample_fold_majority():
    dates = pd.date_range("2026-01-01", periods=10, freq="D").date
    metrics = pd.DataFrame(
        [
            {"date": dates[index], "annualized_return": value, "max_drawdown": drawdown}
            for index, (value, drawdown) in enumerate(
                [
                    (0.01, -0.01),
                    (0.01, -0.01),
                    (0.01, -0.01),
                    (0.01, -0.01),
                    (0.12, -0.03),
                    (0.11, -0.04),
                    (0.00, -0.12),
                    (0.01, -0.10),
                    (0.13, -0.02),
                    (0.12, -0.02),
                ]
            )
        ]
    )

    result = backtest_check(
        metrics,
        {
            "train_window_days": 3,
            "test_window_days": 2,
            "step_days": 2,
            "embargo_days": 1,
            "min_annualized_return": 0.08,
            "max_drawdown": 0.08,
        },
    )

    assert result["passed"] is True
    assert result["passed_folds"] == 2
    assert result["total_folds"] == 3
    assert [fold["passed"] for fold in result["folds"]] == [True, False, True]
