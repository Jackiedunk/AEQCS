from deploy.init_db import SCHEMA_SQL


def read_deploy_file(path: str) -> str:
    return __import__("pathlib").Path(path).read_text(encoding="utf-8")


def test_doc_chunks_schema_keeps_chunks_attached_to_uploaded_docs():
    assert "doc_id BIGINT NOT NULL REFERENCES uploaded_docs(doc_id) ON DELETE CASCADE" in SCHEMA_SQL
    assert "seq INT NOT NULL" in SCHEMA_SQL
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_chunks_doc_seq" in SCHEMA_SQL


def test_decision_snapshot_schema_uses_core_output_fields_not_llm_fields():
    assert "output_model VARCHAR(50)" in SCHEMA_SQL
    assert "output JSONB" in SCHEMA_SQL
    assert "llm_model" not in SCHEMA_SQL
    assert "llm_output" not in SCHEMA_SQL


def test_hot_tables_have_table_level_autovacuum_settings():
    hot_tables = [
        "minute_bar_hot",
        "factor_values",
        "event_log",
        "event_consumptions",
        "news_raw",
        "proposals",
        "signal_log",
        "cooccurrence_cache",
        "doc_chunks",
    ]

    for table in hot_tables:
        assert f"ALTER TABLE {table} SET (" in SCHEMA_SQL
        assert "autovacuum_vacuum_scale_factor" in SCHEMA_SQL
        assert "autovacuum_analyze_scale_factor" in SCHEMA_SQL


def test_vacuum_maintenance_script_documents_target_tables():
    script = read_deploy_file("deploy/vacuum_maintenance.sql")

    for table in [
        "minute_bar_hot",
        "factor_values",
        "event_log",
        "event_consumptions",
        "proposals",
        "signal_log",
        "cooccurrence_cache",
        "doc_chunks",
    ]:
        assert f"VACUUM (ANALYZE) {table};" in script


def test_vacuum_maintenance_has_systemd_timer_entrypoint():
    service = read_deploy_file("deploy/systemd/db-vacuum.service")
    timer = read_deploy_file("deploy/systemd/db-vacuum.timer")

    assert "psql" in service
    assert "AEQCS_PG_DSN" in service
    assert "deploy/vacuum_maintenance.sql" in service
    assert "OnCalendar=Mon..Fri 23:40:00 Asia/Shanghai" in timer
    assert "Persistent=true" in timer


def test_systemd_services_set_cgroup_memory_hard_limit():
    for service_name in [
        "batch-eod.service",
        "batch-night.service",
        "db-vacuum.service",
        "intraday.service",
        "mcp-server.service",
        "restore-rehearsal.service",
    ]:
        service = read_deploy_file(f"deploy/systemd/{service_name}")

        assert "MemoryMax=16G" in service, service_name


def test_batch_night_has_independent_systemd_timer_entrypoint():
    service = read_deploy_file("deploy/systemd/batch-night.service")
    timer = read_deploy_file("deploy/systemd/batch-night.timer")
    vacuum_timer = read_deploy_file("deploy/systemd/db-vacuum.timer")

    assert "Description=AEQCS nightly batch DAG" in service
    assert "ExecStart=/opt/aeqcs/.venv/bin/python -m aeqcs.runtime.batch night" in service
    assert "OnCalendar=*-*-* 00:30:00 Asia/Shanghai" in timer
    assert "Persistent=true" in timer
    assert "OnCalendar=*-*-* 00:30:00 Asia/Shanghai" not in vacuum_timer


def test_restore_rehearsal_has_systemd_timer_entrypoint():
    service = read_deploy_file("deploy/systemd/restore-rehearsal.service")
    timer = read_deploy_file("deploy/systemd/restore-rehearsal.timer")
    env_template = read_deploy_file("deploy/aeqcs.env.example")

    assert "Description=AEQCS restore rehearsal" in service
    assert "EnvironmentFile=-/etc/aeqcs/aeqcs.env" in service
    assert "AEQCS_RESTORE_PG_DSN=" in env_template
    assert "ExecStart=/opt/aeqcs/.venv/bin/python -m aeqcs.runtime.batch restore-rehearsal" in service
    assert "OnCalendar=Sun 02:30:00 Asia/Shanghai" in timer
    assert "Persistent=true" in timer


def test_mcp_server_systemd_service_uses_sse_loopback_and_restart():
    service = read_deploy_file("deploy/systemd/mcp-server.service")
    env_template = read_deploy_file("deploy/aeqcs.env.example")

    assert "User=aeqcs" in service
    assert "EnvironmentFile=-/etc/aeqcs/aeqcs.env" in service
    assert "AEQCS_MCP_TRANSPORT=sse" in env_template
    assert "AEQCS_MCP_HOST=127.0.0.1" in env_template
    assert "Restart=on-failure" in service
    assert "ExecStart=/opt/aeqcs/.venv/bin/python -m aeqcs.core.mcp_server" in service


def test_semantic_graph_schema_keeps_manual_audit_and_asof_fields():
    assert "CREATE TABLE IF NOT EXISTS semantic_nodes" in SCHEMA_SQL
    assert "label VARCHAR(200)" in SCHEMA_SQL
    assert "level VARCHAR(50)" in SCHEMA_SQL
    assert "created_by VARCHAR(50)" in SCHEMA_SQL
    assert "as_of_date DATE" in SCHEMA_SQL
    assert "status VARCHAR(20)" in SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS semantic_edges" in SCHEMA_SQL
    assert "created_by VARCHAR(50)" in SCHEMA_SQL
    assert "verified_by VARCHAR(50)" in SCHEMA_SQL
    assert "verified_as_of DATE" in SCHEMA_SQL
    assert "retired_by VARCHAR(50)" in SCHEMA_SQL
    assert "valid_from DATE" in SCHEMA_SQL
    assert "valid_to DATE" in SCHEMA_SQL


def test_schema_defines_restricted_mcp_database_role():
    assert "CREATE ROLE aeqcs_core LOGIN PASSWORD 'CHANGE_ME_AEQCS_CORE'" in SCHEMA_SQL
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aeqcs_core" in SCHEMA_SQL
    assert "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO aeqcs_core" in SCHEMA_SQL
    assert "CREATE ROLE aeqcs_mcp LOGIN PASSWORD 'CHANGE_ME_AEQCS_MCP'" in SCHEMA_SQL
    assert "REVOKE ALL ON SCHEMA public FROM aeqcs_mcp" in SCHEMA_SQL
    assert "GRANT USAGE ON SCHEMA public TO aeqcs_mcp" in SCHEMA_SQL
    assert "GRANT SELECT ON stock_daily_origin, adj_factor, financial_indicators" in SCHEMA_SQL
    assert "GRANT SELECT ON index_constituents TO aeqcs_mcp" in SCHEMA_SQL
    assert "TO aeqcs_mcp" in SCHEMA_SQL
    assert "GRANT SELECT, INSERT, UPDATE ON proposals" in SCHEMA_SQL
    assert "GRANT SELECT, INSERT, UPDATE ON semantic_nodes, semantic_edges" in SCHEMA_SQL
    assert "GRANT SELECT, INSERT ON event_log TO aeqcs_mcp" in SCHEMA_SQL
    assert "GRANT SELECT, INSERT ON event_consumptions TO aeqcs_mcp" in SCHEMA_SQL
    assert "GRANT USAGE, SELECT ON SEQUENCE proposals_proposal_id_seq" in SCHEMA_SQL
    assert "GRANT USAGE, SELECT ON SEQUENCE semantic_edges_edge_id_seq" in SCHEMA_SQL


def test_financial_indicators_schema_includes_profitability_margin_factor_inputs():
    assert "gross_margin DECIMAL(8,4)" in SCHEMA_SQL
    assert "net_margin DECIMAL(8,4)" in SCHEMA_SQL


def test_financial_indicators_schema_includes_liquidity_factor_inputs():
    assert "current_ratio DECIMAL(8,4)" in SCHEMA_SQL
    assert "quick_ratio DECIMAL(8,4)" in SCHEMA_SQL


def test_mcp_systemd_service_uses_restricted_pg_dsn_environment():
    service = read_deploy_file("deploy/systemd/mcp-server.service")
    env_template = read_deploy_file("deploy/aeqcs.env.example")

    assert "EnvironmentFile=-/etc/aeqcs/aeqcs.env" in service
    assert "AEQCS_CORE_PG_DSN=postgresql://aeqcs_mcp:CHANGE_ME_AEQCS_MCP@127.0.0.1:5432/aeqcs" in env_template
    assert "AEQCS_MCP_POOL_SIZE=8" in env_template


def test_backtest_tasks_schema_persists_mcp_background_task_state():
    assert "CREATE TABLE IF NOT EXISTS backtest_tasks" in SCHEMA_SQL
    assert "task_id VARCHAR(64) PRIMARY KEY" in SCHEMA_SQL
    assert "status VARCHAR(20)" in SCHEMA_SQL
    assert "strategy_name VARCHAR(100)" in SCHEMA_SQL
    assert "parameters JSONB" in SCHEMA_SQL
    assert "result JSONB" in SCHEMA_SQL
    assert "error TEXT" in SCHEMA_SQL
    assert "created_ts TIMESTAMP" in SCHEMA_SQL
    assert "updated_ts TIMESTAMP" in SCHEMA_SQL
    assert "GRANT SELECT, INSERT, UPDATE ON backtest_tasks TO aeqcs_mcp" in SCHEMA_SQL


def test_backtest_results_schema_persists_order_lifecycle():
    assert "CREATE TABLE IF NOT EXISTS backtest_results" in SCHEMA_SQL
    assert "orders JSONB" in SCHEMA_SQL


def test_corporate_actions_schema_covers_st_name_and_code_changes():
    assert "CREATE TABLE IF NOT EXISTS corporate_actions" in SCHEMA_SQL
    assert "action_type VARCHAR(20)" in SCHEMA_SQL
    assert "old_value VARCHAR(100)" in SCHEMA_SQL
    assert "new_value VARCHAR(100)" in SCHEMA_SQL
    assert "CREATE INDEX IF NOT EXISTS idx_corporate_actions_asof" in SCHEMA_SQL


def test_data_quality_alerts_schema_records_cross_source_mismatches():
    assert "CREATE TABLE IF NOT EXISTS data_quality_alerts" in SCHEMA_SQL
    assert "alert_type VARCHAR(50)" in SCHEMA_SQL
    assert "payload JSONB" in SCHEMA_SQL
    assert "CREATE INDEX IF NOT EXISTS idx_data_quality_alerts_type" in SCHEMA_SQL


def test_event_consumptions_schema_persists_cross_process_idempotency():
    assert "CREATE TABLE IF NOT EXISTS event_consumptions" in SCHEMA_SQL
    assert "event_id VARCHAR(100) REFERENCES event_log(event_id) ON DELETE CASCADE" in SCHEMA_SQL
    assert "consumer_id VARCHAR(100)" in SCHEMA_SQL
    assert "PRIMARY KEY(event_id, consumer_id)" in SCHEMA_SQL
