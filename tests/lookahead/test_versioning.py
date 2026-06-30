from datetime import date

import pytest

from aeqcs.core.exceptions import LookAheadViolation
from aeqcs.core.versioning import assert_not_after, require_as_of


def test_require_as_of_rejects_missing_value():
    with pytest.raises(LookAheadViolation):
        require_as_of(None)


def test_assert_not_after_rejects_future_knowledge():
    with pytest.raises(LookAheadViolation):
        assert_not_after(date(2026, 6, 30), date(2026, 6, 29))
