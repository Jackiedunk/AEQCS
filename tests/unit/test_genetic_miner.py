from datetime import date

import pandas as pd
import pytest

from aeqcs.core.exceptions import LookAheadViolation
from aeqcs import factor
from aeqcs.factor.genetic_miner import GeneticMinerConfig, mine_genetic_factors


def genetic_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": date(2026, 1, 1), "symbol": "000001", "mom": 0.10, "value": 1.0, "forward_return": 0.02},
            {"date": date(2026, 1, 1), "symbol": "000002", "mom": 0.20, "value": 0.5, "forward_return": 0.03},
            {"date": date(2026, 1, 2), "symbol": "000001", "mom": 0.30, "value": 1.5, "forward_return": 0.05},
            {"date": date(2026, 1, 2), "symbol": "000002", "mom": -0.10, "value": 2.0, "forward_return": -0.01},
        ]
    )


def test_genetic_miner_returns_deterministic_ranked_candidates():
    config = GeneticMinerConfig(seed=7, population_size=8, generations=2, top_k=3)

    first = mine_genetic_factors(
        genetic_frame(),
        feature_columns=["mom", "value"],
        target_column="forward_return",
        as_of_date=date(2026, 1, 2),
        config=config,
    )
    second = mine_genetic_factors(
        genetic_frame(),
        feature_columns=["mom", "value"],
        target_column="forward_return",
        as_of_date=date(2026, 1, 2),
        config=config,
    )

    assert first == second
    assert len(first) == 3
    assert first[0].expression.render() == "mom"
    assert first[0].score == pytest.approx(1.0)
    assert first[0].observations == 4


def test_genetic_miner_is_exported_from_factor_package():
    assert factor.mine_genetic_factors is mine_genetic_factors


def test_genetic_miner_rejects_future_rows():
    frame = pd.concat(
        [
            genetic_frame(),
            pd.DataFrame(
                [
                    {
                        "date": date(2026, 1, 3),
                        "symbol": "000003",
                        "mom": 9.0,
                        "value": 9.0,
                        "forward_return": 9.0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    with pytest.raises(LookAheadViolation):
        mine_genetic_factors(
            frame,
            feature_columns=["mom", "value"],
            target_column="forward_return",
            as_of_date=date(2026, 1, 2),
            config=GeneticMinerConfig(seed=7),
        )


def test_genetic_miner_rejects_missing_required_columns():
    with pytest.raises(ValueError, match="missing columns"):
        mine_genetic_factors(
            genetic_frame().drop(columns=["forward_return"]),
            feature_columns=["mom", "value"],
            target_column="forward_return",
            as_of_date=date(2026, 1, 2),
            config=GeneticMinerConfig(seed=7),
        )
