# AEQCS 开发进度记录

更新时间：2026-06-30

## 当前状态

项目正在按“持续推进完成项目并复审 bug 修复直到没有任何问题”的目标推进，但还没有达到完整完成态。

当前最后一个已确认推送到 GitHub 的提交是：

```text
本进度文档所在提交：Add AEQCS v2 architecture blueprint
```

GitHub 仓库：

```text
https://github.com/Jackiedunk/AEQCS
```

本次按用户要求把 AEQCS v2 核心架构书纳入仓库，并在 README 与进度文档中记录入口。

## 已完成并推送的阶段

### 1. 项目骨架

已完成：

- 创建 AEQCS Python 项目结构
- 创建配置目录、核心模块、数据层、因子层、策略/回测层、闸门层、知识层、运行入口、部署目录和测试目录
- 初始化本地 Git 仓库并推送到 GitHub

对应提交：

```text
0967c2a Scaffold AEQCS deterministic core
```

### 2. 确定性核心第一阶段

已完成：

- 标准数据模型：日线、财务指标、因子值
- 日线数据质量校验
- PIT 财务切片
- 基础因子计算：技术、基本面、情绪、另类因子
- 最小事件驱动回测
- 次日开盘成交规则
- 组合记账和回撤计算

对应提交：

```text
8c3ad38 Build deterministic phase one core
```

### 3. 本地核心服务与 MCP 工具核心

已完成：

- `LocalStore`：本地 CSV 开发存储
- `CoreService`：核心业务服务层
- `call_local_tool()`：MCP 工具逻辑的本地可测试入口
- 行情、财务、因子、回测、proposal 的本地调用路径

对应提交：

```text
c3d9533 Add local core service tool implementations
```

### 4. 数据源适配边界

已完成：

- Tushare 适配器边界
- Akshare 适配器边界
- 懒加载外部依赖
- fake client 测试
- 日线和财务导入到 `LocalStore`
- `scripts/import_tushare_local.py`

对应提交：

```text
8014cbb Add market data adapter boundaries
```

### 5. 核心服务边界加固

已完成：

- JSON 安全转换
- `CoreStore` / `AsyncCoreStore` 协议初步拆分
- `PgCoreStore` 基础接口
- 防前视边界：拒绝 `end_date > as_of_date`
- 未知因子显式报错

对应提交：

```text
881673c Harden core service storage boundaries
```

### 6. Proposal 验证闸门状态机

已完成：

- `ProposalStatus`
- `ProposalReview`
- 闸门状态迁移规则
- `GateStateError`
- proposal 结构校验
- 本地/PG proposal 审核状态更新
- MCP 本地工具 `review_proposal`

对应提交：

```text
2f3e89c Add proposal gate state machine
```

### 7. 回测结果持久化

已完成：

- `BacktestReport`
- `run_backtest` 返回 `backtest_result_id`
- `get_backtest_result`
- 本地/PG 保存和查询回测结果
- `deploy/init_db.py` 增加 `backtest_results` 表

对应提交：

```text
f7289bf Persist backtest reports behind tool contract
```

### 8. 因子值持久化

已完成：

- `compute_factors` 计算后保存标准化 `factor_values`
- `get_factor_values`
- 本地/PG 保存和查询因子值
- 因子查询强制 as-of 约束

对应提交：

```text
240fc46 Persist computed factor values
```

### 9. 上传学习闭环第一段

已完成：

- `load_inbox` 本地工具入口
- `get_uploaded_doc` 本地工具入口
- base64 上传内容解码
- txt/md/markdown 文档解析
- sha256 去重
- 文本分块
- 本地保存 `uploaded_docs`
- 本地保存 `doc_chunks`
- PG 保存 `uploaded_docs`
- PG 保存 `doc_chunks`
- PG 保存同一文档时先删除旧 chunks，避免重复
- 简单规则抽取：
  - `factor: factor_id = definition`
  - `correction: target => corrected`
- 抽取结果进入 proposal 闸门
- 增加 ingest 单元测试和 PG chunk 替换测试

对应提交：

```text
本进度文档所在提交：Add local inbox document ingestion
```

### 10. 上传入口安全校验加固

已完成：

- 增加项目内 `DocumentParseError` 文档解析错误类型
- base64 上传内容非法时返回明确解析错误
- 上传文件名必须是单文件名，拒绝路径穿越、子目录路径、Windows 盘符路径和控制字符
- 上传入口只写入校验后的安全文件名
- 不支持的扩展名统一按文档解析错误处理
- UTF-8 解码失败统一按文档解析错误处理
- 增加路径安全和不支持扩展名单元测试

对应提交：

```text
本进度文档所在提交：Harden inbox upload validation
```

### 11. PG 上传服务路径与 schema 约束

已完成：

- 增加 `parse_text_upload`，支持不落盘地从上传字节生成标准 `ParsedDocument`
- 增加 `AsyncCoreService.load_inbox`
- 异步上传路径可直接服务 `PgCoreStore`
- PG 上传路径复用同一套安全文件名、base64、UTF-8、分块和 proposal 抽取逻辑
- `PgCoreStore.save_uploaded_doc` 重复 sha256 时同步更新 filename/doc_type/path/status
- `doc_chunks` 增加 doc 外键、非空 doc_id/seq、`(doc_id, seq)` 唯一约束
- chunk 写入支持 `(doc_id, seq)` 冲突更新
- 增加异步服务测试、PG upsert 语义测试和 schema 约束测试

对应提交：

```text
本进度文档所在提交：Add async inbox service path
```

### 12. MCP stdio 工具注册

已完成：

- `aeqcs-mcp` 入口从占位退出改为启动 FastMCP stdio 服务
- 增加 `build_mcp_server()`，便于测试和部署复用
- 注册当前已实现的 12 个核心工具
- manifest 删除未实现的 semantic 占位工具，避免客户端看到不可调用工具
- MCP 工具复用现有 `call_local_tool` 确定性实现
- 支持 `AEQCS_LOCAL_ROOT` 环境变量覆盖本地数据目录
- 增加 MCP 工具注册、健康检查、上传调用测试

对应提交：

```text
本进度文档所在提交：Wire MCP stdio server tools
```

### 13. PostgreSQL 集成测试入口

已完成：

- 增加 pytest `integration` 标记
- 增加 `tests/integration/test_pg_integration.py`
- 集成测试默认跳过，只有设置 `AEQCS_TEST_PG_DSN` 时才连接真实数据库
- 集成测试会执行 `deploy.init_db.SCHEMA_SQL`
- 覆盖 PG 日线 PIT 查询、财务 PIT 查询、上传文档/chunk round trip、proposal 提交和审核 round trip
- 增加 [docs/POSTGRES_INTEGRATION_TESTS.md](POSTGRES_INTEGRATION_TESTS.md) 说明运行前提和命令
- README 增加可选 PG 集成测试运行方式

对应提交：

```text
本进度文档所在提交：Add PostgreSQL integration test entrypoint
```

### 14. 回测执行成本和基础可成交性

已完成：

- 增加 `ExecutionConfig`
- 回测支持 `fee_rate`
- 回测支持 `min_fee`
- 回测支持买入方向 `slippage_bps`
- 股数计算会把手续费纳入预算，避免费用导致现金超支
- 回测接入基础买入可成交性过滤：`is_trading`、`is_suspend`、`is_one_word_limit`、`bid_volume`
- `run_backtest` 工具参数支持 `fee_rate`、`min_fee`、`slippage_bps`、`lot_size`
- 增加手续费/滑点、停牌、一字板、无买盘和服务层参数透传测试

对应提交：

```text
本进度文档所在提交：Add backtest execution costs and tradability
```

### 15. MCP stdio 通道污染防护

已完成：

- 新增 `configure_stdio_safety()`
- `aeqcs-mcp` 启动 stdio 服务前强制把 Python root logging 配置到 `stderr`
- structlog 存在时改为 stdlib logger factory，避免默认 stdout 输出污染 MCP stdout
- 新增 `_call_tool_safely()`，所有 MCP 工具调用都在 `redirect_stdout(sys.stderr)` 内执行
- 防止业务代码、三方库或误用 `print()` 在工具执行期间写入 stdout
- 保留 FastMCP/MCP transport 自己使用 stdout 发送 JSON-RPC 帧
- 新增测试：模拟工具内部误写 stdout，验证 stdout 为空、噪声进入 stderr
- 新增测试：验证 logging warning 不进入 stdout

对应提交：

```text
本进度文档所在提交：Harden MCP stdio safety
```

### 16. AEQCS v2 核心架构书入库

已完成：

- 新增 [docs/AEQCS_ARCHITECTURE_V2.md](AEQCS_ARCHITECTURE_V2.md)
- 架构书正文从 `# AEQCS 完整开发架构书 v2` 开始保存，去掉粘贴附件头部说明
- README 增加核心蓝图入口
- 本次未改变运行时代码逻辑

对应提交：

```text
本进度文档所在提交：Add AEQCS v2 architecture blueprint
```

## 五大核心风险当前处理状态

1. stdio 通道污染：本次已做第一轮代码级防护和测试。MCP 工具执行期间 stdout 会重定向到 stderr，日志配置到 stderr。仍需后续做真实进程级 stdio 客户端握手测试。
2. Qlib 强融 Pandas 内存爆仓：尚未处理。下一步应把因子计算边界明确为 DuckDB/Polars 优先，Qlib 仅做后置分析，并增加内存预算/禁止全市场 Pandas MultiIndex 强喂的测试或守卫。
3. Qlib PIT 对齐前视漏洞：尚未处理。下一步应在 `data/qlib_adapter.py` 强制 as-of 快照生成，禁止多 vintage 财务数据直接进入 Qlib。
4. PostgreSQL 高频写入表膨胀：尚未处理。下一步应补 `postgresql.conf` 表级 autovacuum 策略和夜间 VACUUM 维护脚本。
5. 大模型 API 延迟阻塞核心层：尚未处理。下一步应为认知层调用建立异步队列/熔断器接口，保证 intraday 主循环不等待 LLM。

## 当前工作区状态

本次推送前验证通过：

```text
python -m pytest
50 passed, 1 skipped

python -m compileall aeqcs tests scripts deploy
passed
```

推送后恢复开发时建议先运行：

```powershell
git --git-dir=.aeqcs_git --work-tree=. status --short
python -m pytest
python -m compileall aeqcs tests scripts deploy
```

## 已验证测试规模

当前推送前测试规模：

```text
50 passed, 1 skipped
```

## 重要技术约束和已守住的边界

目前已明确实现或测试过：

- PIT/as-of 是核心数据访问边界
- 回测拒绝 `end_date > as_of_date`
- 因子查询拒绝 `end_date > as_of_date`
- 财务数据按 `ann_date <= as_of_date` 切片
- proposal 不能绕过闸门状态机
- `rejected/promoted` 是终态
- `approved` 只能进入 `promoted`
- 回测使用次日开盘成交
- 回测买入执行已支持手续费、最低费用、滑点和基础可成交性过滤
- MCP 本地工具输出经过 JSON 安全转换
- MCP stdio 服务已能注册并调用当前已实现工具
- MCP 工具执行期间 stdout 已重定向到 stderr，降低 stdio JSON-RPC 通道污染风险
- PostgreSQL 集成测试入口已建立，未配置 DSN 时默认跳过
- 股票代码前导零在本地 CSV 中保留
- 上传文件名拒绝路径穿越和非文本扩展名
- 上传文档解析错误使用项目内显式错误类型
- PG 文档 chunk 受 doc 外键和 `(doc_id, seq)` 唯一约束保护

## 仍未完成的主要范围

项目距离完整架构书仍有大量工作：

- MCP stdio 本地工具服务已接通并做了 stdout 污染防护，但尚未接入生产 PG 配置和真实 stdio 客户端握手测试
- PG/TimescaleDB/pgvector 集成测试入口已建立，但尚未在目标主机真实数据库上执行验证
- Tushare/Akshare 真实网络数据未跑通
- Qlib 表达式引擎尚未真正接入生产因子管线
- 回测仍是最小 buy-and-hold 框架，尚未支持多策略组合和完整订单生命周期
- 执行模型已支持基础手续费/滑点/买入可成交性，但卖出、涨跌停细分、成交量约束和撮合细节仍需扩展
- Telegram 告警未实现
- intraday 监听和 CEP 规则执行未实现
- semantic network 的写入、搜索、递归树接口还很薄
- 上传学习闭环已做到本地/PG 文档解析、分块、简单 proposal 抽取和文件名安全校验，未做 embedding、PDF/EPUB、人工审核 UI
- dashboard 未实现
- 报告系统未实现
- 8 个 agent 只有角色 prompt，还没有完整行为实现
- 部署脚本没有在 Ubuntu 目标机上实测
- 权限隔离 `aeqcs_core/aeqcs_cog` 尚未完整落地测试

## 建议的下一步

恢复时建议进入以下顺序：

1. 继续处理风险 2：禁止 Qlib 强融 Pandas 全市场大矩阵，明确 DuckDB/Polars 因子计算边界
2. 处理风险 3：在 `data/qlib_adapter.py` 增加 as-of/PIT 快照对齐守卫
3. 处理风险 4：补高频写入表 autovacuum/VACUUM 维护配置
4. 处理风险 5：补认知层 LLM 异步队列和熔断器接口
5. 对风险 1 做真实 MCP stdio 客户端握手级测试

## 说明

本记录用于仓库内追踪 AEQCS 当前开发进度。项目仍处于持续开发中，尚未达到完整架构书的最终完成态。
