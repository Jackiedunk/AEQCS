"""Data source health checks."""

from __future__ import annotations

from datetime import date
from typing import Any

from aeqcs.data.etl.market_data import validate_daily_frame
from aeqcs.data.quality.outlier_detector import detect_daily_outliers


def check_baostock_health(adapter: Any, *, symbol: str, day: date) -> dict[str, Any]:
    """Check baostock by reading a tiny daily fixture/request through normal validation."""

    try:
        frame = adapter.daily(symbol, day, day)
        errors = validate_daily_frame(frame) if not frame.empty else []
        outliers = detect_daily_outliers(frame) if len(frame) > 1 else []
    except Exception as exc:  # pragma: no cover - exercised by runtime integration
        return {
            "source": "baostock",
            "status": "error",
            "rows": 0,
            "errors": [str(exc)],
        }
    status = "ok" if not errors and not outliers and not frame.empty else "degraded"
    return {
        "source": "baostock",
        "status": status,
        "rows": int(len(frame)),
        "errors": errors,
        "outliers": outliers,
    }
