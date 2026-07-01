import pytest

from aeqcs.factor.registry import load_factor_specs


def test_load_factor_specs_includes_engine_window_and_preprocess_steps():
    specs = load_factor_specs("aeqcs/config/factor_registry.yaml")

    assert specs["momentum_20d"].engine == "duckdb"
    assert specs["momentum_20d"].factor_type == "alpha"
    assert specs["momentum_20d"].preprocess == ["winsorize", "industry_neutralize", "zscore"]
    assert specs["momentum_20d"].window_type == "historical"
    assert specs["momentum_20d"].lookback_days == 20
    assert specs["momentum_1d"].compute == "close / lag(close, 1) - 1"
    assert specs["momentum_1d"].lookback_days == 1
    assert specs["roe_quarterly"].compute == "financials.roe"
    assert specs["debt_ratio_quarterly"].compute == "financials.debt_ratio"
    assert specs["profit_yoy_quarterly"].compute == "financials.profit_yoy"
    assert specs["current_ratio_quarterly"].compute == "financials.current_ratio"
    assert specs["quick_ratio_quarterly"].compute == "financials.quick_ratio"
    assert specs["revenue_yoy_quarterly"].compute == "financials.revenue_yoy"
    assert specs["eps_quarterly"].compute == "financials.eps"
    assert specs["bps_quarterly"].compute == "financials.bps"
    assert specs["gross_margin_quarterly"].compute == "financials.gross_margin"
    assert specs["net_margin_quarterly"].compute == "financials.net_margin"
    assert specs["equity_ratio_quarterly"].compute == "1 - financials.debt_ratio"
    assert specs["debt_to_equity_quarterly"].compute == "financials.debt_ratio / (1 - financials.debt_ratio)"
    assert specs["risk_size"].factor_type == "risk"
    assert specs["risk_industry_l1"].category == "industry"


def test_load_factor_specs_requires_explicit_window_type(tmp_path):
    registry = tmp_path / "factor_registry.yaml"
    registry.write_text(
        """
factors:
  - id: missing_window
    category: technical
    engine: duckdb
    compute: close / ref(close, 1) - 1
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="window_type is required"):
        load_factor_specs(registry)


def test_load_factor_specs_rejects_invalid_lookback_days(tmp_path):
    registry = tmp_path / "factor_registry.yaml"
    registry.write_text(
        """
factors:
  - id: bad_lookback
    category: technical
    engine: duckdb
    compute: close / ref(close, 1) - 1
    window_type: historical
    lookback_days: 0
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="factor bad_lookback lookback_days must be positive"):
        load_factor_specs(registry)


def test_load_factor_specs_rejects_duckdb_lookback_below_builtin_window(tmp_path):
    registry = tmp_path / "factor_registry.yaml"
    registry.write_text(
        """
factors:
  - id: momentum_20d
    category: technical
    engine: duckdb
    compute: close / lag(close, 20) - 1
    window_type: historical
    lookback_days: 1
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="factor momentum_20d lookback_days must be at least 20"):
        load_factor_specs(registry)
