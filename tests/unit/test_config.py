from copy import deepcopy

import pytest

from aeqcs.core.config import (
    connection_budget,
    load_yaml,
    load_settings,
    memory_resource_budget,
    validate_connection_budget,
    validate_memory_resource_budget,
)
from aeqcs.runtime import batch, intraday


def test_core_settings_exclude_llm_and_cognitive_database():
    settings = load_settings()

    assert "llm" not in settings
    assert "cognitive" not in settings["database"]


def test_embedding_settings_have_cpu_bge_resource_budget():
    embedding = load_settings()["embedding"]

    assert embedding["provider"] == "sentence-transformers"
    assert embedding["model"] == "BAAI/bge-base-zh-v1.5"
    assert embedding["device"] == "cpu"
    assert embedding["max_resident_mb"] <= 1024


def test_resource_settings_document_cgroup_memory_hard_limit():
    resources = load_settings()["resources"]

    assert resources["cgroup_memory_max"] == "16G"


def test_validation_settings_define_rolling_out_of_sample_windows():
    validation = load_settings()["validation"]

    assert validation["train_window_days"] > validation["test_window_days"]
    assert validation["step_days"] == validation["test_window_days"]
    assert validation["embargo_days"] >= 1


def test_memory_resource_budget_counts_embedding_resident_memory():
    budget = memory_resource_budget(load_settings())

    assert budget["cgroup_memory_mb"] == 16384
    assert budget["duckdb_memory_mb"] == 4096
    assert budget["embedding_resident_mb"] == 1024
    assert budget["total_planned_mb"] == 5120
    assert budget["within_limit"] is True


def test_memory_resource_budget_rejects_excessive_embedding_resident_memory():
    settings = deepcopy(load_settings())
    settings["embedding"]["max_resident_mb"] = 14000

    with pytest.raises(ValueError, match="planned resident memory exceeds cgroup_memory_max=16384MB"):
        validate_memory_resource_budget(settings)


def test_pg_connection_budget_stays_under_max_connections():
    budget = connection_budget(load_settings())

    assert budget["max_connections"] == 20
    assert budget["mcp_pool_size"] == 8
    assert budget["batch_connections"] == 4
    assert budget["intraday_connections"] == 4
    assert budget["maintenance_connections"] == 2
    assert budget["reserved_connections"] == 2
    assert budget["total_planned_connections"] == 20
    assert budget["within_limit"] is True


def test_pg_connection_budget_matches_runtime_reservations():
    settings = load_settings()
    budget = settings["database"]["connection_budget"]

    assert budget["batch_connections"] == batch.BATCH_PG_CONNECTIONS
    assert budget["intraday_connections"] == intraday.INTRADAY_PG_CONNECTIONS


def test_pg_connection_budget_rejects_excessive_pool_size():
    settings = deepcopy(load_settings())
    settings["database"]["core"]["pool_size"] = 12

    with pytest.raises(ValueError, match="planned PostgreSQL connections exceed max_connections=20"):
        validate_connection_budget(settings)


def test_data_sources_register_baostock_only_for_minute_and_daily_cross_check():
    config = load_yaml("aeqcs/config/data_sources.yaml")

    assert config["rate_limits"]["baostock"] == {"daily_quota": 50000, "concurrent": False}
    assert config["sources"]["minute"] == "baostock"
    assert config["sources"]["daily_cross_check"] == "baostock"
    assert config["sources"]["financial"] == "tushare"
