from scripts.restore_rehearsal_health import build_restore_rehearsal_report


def test_restore_rehearsal_report_wraps_system_health_for_audit():
    report = build_restore_rehearsal_report(
        {
            "status": "ok",
            "backend": "postgresql-restore-rehearsal",
            "resource_budget": {
                "total_planned_mb": 5120,
                "within_limit": True,
            },
        }
    )

    assert report["status"] == "ok"
    assert report["restore_rehearsal"] == {
        "isolated_database": True,
        "backend": "postgresql-restore-rehearsal",
        "system_health_status": "ok",
    }
    assert report["resource_budget"]["within_limit"] is True
    assert report["system_health"]["backend"] == "postgresql-restore-rehearsal"
