# AEQCS 完整开发架构书 v2

> **目标硬件**：AMD R5-5625U（6 核 12 线程 Zen3）· 16 GB 内存 · 512 GB SSD · Ubuntu Server 24.04（无桌面）
> **定位**：单机 · 事件驱动 · 双平面 · 认知可进化的 A 股量化研究与监控系统。重心 = 收盘后研究 + 次日计划 + 盘中监控告警，不做盘中自动执行。
> **主轴**：两平面（确定性核心 / 认知层）+ 验证闸门隔离非确定性。
> **唯一硬约束**：16 GB 内存。512 GB SSD 与 6 核 CPU 为余量。
> **本书用法**：从零搭建的逐模块规格说明。代码块为接口契约与关键逻辑骨架，非完整实现。按 §23 文件级顺序开工。

## 目录
0 元信息 · 1 设计哲学 · 2 指标 · 3 总体架构 · 4 代码结构 · 5 调度 · 6 存储 · 7 数据库全表 · 8 配置全文 · 9 核心基础设施 · 10 数据层 · 11 因子工厂 · 12 策略/回测/执行 · 13 验证闸门 · 14 认知层 · 15 概念宇宙L1-Ln · 16 上传学习闭环 · 17 滞后性 · 18 八角色 · 19 交互层 · 20 部署运维 · 21 监控 · 22 测试 · 23 建造顺序 · 24 风险取舍

---

## 0. 元信息与目录约定

运行时根目录 `/opt/aeqcs`，数据根 `/data`，代码包 `aeqcs/`。Python 3.11，依赖管理 uv。所有时间为 Asia/Shanghai。所有金额 DECIMAL，所有时间戳分 `timestamp`（事件发生）与 `knowledge_ts`（系统知晓）。

---

## 1. 设计哲学（七条铁律）

1. **两平面 + 信任闸门**：确定性核心（碰真钱、可复现可审计）与认知层（柔性、可自进化、允许出错）分离；认知层只读核心数据，写回必经闸门。
2. **单库主义**：一个 PostgreSQL（Timescale + pgvector）=系统记录 + 实时状态 + 向量 + 图。
3. **分析层旁路**：历史面板与回测走 DuckDB 扫 Parquet，超内存自动 spill。
4. **时间复用**：重活排到收盘后，与盘中轻量进程错峰（16G 够用的前提）。
5. **角色即函数**：8 角色是进程内类或 Hermes 技能，不做跨进程 RPC。
6. **Hermes 分层**：Hermes+MemOS 只承载认知层，不承载核心。
7. **进化即受控迭代**：进化 = 知识/记忆/已验证产物累积，非本地重训；一切碰钱产出经回测+人工双验。

---

## 2. 真实指标

| 指标 | 结论 | 说明 |
|---|---|---|
| 盘中催化映射延迟 | ✅ <2min | 映射查表 O(1) + API 兜底 + 决策快照缓存 |
| 盘面异动检测 | ✅ <30s（分钟线） | ❌ 不做 <1s（见 §17） |
| 收盘全量因子更新 | ✅ <30min | DuckDB 6 核并行 |
| 回测实盘一致性 | ⚠️ 执行层一致+可复现 | 认知层含 LLM 非确定性，回放一致 |
| 新题材发现 | ✅ <1 天 | 夜间快引擎 + 候选池 |
| 可用性 | ⚠️ 重定义 | 单机无 HA；WAL 不丢 + 幂等重启 + 状态 checkpoint |

---

## 3. 总体架构

### 3.1 两平面拓扑
认知层(Hermes+MemOS) 非确定·自进化·可错
对话/通知 · 催化推理(LLM) · 语义发现(候选) · 慢/快引擎 · 长期记忆 · 报告
│只读↑ ↓提案/候选
│ [验证闸门] 回测+结构检查+人工审核+决策快照
│ ↓仅通过验证的
确定性核心(纯Python,不依赖Hermes) 可复现·可审计·可单测
数据/PIT(PG/Parquet) · 因子工厂(DuckDB) · 回测 · 执行/风控/可成交性 · 概念图谱(权威)

text

### 3.2 单向信任规则（代码强制）
- 核心→认知：只读（SELECT）。
- 认知→核心：仅可 `INSERT proposals`；对权威表无 UPDATE/INSERT 权限。
- 数据库双角色：`aeqcs_core`（全权）、`aeqcs_cog`（核心表 SELECT + proposals INSERT + MemOS/cooccurrence 写）。
- 认知层永不直连下单或改权威因子/策略/交易集/已验证图谱。

### 3.3 关键数据流时序

**盘中催化**：NewsEvent→NOTIFY→intraday 监听→实体抽取→查热索引图谱(命中→CatalystDetected;未命中→LLM 提案写 proposals+决策快照)→可成交性过滤→Telegram。

**收盘因子**：batch-eod→DuckDB 读 Parquet→分块计算→写 factor_values(版本化)→evaluator 算 IC→写 factor_registry。

**上传学习**：文件落 inbox 或 Telegram→batch 解析→抽取→embedding→原文落盘+抽取写 proposals→夜间 validator→人工审核→晋升入图谱/记忆/因子。

**晋升**：proposals(pending)→validator(回测/结构检查)→backtested→Telegram 推人工审→approved→promote 写权威表。

---

## 4. 完整项目代码结构（文件职责）
/opt/aeqcs/aeqcs/
├── config/
│ ├── settings.yaml 系统参数/路径/阈值/内存并发
│ ├── data_sources.yaml 数据源定义 + 限速器
│ ├── cep_rules.yaml 盘中规则
│ ├── factor_registry.yaml 因子定义清单
│ └── roles/*.txt 8 角色 prompt
├── core/
│ ├── event_bus.py LISTEN/NOTIFY 封装 publish/subscribe
│ ├── events.py 所有事件 dataclass
│ ├── clock.py 交易日历/逻辑时钟/时间戳
│ ├── versioning.py PIT as-of 取数 + 决策快照写入
│ └── exceptions.py LookAheadViolation 等
├── store/
│ ├── pg.py 连接池/事务/upsert helper
│ ├── parquet.py 分区读写 minute/factors
│ └── duck.py DuckDB 会话(memory_limit/threads)
├── data/
│ ├── adapters/{tushare,akshare,scrapling,websocket}.py
│ ├── etl/{market,financial,news,alternative}.py
│ ├── quality/{validator,outlier_detector,health_checker}.py
│ ├── rate_limiter.py 令牌桶
│ └── models.py ORM
├── factor/
│ ├── compute/{technical,fundamental,sentiment,alternative}.py
│ ├── registry.py 注册(带 version)
│ ├── evaluator.py IC/IC_IR/分层/衰减
│ └── genetic_miner.py 遗传规划→写 proposals
├── strategy/
│ ├── base.py primitives.py portfolio.py risk.py
│ ├── tradability.py 可成交性过滤
│ └── backtest/{engine,execution,performance}.py
├── gate/
│ ├── proposals.py 候选 CRUD
│ ├── validator.py 回测验证 + 结构一致性
│ └── promote.py 晋升入权威表
├── knowledge/
│ ├── semantic_network.py 节点/边/向量检索/递归遍历
│ ├── universe_builder.py L1-Ln 单步下钻
│ ├── slow_engine/{research_parser,book_ingestion,industry_health}.py
│ └── fast_engine/{cooccurrence,linkage_verifier,llm_zero_shot}.py
├── memory/memory.py MemOS 封装
├── ingest/ 【上传学习闭环】
│ ├── inbox_watcher.py 监听 /data/inbox
│ ├── document_parser.py PDF/EPUB/MD/TXT 解析
│ ├── extractor.py 实体/关系/因子抽取→proposals
│ └── correction.py 人工纠错回路
├── agents/{data_steward,factor_researcher,market_observer,knowledge_curator,
│ strategy_engineer,risk_officer,chief_editor,chief_researcher}.py
├── interaction/
│ ├── telegram_bot.py 告警/查询/上传/审核入口
│ ├── report_generator/
│ └── dashboard/ 可选 FastAPI
├── runtime/
│ ├── intraday.py 盘中常驻
│ ├── batch.py 批处理 DAG
│ └── skill_dispatcher.py 角色调度
├── llm/client.py LLM API 封装(决策快照)
├── deploy/{postgresql.conf,systemd/,tune_os.sh,init_db.py}
└── tests/{unit,integration,e2e,lookahead}/

text

---

## 5. 时间复用调度

| OnCalendar | 时段 | 内存 | 内容 | unit |
|---|---|---|---|---|
| Mon..Fri 09:15 | 盘中起 | 低 | CEP告警/催化映射/风控监控 | intraday.service(15:05自停) |
| Mon..Fri 04:00 | 盘前 | 低中 | 财务/行情增量·复权·universe·概念成分 | batch-pre.timer |
| Mon..Fri 15:10 | 盘后 | **峰值** | 全量因子·回测·embedding | batch-eod.timer |
| *-*-* 00:30 | 夜间 | 低 | 备份·VACUUM·HNSW重建·上传解析 | batch-night.timer |
| Mon..Fri 19:00 | 晚间 | 中 | 日报·认知进化·概念下钻·遗传挖掘·候选晋升 | batch-night2.timer |

铁律：intraday 退出后 batch 才启动。

---

## 6. 存储分层与磁盘布局

| 系统 | 职责 | 内容 |
|---|---|---|
| PostgreSQL | 系统记录+实时状态+向量+图 | universe·近月分钟线热·财务PIT·因子注册·语义节点边·概念成分·记忆·日志·决策快照·proposals |
| Parquet | 历史冷存+分析底座 | 全历史分钟线·因子面板·共现缓存 |
| DuckDB | 分析/回测扫描 | 读 Parquet，spill /data/duckdb_tmp |
/data/postgres/ /data/parquet/minute/(date=YYYYMMDD) /data/parquet/factors/
/data/duckdb_tmp/ /data/models/(bge-base) /data/docs/(上传原文) /data/inbox/(上传投递)
/data/backups/(pg_dump+parquet快照)

text
内存峰值(盘后)：OS 1.0 + PG 3.0 + DuckDB 4.0 + Python 2.5 + 页缓存/余量 3.5 ≈ 守住 16G。

---

## 7. 完整数据库设计

### 7.1 行情与状态
```sql
CREATE TABLE stock_daily_origin (
  symbol VARCHAR(10), date DATE,
  open DECIMAL(10,3), high DECIMAL(10,3), low DECIMAL(10,3), close DECIMAL(10,3),
  volume BIGINT, amount DECIMAL(20,2),
  PRIMARY KEY (symbol,date));
SELECT create_hypertable('stock_daily_origin','date');

CREATE TABLE minute_bar_hot (              -- 仅近月热数据；历史在 Parquet
  symbol VARCHAR(10), ts TIMESTAMP,
  open DECIMAL(10,3),high DECIMAL(10,3),low DECIMAL(10,3),close DECIMAL(10,3),
  volume BIGINT, pre_close DECIMAL(10,3),
  high_limit DECIMAL(10,3), low_limit DECIMAL(10,3),
  bid_volume BIGINT, is_one_word_limit BOOLEAN,
  PRIMARY KEY (symbol,ts));
SELECT create_hypertable('minute_bar_hot','ts');

CREATE TABLE adj_factor (                  -- 只追加不回改；累计前复权固定快照
  symbol VARCHAR(10),date DATE,factor DECIMAL(12,6),PRIMARY KEY(symbol,date));

CREATE TABLE stock_universe (
  symbol VARCHAR(10) PRIMARY KEY,name VARCHAR(50),
  ipo_date DATE,delist_date DATE,status VARCHAR(20));   -- Normal/ST/Suspended/Delisted

CREATE TABLE suspend_info (
  symbol VARCHAR(10),date DATE,is_suspend BOOLEAN,PRIMARY KEY(symbol,date));

CREATE TABLE index_constituents (
  index_code VARCHAR(10),symbol VARCHAR(10),in_date DATE,out_date DATE,
  PRIMARY KEY(index_code,symbol,in_date));
7.2 财务 PIT 多版本
sql
CREATE TABLE financial_indicators (
  symbol VARCHAR(10),period VARCHAR(10),ann_date DATE,vintage INT DEFAULT 0,
  roe DECIMAL(8,4),eps DECIMAL(8,4),bps DECIMAL(8,4),
  revenue_yoy DECIMAL(8,4),profit_yoy DECIMAL(8,4),
  debt_ratio DECIMAL(8,4),current_ratio DECIMAL(8,4),
  PRIMARY KEY(symbol,period,ann_date,vintage));
CREATE INDEX idx_fin_asof ON financial_indicators(symbol,period,ann_date DESC,vintage DESC);
7.3 新闻与因子
sql
CREATE TABLE news_raw (
  id BIGSERIAL PRIMARY KEY,timestamp TIMESTAMP,knowledge_ts TIMESTAMP,
  source VARCHAR(50),level CHAR(1),title TEXT,content TEXT,
  entities JSONB,sentiment DECIMAL(3,2));

CREATE TABLE factor_registry (
  factor_id VARCHAR(50),version INT DEFAULT 1,name VARCHAR(100),category VARCHAR(50),
  description TEXT,data_dependency JSONB,preprocessing JSONB,status VARCHAR(20),
  ic_12m DECIMAL(6,4),ic_ir DECIMAL(6,4),created_date DATE,last_evaluated DATE,
  PRIMARY KEY(factor_id,version));

CREATE TABLE factor_values (
  symbol VARCHAR(10),date DATE,factor_id VARCHAR(50),version INT DEFAULT 1,
  value DECIMAL(12,6),calc_timestamp TIMESTAMP,
  PRIMARY KEY(symbol,date,factor_id,version));
7.4 语义网络 / 概念宇宙
sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE semantic_nodes (
  node_id VARCHAR(100) PRIMARY KEY,name VARCHAR(200),type VARCHAR(50),level INT,
  embedding vector(768),embed_model VARCHAR(50),aliases JSONB,created_at TIMESTAMP);
CREATE INDEX idx_sn_hnsw ON semantic_nodes USING hnsw (embedding vector_cosine_ops);

CREATE TABLE semantic_edges (
  edge_id BIGSERIAL PRIMARY KEY,parent_id VARCHAR(100),child_id VARCHAR(100),
  relation_type VARCHAR(50),revenue_share DECIMAL(5,4),
  source VARCHAR(50),confidence DECIMAL(4,3),verified BOOLEAN DEFAULT FALSE,
  valid_from DATE,valid_to DATE);
CREATE INDEX idx_se_parent ON semantic_edges(parent_id) WHERE verified;
CREATE INDEX idx_se_child ON semantic_edges(child_id) WHERE verified;

CREATE TABLE cooccurrence_cache (
  concept VARCHAR(100),symbol VARCHAR(10),date DATE,frequency INT,
  PRIMARY KEY(concept,symbol,date));

CREATE TABLE theme_lifecycle (
  theme_id VARCHAR(100) PRIMARY KEY,name VARCHAR(200),stage VARCHAR(20),
  first_detected TIMESTAMP,last_active TIMESTAMP);
7.5 闸门：候选 + 决策快照
sql
CREATE TABLE proposals (
  proposal_id BIGSERIAL PRIMARY KEY,created_ts TIMESTAMP,
  kind VARCHAR(50),                       -- catalyst/edge/signal/factor/theme/correction
  payload JSONB,source VARCHAR(50),confidence DECIMAL(4,3),snapshot_id BIGINT,
  status VARCHAR(20) DEFAULT 'pending',    -- pending/backtested/approved/rejected
  backtest_result JSONB,reviewed_by VARCHAR(50),reviewed_ts TIMESTAMP);
CREATE INDEX idx_prop_status ON proposals(status,kind);

CREATE TABLE decision_snapshot (
  snapshot_id BIGSERIAL PRIMARY KEY,decision_ts TIMESTAMP,role VARCHAR(50),
  input_hash VARCHAR(64),input JSONB,
  llm_model VARCHAR(50),llm_output JSONB,embed_model VARCHAR(50));
CREATE INDEX idx_snap_hash ON decision_snapshot(input_hash);
7.6 上传文档 + 记忆
sql
CREATE TABLE uploaded_docs (
  doc_id BIGSERIAL PRIMARY KEY,uploaded_ts TIMESTAMP,filename TEXT,
  doc_type VARCHAR(20),                    -- research/book/note/factor/correction
  path TEXT,sha256 VARCHAR(64) UNIQUE,
  status VARCHAR(20) DEFAULT 'parsed',     -- parsed/extracted/indexed
  meta JSONB);

CREATE TABLE doc_chunks (
  chunk_id BIGSERIAL PRIMARY KEY,doc_id BIGINT,seq INT,text TEXT,
  embedding vector(768),embed_model VARCHAR(50));
CREATE INDEX idx_chunk_hnsw ON doc_chunks USING hnsw (embedding vector_cosine_ops);

-- 记忆四层(由 MemOS 管理则此表为镜像/兜底)
CREATE TABLE memory_store (
  mem_id BIGSERIAL PRIMARY KEY,layer VARCHAR(20),  -- policy/trace/world_model/skill
  role VARCHAR(50),content JSONB,embedding vector(768),
  created_ts TIMESTAMP,feedback_ts TIMESTAMP);
7.7 策略与组合
sql
CREATE TABLE signal_log (signal_id BIGSERIAL PRIMARY KEY,timestamp TIMESTAMP,
  strategy_id VARCHAR(50),symbol VARCHAR(10),score DECIMAL(8,6),source_tags JSONB);
CREATE TABLE order_fill_log (fill_id BIGSERIAL PRIMARY KEY,timestamp TIMESTAMP,
  symbol VARCHAR(10),side VARCHAR(5),quantity INT,price DECIMAL(10,3),fee DECIMAL(10,3));
CREATE TABLE portfolio_snapshot (date DATE PRIMARY KEY,
  cash DECIMAL(20,2),positions_value DECIMAL(20,2),nav DECIMAL(20,4),drawdown DECIMAL(8,4));
8. 配置文件全文
config/settings.yaml
yaml
paths: {data_root: /data, docs: /data/docs, inbox: /data/inbox, parquet: /data/parquet}
database: {url: postgresql://aeqcs_core@localhost/aeqcs, pool_size: 8}
database_cog: {url: postgresql://aeqcs_cog@localhost/aeqcs, pool_size: 4}
duckdb: {memory_limit: 4GB, threads: 6, temp: /data/duckdb_tmp}
memory: {batch_chunk_symbols: 500}      # 因子计算分块，禁全市场一次load
llm: {provider: api, model: <your-model>, max_retries: 3, cache: true}
embedding: {model: bge-base-zh, device: cpu, batch: 64}
thresholds:
  spike_pct: 0.05
  drawdown_warn: 0.05
  drawdown_red: 0.10
  factor_ic_min: 0.02
  proposal_conf_min: 0.6
trading_calendar: tushare
config/data_sources.yaml
yaml
rate_limits:
  tushare:   {burst: 5, per_second: 3}
  akshare:   {burst: 2, per_second: 0.5, cooldown_after_fail: 1800}
  scrapling: {burst: 1, per_second: 0.2, max_daily: 1000, respect_robots: true, cache_ttl: 3600}
sources:
  daily: tushare
  financial: tushare
  concept: akshare         # stock_board_concept_cons_ths / _em
  news: [scrapling, akshare]
  minute: tushare
compliance: {scrape_third_party_curated_products: false}   # 只取原料,不爬成品
config/cep_rules.yaml
yaml
rules:
  - {id: sudden_spike, condition: "abs(e.close/e.pre_close-1)>0.05", action: market_observer.analyze_spike, priority: urgent}
  - {id: s_level_news, condition: "e.level=='S'", action: market_observer.catalyst_mapping, priority: urgent}
  - {id: limit_up_open, condition: "e.tick_status=='OPEN' and abs(e.close-e.high_limit)<1e-3", action: market_observer.limit_alert, priority: important}
  - {id: sector_linkage, condition: "count(events[same_concept].change_pct>0.03, 5min)>=3", action: market_observer.sector_alert, priority: important}
  - {id: volume_breakout, condition: "e.volume>3*rolling_mean(e.volume,20)", action: market_observer.volume_alert, priority: important}
  - {id: portfolio_drawdown, condition: "portfolio.drawdown>0.05", action: risk_officer.analyze_drawdown, priority: urgent}
config/factor_registry.yaml
yaml
factors:
  - {id: momentum_20d, category: technical, compute: "close.pct_change(20)", preprocess: [winsorize, industry_neutralize, zscore]}
  - {id: roe_quarterly, category: fundamental, compute: "financials.roe", align: f_ann_date, update_freq: quarterly}
  - {id: north_flow_5d, category: moneyflow, compute: "sum(moneyflow.net_inflow,5)/market_cap", preprocess: [winsorize, sector_neutralize]}
  - {id: news_sentiment_1d, category: sentiment, compute: "mean(news.sentiment, last 1 day)", preprocess: [zscore]}
  - {id: concept_heat, category: alternative, compute: "concept.news_frequency*concept.price_correlation", update_freq: daily}
9. 核心基础设施接口
core/events.py
python
@dataclass(frozen=True)
class Event: event_id: str; timestamp: datetime; knowledge_ts: datetime

@dataclass(frozen=True)
class MarketEvent(Event):
    symbol:str; open:float; high:float; low:float; close:float; volume:int
    is_trading:bool; tick_status:str
    pre_close:float; high_limit:float; low_limit:float        # 补
    bid_volume:int; is_one_word_limit:bool                    # 补:可成交性
@dataclass(frozen=True)
class NewsEvent(Event): source:str; level:str; title:str; content:str; entities:list; sentiment:float|None
@dataclass(frozen=True)
class FinancialEvent(Event): symbol:str; period:str; ann_date:datetime; indicators:dict
@dataclass(frozen=True)
class CatalystDetected(Event): news_id:str; concept:str; affected_stocks:list; confidence:float
@dataclass(frozen=True)
class SignalEvent(Event): strategy_id:str; symbol:str; score:float; source_tags:list
@dataclass(frozen=True)
class RiskAlert(Event): type:str; message:str; severity:str
# OrderEvent/FillEvent/PortfolioSnapshot/TaskEvent 同上风格
core/event_bus.py
python
class EventBus:                       # Postgres LISTEN/NOTIFY 替 Redis
    def publish(self, channel:str, event:Event): ...   # INSERT event_log + pg_notify
    def subscribe(self, channels:list, handler): ...    # LISTEN 循环, 幂等(event_id 去重)
core/versioning.py
python
def asof_financials(symbol, period, decision_date) -> dict: ...   # §7.2 查询
def snapshot(role, input:dict, llm_output:dict=None, ...) -> int: ...  # 写 decision_snapshot, 返回 id
def replay_llm(input_hash) -> dict|None: ...                       # 回测回放,命中快照不调 LLM
core/clock.py
python
def is_trading_day(d)->bool; def prev_trading_day(d); def trading_minutes(d)->list
core/exceptions.py
python
class LookAheadViolation(Exception): ...
class GateBypassError(Exception): ...
class RateLimitExceeded(Exception): ...
10. 数据层接口
python
# adapters: 统一返回标准 DataFrame, 内部经 rate_limiter
class TushareAdapter: def daily(symbol,start,end); def fina_indicator(symbol)
class AkshareAdapter: def concept_cons(concept_src='ths'); def news()
# rate_limiter.py
class RateLimiter:
    def __init__(self,cfg): self.buckets={s:TokenBucket(c['burst'],c['per_second']) for s,c in cfg.items()}
    def acquire(self,source)->bool: return self.buckets[source].consume()
# etl: 清洗+标准化+对齐, 写 timestamp/knowledge_ts
# quality: validator(schema/范围), outlier_detector(MAD), health_checker(源存活)
11. 因子工厂接口
python
# compute/*: 纯函数 f(panel:DataFrame)->Series
# registry.py
def register(factor_id, version, meta); def get_active()->list
# evaluator.py
def ic(factor_id, window='12m')->float; def ic_ir(...); def layered_return(...); def decay(...)
# genetic_miner.py
def mine(generations=20)->list[dict]   # 输出候选→proposals(kind='factor'), 不直接上线
# 计算: store.duck 扫 Parquet, 按 settings.memory.batch_chunk_symbols 分块流式
12. 策略/回测/执行/可成交性/风控
python
# tradability.py
def is_tradable(mkt:MarketEvent, position)->bool:
    # 拒: is_one_word_limit / bid_volume 不足 / 停牌 / T+1 当日买入卖出
# backtest/execution.py
def fill_price(order, mkt)->float   # A股成本: 印花税+过户费+佣金+滑点; 禁用 close 直接成交
# backtest/engine.py
def run(strategy, start, end, replay_snapshots=True)->Result  # 信号回放读 decision_snapshot
# backtest/performance.py
def metrics(result)->dict; def assert_reproducible(r1,r2)     # 字节级一致校验
# risk.py: drawdown/exposure/concentration 分级; portfolio.py: 仓位/集中度/单票上限
13. 验证闸门
python
# proposals.py
def insert(kind, payload, source, confidence, snapshot_id)->int   # 认知层唯一写入口
def pending(kind=None)->list; def mark(pid, status, result=None)
# validator.py
def validate(proposal)->dict:
    if proposal.kind in ('edge','theme'): return structural_check(proposal)
    if proposal.kind in ('signal','factor'): return backtest_check(proposal)  # 回放, 达 ic_min/收益门槛
def structural_check(p):       # 反坍缩
    # 父节点存在? 与现有节点同义重复(向量近似+aliases)? 是否该拆为并列而非合并? 置信度阈值?
# promote.py
def promote(pid):              # status=approved 后才写权威表
    # edge→semantic_edges(verified=true) / factor→factor_registry / signal→交易集
人工审核：validator 标 backtested 后，Telegram 推送待审卡片（payload+回测结果），你回复 approve/reject → promote。

14. 认知层接口
python
# semantic_network.py
def add_node(name,type,level,embedding,aliases); def add_edge(parent,child,**props)
def search_similar(name_or_vec, top_k=10)->list; def traverse(root, depth=3)->tree   # 递归CTE
def hot_index_load()->dict   # 概念→个股 常驻 intraday 内存, O(1)
# slow_engine: research_parser/book_ingestion/industry_health → 产 proposals
# fast_engine: cooccurrence(写cache)/linkage_verifier(回测验证,防数据窥探)/llm_zero_shot(写proposals+快照)
# memory/memory.py (MemOS 封装)
def store(layer,role,content); def query_similar(role,vec,top_k=5); def feedback(mem_id,correction)
15. 概念宇宙 L1–Ln
层级：L1 板块(人工播种)→L2 赛道/L3 概念(LLM 提案+审核)→L4 环节/L5 个股(厂商数据+营收占比)。semantic_nodes.level + semantic_edges，多挂载 DAG，树视图为投影。

反坍缩五机制：①LLM 只单步提问(下级/归属)；②稳定 ID 只挂边不重写；③底层硬数据锚定(revenue_share)；④多挂载独立边；⑤闸门结构检查拒笼统父节点+去重同义。

python
# universe_builder.py
def propose_children(node_id):       # 单步: 问 LLM 该节点直接下级 → proposals + 快照
    node=sn.get(node_id); out=llm.ask(prompt_children(node)); snap=snapshot('universe',node,out)
    for c in out['children']:
        proposals.insert('edge', {'parent_id':node_id,'child_name':c['name'],'relation_type':'belongs'},
                         'llm', c['conf'], snap)
def attach_stocks_by_revenue(concept_id):   # L5: 用财务/营收数据归属, source=vendor/manual
def refresh_vendor_concepts():       # akshare 概念成分 upsert, 变动用 valid_to 关旧边
出树（递归 CTE，§前文）：WITH RECURSIVE + 防环 + verified + valid_to 过滤。

16. 上传学习闭环（四通道）
16.1 投递入口
文件夹：inbox_watcher.py 监听 /data/inbox（watchdog），新文件入队。

Telegram：telegram_bot.py 接收文档/文本 → 落 /data/inbox。

16.2 流水线（夜间 batch 触发）
text
落盘→sha256去重(uploaded_docs)→document_parser(PDF/EPUB/MD/TXT→纯文本+分块)
→embedding(bge CPU)→doc_chunks(可检索)→extractor 按 doc_type 抽取→proposals
16.3 四通道（落点与门槛不同）
上传	学成	落点	闸门	碰钱
研报/书/产业链	图谱新节点/边/归属	认知层→图谱	人工审核	否(间接)
笔记/自选/偏好/风格	记忆+世界模型	MemOS	不需要	否
因子公式/策略	因子库/交易集候选	闸门→核心	回测验证	是
纠错/标注	修正图谱+记住	图谱(verified)+MemOS	你即真相源	视内容
16.4 纠错回路（进化核心）
python
# correction.py
def apply_correction(target_edge_id, corrected, reason):
    sn.update_edge(target_edge_id, verified=True, source='manual', **corrected)  # 人工真相覆盖
    memory.store('policy','knowledge_curator',{'avoid':reason})                  # 记住别再犯
    memory.feedback(...)   # MemOS 反馈驱动修正
16.5 诚实边界
不本地微调基座：进化=知识库+记忆+已验证因子在长大，非梯度下降。

垃圾进→垃圾候选：闭环放大输入质量；上传策展质量决定进化质量，系统替不了你。

碰钱上传必过闸：研报不能"信了就交易"，只变候选+可检索知识；交易由回测+你的审核决定。

17. 滞后性策略
可控延迟压：映射查表(热索引常驻 intraday 内存,O(1),仅新题材退 LLM)·实时数据(websocket/L2)·决策快照缓存。
不可控延迟认并换战场：单机不比首板速度;A股 T+1 当天本不能往返,第一根涨停吃不到→价值放在:①题材发酵中段;②二阶映射(图谱算未发现的二三线);③历史类比(MemOS);④广度。结论:作次日/多日研究监控系统,30s–2min 滞后无关紧要。

18. 八角色
角色	平面	职责	可用工具
data_steward	核心	数据更新/质量/复权/universe/概念成分	adapters,etl,quality
factor_researcher	核心	因子计算/评估/挖掘	duck,evaluator,genetic_miner
strategy_engineer	核心	策略/回测/组合	backtest,portfolio
risk_officer	核心	风控监控/告警	risk,tradability
market_observer	认知	盘中异动/催化映射	semantic_network,llm,publish
knowledge_curator	认知	图谱维护/上传抽取/纠错	universe_builder,extractor,memory
chief_editor	认知	日报/周报	report_generator
chief_researcher	认知	周度复盘/进化决策	memory,evaluator,proposals
role prompt 模板（market_observer.txt 例）：

text
你是实时市场观察员。职责:监听NewsEvent/MarketEvent;S级新闻立即抽实体、查semantic_network检索受影响标的;
检索无果调LLM零样本推理生成临时映射(标置信度,写proposals);监控CEP异动;生成CatalystDetected/RiskAlert推总线。
所有输出附证据链,不凭空猜测。可用工具:semantic_network_search,llm_zero_shot,publish_event,get_price,get_news。
19. 交互层
telegram_bot.py：盘中告警推送 · 自然语言查询(只读核心) · 文档上传 · 待审卡片 approve/reject。

report_generator/：日报(异动/催化/持仓/风控)、周报(因子IC/策略绩效/题材生命周期)。

dashboard/（可选 FastAPI）：概念树视图(递归CTE渲染)、系统状态、候选池待审量。

20. 部署运维
postgresql.conf
ini
shared_buffers=2GB
effective_cache_size=8GB
work_mem=32MB
maintenance_work_mem=512MB
max_connections=20
max_parallel_workers_per_gather=4
max_parallel_workers=6
wal_compression=on
max_wal_size=4GB
random_page_cost=1.1
tune_os.sh
bash
sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo 'vm.swappiness=10'|sudo tee -a /etc/sysctl.conf
# 必须 Ubuntu Server 无桌面
systemd（deploy/systemd/）
ini
# intraday.service
[Service] Type=simple ExecStart=/opt/aeqcs/.venv/bin/python -m aeqcs.runtime.intraday
RuntimeMaxSec=21000   # ~5h50m 自停
# intraday.timer  [Timer] OnCalendar=Mon..Fri 09:15
# batch-eod.service Type=oneshot ExecStart=...batch eod ; batch-eod.timer OnCalendar=Mon..Fri 15:10
# 同理 batch-pre(04:00) batch-night(00:30) batch-night2(Mon..Fri 19:00)
.env / 角色与备份
DB 双角色 aeqcs_core / aeqcs_cog（§3.2 授权）。夜间 pg_dump + Parquet 快照到外置盘；可选 5 美元 VPS 跑告警影子进程。

21. 监控与日志
structlog JSON→可选 ELK。Prometheus：事件总线延迟·因子计算耗时·数据源健康·内存峰值·候选池待审量。Grafana：系统状态·策略绩效·因子IC·CEP触发·题材生命周期。

22. 测试策略
单元：因子函数·事件schema·限速器·可成交性·asof_financials。

集成：LISTEN/NOTIFY·DuckDB读写·回测对齐Buy&Hold·递归CTE出树。

端到端：上传→解析→抽取→候选→闸门→晋升；新闻→催化→告警→日报。

防前视注入：注入未来财务/复权/语义状态→断言 LookAheadViolation。

回测复现：同输入两次回测 assert 字节级一致(依赖决策快照)。

闸门隔离：断言 aeqcs_cog 角色对权威表 UPDATE 抛权限错误。

23. 文件级建造顺序
阶段一(地基,无LLM)

deploy/init_db.py + 全部 §7 建表 + 双角色授权

store/{pg,parquet,duck} + core/{clock,events,exceptions,versioning}

data/{adapters,etl,quality,rate_limiter} + scripts/backfill

factor/{compute,registry,evaluator} + DuckDB 分块计算

strategy/tradability + backtest/{engine,execution,performance} + 对齐 Buy&Hold + 防前视测试
→ 可用研究系统

阶段二(盘中监控)

core/event_bus(LISTEN/NOTIFY) + runtime/intraday + CEP + interaction/telegram_bot(告警)
→ 盘中告警,不自动交易

阶段三(认知+闸门+上传)

gate/{proposals,validator,promote} + 双角色权限断言

knowledge/semantic_network + universe_builder + 递归CTE + akshare概念成分保鲜

llm/client(决策快照) + fast/slow engine + memory/memory(MemOS)

ingest/{inbox_watcher,document_parser,extractor,correction} + Telegram 上传/审核
→ 概念宇宙 + 上传学习闭环跑通

阶段四(进化)

genetic_miner + chief_researcher 周度进化 + 8 角色完整协同 + dashboard

最高优先级：§7.2 PIT 财务表、§12 可复现回测、§13 闸门边界。三者写松则防前视与两平面隔离失守。

24. 风险与诚实取舍
不要做：本地生成式LLM·装Neo4j/Milvus/Redis·整站爬第三方策展产品·一次性load全市场面板·桌面Ubuntu·盘中跑embedding/回测·追<1s首板·认知层直连下单·本地微调基座。

接受的降级：单机无HA·回测仅执行层一致+可复现·盘中<30s非<1s·概念深树上层需人工策展·进化非梯度下降。

坚守纪律：两平面单向信任·时间错峰·重活落盘不爆内存·生成走API·PIT+决策快照+asof回放·LLM单步提案·底层认数据·上层人工审·动态关系必经回测+人工双验·上传碰钱必过闸。

最该认清：架构再完整也不产生 alpha。它解决"不亏在工程上";真正决定成败的是闸门后"回测验证+人工判断"里你对市场的认知,以及你上传资料的策展质量。把它当让你安全可重复试错的实验台,是顶配;当自动印钞机,会让你亏得很有条理。

— 完 —
