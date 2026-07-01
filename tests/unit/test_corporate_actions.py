from datetime import date, datetime

import pandas as pd
import pytest

from aeqcs.data.etl.corporate_actions import corporate_state_as_of, normalize_corporate_actions


def test_corporate_actions_state_tracks_st_name_and_code_changes_as_of_date():
    frame = normalize_corporate_actions(
        pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "effective_date": "2026-01-03",
                    "action_type": "st_add",
                    "old_value": "",
                    "new_value": "ST",
                    "knowledge_ts": datetime(2026, 1, 3, 8),
                },
                {
                    "symbol": "000001",
                    "effective_date": "2026-01-10",
                    "action_type": "name_change",
                    "old_value": "Ping An",
                    "new_value": "Ping An Bank",
                    "knowledge_ts": datetime(2026, 1, 10, 8),
                },
                {
                    "symbol": "000001",
                    "effective_date": "2026-01-15",
                    "action_type": "st_remove",
                    "old_value": "ST",
                    "new_value": "",
                    "knowledge_ts": datetime(2026, 1, 15, 8),
                },
                {
                    "symbol": "000001",
                    "effective_date": "2026-01-20",
                    "action_type": "code_change",
                    "old_value": "000001",
                    "new_value": "001001",
                    "knowledge_ts": datetime(2026, 1, 20, 8),
                },
            ]
        )
    )

    before_remove = corporate_state_as_of(frame, "000001", date(2026, 1, 12))
    after_code_change = corporate_state_as_of(frame, "000001", date(2026, 1, 21))

    assert before_remove["is_st"] is True
    assert before_remove["name"] == "Ping An Bank"
    assert before_remove["current_symbol"] == "000001"
    assert after_code_change["is_st"] is False
    assert after_code_change["current_symbol"] == "001001"


def test_corporate_actions_reject_unknown_action_type():
    with pytest.raises(ValueError, match="unsupported corporate action_type"):
        normalize_corporate_actions(
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "effective_date": "2026-01-03",
                        "action_type": "split",
                        "old_value": "",
                        "new_value": "",
                        "knowledge_ts": datetime(2026, 1, 3, 8),
                    }
                ]
            )
        )
