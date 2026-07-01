from datetime import date

from aeqcs.runtime import batch


def test_night_dag_serializes_backup_vacuum_hnsw_and_archive_work():
    dag = batch.build_night_dag(retention_months=3)

    assert [task.name for task in dag.tasks] == [
        "backup_snapshot",
        "archive_minute_bar_hot",
        "vacuum_full_window",
        "vacuum_analyze_hot_tables",
        "reindex_hnsw",
        "parse_upload_inbox",
    ]
    assert dag.tasks[1] == batch.BatchTask(
        name="archive_minute_bar_hot",
        command="archive_minute_bar_hot",
        after=("backup_snapshot",),
        resource_group="io",
    )
    assert dag.tasks[2].after == ("archive_minute_bar_hot",)
    assert dag.tasks[3].after == ("vacuum_full_window",)
    assert dag.tasks[4].after == ("vacuum_analyze_hot_tables",)


def test_minute_bar_archive_plan_partitions_by_cutoff_month():
    plan = batch.build_minute_bar_archive_plan(
        today=date(2026, 6, 30),
        retention_months=3,
        archive_root="/data/aeqcs/archive/minute_bar_hot",
    )

    assert plan.cutoff_date == date(2026, 3, 1)
    assert plan.partition_path == "/data/aeqcs/archive/minute_bar_hot/year=2026/month=03"
    assert "COPY (" in plan.copy_sql
    assert "FROM minute_bar_hot" in plan.copy_sql
    assert "ts < DATE '2026-03-01'" in plan.copy_sql
    assert "TO '/data/aeqcs/archive/minute_bar_hot/year=2026/month=03/minute_bar_hot.parquet'" in plan.copy_sql
    assert plan.delete_sql == "DELETE FROM minute_bar_hot WHERE ts < DATE '2026-03-01';"


def test_night_cli_prints_the_resource_order(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["aeqcs-batch", "night"])

    batch.main()

    out = capsys.readouterr().out
    assert "batch-night-retain-3m" in out
    assert "backup_snapshot -> archive_minute_bar_hot" in out
    assert "vacuum_full_window -> vacuum_analyze_hot_tables" in out
    assert "is not wired to production storage yet" not in out


def test_night_cli_prints_auditable_commands(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["aeqcs-batch", "night", "--today", "2026-06-30"])

    batch.main()

    out = capsys.readouterr().out
    assert "backup_snapshot: pg_dump \"$AEQCS_PG_DSN\"" in out
    assert "archive_minute_bar_hot: psql \"$AEQCS_PG_DSN\"" in out
    assert "vacuum_full_window: psql \"$AEQCS_PG_DSN\"" in out
    assert "reindex_hnsw: psql \"$AEQCS_PG_DSN\"" in out


def test_night_command_plan_wires_pg_backup_archive_vacuum_and_hnsw():
    plan = batch.build_night_command_plan(
        today=date(2026, 6, 30),
        retention_months=3,
        archive_root="/data/aeqcs/archive/minute_bar_hot",
        backup_root="/data/backups/aeqcs",
        project_root="/opt/aeqcs",
        pg_dsn_env="AEQCS_PG_DSN",
    )

    commands = {step.task_name: step.command for step in plan.steps}

    assert commands["backup_snapshot"] == (
        "pg_dump \"$AEQCS_PG_DSN\" "
        "-Fc -f /data/backups/aeqcs/2026-06-30/aeqcs.pg.dump"
    )
    assert commands["archive_minute_bar_hot"].startswith(
        "psql \"$AEQCS_PG_DSN\" -v ON_ERROR_STOP=1 -c \"COPY (SELECT * FROM minute_bar_hot"
    )
    assert "DELETE FROM minute_bar_hot WHERE ts < DATE '2026-03-01';" in commands["archive_minute_bar_hot"]
    assert commands["vacuum_full_window"] == (
        "psql \"$AEQCS_PG_DSN\" -v ON_ERROR_STOP=1 "
        "-c \"VACUUM FULL minute_bar_hot; VACUUM FULL factor_values; VACUUM FULL event_log; "
        "VACUUM FULL proposals; VACUUM FULL signal_log; VACUUM FULL cooccurrence_cache;\""
    )
    assert commands["vacuum_analyze_hot_tables"] == (
        "psql \"$AEQCS_PG_DSN\" -v ON_ERROR_STOP=1 "
        "-f /opt/aeqcs/deploy/vacuum_maintenance.sql"
    )
    assert commands["reindex_hnsw"] == (
        "psql \"$AEQCS_PG_DSN\" -v ON_ERROR_STOP=1 "
        "-c \"REINDEX INDEX CONCURRENTLY idx_sn_hnsw; REINDEX INDEX CONCURRENTLY idx_chunk_hnsw;\""
    )

    assert [step.task_name for step in plan.steps] == [task.name for task in batch.build_night_dag(retention_months=3).tasks]


def test_restore_rehearsal_plan_restores_dump_verifies_parquet_and_runs_health():
    plan = batch.build_restore_rehearsal_plan(
        backup_date=date(2026, 6, 30),
        backup_root="/data/backups/aeqcs",
        parquet_snapshot_root="/data/aeqcs/archive/minute_bar_hot",
        project_root="/opt/aeqcs",
        restore_pg_dsn_env="AEQCS_RESTORE_PG_DSN",
    )

    commands = {step.name: step.command for step in plan.steps}

    assert [step.name for step in plan.steps] == [
        "restore_pg_dump",
        "verify_parquet_snapshot",
        "run_system_health",
    ]
    assert commands["restore_pg_dump"] == (
        "pg_restore --clean --if-exists --no-owner "
        "--dbname \"$AEQCS_RESTORE_PG_DSN\" /data/backups/aeqcs/2026-06-30/aeqcs.pg.dump"
    )
    assert commands["verify_parquet_snapshot"] == (
        "duckdb -c \"SELECT COUNT(*) AS rows "
        "FROM read_parquet('/data/aeqcs/archive/minute_bar_hot/**/*.parquet');\""
    )
    assert commands["run_system_health"] == (
        "AEQCS_RESTORE_PG_DSN=\"$AEQCS_RESTORE_PG_DSN\" "
        "/opt/aeqcs/.venv/bin/python -m scripts.restore_rehearsal_health"
    )


def test_restore_rehearsal_cli_prints_auditable_commands(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["aeqcs-batch", "restore-rehearsal", "--backup-date", "2026-06-30"],
    )

    batch.main()

    out = capsys.readouterr().out
    assert "restore-rehearsal-2026-06-30" in out
    assert "restore_pg_dump: pg_restore --clean --if-exists --no-owner" in out
    assert "verify_parquet_snapshot: duckdb -c" in out
    assert "run_system_health: AEQCS_RESTORE_PG_DSN" in out


def test_minute_backfill_dry_run_scales_sample_calls_against_daily_quota():
    estimate = batch.estimate_minute_backfill_calls(
        sample_request_counts={"sh.000001": 18, "sz.000001": 20},
        total_symbols=5200,
        daily_quota=50000,
    )

    assert estimate.average_calls_per_symbol == 19
    assert estimate.estimated_total_calls == 98800
    assert estimate.exceeds_daily_quota is True


class CountingMinuteAdapter:
    def __init__(self):
        self.calls = []

    def estimate_minute_history_request_count(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        return 18 if symbol == "sh.000001" else 20


def test_minute_backfill_dry_run_records_sample_request_counts_before_bulk_backfill():
    estimate = batch.run_minute_backfill_dry_run(
        adapter=CountingMinuteAdapter(),
        sample_symbols=("sh.000001", "sz.000001"),
        start=date(2020, 1, 1),
        end=date(2026, 1, 1),
        total_symbols=5200,
        daily_quota=50000,
    )

    assert estimate.sample_request_counts == {"sh.000001": 18, "sz.000001": 20}
    assert estimate.estimated_total_calls == 98800


def test_minute_backfill_resume_plan_uses_checkpoint_when_estimate_exceeds_quota():
    plan = batch.build_minute_backfill_resume_plan(
        estimate=batch.MinuteBackfillEstimate(
            sample_symbols=("sh.000001", "sz.000001"),
            sample_request_counts={"sh.000001": 18, "sz.000001": 20},
            total_symbols=5200,
            daily_quota=50000,
            average_calls_per_symbol=19,
            estimated_total_calls=98800,
            exceeds_daily_quota=True,
        ),
        checkpoint_path="/data/aeqcs/runtime/minute_backfill_checkpoint.json",
        source="baostock",
    )

    assert plan.requires_resume is True
    assert plan.source == "baostock"
    assert plan.checkpoint_path == "/data/aeqcs/runtime/minute_backfill_checkpoint.json"
    assert "minute_backfill_resume" in plan.command
    assert "--checkpoint /data/aeqcs/runtime/minute_backfill_checkpoint.json" in plan.command
