"""Factor registry helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from aeqcs.factor.pipeline import DUCKDB_FACTOR_WINDOWS


@dataclass(frozen=True)
class FactorSpec:
    factor_id: str
    category: str
    engine: str
    compute: str
    window_type: str
    preprocess: list[str]
    align: str | None = None
    update_freq: str | None = None
    lookback_days: int | None = None
    factor_type: str = "alpha"


def load_factor_specs(path: str | Path) -> dict[str, FactorSpec]:
    with Path(path).open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    specs: dict[str, FactorSpec] = {}
    for factor in payload.get("factors", []):
        if not isinstance(factor, dict):
            continue
        factor_id = factor.get("id")
        if not isinstance(factor_id, str):
            continue
        if not isinstance(factor.get("window_type"), str):
            raise ValueError(f"factor {factor_id} window_type is required")
        lookback_days = factor.get("lookback_days")
        if lookback_days is not None:
            if not isinstance(lookback_days, int) or isinstance(lookback_days, bool) or lookback_days <= 0:
                raise ValueError(f"factor {factor_id} lookback_days must be positive")
            minimum_lookback = DUCKDB_FACTOR_WINDOWS.get(factor_id)
            if minimum_lookback is not None and lookback_days < minimum_lookback:
                raise ValueError(
                    f"factor {factor_id} lookback_days must be at least {minimum_lookback}"
                )
        preprocess = factor.get("preprocess", [])
        factor_type = str(factor.get("factor_type", "alpha"))
        if factor_type not in {"alpha", "risk"}:
            raise ValueError(f"factor {factor_id} factor_type must be alpha or risk")
        specs[factor_id] = FactorSpec(
            factor_id=factor_id,
            category=str(factor.get("category", "")),
            factor_type=factor_type,
            engine=str(factor.get("engine", "duckdb")),
            compute=str(factor.get("compute", "")),
            window_type=factor["window_type"],
            preprocess=[str(step) for step in preprocess] if isinstance(preprocess, list) else [],
            align=factor.get("align") if isinstance(factor.get("align"), str) else None,
            update_freq=factor.get("update_freq") if isinstance(factor.get("update_freq"), str) else None,
            lookback_days=lookback_days,
        )
    return specs
