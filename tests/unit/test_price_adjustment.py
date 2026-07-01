from datetime import date

import pandas as pd
import pytest

from aeqcs.data.etl.adjustment import apply_backward_adjustment, apply_dual_price_adjustment


def price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "000001",
                "date": date(2026, 1, 1),
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.0,
                "adj_factor": 1.0,
            },
            {
                "symbol": "000001",
                "date": date(2026, 1, 2),
                "open": 8.0,
                "high": 8.5,
                "low": 7.5,
                "close": 8.0,
                "adj_factor": 1.2,
            },
        ]
    )


def test_backward_adjustment_uses_first_observed_adj_factor_as_base():
    adjusted = apply_backward_adjustment(price_frame())

    assert adjusted[["symbol", "date", "hfq_open", "hfq_high", "hfq_low", "hfq_close"]].to_dict(
        "records"
    ) == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "hfq_open": 10.0,
            "hfq_high": 11.0,
            "hfq_low": 9.5,
            "hfq_close": 10.0,
        },
        {
            "symbol": "000001",
            "date": date(2026, 1, 2),
            "hfq_open": 9.6,
            "hfq_high": 10.2,
            "hfq_low": 9.0,
            "hfq_close": 9.6,
        },
    ]


def test_backward_adjustment_is_append_safe_for_existing_history():
    first_adjusted = apply_backward_adjustment(price_frame())
    extended = pd.concat(
        [
            price_frame(),
            pd.DataFrame(
                [
                    {
                        "symbol": "000001",
                        "date": date(2026, 1, 3),
                        "open": 7.0,
                        "high": 7.5,
                        "low": 6.5,
                        "close": 7.0,
                        "adj_factor": 1.5,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    extended_adjusted = apply_backward_adjustment(extended)

    assert extended_adjusted.iloc[:2][["hfq_open", "hfq_high", "hfq_low", "hfq_close"]].to_dict(
        "records"
    ) == first_adjusted[["hfq_open", "hfq_high", "hfq_low", "hfq_close"]].to_dict("records")


def test_backward_adjustment_uses_symbol_local_base_factor():
    frame = pd.DataFrame(
        [
            {
                "symbol": "000001",
                "date": date(2026, 1, 1),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "adj_factor": 1.0,
            },
            {
                "symbol": "000002",
                "date": date(2026, 1, 1),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "adj_factor": 2.0,
            },
            {
                "symbol": "000002",
                "date": date(2026, 1, 2),
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "adj_factor": 3.0,
            },
        ]
    )

    adjusted = apply_backward_adjustment(frame)

    assert adjusted[["symbol", "date", "hfq_close"]].to_dict("records") == [
        {"symbol": "000001", "date": date(2026, 1, 1), "hfq_close": 10.0},
        {"symbol": "000002", "date": date(2026, 1, 1), "hfq_close": 10.0},
        {"symbol": "000002", "date": date(2026, 1, 2), "hfq_close": 15.0},
    ]


def test_backward_adjustment_requires_adj_factor():
    with pytest.raises(ValueError, match="adj_factor column is required"):
        apply_backward_adjustment(price_frame().drop(columns=["adj_factor"]))


def test_dual_price_adjustment_adds_hfq_for_storage_and_qfq_for_display():
    adjusted = apply_dual_price_adjustment(price_frame())

    assert adjusted[["date", "hfq_close", "qfq_close"]].to_dict("records") == [
        {"date": date(2026, 1, 1), "hfq_close": 10.0, "qfq_close": 8.333333333333},
        {"date": date(2026, 1, 2), "hfq_close": 9.6, "qfq_close": 8.0},
    ]
