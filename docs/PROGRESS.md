# AEQCS 开发进度记录

更新时间：2026-06-30

## 当前状态

项目正在按“持续推进完成项目并复审 bug 修复直到没有任何问题”的目标推进，但还没有达到完整完成态。

当前最后一个已确认推送到 GitHub 的提交是：

```text
本进度文档所在提交：Add local inbox document ingestion
```

GitHub 仓库：

```text
https://github.com/Jackiedunk/AEQCS
```

本次已把通过验证的“上传学习闭环第一段”和本进度文档纳入提交并准备推送到 GitHub。

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

## 当前工作区状态

本次推送前验证通过：

```text
python -m pytest
33 passed

python -m compileall aeqcs tests scripts
passed
```

推送后恢复开发时建议先运行：

```powershell
git --git-dir=.aeqcs_git --work-tree=. status --short
python -m pytest
python -m compileall aeqcs tests scripts
```

## 已验证测试规模

当前推送前测试规模：

```text
33 passed
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
- MCP 本地工具输出经过 JSON 安全转换
- 股票代码前导零在本地 CSV 中保留

## 仍未完成的主要范围

项目距离完整架构书仍有大量工作：

- 真正的 MCP stdio 服务未接通
- PG/TimescaleDB/pgvector 未在真实数据库上做集成测试
- Tushare/Akshare 真实网络数据未跑通
- Qlib 表达式引擎尚未真正接入生产因子管线
- 回测仍是最小 buy-and-hold 框架
- 执行模型、可成交性、手续费、滑点仍需扩展
- Telegram 告警未实现
- intraday 监听和 CEP 规则执行未实现
- semantic network 的写入、搜索、递归树接口还很薄
- 上传学习闭环已做到本地文档解析/分块/简单 proposal 抽取，未做 embedding、PDF/EPUB、人工审核 UI
- dashboard 未实现
- 报告系统未实现
- 8 个 agent 只有角色 prompt，还没有完整行为实现
- 部署脚本没有在 Ubuntu 目标机上实测
- 权限隔离 `aeqcs_core/aeqcs_cog` 尚未完整落地测试

## 建议的下一步

恢复时建议进入以下顺序：

1. 增加文档解析错误类型和安全文件名处理
2. 完成真实 `load_inbox` 的 PG 集成测试和 schema 细节修正
3. 实现 MCP stdio 服务真实工具注册
4. 增加 PostgreSQL 集成测试配置
5. 扩展回测执行模型：手续费、滑点、可成交性、停牌/一字板过滤
6. 实现 semantic network 的本地/PG 节点边写入和查询
7. 把上传提案接到闸门验证和晋升流程

## 说明

本记录用于仓库内追踪 AEQCS 当前开发进度。项目仍处于持续开发中，尚未达到完整架构书的最终完成态。
