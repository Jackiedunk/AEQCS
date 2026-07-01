"""Batch task entrypoint."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import PurePosixPath

from aeqcs.strategy.backtest.engine import run_daily_backtest
from aeqcs.strategy.base import BuyAndHoldStrategy


BATCH_PG_CONNECTIONS = 4


@dataclass(frozen=True)
class BatchTask:
    name: str
    command: str
    after: tuple[str, ...] = ()
    resource_group: str = "general"


@dataclass(frozen=True)
class BatchDag:
    name: str
    tasks: tuple[BatchTask, ...]


@dataclass(frozen=True)
class MinuteBarArchivePlan:
    cutoff_date: date
    partition_path: str
    copy_sql: str
    delete_sql: str


@dataclass(frozen=True)
class BatchCommandStep:
    task_name: str
    command: str


@dataclass(frozen=True)
class NightCommandPlan:
    dag: BatchDag
    steps: tuple[BatchCommandStep, ...]


@dataclass(frozen=True)
class RestoreRehearsalStep:
    name: str
    command: str


@dataclass(frozen=True)
class RestoreRehearsalPlan:
    name: str
    steps: tuple[RestoreRehearsalStep, ...]


@dataclass(frozen=True)
class MinuteBackfillEstimate:
    sample_symbols: tuple[str, ...]
    sample_request_counts: dict[str, int]
    total_symbols: int
    daily_quota: int
    average_calls_per_symbol: int
    estimated_total_calls: int
    exceeds_daily_quota: bool


@dataclass(frozen=True)
class MinuteBackfillResumePlan:
    source: str
    checkpoint_path: str
    requires_resume: bool
    command: str


def _subtract_months(value: date, months: int) -> date:
    month_index = (value.year * 12 + value.month - 1) - months
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def build_night_dag(*, retention_months: int) -> BatchDag:
    if retention_months < 1:
        raise ValueError("retention_months must be positive")

    tasks = (
        BatchTask(
            name="backup_snapshot",
            command="backup_pg_and_parquet_snapshot",
            resource_group="io",
        ),
        BatchTask(
            name="archive_minute_bar_hot",
            command="archive_minute_bar_hot",
            after=("backup_snapshot",),
            resource_group="io",
        ),
        BatchTask(
            name="vacuum_full_window",
            command="vacuum_full_hot_tables",
            after=("archive_minute_bar_hot",),
            resource_group="postgres",
        ),
        BatchTask(
            name="vacuum_analyze_hot_tables",
            command="vacuum_analyze_hot_tables",
            after=("vacuum_full_window",),
            resource_group="postgres",
        ),
        BatchTask(
            name="reindex_hnsw",
            command="reindex_hnsw_vectors",
            after=("vacuum_analyze_hot_tables",),
            resource_group="postgres",
        ),
        BatchTask(
            name="parse_upload_inbox",
            command="parse_upload_inbox",
            after=("reindex_hnsw",),
            resource_group="cpu",
        ),
    )
    return BatchDag(name=f"batch-night-retain-{retention_months}m", tasks=tasks)


def build_minute_bar_archive_plan(
    *,
    today: date,
    retention_months: int,
    archive_root: str,
) -> MinuteBarArchivePlan:
    if retention_months < 1:
        raise ValueError("retention_months must be positive")
    if not archive_root:
        raise ValueError("archive_root is required")

    cutoff = _subtract_months(today, retention_months)
    partition = PurePosixPath(archive_root) / f"year={cutoff.year:04d}" / f"month={cutoff.month:02d}"
    parquet_path = partition / "minute_bar_hot.parquet"
    cutoff_literal = cutoff.isoformat()
    copy_sql = (
        "COPY ("
        "SELECT * FROM minute_bar_hot "
        f"WHERE ts < DATE '{cutoff_literal}' "
        "ORDER BY ts, symbol"
        f") TO '{parquet_path}' (FORMAT PARQUET);"
    )
    delete_sql = f"DELETE FROM minute_bar_hot WHERE ts < DATE '{cutoff_literal}';"
    return MinuteBarArchivePlan(
        cutoff_date=cutoff,
        partition_path=str(partition),
        copy_sql=copy_sql,
        delete_sql=delete_sql,
    )


def build_night_command_plan(
    *,
    today: date,
    retention_months: int,
    archive_root: str,
    backup_root: str,
    project_root: str,
    pg_dsn_env: str,
) -> NightCommandPlan:
    if not backup_root:
        raise ValueError("backup_root is required")
    if not project_root:
        raise ValueError("project_root is required")
    if not pg_dsn_env:
        raise ValueError("pg_dsn_env is required")

    dag = build_night_dag(retention_months=retention_months)
    archive = build_minute_bar_archive_plan(
        today=today,
        retention_months=retention_months,
        archive_root=archive_root,
    )
    backup_dir = PurePosixPath(backup_root) / today.isoformat()
    env_ref = f'"${pg_dsn_env}"'
    psql = f"psql {env_ref} -v ON_ERROR_STOP=1"
    vacuum_full_tables = (
        "minute_bar_hot",
        "factor_values",
        "event_log",
        "proposals",
        "signal_log",
        "cooccurrence_cache",
    )
    vacuum_full_sql = " ".join(f"VACUUM FULL {table};" for table in vacuum_full_tables)
    archive_sql = f"{archive.copy_sql} {archive.delete_sql}"

    commands = {
        "backup_snapshot": f"pg_dump {env_ref} -Fc -f {backup_dir / 'aeqcs.pg.dump'}",
        "archive_minute_bar_hot": f'{psql} -c "{archive_sql}"',
        "vacuum_full_window": f'{psql} -c "{vacuum_full_sql}"',
        "vacuum_analyze_hot_tables": f"{psql} -f {PurePosixPath(project_root) / 'deploy' / 'vacuum_maintenance.sql'}",
        "reindex_hnsw": f'{psql} -c "REINDEX INDEX CONCURRENTLY idx_sn_hnsw; REINDEX INDEX CONCURRENTLY idx_chunk_hnsw;"',
        "parse_upload_inbox": f"{PurePosixPath(project_root) / '.venv' / 'bin' / 'python'} -m aeqcs.runtime.batch eod",
    }
    steps = tuple(BatchCommandStep(task_name=task.name, command=commands[task.name]) for task in dag.tasks)
    return NightCommandPlan(dag=dag, steps=steps)


def build_restore_rehearsal_plan(
    *,
    backup_date: date,
    backup_root: str,
    parquet_snapshot_root: str,
    project_root: str,
    restore_pg_dsn_env: str,
) -> RestoreRehearsalPlan:
    if not backup_root:
        raise ValueError("backup_root is required")
    if not parquet_snapshot_root:
        raise ValueError("parquet_snapshot_root is required")
    if not project_root:
        raise ValueError("project_root is required")
    if not restore_pg_dsn_env:
        raise ValueError("restore_pg_dsn_env is required")

    backup_dir = PurePosixPath(backup_root) / backup_date.isoformat()
    dump_path = backup_dir / "aeqcs.pg.dump"
    parquet_glob = PurePosixPath(parquet_snapshot_root) / "**" / "*.parquet"
    python_path = PurePosixPath(project_root) / ".venv" / "bin" / "python"
    env_ref = f'"${restore_pg_dsn_env}"'
    steps = (
        RestoreRehearsalStep(
            name="restore_pg_dump",
            command=(
                "pg_restore --clean --if-exists --no-owner "
                f"--dbname {env_ref} {dump_path}"
            ),
        ),
        RestoreRehearsalStep(
            name="verify_parquet_snapshot",
            command=(
                "duckdb -c \"SELECT COUNT(*) AS rows "
                f"FROM read_parquet('{parquet_glob}');\""
            ),
        ),
        RestoreRehearsalStep(
            name="run_system_health",
            command=(
                f"{restore_pg_dsn_env}={env_ref} "
                f"{python_path} -m scripts.restore_rehearsal_health"
            ),
        ),
    )
    return RestoreRehearsalPlan(name=f"restore-rehearsal-{backup_date.isoformat()}", steps=steps)


def estimate_minute_backfill_calls(
    *,
    sample_request_counts: dict[str, int],
    total_symbols: int,
    daily_quota: int,
) -> MinuteBackfillEstimate:
    if not sample_request_counts:
        raise ValueError("sample_request_counts is required")
    if total_symbols < 1:
        raise ValueError("total_symbols must be positive")
    if daily_quota < 1:
        raise ValueError("daily_quota must be positive")
    if any(count < 1 for count in sample_request_counts.values()):
        raise ValueError("sample request counts must be positive")

    average = round(sum(sample_request_counts.values()) / len(sample_request_counts))
    estimated_total = average * total_symbols
    return MinuteBackfillEstimate(
        sample_symbols=tuple(sample_request_counts),
        sample_request_counts=dict(sample_request_counts),
        total_symbols=total_symbols,
        daily_quota=daily_quota,
        average_calls_per_symbol=average,
        estimated_total_calls=estimated_total,
        exceeds_daily_quota=estimated_total > daily_quota,
    )


def run_minute_backfill_dry_run(
    *,
    adapter: object,
    sample_symbols: tuple[str, ...],
    start: date,
    end: date,
    total_symbols: int,
    daily_quota: int,
) -> MinuteBackfillEstimate:
    if not sample_symbols:
        raise ValueError("sample_symbols is required")
    if start > end:
        raise ValueError("start must be on or before end")
    counter = getattr(adapter, "estimate_minute_history_request_count", None)
    if counter is None:
        raise ValueError("adapter must implement estimate_minute_history_request_count")
    counts = {
        symbol: int(counter(symbol, start, end))
        for symbol in sample_symbols
    }
    return estimate_minute_backfill_calls(
        sample_request_counts=counts,
        total_symbols=total_symbols,
        daily_quota=daily_quota,
    )


def build_minute_backfill_resume_plan(
    *,
    estimate: MinuteBackfillEstimate,
    checkpoint_path: str,
    source: str,
) -> MinuteBackfillResumePlan:
    if not checkpoint_path:
        raise ValueError("checkpoint_path is required")
    if not source:
        raise ValueError("source is required")
    command = (
        "minute_backfill_resume "
        f"--source {source} "
        f"--checkpoint {checkpoint_path} "
        f"--daily-quota {estimate.daily_quota}"
    )
    return MinuteBackfillResumePlan(
        source=source,
        checkpoint_path=checkpoint_path,
        requires_resume=estimate.exceeds_daily_quota,
        command=command,
    )


def run_smoke() -> None:
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "11", "close": "12"},
        {"symbol": "000001", "date": date(2026, 1, 5), "open": "12", "close": "11.8"},
    ]
    result = run_daily_backtest(panel, BuyAndHoldStrategy("000001"), Decimal("1000000"))
    print({"fills": [asdict(fill) for fill in result.fills], "nav": result.nav})


def run_night(
    *,
    today: date | None = None,
    retention_months: int = 3,
    archive_root: str = "/data/aeqcs/archive/minute_bar_hot",
    backup_root: str = "/data/backups/aeqcs",
    project_root: str = "/opt/aeqcs",
    pg_dsn_env: str = "AEQCS_PG_DSN",
) -> None:
    run_date = today or date.today()
    dag = build_night_dag(retention_months=retention_months)
    plan = build_night_command_plan(
        today=run_date,
        retention_months=retention_months,
        archive_root=archive_root,
        backup_root=backup_root,
        project_root=project_root,
        pg_dsn_env=pg_dsn_env,
    )
    task_names = [task.name for task in dag.tasks]
    print(dag.name)
    print(" -> ".join(task_names))
    for step in plan.steps:
        print(f"{step.task_name}: {step.command}")


def run_restore_rehearsal(
    *,
    backup_date: date,
    backup_root: str = "/data/backups/aeqcs",
    parquet_snapshot_root: str = "/data/aeqcs/archive/minute_bar_hot",
    project_root: str = "/opt/aeqcs",
    restore_pg_dsn_env: str = "AEQCS_RESTORE_PG_DSN",
) -> None:
    plan = build_restore_rehearsal_plan(
        backup_date=backup_date,
        backup_root=backup_root,
        parquet_snapshot_root=parquet_snapshot_root,
        project_root=project_root,
        restore_pg_dsn_env=restore_pg_dsn_env,
    )
    print(plan.name)
    for step in plan.steps:
        print(f"{step.name}: {step.command}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="aeqcs-batch")
    parser.add_argument("job", nargs="?", default="smoke", choices=["smoke", "pre", "eod", "night", "restore-rehearsal"])
    parser.add_argument("--today", help="Run date for deterministic batch plans, YYYY-MM-DD")
    parser.add_argument("--backup-date", help="Backup date for restore rehearsal plans, YYYY-MM-DD")
    parser.add_argument("--retention-months", type=int, default=3)
    parser.add_argument("--archive-root", default="/data/aeqcs/archive/minute_bar_hot")
    parser.add_argument("--backup-root", default="/data/backups/aeqcs")
    parser.add_argument("--project-root", default="/opt/aeqcs")
    parser.add_argument("--pg-dsn-env", default="AEQCS_PG_DSN")
    parser.add_argument("--restore-pg-dsn-env", default="AEQCS_RESTORE_PG_DSN")
    args = parser.parse_args()
    if args.job == "smoke":
        run_smoke()
        return
    if args.job == "night":
        run_date = date.fromisoformat(args.today) if args.today else None
        run_night(
            today=run_date,
            retention_months=args.retention_months,
            archive_root=args.archive_root,
            backup_root=args.backup_root,
            project_root=args.project_root,
            pg_dsn_env=args.pg_dsn_env,
        )
        return
    if args.job == "restore-rehearsal":
        backup_date = date.fromisoformat(args.backup_date) if args.backup_date else date.today()
        run_restore_rehearsal(
            backup_date=backup_date,
            backup_root=args.backup_root,
            parquet_snapshot_root=args.archive_root,
            project_root=args.project_root,
            restore_pg_dsn_env=args.restore_pg_dsn_env,
        )
        return
    print(f"AEQCS batch job '{args.job}' is not wired to production storage yet")


if __name__ == "__main__":
    main()
