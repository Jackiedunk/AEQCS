# AEQCS 确定性核心层开发进度

更新时间：2026-07-01

当前目标：专注完成“确定性核心层开发文档（最大化利用 Qlib）”对应的核心层开发。范围限定为可测试、可审查、可运行的确定性核心，不扩展 UI、对话层、Hermes、LLM 或非四角色认知功能。

## 当前验证状态

```text
.\.venv\Scripts\python.exe -m pytest
482 passed

.\.venv\Scripts\python.exe -m ruff check .
All checks passed!

.\.venv\Scripts\python.exe -m mypy aeqcs scripts
Success: no issues found in 78 source files

.\.venv\Scripts\python.exe -m compileall aeqcs tests scripts deploy
passed

.\.venv\Scripts\python.exe -m pip check
此前已通过；本轮未重复执行。
```

说明：当前工作区没有 `.git` 元数据，因此无法确认 commit hash、远端推送状态或 GitHub 同步状态。

## 当前范围判定

- 正在开发的是“确定性核心层开发文档（最大化利用 Qlib）”这一层。
- 核心层只保留确定性能力：行情、财务、指数成分股 PIT 查询、因子、回测、proposal gate、文档上传、PostgreSQL store、MCP 服务边界、确定性图谱维护与持久化。
- Qlib 不作为核心因子表达式引擎；Qlib 当前只保留数据边界守卫与后置风险分析边界。
- 生产因子计算优先落到 DuckDB/Polars 等有界管线，避免把全市场矩阵强行塞进 Pandas/Qlib。
- 已移除核心包中的 LLM、market_observer、cognitive database 配置、非四角色提示文件与 Qlib expression handler。

## 已完成能力

### 1. 环境与质量门

- 已建立 Python 3.11.9 虚拟环境 `.venv`。
- 已安装开发依赖、数据依赖和 Qlib 可选依赖。
- 已补齐 `pandas-stubs`、`types-PyYAML` 和 mypy 配置。
- 当前 pytest、ruff、mypy、compileall 均已在本轮通过；pip check 此前已通过，本轮未重复执行。
- 当前测试总数为 `448 passed, 3 skipped`；其中 PostgreSQL 集成测试在未配置 `AEQCS_TEST_PG_DSN` 时按设计跳过。

### 2. 确定性服务与存储

- 已建立 `LocalStore` 和异步 `PgCoreStore`。
- 已建立 `CoreStore` / `AsyncCoreStore` 协议。
- `CoreService` / `AsyncCoreService` 支持行情、财务、因子、回测、proposal、文档上传等核心工具逻辑。
- `core/event_bus.py` 已提供 PostgreSQL `event_log` + `pg_notify` 的 fire-and-forget 事件发布边界。
- 行情、财务、因子、回测查询保留显式 `as_of_date` / PIT 约束。
- 财务导入已定义 `vintage` 递增规则：同一 `symbol/period` 的新修订版本递增 `vintage`，新一期财报从 `vintage=0` 开始，重复导入同一版本保持幂等。
- 财务导入的 `assign_financial_vintages()` 会让同一批次内较早分配的 `symbol/period` 修订参与后续 `vintage` 判定，避免单次 adapter 返回多条同期间修订时全部落为 `vintage=0`。
- 复权策略已明确选择后复权：`apply_backward_adjustment()` 以每个 symbol 首个已观测 `adj_factor` 为基准生成 `hfq_open/high/low/close`，追加新除权事件时不改写既有历史复权价。
- 回测和因子查询拒绝 `end_date > as_of_date`。
- 行情查询、因子计算、因子查询和回测入口拒绝 `start_date > end_date`；本地与 PostgreSQL store 层同样拒绝反向行情和因子值日期范围，避免坏日期范围穿透到底层查询或任务提交。
- 本地 store 与 PostgreSQL store 的 `save_factor_values` 会在读取 CSV 或执行 SQL 写入前拒绝空 `symbol` / `factor_id`、非正 `version`、非 finite `value`，以及不可解析的 `date` / `calc_timestamp`，避免坏因子维度键、NaN/Inf 因子值或坏时间戳进入 `factor_values` 持久化层。
- 行情和财务 PIT 查询已在同步服务、异步服务、MCP 工具入口、本地 store 与 PostgreSQL store 层拒绝空 `symbol`；财务查询同时拒绝空 `period`，避免空标识符穿透到底层 CSV/SQL 查询。
- 本地 store 的 `save_daily` / `save_financials` 会在写入 CSV 前拒绝空行情 `symbol`、空财务 `symbol/period`、不可解析的行情 `date` / 财务 `ann_date`、非 finite 行情价格/成交量/成交额、非法财务 `vintage`，以及有值但非 finite 的财务指标，避免坏原始数据进入 PIT 查询和因子计算入口。
- 指数成分股 PIT 查询已在同步服务、异步服务、MCP 工具入口、本地 store 与 PostgreSQL store 层拒绝空 `index_code`，且本地 CSV store 会在 as-of 过滤前拒绝空成分股 `symbol` 与不可解析的 `in_date/out_date`，避免坏成分股边界穿透到底层查询或被静默解释为仍在指数内。
- 图谱子节点 as-of 查询已在同步服务、异步服务、MCP 工具入口、本地 store 与 PostgreSQL store 层拒绝空 `parent_id`，避免空图谱父节点穿透到底层 CSV/SQL 查询。
- 本地 store 与 PostgreSQL store 的图谱边验证/失效入口会在读取 CSV 或发起 SQL 更新前拒绝非正 `edge_id`，为绕过服务/MCP 层的直接图谱生命周期调用提供兜底防线。
- 本地 store 与 PostgreSQL store 的图谱边验证/失效入口也会在读取 CSV 或发起 SQL 更新前拒绝空 `verified_by` / `retired_by`，避免缺失审计责任人的生命周期变更进入持久化层。
- 本地 store 与 PostgreSQL store 的图谱边保存入口会在读取节点/边存储或发起 SQL 前拒绝显式传入的非正 `edge_id`；未显式传入 `edge_id` 时仍保持自动分配语义。
- 本地 store 与 PostgreSQL store 的图谱边保存入口会在读取节点/边存储或发起 SQL 前拒绝空 `parent_id`、`child_id`、`relation_type` 和 `created_by`，避免坏边端点、空关系类型或缺失审计责任人进入持久化层。
- 本地 store 与 PostgreSQL store 的图谱节点保存入口会在读取节点存储或发起 SQL 前拒绝空 `node_id`，为绕过服务/MCP 层的直接节点写入提供兜底防线。
- 本地 store 与 PostgreSQL store 的图谱节点保存入口也会在读取节点存储或发起 SQL 前拒绝空 `label`，避免空语义标签进入同义重复检查、搜索索引或持久化层。
- 本地 store 与 PostgreSQL store 的图谱节点保存入口也会在读取节点存储或发起 SQL 前拒绝空 `level`，避免无层级语义节点进入图谱持久化层。
- 本地 store 与 PostgreSQL store 的图谱节点保存入口也会在读取节点存储或发起 SQL 前拒绝空 `created_by`，避免缺失审计责任人的图谱节点进入持久化层。
- 指数成分股查询新增 `get_index_constituents(index_code, as_of_date)`，必须显式传入 `as_of_date`。
- 本地 CSV store 与 PostgreSQL store 都只返回 `in_date <= as_of_date` 且 `out_date` 为空或晚于查询日的成分股，避免用当前最新成分股回灌历史股票池。

### 3. MCP 核心服务

- 已注册 25 个确定性核心 MCP 工具。
- MCP 默认传输已改为 HTTP/SSE。
- MCP HTTP/SSE 默认绑定 `127.0.0.1:8000`，非 loopback host 会被拒绝。
- stdio 仅保留为显式 `AEQCS_MCP_TRANSPORT=stdio` 的测试/调试路径。
- 配置 `AEQCS_CORE_PG_DSN`、`AEQCS_PG_DSN` 或 `AEQCS_CORE_DSN` 时，MCP 可切换 PostgreSQL 后端。
- 已新增 `deploy/systemd/mcp-server.service`，以独立 systemd 长驻服务运行 MCP HTTP/SSE，`Restart=on-failure`。
- 列表型 MCP 输出已增加统一分页包装：`items`、`count`、`offset`、`limit`、`has_more`。
- MCP 列表型工具默认单页上限为 1000 条，`limit` 超出 `1..1000` 会被拒绝。
- MCP 列表型工具已新增序列化 JSON 返回体字节预算：默认 `max_bytes=1000000`，调用方可传更小预算做压力边界验证；超过预算时会以可解释 `ValueError` 拒绝，要求降低 `limit` 或提高 `max_bytes`。
- MCP 非列表大对象工具 `get_uploaded_doc`、`get_backtest_result`、`get_backtest_task` 已接入同一套序列化 JSON 返回体字节预算，避免文档 chunks、回测订单明细或任务结果在 HTTP/SSE 下无限制放大响应体。
- 当前已分页的列表型工具包括 `get_market_data`、`compute_factors`、`get_factor_values`、`get_index_constituents`、`get_universe_children`、`search_semantic_nodes`、`scan_intraday_events`。
- MCP `get_market_data` 已支持显式 `start_date/end_date/as_of_date` 的日期范围查询，并通过 `limit/offset` 返回分页包装，避免单次拉取过多行情行。
- MCP 已新增 `search_semantic_nodes`，支持按显式 `as_of_date` 查询已审计 active 语义节点，并返回统一分页包装。
- `search_semantic_nodes` 在本地 store 下使用确定性 `node_id` / `label` 文本匹配，在 PostgreSQL store 下保留 `embedding <=> query_embedding` 向量相似度入口并以 `label/node_id ILIKE` 兜底；该路径不生成 embedding、不调用 LLM、不主动连接认知层。
- `search_semantic_nodes` 在同步服务、异步服务和 MCP 路径下会拒绝空 `query`，并要求调用方传入的 `query_embedding` 为 finite 数值列表，避免坏向量字面量穿透到 PostgreSQL vector 查询。
- `get_uploaded_doc` 在同步服务、异步服务、本地 MCP 工具和异步 MCP 入口下会拒绝空 `sha256`，避免空文档哈希穿透到本地或 PostgreSQL 文档查询。
- 本地 store 与 PostgreSQL store 的 `get_uploaded_doc` 同样会在读取 CSV 或发起 SQL 查询前拒绝空 `sha256`，为绕过服务/MCP 层的直接 store 调用提供兜底防线。
- 已新增 `scripts/verify_core_offline.py` 离线核心自检入口，在不依赖 Hermes、LLM 或任何下游认知服务的情况下，串联验证 `system_health`、夜间 `batch-night-retain-3m` DAG 计划、盘中 CEP 规则扫描和策略风险扫描工具。
- 离线核心自检报告会显式返回 `resource_budget.memory` 与 `resource_budget.postgresql_connections`，并复用 `settings.yaml` 的内存硬限制和 PostgreSQL 连接预算校验，防止资源预算漂移到上线后才暴露。
- 离线核心自检报告显式返回 `offline_boundary.used_external_cognitive_service=false`，用于证明核心层不会主动反向调用认知层。
- 新增单元测试覆盖模拟 `AEQCS_HERMES_URL` 不可用时，核心 `system_health`、夜间批处理任务计划和盘中 `sudden_spike` CEP 告警仍可正常运行。
- 新增单元测试覆盖模拟 `AEQCS_HERMES_URL` 不可用时，离线核心自检仍可通过 MCP 工具执行 `scan_drawdown_risk` 和 `scan_portfolio_risk` 并返回 `risk_officer.*` 告警。
- 已新增 `scripts/verify_mcp_concurrency.py`，可并发调用 `system_health`、`scan_intraday_events`、`scan_drawdown_risk`、`scan_portfolio_risk` 和 `get_market_data`，输出结构化 MCP 并发工具层自检报告。
- MCP 并发自检当前覆盖本地 FastMCP 工具调用边界、分页返回体、列表与非列表返回体字节预算、CEP 扫描稳定性和策略风险扫描工具稳定性。
- 已新增 `scripts/verify_mcp_http_sse.py`，用于在目标部署环境对 `http://127.0.0.1:8000/sse` 执行真实 HTTP/SSE 多连接工具调用压测；脚本会拒绝非 loopback endpoint，并输出连接数、每连接工具数、总调用数、失败项与工具成功计数。
- MCP systemd 服务已配置 `AEQCS_CORE_PG_DSN`，默认使用受限 PostgreSQL 角色 `aeqcs_mcp`。
- MCP systemd 服务已显式配置 `AEQCS_MCP_POOL_SIZE=8`，并且 MCP PostgreSQL 后端会以该值作为 `asyncpg.create_pool(max_size=...)`。
- MCP 已新增回测后台任务工具：`submit_backtest_task` 与 `get_backtest_task`。
- MCP `run_backtest` 已改为非阻塞后台任务语义：立即返回 `backtest_result_id` 与 `running` 状态，调用方通过 `get_backtest_result(backtest_result_id)` 轮询任务状态和完成结果。
- 本地 store 与 PostgreSQL store 的 `get_backtest_result` 会在读取 CSV 或发起 SQL 查询前拒绝空 `backtest_result_id`，为服务/MCP 边界之外的直接 store 调用提供同一层防线。
- 本地 store 与 PostgreSQL store 的 `save_backtest_result` 会在读取 CSV 或 upsert `backtest_results` 前拒绝空 `backtest_result_id` 与空 `strategy_name`，避免坏结果标识或无策略来源的回测报告进入持久化层。
- `run_backtest` 同步服务、异步服务与 MCP 入队入口已共用显式参数校验：缺失 `parameters.symbol`、非正 `initial_cash` / `lot_size`、负费率/滑点等输入会在执行或建任务前以可解释 `ValueError` 拒绝。
- MCP 回测后台任务入队前已显式拒绝不支持的 `strategy_name` 与 `end_date > as_of_date` 的前视请求，避免无效请求写入 `backtest_tasks`。
- 同步/异步服务与本地工具调用边界已统一必填参数读取、日期解析和正整数 ID 解析错误：缺少 `as_of_date` 等必填字段、日期不是 ISO 格式、或 `proposal_id` / `edge_id` 等 ID 不是正整数时，会以可解释 `ValueError` 拒绝，不再暴露裸 `KeyError`、Python 原始转换错误，或把非正 ID 穿透到 PostgreSQL store。
- 本地 store 与 PostgreSQL store 的 `get_proposal_status` 会在读取 CSV 或发起 SQL 查询前拒绝非正 `proposal_id`，为绕过服务/MCP 层的直接 proposal 状态查询提供兜底防线。
- 本地 store 与 PostgreSQL store 的 `review_proposal` 会在读取 CSV 或发起 SQL 查询前拒绝非正 `proposal_id`，为绕过服务/MCP 层的直接 proposal 审核调用提供兜底防线。
- `get_backtest_result` 在同步服务、异步服务、本地 MCP 工具和异步 MCP 入口下会拒绝空 `backtest_result_id`，避免空轮询 ID 穿透到任务注册器、PG 任务恢复逻辑或底层回测结果查询。
- `compute_factors` 与 `get_factor_values` 在同步服务、异步服务和本地 MCP 工具路径下共用 `factor_ids` 结构校验，要求传入非空字符串列表，避免字符串被拆成字符列表后穿透到因子逻辑。
- `submit_backtest_task` 会返回 `task_id` 和任务状态，回测执行在 MCP 事件循环后台完成，避免长回测阻塞 HTTP/SSE 请求。
- `get_backtest_task` 可查询 `queued`、`running`、`completed`、`failed` 状态以及完成后的 `backtest_result_id`，并会在查询任务注册器或 PostgreSQL 任务表前拒绝空 `task_id`。
- PostgreSQL store 的 `get_backtest_task` 同样会在发起 SQL 查询前拒绝空 `task_id`，为绕过 MCP 层的直接 store 调用提供兜底防线。
- PostgreSQL store 的 `save_backtest_task` 会在 upsert `backtest_tasks` 前拒绝空 `task_id` 与空 `status`，避免坏任务标识或无状态任务写入异步回测持久化表。
- PostgreSQL schema 已新增 `backtest_tasks`，用于持久化 MCP 回测后台任务状态。
- `PgCoreStore` 已新增 `save_backtest_task()` / `get_backtest_task()`，支持任务状态 upsert 与查询。
- MCP 回测任务注册器在 PG 后端下会把 `queued`、`running`、`completed` / `failed` 状态同步写入 `backtest_tasks`。
- `get_backtest_task` 会优先读进程内状态；进程内缺失且存在 PG store 时可回落读取持久化任务记录。
- 当新 MCP 进程从 PG store 回落读取到孤儿态 `queued` / `running` 回测任务时，`get_backtest_task` 与 `get_backtest_result` 会将其确定性标记为 `failed` 并写回，避免进程重启后任务永久挂起。
- 已新增 `scripts/verify_mcp_backtest_recovery.py`，可在 `AEQCS_RECOVERY_PG_DSN` 或 `AEQCS_CORE_PG_DSN` 指向的目标 PostgreSQL store 上写入孤儿态回测任务，并通过 `get_backtest_task` / `get_backtest_result` 验证恢复写回路径。
- MCP 已新增盘中异动扫描工具 `scan_intraday_events`，接收结构化行情/新闻事件并返回分页 CEP 告警。
- MCP 已新增策略风险扫描工具 `scan_drawdown_risk` 与 `scan_portfolio_risk`，接收 JSON 友好的 NAV/组合输入并返回确定性 `risk_officer.*` 告警报告。

### 4. PostgreSQL 生产化边界

- 已实现 `PgCoreStore` 基础异步 store。
- 已提供可选 PG 集成测试入口；未配置 `AEQCS_TEST_PG_DSN` 时默认跳过。
- 已为热表加入表级 autovacuum 配置，覆盖 `minute_bar_hot`、`factor_values`、`event_log`、`news_raw`、`proposals`、`signal_log`、`cooccurrence_cache`、`doc_chunks`。
- 已提供 `deploy/vacuum_maintenance.sql`，夜间维护脚本显式包含 `signal_log` 与 `cooccurrence_cache` 的 `VACUUM (ANALYZE)`。
- 已提供 systemd vacuum service/timer 模板。
- 已新增 `runtime/batch.py` 夜间 DAG 计划，显式串行排队备份、`minute_bar_hot` 归档、VACUUM FULL、VACUUM ANALYZE、HNSW 重建和上传解析。
- 已新增 `minute_bar_hot` 归档计划生成逻辑，按保留月数计算 cutoff，并生成 Parquet 分区路径、COPY SQL 与 DELETE SQL。
- 已新增 `batch-night` 命令计划生成逻辑，可审查输出 `pg_dump` 备份、`minute_bar_hot` 归档 COPY/DELETE、VACUUM FULL、`vacuum_maintenance.sql`、HNSW 索引重建和上传解析命令。
- 已新增 `deploy/systemd/batch-night.service` 与 `batch-night.timer`，夜间 DAG 独立在 `00:30 Asia/Shanghai` 触发，避免与 `db-vacuum.timer` 共用同一 OnCalendar 时刻。
- 已新增恢复演练命令计划，包含隔离库 `pg_restore`、Parquet 快照可读性校验和恢复库 `system_health` 自检。
- 已新增 `scripts/restore_rehearsal_health.py`，用于在 `AEQCS_RESTORE_PG_DSN` 指向的隔离恢复库上调用核心层 `system_health`。
- 恢复演练健康检查现在输出结构化审计报告，显式包含 `restore_rehearsal.isolated_database`、恢复库后端名、`system_health` 状态和资源预算，避免只保留裸健康检查结果。
- 已新增 `deploy/systemd/restore-rehearsal.service` 与 `restore-rehearsal.timer`，默认每周日 `02:30 Asia/Shanghai` 触发恢复演练入口。
- 已在 `settings.yaml` 记录 `resources.cgroup_memory_max: 16G`，并为 MCP、盘中、盘后、夜间、vacuum、恢复演练 systemd service 配置 `MemoryMax=16G`。
- 已在配置层新增内存资源预算校验：DuckDB `memory_limit=4GB` 与 embedding 常驻 `max_resident_mb=1024` 会合并计入 16G cgroup 红线。
- `system_health` 已返回 `resource_budget`，可直接审查 `embedding_resident_mb`、`total_planned_mb` 与 `within_limit`。
- 已在 `settings.yaml` 记录 PostgreSQL 连接预算：`max_connections=20`，MCP pool 8、batch 4、intraday 4、maintenance 2、reserved 2；启动前会校验计划连接数不超过上限。
- `runtime/batch.py` 与 `runtime/intraday.py` 已显式声明各自 PG 连接预留，配置测试会校验运行入口声明与 `settings.yaml` 连接预算一致，避免运行侧和配置侧漂移。
- `deploy/init_db.py` 已创建受限 MCP 数据库角色 `aeqcs_mcp`，并只授予核心工具所需的表和序列权限。
- `aeqcs_mcp` 具备行情/财务/因子/回测/文档/图谱/proposal gate 所需的最小读写权限，不授予 schema 全权。
- `aeqcs_mcp` 已具备 `index_constituents` 的只读权限，用于 MCP 按 as-of 查询历史指数成分股。
- `aeqcs_mcp` 已具备 `event_log` 的 SELECT/INSERT 权限，用于核心层发布轻量事件引用，不授予 UPDATE/DELETE。
- `aeqcs_mcp` 已具备 `backtest_tasks` 的 SELECT/INSERT/UPDATE 权限，用于 MCP 回测任务状态持久化。
- 已新增 `scripts/verify_mcp_permissions.py`，可在目标 PostgreSQL 环境审计 `aeqcs_mcp` 的实际授权，检查必需权限是否缺失以及权威表写权限、`event_log` UPDATE/DELETE 等禁止权限是否出现。
- 已新增 `scripts/verify_table_bloat.py`，可在盘中运行满 4 小时后读取 `pg_stat_user_tables`，核验 `signal_log`、`proposals`、`cooccurrence_cache`、`minute_bar_hot` 的死元组比例是否低于阈值。
- 表膨胀 verifier 会显式拒绝观测窗口不足 4 小时的报告，并输出每张热写表的 `n_live_tup`、`n_dead_tup` 与 `dead_tuple_ratio`。

### 5. Qlib 边界守卫

- `aeqcs/data/qlib_adapter.py` 已加入 `QlibBoundaryError`。
- Qlib 市场面板入口要求显式 `as_of_date`。
- Qlib 市场面板会检查 pandas 行数预算和标的数量预算。
- Qlib 市场面板最新日期不得晚于 `as_of_date`。
- Qlib 市场面板在进入后置分析前要求显式 `date` / `instrument` 二维轴，并会拒绝空 `instrument`、不可解析的 `date`、重复 `date/instrument` 行，以及非 finite 的行情数值列，保证传给 Qlib/Pandas 的面板已完成基础清洗。
- 财务 PIT 快照会过滤 `ann_date > as_of_date` 的未来数据。
- 财务 PIT 快照会先通过 DuckDB `DISTINCT ON (instrument, period)` 按 `ann_date DESC, vintage DESC` 选出 as-of 下最新已知版本，再交给 Qlib 后置算子。
- 同一 `instrument/period` 的多 vintage 财务数据不会直接原样进入 Qlib，而是在核心层边界完成 PIT 去重和日期校验。
- 财务 PIT 快照在进入 DuckDB/Qlib 前会拒绝空 `instrument/period`、不可解析的 `ann_date`、重复 `instrument/period/ann_date/vintage` 版本行、非法 `vintage`，以及有值但非 finite 的财务指标，保证 Qlib 只接收已清洗矩阵。
- 已移除 Qlib 表达式因子引擎路径，核心服务拒绝 Qlib 表达式因子 ID。

### 6. DuckDB 因子管线

- 已新增 `aeqcs/factor/pipeline.py`。
- 已新增 `compute_duckdb_factor_values()`，把基础技术因子计算放入 DuckDB。
- DuckDB 管线支持 `memory_limit` 和 `temp_directory`。
- DuckDB 管线支持横截面 `winsorize` 和 `zscore`。
- DuckDB 管线支持按日期、按行业的 `industry_neutralize` 和按日期、按板块的 `sector_neutralize`，中性化在 DuckDB 全市场 reduce 阶段完成。
- `industry_neutralize` / `sector_neutralize` 会要求输入显式提供 `industry` / `sector` 列，缺失时拒绝执行。
- 因子注册表加载时强制每个因子显式声明 `window_type`，不再静默默认为历史窗口；已知 DuckDB 因子的 `lookback_days` 不能低于内置计算窗口。
- `CoreService.compute_factors()` / `AsyncCoreService.compute_factors()` 会拒绝非 `historical` 窗口因子，防止 `centered` 等前视窗口进入生产计算。
- 当前支持并注册 `momentum_1d` 与 `momentum_20d`。
- 技术因子计算已区分输出窗口和历史 lookback 输入窗口：因子注册表可声明 `lookback_days`，服务层按本次 DuckDB 因子的最大 lookback 有界保留历史行供 `lag()` 使用，最终输出仍由 `start_date..end_date` 控制。
- 服务层会取注册 `lookback_days` 与 DuckDB 因子内置窗口的最大值作为裁剪边界，避免误配置把 `momentum_20d` 等计算窗口削短导致因子缺失。
- 已支持基本面 PIT 因子 `roe_quarterly`、`debt_ratio_quarterly`、`equity_ratio_quarterly`、`debt_to_equity_quarterly`、`profit_yoy_quarterly`、`current_ratio_quarterly`、`quick_ratio_quarterly`、`revenue_yoy_quarterly`、`eps_quarterly`、`bps_quarterly`、`gross_margin_quarterly`、`net_margin_quarterly` 和 `margin_spread_quarterly`，从 `financial_indicators` 按 `ann_date <= as_of_date` 取最新已知 vintage，不泄漏未来财报修订。
- `roe_quarterly`、`debt_ratio_quarterly`、`equity_ratio_quarterly`、`debt_to_equity_quarterly`、`profit_yoy_quarterly`、`current_ratio_quarterly`、`quick_ratio_quarterly`、`revenue_yoy_quarterly`、`eps_quarterly`、`bps_quarterly`、`gross_margin_quarterly`、`net_margin_quarterly` 和 `margin_spread_quarterly` 计算不依赖日行情表非空；技术因子走日行情路径，基本面因子走财务 PIT 路径。
- 输出标准字段：`symbol`、`date`、`factor_id`、`version`、`value`、`calc_timestamp`。
- 已新增 `aeqcs/factor/genetic_miner.py`，作为 factor_researcher 范围内的确定性遗传因子挖掘器。
- `mine_genetic_factors()` 使用固定 seed、白名单表达式树和 Spearman 相关评分，不使用 LLM、不使用 `eval`。
- 遗传因子挖掘入口强制 `as_of_date`，拒绝未来样本，并对缺失输入列做显式错误处理。
- 新增单元测试覆盖遗传挖掘输出稳定性、PIT 前视拒绝、输入列校验和因子包公共导出。
- 新增单元测试覆盖 DuckDB 行业中性化、板块中性化，以及缺失行业/板块列时的显式错误。
- 新增单元测试覆盖同步和异步服务的 `roe_quarterly` / `debt_ratio_quarterly` / `equity_ratio_quarterly` / `debt_to_equity_quarterly` / `profit_yoy_quarterly` / `current_ratio_quarterly` / `quick_ratio_quarterly` / `revenue_yoy_quarterly` / `eps_quarterly` / `bps_quarterly` / `gross_margin_quarterly` / `net_margin_quarterly` / `margin_spread_quarterly` PIT 计算，以及无日行情数据时仍可计算基本面因子。
- 新增单元测试覆盖只请求目标日 `momentum_20d` 时仍保留历史 lookback 行、注册表拒绝无效或低于内置窗口的 `lookback_days`，以及服务层按注册 lookback 和内置窗口下限裁剪 DuckDB 输入历史，避免无界历史输入撑大内存或误裁剪造成因子缺失。
- 新增单元测试覆盖财务导入时的 vintage 递增、新 period 重置、同批次修订递增和重复导入幂等。
- 新增单元测试覆盖后复权首日基准、多 symbol 独立基准、追加新除权事件不改写历史，以及缺失 `adj_factor` 时显式拒绝。

### 7. Qlib 后置风险分析边界

- 已新增 `qlib_risk_report()`，作为 Qlib `risk_analysis` 的标准化边界。
- `qlib_risk_report()` 强制要求显式 `as_of_date`。
- NAV 为空、NAV 索引日期不可解析、NAV 值非 finite，或 NAV 最新日期晚于 `as_of_date` 时拒绝执行。
- 输出标准化为 `as_of_date` 与 `metrics`，且会拒绝 Qlib risk_analysis 返回的空指标集合、空白/重复指标名或非 finite 指标值。
- 已新增 `qlib_icir_report()`，作为干净因子矩阵后的 IC/IR 标准化后置分析边界。
- `qlib_icir_report()` 强制要求显式 `as_of_date`，并拒绝日期晚于 `as_of_date` 的因子/收益行。
- `qlib_icir_report()` 在进入 IC/IR 计算前会拒绝空 `symbol`、不可解析的 `date`、重复 `date/symbol` 行，以及非 finite 的因子值或 forward return，保证 Qlib 后置评估只接收已清洗的对齐矩阵。
- IC/IR 输出标准化为 `as_of_date` 与 `metrics`，包含 `ic`、`icir`、`observations`、`dates`。
- 已新增 `qlib_portfolio_optimization_report()`，作为干净 alpha 截面后的组合优化标准化后置边界。
- `qlib_portfolio_optimization_report()` 强制要求显式 `as_of_date`，并拒绝日期晚于 `as_of_date` 的 alpha 输入。
- `qlib_portfolio_optimization_report()` 在进入优化器前会拒绝空 `symbol`、不可解析的 `date`、重复 `date/symbol` 行，以及非 finite 的 alpha 值，保证后置组合优化只接收已清洗的当日 alpha 截面。
- `qlib_portfolio_optimizer()` 已提供确定性 long-only fallback：只使用当日正 alpha，归一到净/总敞口 1.0；无正 alpha 时显式拒绝，真实 Qlib optimizer 仍可通过 `optimizer_fn` 注入替换。
- 组合优化输出标准化为 `as_of_date`、`weights` 与 `metrics`，包含 `gross_exposure`、`net_exposure`、`positions`；optimizer 返回的空有效权重、空 `symbol`、重复 `symbol`、非 finite 权重、零总敞口权重，或不属于当日 alpha 截面的未知标的会被拒绝。

### 8. Proposal 审计晋升入口

- 已新增 `approve_proposal(proposal_id, approver_id, decision)` 核心服务入口。
- 已新增 MCP 工具 `approve_proposal`。
- `submit_proposal` 在同步服务、异步服务和本地 MCP 工具路径下要求 `kind` 为非空提案类型、`payload` 为结构化对象、`source` 为非空审计来源、`confidence` 为 `0..1` 范围内的 finite 数值，且可选 `snapshot_id` 必须为空或正整数，避免坏候选边、空类型、空来源或坏快照引用写入 proposal gate。
- `review_proposal` 在同步与异步服务边界均要求非空 `reviewed_by`，避免空审计身份进入 proposal 状态机。
- `approve_proposal` 要求非空 `approver_id`，并且 `decision` 只允许 `promote`。
- `approve_proposal` 在查找目标 proposal 前即校验 `approver_id` 和 `decision`，避免目标缺失时绕过审计身份要求，或让非法晋升动作触碰 proposal 存储。
- 本地 store 与 PostgreSQL store 的 `approve_proposal` 会在读取 CSV 或发起 SQL 查询前拒绝非正 `proposal_id`，为绕过服务/MCP 层的直接晋升调用提供兜底防线。
- 本地 store 与 PostgreSQL store 的 `review_proposal` 同样会在读取 CSV 或发起 SQL 查询前拒绝非正 `proposal_id`，为 proposal 审核路径补齐存储层输入校验。
- 当前唯一支持的 `decision` 是 `promote`。
- 只有 `approved` proposal 可晋升为 `promoted`。
- `LocalStore` 和 `PgCoreStore` 均已实现该入口。

### 9. 文档上传闭环

- `load_inbox` 支持 base64 上传 txt/md/markdown 文档。
- 文件名校验拒绝路径穿越、子目录路径、Windows 盘符和控制字符。
- 文档解析后会生成 sha256、chunks，并提取简单 proposal。
- 本地 store 和 PG store 均支持上传文档和 chunks 持久化。

### 10. 确定性图谱构建

- 已新增 `aeqcs/knowledge/universe_builder.py`。
- `UniverseBuilder` 支持人工创建节点，要求 `node_id`、`label`、`level`、`created_by` 和 `as_of_date`。
- `UniverseBuilder` 支持创建边，要求父子节点都已存在。
- `UniverseBuilder` 与本地 MCP 图谱工具会拒绝非字符串身份字段，避免 `node_id`、`relation_type` 等坏输入穿透为内部属性错误。
- `UniverseBuilder` 会拒绝 `unknown/root/generic` 等笼统父节点，以及“概念/行业/全部/其他”等泛化父 label，避免把结构化候选边挂到不可审计的大桶上。
- `UniverseBuilder` 会对节点 label 做确定性规范化，拒绝大小写、空白、标点差异造成的同义重复节点。
- 边需要显式 `verify_edge()` 后才会进入 as-of 查询结果。
- `children_as_of()` 拒绝空 `parent_id`，并只返回查询日期前已验证、且查询日期未失效的边。
- `retire_edge()` 支持按日期让边失效，保留审计身份。
- 新增单元测试覆盖节点审计字段、缺失节点拒绝、验证/失效后的 as-of 查询行为。
- PostgreSQL schema 的 `semantic_nodes` 已补入 `label`、`level`、`created_by`、`as_of_date`、`status` 等人工审计字段。
- PostgreSQL schema 的 `semantic_edges` 已补入 `created_by`、`verified_by`、`verified_as_of`、`retired_by`、`valid_from`、`valid_to` 等生命周期字段。
- `PgCoreStore` 已新增 `save_universe_node()`、`save_universe_edge()`、`verify_universe_edge()`、`retire_universe_edge()`、`get_universe_children_as_of()`。
- `get_universe_children_as_of()` 在 PG 路径下只返回 `verified_as_of <= as_of_date` 且未在查询日失效的 child 节点。
- 已为图谱工具新增真实 PostgreSQL 集成测试入口，覆盖节点写入、边写入、验证、按 as-of 查询和失效后查询为空；未配置 `AEQCS_TEST_PG_DSN` 时该测试按设计跳过。
- `CoreService` / `AsyncCoreService` 已挂入确定性图谱工具：创建节点、创建边、验证边、失效边、as-of 查询子节点。
- `CoreService` / `AsyncCoreService` 在验证边和失效边前会显式要求 `verified_by` / `retired_by` 非空，避免空审计身份写入本地或 PostgreSQL 图谱生命周期字段。
- `LocalStore` 与 `PgCoreStore` 的 `verify_universe_edge` / `retire_universe_edge` 会在读取 `semantic_edges.csv` 或更新 `semantic_edges` 前拒绝非正 `edge_id`，避免坏生命周期 ID 穿透到持久化层。
- `LocalStore` 与 `PgCoreStore` 的 `verify_universe_edge` / `retire_universe_edge` 也会在读取 `semantic_edges.csv` 或更新 `semantic_edges` 前拒绝空 `verified_by` / `retired_by`，保证生命周期审计来源在持久化写入前已归一为非空文本。
- `LocalStore` 与 `PgCoreStore` 的 `save_universe_edge` 会在读取图谱节点/边或写入 `semantic_edges` 前拒绝显式非正 `edge_id`，避免坏边 ID 被静默自动改写或写入持久化层。
- `LocalStore` 与 `PgCoreStore` 的 `save_universe_edge` 也会在读取 `semantic_nodes.csv` / `semantic_edges.csv` 或查询 `semantic_nodes` 前拒绝空 `parent_id`、`child_id`、`relation_type` 和 `created_by`，保证图谱边端点、关系类型和人工审计来源在持久化写入前已归一为非空文本。
- `LocalStore` 与 `PgCoreStore` 的 `save_universe_node` 会在读取 `semantic_nodes.csv` 或查询 `semantic_nodes` 前拒绝空 `node_id`，避免坏节点 ID 穿透到同义重复检查或持久化写入。
- `LocalStore` 与 `PgCoreStore` 的 `save_universe_node` 也会在读取 `semantic_nodes.csv` 或查询 `semantic_nodes` 前拒绝空 `label`，保证节点 label 在同义重复检查和持久化写入前已归一为非空文本。
- `LocalStore` 与 `PgCoreStore` 的 `save_universe_node` 也会在读取 `semantic_nodes.csv` 或查询 `semantic_nodes` 前拒绝空 `level`，保证节点层级在持久化写入前已归一为非空文本。
- `LocalStore` 与 `PgCoreStore` 的 `save_universe_node` 也会在读取 `semantic_nodes.csv` 或查询 `semantic_nodes` 前拒绝空 `created_by`，保证人工审计来源在持久化写入前已归一为非空文本。
- MCP 已新增图谱工具：`create_universe_node`、`create_universe_edge`、`verify_universe_edge`、`retire_universe_edge`、`get_universe_children`。
- `LocalStore` 已新增 `semantic_nodes.csv` / `semantic_edges.csv` 本地持久化路径，便于无 PG 环境测试同一套图谱工具。
- `LocalStore` 和 `PgCoreStore` 保存图谱节点时会复用同一套 label 规范化规则拒绝同义重复；保存边时会读取父节点 label/level 并拒绝笼统父节点。

### 11. 回测执行边界

- 回测执行器已支持目标权重降为 0 时，按下一交易日开盘价卖出当前持仓。
- 卖出成交价支持卖方滑点，手续费按卖出金额计算。
- 买入可成交性现在检查卖方盘口 `ask_volume`；卖出可成交性现在检查买方盘口 `bid_volume`。
- 缺失盘口量但开盘价贴 `high_limit` / `low_limit` 时，会分别保守拒绝买入/卖出。
- 卖出路径会拒绝停牌、一字涨跌停和 `bid_volume <= 0` 的不可成交 bar。
- 持仓遇到一字跌停且存在 `low_limit` 时，回测 NAV 会按跌停价计提浮亏，不依赖外部 `close` 字段是否已正确落在跌停价。
- 信号生成后，若下一交易日突然停牌或不可成交，回测不会静默丢弃信号，而是顺延到下一条满足买入/卖出可成交条件的同标的 bar。
- 买入和卖出路径都会按 bar `volume` 裁剪成交数量，并按 `lot_size` 向下取整；无 `volume` 字段时沿用旧行为。
- 回测结果已新增基础订单生命周期记录：每个信号会产生 `filled`、`partial_filled`、`expired` 或 `rejected` 订单状态，记录提交日期、执行日期、方向、数量和原因，并随回测结果持久化到本地 store 与 PostgreSQL `backtest_results.orders`。
- 新增单元测试覆盖正常卖出、次日停牌顺延成交、一字跌停禁止卖出、一字跌停按跌停价计提浮亏、无买方/卖方盘口流动性禁止成交、涨停无卖盘禁止买入、跌停无买盘禁止卖出、买入成交量上限、卖出成交量上限、无持仓卖出拒单、订单 filled/partial_filled/expired/rejected 生命周期，以及 `backtest_results.orders` schema 持久化。
- `strategy/risk.py` 已新增 `scan_drawdown_risk()`，按 NAV 峰值回撤扫描 `warn_threshold` / `red_threshold`，只输出 `risk_officer.review_drawdown` 与 `risk_officer.reduce_risk` 确定性告警。
- 新增单元测试覆盖 drawdown 计算、warn/red 阈值穿越告警，以及低于 warn 阈值时保持 `ok` 且无告警。
- `strategy/portfolio.py` 已新增 `scan_portfolio_risk()`，按组合 NAV 计算总暴露、净暴露和最大单票权重，超过阈值时只输出 `risk_officer.reduce_exposure` 与 `risk_officer.review_concentration` 确定性告警。
- 新增单元测试覆盖组合市值计算、总暴露/单票集中度告警，以及仓位处于阈值内时保持 `ok` 且无告警。
- `CoreService` / `AsyncCoreService` 与 MCP 均已挂载 `scan_drawdown_risk` 和 `scan_portfolio_risk`，服务层负责把 JSON 输入解析为 `date` / `Decimal` 后交给确定性策略模块。
- 策略风险扫描输入解析已新增显式错误边界：NAV 必须是对象列表、NAV 行缺少 `date`、NAV 日期非严格递增、NAV 数值非 decimal、NAV 值非 finite 或非正数、组合持仓和价格必须是对象、组合持仓缺少对应价格、组合输入非 finite decimal、风险阈值非 finite 或为负数等会以可解释 `ValueError` 拒绝。
- 新增单元测试覆盖本地服务和 MCP 工具对 drawdown 风险与组合风险扫描的调用边界，以及风险扫描坏输入的显式拒绝。
- `runtime/risk_alerts.py` 已新增 `publish_strategy_risk_alerts()`，可将 `risk.py` / `portfolio.py` 的确定性扫描报告转换为标准 `RiskAlert` 并发布到 `risk_alerts` 通道。
- 风险报告发布入口强制要求 action 以 `risk_officer.` 开头，拒绝 `market_observer` 等非核心角色路径。

### 12. 事件总线边界

- `EventBus.publish()` 会把完整事件 JSON 写入 `event_log`。
- `pg_notify` 只发布 `event_id` 与 `channel` 轻量引用，避免把 `news_raw.content` 等全文字段塞进 PostgreSQL NOTIFY 的 8000 字节 payload 限制。
- `EventBus.dispatch_notification()` 会按轻量引用回查 `event_log.payload` 后再交给处理器，订阅侧不会依赖 NOTIFY payload 承载全文。
- 事件总线已加入进程内 `event_id` 去重，重复通知同一事件时只派发一次。
- `EventBus.dispatch_notification(..., consumer_id=...)` 已支持数据库级跨进程幂等消费声明：通过 `event_consumptions(event_id, consumer_id)` 唯一键保证同一消费者只处理同一事件一次。
- PostgreSQL schema 已新增 `event_consumptions`，并为受限 MCP 角色授予 SELECT/INSERT 权限；该表已纳入 autovacuum 配置和夜间 `vacuum_maintenance.sql`。
- `EventBus.subscribe()` 已加入可取消的订阅生命周期清理：任务取消时会移除已注册 listener 并释放连接。
- `EventBus.subscribe()` 已加入异常断线后的重连恢复语义：旧 listener 会先清理、旧连接会释放，然后重新获取连接并重新注册订阅。
- 已为事件总线新增真实 PostgreSQL 集成测试入口，覆盖 `EventBus.publish()` 写入完整 `event_log.payload`、真实 LISTEN/NOTIFY 收到轻量引用、`dispatch_notification()` 回查完整 payload，以及重复通知的进程内幂等消费；未配置 `AEQCS_TEST_PG_DSN` 时该测试按设计跳过。
- 已新增 `scripts/verify_risk_alert_delivery.py`，可在 `AEQCS_ALERT_PG_DSN` 或 `AEQCS_CORE_PG_DSN` 指向的目标 PostgreSQL store 上发布确定性 `risk_alerts` 告警，验证真实 LISTEN/NOTIFY 轻量引用、`event_log` 完整 payload、以及 `consumer_id` 幂等消费。
- 新增单元测试覆盖超大新闻正文事件：完整正文保留在 `event_log`，通知 payload 保持轻量且低于 8000 字节。
- 新增单元测试覆盖轻量通知回查完整 payload，并验证重复通知不会重复调用处理器。
- 新增单元测试覆盖订阅任务取消后的 listener 清理和连接释放。
- 新增单元测试覆盖订阅连接异常后的重连、重新注册 listener 和旧连接释放。
- 新增单元测试覆盖策略风险扫描报告发布为确定性 `RiskAlert` 事件，以及非 `risk_officer.*` action 被拒绝。

### 13. 盘中 CEP 规则扫描

- `runtime/intraday.py` 已从脚手架升级为确定性 CEP 规则入口，可加载 `config/cep_rules.yaml`。
- CEP 扫描只执行白名单规则 ID，不使用 `eval` 执行配置中的条件字符串。
- 当前已支持 `sudden_spike`、`s_level_news`、`limit_up_open`、`sector_linkage`、`volume_breakout`、`portfolio_drawdown` 六类配置规则。
- CEP action 仅允许 `risk_officer.*` 与 `data_steward.*`，拒绝 `market_observer`、LLM 或其他非核心角色路径。
- `CoreService` / `AsyncCoreService` 已新增 `scan_intraday_events()`。
- MCP `scan_intraday_events` 返回统一分页包装：`items`、`count`、`offset`、`limit`、`has_more`。
- CEP 事件输入已新增显式校验：缺少 `event_id` / `event_type`、触发行情规则但缺少必需价格字段、或数值字段不可转换时，会以可解释 `ValueError` 拒绝，不再暴露裸 `KeyError`。
- CEP alert 可通过 `publish_cep_alerts()` 转换为标准 `RiskAlert`。
- `RiskAlert` 会通过 `EventBus.publish("risk_alerts", ...)` fire-and-forget 写入 `event_log`，并仅通过 `pg_notify` 发布 `{event_id, channel}` 轻量引用。
- 新增单元测试覆盖 `cep_rules.yaml` 中已配置的 `sector_linkage`、`volume_breakout` 与 `portfolio_drawdown` 确定性 matcher，以及 CEP 坏事件输入的显式拒绝，避免配置规则被扫描器静默跳过或坏输入穿透到底层异常。

### 14. 真实数据适配器输入边界

- `TushareAdapter.daily()` 会在调用限速器或外部 Tushare client 前拒绝空 `symbol` 与 `start > end` 的反向日期范围；`TushareAdapter.fina_indicator()` 会在调用外部 client 前拒绝空 `symbol`。
- Tushare 行情与财务返回行在归一化阶段出现空 `symbol`、不可解析行情 `date` / 财务 `ann_date`、非 finite 数值或非法 `vintage` 时，会在适配器边界统一转为 `DataSourceError`，避免底层清洗异常裸露或坏 provider 行继续写入本地 store。
- 本地导入器 `import_daily_to_local()` / `import_financials_to_local()` 会在调用 adapter 前拒绝空 `symbol`，且 `import_daily_to_local()` 会在调用 adapter 前拒绝 `start > end`，让落盘管线自身也具备外部调用前请求守卫。
- 本地导入器在归一化外部 adapter 输出时会把行情/财务坏行统一包装为 `DataSourceError`，避免非标准 adapter 的底层清洗异常裸露或坏输出越过导入边界。
- 本地导入器会把日行情 OHLC/成交量质量校验失败统一包装为 `DataSourceError`，避免外部 adapter 的逻辑坏 bar 以普通 `ValueError` 形式越过导入边界。
- `AkshareAdapter.concept_constituents()` 会在调用限速器或外部 Akshare client 前拒绝空 `concept`；`AkshareAdapter.stock_news()` 会在调用外部 client 前拒绝空 `symbol`。
- Akshare 返回行归一化会拒绝空成分股 `symbol/name`、非数字成分股 `symbol`、空新闻 `timestamp/title` 与不可解析新闻 `timestamp`，避免外部源坏字段被静默补零、补空或写入后续核心层。
- Tushare 凭据继续通过环境变量或运行时注入传入，不写入代码、文档或本地持久化文件。

## 当前主要风险

1. 真实 TimescaleDB 测试库已通过集成测试、权限审计和 MCP 回测恢复验收；高频表 autovacuum 参数、夜间 VACUUM 脚本、PG 连接预算、表膨胀 verifier 和 systemd `MemoryMax=16G` 已配置，但仍需在目标 systemd/cgroup/PG 环境实际运行 4 小时盘中负载后执行死元组比例抽查，并验证内存硬限制、连接预算和 HTTP/SSE 多连接压测生效。
2. DuckDB/确定性因子管线当前覆盖动量因子、`roe_quarterly` / `debt_ratio_quarterly` / `equity_ratio_quarterly` / `debt_to_equity_quarterly` / `profit_yoy_quarterly` / `current_ratio_quarterly` / `quick_ratio_quarterly` / `revenue_yoy_quarterly` / `eps_quarterly` / `bps_quarterly` / `gross_margin_quarterly` / `net_margin_quarterly` / `margin_spread_quarterly` 基本面 PIT 因子、winsorize、zscore、行业/板块中性化和窗口类型防前视守卫；确定性遗传因子挖掘器已补回核心层，但更多基本面 PIT 因子仍需继续迁移到有界全市场 reduce 流程。
3. Qlib 当前已完成入口守卫、risk_analysis、IC/IR 和组合优化标准化后置边界；组合优化已有确定性 long-only fallback，真实 Qlib 优化器接入仍需目标环境验证。
4. 真实 Tushare/Akshare 网络数据源尚未在当前环境跑通。
5. 事件总线已具备轻量通知发布、订阅侧回查、进程内幂等消费、数据库级跨进程消费声明、订阅取消清理和异常断线重连边界，盘中 CEP 已具备确定性扫描入口，并可把 CEP 告警发布为 `risk_alerts` 轻量事件；真实 PG LISTEN/NOTIFY 集成测试和目标环境告警投递脚本仍需在目标环境执行验证。
6. 回测仍是最小框架；买卖方向盘口可成交性、涨跌停保守拒单、停牌顺延、bar 成交量约束和基础订单 filled/partial_filled/expired/rejected 生命周期已补入，更细粒度撮合和更完整订单状态机仍需扩展。
7. 夜间 `batch-night` DAG 和恢复演练已具备确定性命令计划与 systemd 入口；`pg_dump`、Parquet 归档落盘、VACUUM FULL、HNSW 重建和隔离库 `system_health` 仍需在目标 PostgreSQL/TimescaleDB 环境实际执行演练。
8. 发布工作区已连接 GitHub 远端并推送 `codex/deterministic-core-layer` 分支；原始开发目录仍是非 Git 工作区，仅作为本机工作副本保留。

## 下一步建议

1. 扩展 DuckDB/Polars 因子管线：更多基本面 PIT 因子和更丰富的生产级表达式覆盖。
2. 在目标环境接入并验证真实 Qlib 后置优化器，同时保持当前标准化输入输出边界。
3. 扩展回测执行模型：更细粒度撮合、部分成交事件链和更完整订单状态机。
4. 扩展事件总线：在目标 PG 环境执行 LISTEN/NOTIFY 集成测试和 `scripts/verify_risk_alert_delivery.py` 告警投递验证脚本。
5. 增强 MCP 生产边界：在目标 PG 环境执行角色授权验证与回测任务恢复演练脚本。
6. 在目标 PG/TimescaleDB 环境执行图谱工具真实 PostgreSQL 集成测试。

## 2026-07-01 baostock and data-correctness update

- Added `BaostockAdapter` as a market-data-only source: minute history and daily cross-check only; no financial fundamentals entrypoint is exposed.
- Baostock requests use `adjustflag=3` raw prices, a transparent login/relogin session, and a process-local global mutex rather than token-bucket concurrency.
- Extended `RateLimiter` with generic per-source `daily_quota` counters; `baostock` is configured with `daily_quota: 50000` and `concurrent: false`.
- Registered `sources.minute=baostock` and `sources.daily_cross_check=baostock`; `sources.financial` remains `tushare`.
- Added baostock health registration, daily Tushare/Baostock close-volume cross-check alerts, outlier detection, source failure policy, and `data_quality_alerts` schema.
- Added minute backfill dry-run estimation and checkpoint-resume planning so full-market minute backfill is not assumed to fit in one day.
- Completed dual price adjustment output: storage/backtest path can use `hfq_*`, while `get_market_data` can also return `qfq_*` display prices when system `adj_factor` is available.
- Added stock-universe as-of filtering to prevent survivor bias from future listings or delisted symbols.
- Added corporate action coverage for ST add/remove, name change, and code change, with production schema support.
- Added risk factor registration, deterministic factor-return/covariance/specific-risk snapshot helpers, and cvxpy risk-constrained portfolio optimization.
- Added rolling out-of-sample `backtest_check` with fold-majority pass criteria and validation settings.
- Added CEP price-basis guard: rules using absolute limit prices must declare `price_basis: raw`.
- Verification: real TimescaleDB-backed integration run passed (`tests/integration -m integration`: `3 passed`), and the full suite with the same real DB connection reports `482 passed`.

## 2026-07-01 production acceptance update

- Published branch `codex/deterministic-core-layer` to `Jackiedunk/AEQCS` with deterministic core implementation.
- Production acceptance started from the published branch, not from the non-git working directory.
- Fixed a PostgreSQL-only MCP recovery bug found during acceptance: orphaned backtest recovery now preserves `date` objects for store writes and only JSON-normalizes the payload returned to MCP clients.
- Added regression coverage for PostgreSQL-style backtest task recovery type preservation.
- Local deployment checks passed:
  - `python -m scripts.verify_core_offline`
  - `python -m scripts.verify_mcp_concurrency --concurrency 16`
  - `python -m aeqcs.runtime.batch night`
  - `python -m aeqcs.runtime.batch restore-rehearsal --backup-date 2026-07-01`
- Real TimescaleDB checks passed:
  - `python -m pytest tests/integration -m integration`: `3 passed`
  - `python -m scripts.verify_mcp_permissions`: `status=ok`
  - `python -m scripts.verify_mcp_backtest_recovery`: `status=ok`
  - full suite with real integration DSN: `482 passed`
- Table bloat check was intentionally not marked accepted yet because the required 4-hour intraday observation window has not run on the target Linux/systemd host. A current-state probe reported insufficient observation time and dead tuples in `proposals`.
- Remaining production acceptance is deployment-environment work: target host systemd/cgroup run, HTTP/SSE probe against the live service, four-hour intraday load, table-bloat recheck, real restore rehearsal into an isolated database, and baostock minute backfill dry-run against the live data source.

## 2026-07-01 Linux packaging and interface handoff update

- Added a production-facing Linux installation guide at `docs/LINUX_INSTALL.md`, covering Ubuntu packages, service user, `/opt/aeqcs`, `/data/aeqcs`, `/etc/aeqcs/aeqcs.env`, PostgreSQL/TimescaleDB initialization, systemd installation, acceptance checks, upgrade flow, and WSL2 notes.
- Added `docs/INTERFACE_SETUP.md`, documenting the MCP HTTP/SSE endpoint, exact registered MCP tool names, Hermes caller contract, data-source responsibilities, required environment variables, common commands, and verification scripts.
- Added `docs/OPERATIONS_RUNBOOK.md`, covering daily service checks, data-quality alert handling, baostock backfill quota policy, restore rehearsal, resource budgets, and incident response commands.
- Added `deploy/aeqcs.env.example` as the production environment template and expanded `.env.example` for local development.
- Added `deploy/install_linux.sh` to create the Linux service layout, install dependencies into `/opt/aeqcs/.venv`, create `/etc/aeqcs/aeqcs.env` when absent, and install systemd units.
- Unified `mcp-server`, `intraday`, `batch-eod`, and `restore-rehearsal` systemd units around `User=aeqcs` and `EnvironmentFile=-/etc/aeqcs/aeqcs.env`.
- Added `baostock` to the `data` optional dependency extra so a fresh Linux install can actually use the configured minute-data source.
- Extended `deploy/init_db.py` to create and grant the full `aeqcs_core` runtime role in addition to the restricted `aeqcs_mcp` role.
