from scripts.verify_mcp_backtest_recovery import (
    build_orphaned_backtest_task,
    evaluate_recovery_payload,
)


def test_build_orphaned_backtest_task_creates_running_pg_record():
    task = build_orphaned_backtest_task("recovery-task")

    assert task["task_id"] == "recovery-task"
    assert task["backtest_result_id"] == "recovery-task"
    assert task["status"] == "running"
    assert task["strategy_name"] == "buy_and_hold"
    assert task["parameters"]["symbol"] == "000001"
    assert task["result"] is None
    assert task["error"] is None


def test_evaluate_recovery_payload_accepts_failed_restart_recovery():
    report = evaluate_recovery_payload(
        {
            "task_id": "recovery-task",
            "status": "failed",
            "error": "task recovered as failed after MCP process restart; resubmit backtest",
        },
        "recovery-task",
    )

    assert report == {
        "task_id": "recovery-task",
        "status": "ok",
        "recovered_status": "failed",
        "error": "task recovered as failed after MCP process restart; resubmit backtest",
    }


def test_evaluate_recovery_payload_rejects_still_running_task():
    report = evaluate_recovery_payload(
        {
            "task_id": "recovery-task",
            "status": "running",
            "error": None,
        },
        "recovery-task",
    )

    assert report["status"] == "failed"
    assert report["recovered_status"] == "running"
