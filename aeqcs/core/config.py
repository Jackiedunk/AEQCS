"""Configuration loading with environment-variable expansion."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")
MEMORY_SIZE_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)([GMK]I?B?|MB)?$")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default or "")

        return ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return _expand_env(yaml.safe_load(fh) or {})


def load_settings(root: str | Path = ".") -> dict[str, Any]:
    return load_yaml(Path(root) / "aeqcs" / "config" / "settings.yaml")


def _memory_to_mb(value: str | int | float) -> int:
    if isinstance(value, int | float):
        return int(value)
    normalized = value.strip().upper()
    match = MEMORY_SIZE_PATTERN.match(normalized)
    if match is None:
        raise ValueError(f"unsupported memory size: {value}")
    amount = float(match.group(1))
    unit = match.group(2) or "MB"
    if unit in {"G", "GB", "GIB"}:
        return int(amount * 1024)
    if unit in {"M", "MB", "MIB"}:
        return int(amount)
    if unit in {"K", "KB", "KIB"}:
        return int(amount / 1024)
    raise ValueError(f"unsupported memory size: {value}")


def memory_resource_budget(settings: dict[str, Any]) -> dict[str, int | bool]:
    resources = settings["resources"]
    duckdb = settings["duckdb"]
    embedding = settings["embedding"]
    cgroup_memory_mb = _memory_to_mb(resources["cgroup_memory_max"])
    duckdb_memory_mb = _memory_to_mb(duckdb["memory_limit"])
    embedding_resident_mb = int(embedding["max_resident_mb"])
    total = duckdb_memory_mb + embedding_resident_mb
    return {
        "cgroup_memory_mb": cgroup_memory_mb,
        "duckdb_memory_mb": duckdb_memory_mb,
        "embedding_resident_mb": embedding_resident_mb,
        "total_planned_mb": total,
        "within_limit": total <= cgroup_memory_mb,
    }


def validate_memory_resource_budget(settings: dict[str, Any]) -> dict[str, int | bool]:
    budget = memory_resource_budget(settings)
    if not budget["within_limit"]:
        raise ValueError(
            "planned resident memory exceeds "
            f"cgroup_memory_max={budget['cgroup_memory_mb']}MB: {budget['total_planned_mb']}MB"
        )
    return budget


def connection_budget(settings: dict[str, Any]) -> dict[str, int | bool]:
    database = settings["database"]
    core = database["core"]
    budget = database["connection_budget"]
    mcp_pool_size = int(core["pool_size"])
    batch_connections = int(budget["batch_connections"])
    intraday_connections = int(budget["intraday_connections"])
    maintenance_connections = int(budget["maintenance_connections"])
    reserved_connections = int(budget["reserved_connections"])
    max_connections = int(budget["max_connections"])
    total = (
        mcp_pool_size
        + batch_connections
        + intraday_connections
        + maintenance_connections
        + reserved_connections
    )
    return {
        "max_connections": max_connections,
        "mcp_pool_size": mcp_pool_size,
        "batch_connections": batch_connections,
        "intraday_connections": intraday_connections,
        "maintenance_connections": maintenance_connections,
        "reserved_connections": reserved_connections,
        "total_planned_connections": total,
        "within_limit": total <= max_connections,
    }


def validate_connection_budget(settings: dict[str, Any]) -> dict[str, int | bool]:
    budget = connection_budget(settings)
    if not budget["within_limit"]:
        raise ValueError(
            "planned PostgreSQL connections exceed "
            f"max_connections={budget['max_connections']}: {budget['total_planned_connections']}"
        )
    return budget
