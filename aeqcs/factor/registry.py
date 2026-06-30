"""Factor registry loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_registry(path: str | Path = "aeqcs/config/factor_registry.yaml") -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return list(data.get("factors", []))
