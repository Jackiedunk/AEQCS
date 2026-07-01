"""Initialize AEQCS PostgreSQL schema.

Run this on the target host with a superuser DSN:

    python deploy/init_db.py postgresql://postgres@localhost/postgres
"""

from __future__ import annotations

import asyncio
import sys

import asyncpg

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS stock_daily_origin (
  symbol VARCHAR(10), date DATE,
  open DECIMAL(10,3), high DECIMAL(10,3), low DECIMAL(10,3), close DECIMAL(10,3),
  volume BIGINT, amount DECIMAL(20,2),
  PRIMARY KEY (symbol,date)
);
SELECT create_hypertable('stock_daily_origin','date', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS minute_bar_hot (
  symbol VARCHAR(10), ts TIMESTAMP,
  open DECIMAL(10,3), high DECIMAL(10,3), low DECIMAL(10,3), close DECIMAL(10,3),
  volume BIGINT, pre_close DECIMAL(10,3),
  high_limit DECIMAL(10,3), low_limit DECIMAL(10,3),
  bid_volume BIGINT, is_one_word_limit BOOLEAN,
  PRIMARY KEY (symbol,ts)
);
SELECT create_hypertable('minute_bar_hot','ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS adj_factor (
  symbol VARCHAR(10), date DATE, factor DECIMAL(12,6), PRIMARY KEY(symbol,date)
);

CREATE TABLE IF NOT EXISTS stock_universe (
  symbol VARCHAR(10) PRIMARY KEY, name VARCHAR(50),
  ipo_date DATE, delist_date DATE, status VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
  symbol VARCHAR(10), effective_date DATE, action_type VARCHAR(20),
  old_value VARCHAR(100), new_value VARCHAR(100), knowledge_ts TIMESTAMP,
  source VARCHAR(50),
  PRIMARY KEY(symbol,effective_date,action_type,knowledge_ts)
);
CREATE INDEX IF NOT EXISTS idx_corporate_actions_asof
  ON corporate_actions(symbol,effective_date,knowledge_ts);

CREATE TABLE IF NOT EXISTS suspend_info (
  symbol VARCHAR(10), date DATE, is_suspend BOOLEAN, PRIMARY KEY(symbol,date)
);

CREATE TABLE IF NOT EXISTS index_constituents (
  index_code VARCHAR(10), symbol VARCHAR(10), in_date DATE, out_date DATE,
  PRIMARY KEY(index_code,symbol,in_date)
);

CREATE TABLE IF NOT EXISTS financial_indicators (
  symbol VARCHAR(10), period VARCHAR(10), ann_date DATE, vintage INT DEFAULT 0,
  roe DECIMAL(8,4), eps DECIMAL(8,4), bps DECIMAL(8,4),
  revenue_yoy DECIMAL(8,4), profit_yoy DECIMAL(8,4),
  debt_ratio DECIMAL(8,4), current_ratio DECIMAL(8,4), quick_ratio DECIMAL(8,4),
  gross_margin DECIMAL(8,4), net_margin DECIMAL(8,4),
  PRIMARY KEY(symbol,period,ann_date,vintage)
);
CREATE INDEX IF NOT EXISTS idx_fin_asof
  ON financial_indicators(symbol,period,ann_date DESC,vintage DESC);

CREATE TABLE IF NOT EXISTS news_raw (
  id BIGSERIAL PRIMARY KEY, timestamp TIMESTAMP, knowledge_ts TIMESTAMP,
  source VARCHAR(50), level CHAR(1), title TEXT, content TEXT,
  entities JSONB, sentiment DECIMAL(3,2)
);

CREATE TABLE IF NOT EXISTS factor_registry (
  factor_id VARCHAR(50), version INT DEFAULT 1, name VARCHAR(100), category VARCHAR(50),
  description TEXT, data_dependency JSONB, preprocessing JSONB, status VARCHAR(20),
  ic_12m DECIMAL(6,4), ic_ir DECIMAL(6,4), created_date DATE, last_evaluated DATE,
  PRIMARY KEY(factor_id,version)
);

CREATE TABLE IF NOT EXISTS factor_values (
  symbol VARCHAR(10), date DATE, factor_id VARCHAR(50), version INT DEFAULT 1,
  value DECIMAL(12,6), calc_timestamp TIMESTAMP,
  PRIMARY KEY(symbol,date,factor_id,version)
);

CREATE TABLE IF NOT EXISTS semantic_nodes (
  node_id VARCHAR(100) PRIMARY KEY, label VARCHAR(200), level VARCHAR(50),
  created_by VARCHAR(50), as_of_date DATE, status VARCHAR(20) DEFAULT 'active',
  embedding vector(768), embed_model VARCHAR(50), aliases JSONB, created_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sn_hnsw
  ON semantic_nodes USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS semantic_edges (
  edge_id BIGSERIAL PRIMARY KEY, parent_id VARCHAR(100), child_id VARCHAR(100),
  relation_type VARCHAR(50), revenue_share DECIMAL(5,4),
  source VARCHAR(50), confidence DECIMAL(4,3), created_by VARCHAR(50),
  verified BOOLEAN DEFAULT FALSE, verified_by VARCHAR(50), verified_as_of DATE,
  retired_by VARCHAR(50), valid_from DATE, valid_to DATE
);
CREATE INDEX IF NOT EXISTS idx_se_parent ON semantic_edges(parent_id) WHERE verified;
CREATE INDEX IF NOT EXISTS idx_se_child ON semantic_edges(child_id) WHERE verified;

CREATE TABLE IF NOT EXISTS cooccurrence_cache (
  concept VARCHAR(100), symbol VARCHAR(10), date DATE, frequency INT,
  PRIMARY KEY(concept,symbol,date)
);

CREATE TABLE IF NOT EXISTS theme_lifecycle (
  theme_id VARCHAR(100) PRIMARY KEY, name VARCHAR(200), stage VARCHAR(20),
  first_detected TIMESTAMP, last_active TIMESTAMP
);

CREATE TABLE IF NOT EXISTS proposals (
  proposal_id BIGSERIAL PRIMARY KEY, created_ts TIMESTAMP,
  kind VARCHAR(50), payload JSONB, source VARCHAR(50), confidence DECIMAL(4,3),
  snapshot_id BIGINT, status VARCHAR(20) DEFAULT 'pending',
  backtest_result JSONB, reviewed_by VARCHAR(50), reviewed_ts TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_prop_status ON proposals(status,kind);

CREATE TABLE IF NOT EXISTS data_quality_alerts (
  alert_id BIGSERIAL PRIMARY KEY, created_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  alert_type VARCHAR(50), severity VARCHAR(20), source VARCHAR(50),
  symbol VARCHAR(10), date DATE, payload JSONB
);
CREATE INDEX IF NOT EXISTS idx_data_quality_alerts_type
  ON data_quality_alerts(alert_type, created_ts DESC);

CREATE TABLE IF NOT EXISTS decision_snapshot (
  snapshot_id BIGSERIAL PRIMARY KEY, decision_ts TIMESTAMP, role VARCHAR(50),
  input_hash VARCHAR(64), input JSONB, output_model VARCHAR(50), output JSONB,
  embed_model VARCHAR(50)
);
CREATE INDEX IF NOT EXISTS idx_snap_hash ON decision_snapshot(input_hash);

CREATE TABLE IF NOT EXISTS uploaded_docs (
  doc_id BIGSERIAL PRIMARY KEY, uploaded_ts TIMESTAMP, filename TEXT,
  doc_type VARCHAR(20), path TEXT, sha256 VARCHAR(64) UNIQUE,
  status VARCHAR(20) DEFAULT 'parsed', meta JSONB
);

CREATE TABLE IF NOT EXISTS doc_chunks (
  chunk_id BIGSERIAL PRIMARY KEY,
  doc_id BIGINT NOT NULL REFERENCES uploaded_docs(doc_id) ON DELETE CASCADE,
  seq INT NOT NULL,
  text TEXT,
  embedding vector(768), embed_model VARCHAR(50)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_chunks_doc_seq ON doc_chunks(doc_id, seq);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc_id ON doc_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunk_hnsw
  ON doc_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS memory_store (
  mem_id BIGSERIAL PRIMARY KEY, layer VARCHAR(20), role VARCHAR(50),
  content JSONB, embedding vector(768), created_ts TIMESTAMP, feedback_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signal_log (
  signal_id BIGSERIAL PRIMARY KEY, timestamp TIMESTAMP,
  strategy_id VARCHAR(50), symbol VARCHAR(10), score DECIMAL(8,6), source_tags JSONB
);

CREATE TABLE IF NOT EXISTS order_fill_log (
  fill_id BIGSERIAL PRIMARY KEY, timestamp TIMESTAMP,
  symbol VARCHAR(10), side VARCHAR(5), quantity INT, price DECIMAL(10,3), fee DECIMAL(10,3)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshot (
  date DATE PRIMARY KEY, cash DECIMAL(20,2), positions_value DECIMAL(20,2),
  nav DECIMAL(20,4), drawdown DECIMAL(8,4)
);

CREATE TABLE IF NOT EXISTS backtest_results (
  backtest_result_id VARCHAR(64) PRIMARY KEY,
  strategy_name VARCHAR(100),
  start_date DATE,
  end_date DATE,
  as_of_date DATE,
  parameters JSONB,
  fills JSONB,
  nav JSONB,
  orders JSONB,
  created_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backtest_tasks (
  task_id VARCHAR(64) PRIMARY KEY,
  status VARCHAR(20),
  strategy_name VARCHAR(100),
  start_date DATE,
  end_date DATE,
  as_of_date DATE,
  parameters JSONB,
  result JSONB,
  error TEXT,
  created_ts TIMESTAMP,
  updated_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS event_log (
  event_id VARCHAR(100) PRIMARY KEY, channel VARCHAR(100), payload JSONB, created_ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS event_consumptions (
  event_id VARCHAR(100) REFERENCES event_log(event_id) ON DELETE CASCADE,
  consumer_id VARCHAR(100),
  consumed_ts TIMESTAMP,
  PRIMARY KEY(event_id, consumer_id)
);

ALTER TABLE minute_bar_hot SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01,
  autovacuum_vacuum_threshold = 5000,
  autovacuum_analyze_threshold = 2500
);
ALTER TABLE factor_values SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 5000,
  autovacuum_analyze_threshold = 2500
);
ALTER TABLE event_log SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 2000,
  autovacuum_analyze_threshold = 1000
);
ALTER TABLE event_consumptions SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 2000,
  autovacuum_analyze_threshold = 1000
);
ALTER TABLE news_raw SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 2000,
  autovacuum_analyze_threshold = 1000
);
ALTER TABLE proposals SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 1000,
  autovacuum_analyze_threshold = 500
);
ALTER TABLE signal_log SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 1000,
  autovacuum_analyze_threshold = 500
);
ALTER TABLE cooccurrence_cache SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 1000,
  autovacuum_analyze_threshold = 500
);
ALTER TABLE doc_chunks SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 1000,
  autovacuum_analyze_threshold = 500
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aeqcs_mcp') THEN
    CREATE ROLE aeqcs_mcp LOGIN PASSWORD 'CHANGE_ME_AEQCS_MCP';
  END IF;
END
$$;

REVOKE ALL ON SCHEMA public FROM aeqcs_mcp;
GRANT USAGE ON SCHEMA public TO aeqcs_mcp;

GRANT SELECT ON stock_daily_origin, financial_indicators TO aeqcs_mcp;
GRANT SELECT ON index_constituents TO aeqcs_mcp;
GRANT SELECT ON factor_values, backtest_results, backtest_tasks, uploaded_docs, doc_chunks TO aeqcs_mcp;
GRANT SELECT, INSERT, UPDATE ON proposals TO aeqcs_mcp;
GRANT SELECT, INSERT, UPDATE ON factor_values, backtest_results TO aeqcs_mcp;
GRANT SELECT, INSERT, UPDATE ON backtest_tasks TO aeqcs_mcp;
GRANT SELECT, INSERT, UPDATE ON uploaded_docs, doc_chunks TO aeqcs_mcp;
GRANT SELECT, INSERT, UPDATE ON semantic_nodes, semantic_edges TO aeqcs_mcp;
GRANT SELECT, INSERT ON event_log TO aeqcs_mcp;
GRANT SELECT, INSERT ON event_consumptions TO aeqcs_mcp;
GRANT USAGE, SELECT ON SEQUENCE proposals_proposal_id_seq TO aeqcs_mcp;
GRANT USAGE, SELECT ON SEQUENCE uploaded_docs_doc_id_seq TO aeqcs_mcp;
GRANT USAGE, SELECT ON SEQUENCE doc_chunks_chunk_id_seq TO aeqcs_mcp;
GRANT USAGE, SELECT ON SEQUENCE semantic_edges_edge_id_seq TO aeqcs_mcp;
"""


async def main(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(SCHEMA_SQL)
    finally:
        await conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python deploy/init_db.py <postgres-superuser-dsn>")
    asyncio.run(main(sys.argv[1]))
