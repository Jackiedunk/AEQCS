import pytest

from aeqcs.core.exceptions import GateStateError
from aeqcs.gate.proposals import ProposalStatus
from aeqcs.gate.validator import assert_transition, validate_structure


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
