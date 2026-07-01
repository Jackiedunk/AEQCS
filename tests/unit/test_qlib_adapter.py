from datetime import date

import pandas as pd
import pytest

from aeqcs.core.exceptions import LookAheadViolation
from aeqcs.data.qlib_adapter import (
    QlibBoundaryError,
    build_pit_financial_snapshot,
    ensure_qlib_market_frame_safe,
)


def test_qlib_market_frame_requires_as_of() -> None:
    frame = pd.DataFrame(
        [{"date": date(2026, 1, 1), "instrument": "000001", "close": 10}]
    ).set_index(["date", "instrument"])

    with pytest.raises(LookAheadViolation):
        ensure_qlib_market_frame_safe(frame, as_of_date=None)


def test_qlib_market_frame_rejects_oversized_multiindex_panel() -> None:
    frame = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 2)],
            "instrument": ["000001", "000002", "000001"],
            "close": [10, 20, 11],
        }
    ).set_index(["date", "instrument"])

    with pytest.raises(QlibBoundaryError, match="exceeds Qlib pandas row budget"):
        ensure_qlib_market_frame_safe(frame, as_of_date=date(2026, 1, 2), max_rows=2)


def test_qlib_market_frame_rejects_empty_instrument() -> None:
    frame = pd.DataFrame(
        {
            "date": [date(2026, 1, 1)],
            "instrument": [" "],
            "close": [10],
        }
    ).set_index(["date", "instrument"])

    with pytest.raises(QlibBoundaryError, match="instrument is required"):
        ensure_qlib_market_frame_safe(frame, as_of_date=date(2026, 1, 2))


def test_qlib_market_frame_rejects_invalid_date() -> None:
    frame = pd.DataFrame(
        {
            "date": ["not-a-date"],
            "instrument": ["000001"],
            "close": [10],
        }
    ).set_index(["date", "instrument"])

    with pytest.raises(QlibBoundaryError, match="date must be a valid date"):
        ensure_qlib_market_frame_safe(frame, as_of_date=date(2026, 1, 2))


def test_qlib_market_frame_rejects_duplicate_date_instrument_rows() -> None:
    frame = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 1)],
            "instrument": ["000001", "000001"],
            "close": [10, 11],
        }
    ).set_index(["date", "instrument"])

    with pytest.raises(QlibBoundaryError, match="duplicate date/instrument"):
        ensure_qlib_market_frame_safe(frame, as_of_date=date(2026, 1, 2))


def test_qlib_market_frame_rejects_non_finite_value() -> None:
    frame = pd.DataFrame(
        {
            "date": [date(2026, 1, 1)],
            "instrument": ["000001"],
            "close": [float("nan")],
        }
    ).set_index(["date", "instrument"])

    with pytest.raises(QlibBoundaryError, match="close must be finite"):
        ensure_qlib_market_frame_safe(frame, as_of_date=date(2026, 1, 2))


def test_qlib_market_frame_requires_date_axis() -> None:
    frame = pd.DataFrame(
        {
            "instrument": ["000001"],
            "close": [10],
        }
    ).set_index("instrument")

    with pytest.raises(QlibBoundaryError, match="market panel requires date"):
        ensure_qlib_market_frame_safe(frame, as_of_date=date(2026, 1, 2))


def test_qlib_market_frame_requires_instrument_axis() -> None:
    frame = pd.DataFrame(
        {
            "date": [date(2026, 1, 1)],
            "close": [10],
        }
    ).set_index("date")

    with pytest.raises(QlibBoundaryError, match="market panel requires instrument"):
        ensure_qlib_market_frame_safe(frame, as_of_date=date(2026, 1, 2))


def test_qlib_financial_snapshot_keeps_latest_known_vintage_per_period() -> None:
    frame = pd.DataFrame(
        [
            {
                "instrument": "000001",
                "period": "2025Q4",
                "ann_date": date(2026, 1, 1),
                "vintage": 0,
                "roe": 0.10,
            },
            {
                "instrument": "000001",
                "period": "2025Q4",
                "ann_date": date(2026, 1, 10),
                "vintage": 1,
                "roe": 0.12,
            },
        ]
    )

    snapshot = build_pit_financial_snapshot(frame, as_of_date=date(2026, 1, 15))

    assert snapshot[["instrument", "period", "ann_date", "vintage", "roe"]].to_dict("records") == [
        {
            "instrument": "000001",
            "period": "2025Q4",
            "ann_date": date(2026, 1, 10),
            "vintage": 1,
            "roe": 0.12,
        }
    ]


def test_qlib_financial_snapshot_filters_as_of_and_keeps_latest_known_row() -> None:
    frame = pd.DataFrame(
        [
            {
                "instrument": "000001",
                "period": "2025Q4",
                "ann_date": date(2026, 1, 1),
                "vintage": 0,
                "roe": 0.10,
            },
            {
                "instrument": "000002",
                "period": "2025Q4",
                "ann_date": date(2026, 1, 20),
                "vintage": 0,
                "roe": 0.15,
            },
        ]
    )

    snapshot = build_pit_financial_snapshot(frame, as_of_date=date(2026, 1, 10))

    assert snapshot["instrument"].tolist() == ["000001"]
    assert snapshot.iloc[0]["roe"] == 0.10


def test_qlib_financial_snapshot_rejects_empty_instrument() -> None:
    frame = pd.DataFrame(
        [
            {
                "instrument": " ",
                "period": "2025Q4",
                "ann_date": date(2026, 1, 1),
                "vintage": 0,
                "roe": 0.10,
            }
        ]
    )

    with pytest.raises(QlibBoundaryError, match="instrument is required"):
        build_pit_financial_snapshot(frame, as_of_date=date(2026, 1, 15))


def test_qlib_financial_snapshot_rejects_invalid_vintage() -> None:
    frame = pd.DataFrame(
        [
            {
                "instrument": "000001",
                "period": "2025Q4",
                "ann_date": date(2026, 1, 1),
                "vintage": -1,
                "roe": 0.10,
            }
        ]
    )

    with pytest.raises(QlibBoundaryError, match="vintage must be a non-negative integer"):
        build_pit_financial_snapshot(frame, as_of_date=date(2026, 1, 15))


def test_qlib_financial_snapshot_rejects_duplicate_version_rows() -> None:
    frame = pd.DataFrame(
        [
            {
                "instrument": "000001",
                "period": "2025Q4",
                "ann_date": date(2026, 1, 1),
                "vintage": 0,
                "roe": 0.10,
            },
            {
                "instrument": "000001",
                "period": "2025Q4",
                "ann_date": date(2026, 1, 1),
                "vintage": 0,
                "roe": 0.12,
            },
        ]
    )

    with pytest.raises(QlibBoundaryError, match="duplicate financial version"):
        build_pit_financial_snapshot(frame, as_of_date=date(2026, 1, 15))


def test_qlib_financial_snapshot_rejects_non_finite_metric() -> None:
    frame = pd.DataFrame(
        [
            {
                "instrument": "000001",
                "period": "2025Q4",
                "ann_date": date(2026, 1, 1),
                "vintage": 0,
                "roe": float("inf"),
            }
        ]
    )

    with pytest.raises(QlibBoundaryError, match="roe must be finite"):
        build_pit_financial_snapshot(frame, as_of_date=date(2026, 1, 15))


def test_qlib_adapter_does_not_expose_expression_factor_engine() -> None:
    import aeqcs.data.qlib_adapter as qlib_adapter

    assert not hasattr(qlib_adapter, "compute_qlib_expression_factor_values")
