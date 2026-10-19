# Proposal: foundation — BudgetBuddy 全量首版（v0.1.0）

## Why

新项目 BudgetBuddy 需要在一次变更中落地完整的**多 Agent 省钱研发工作流套件**（10 个子 agent、5 阶段工作流、Coder Guard、Review Gate、Director 终裁、模型分级预设、personas、通知、hooks、openspec 集成），并以「单一中立源 + 构建转换」架构同时支持 CodeBuddy 与 OpenCode 双平台。架构设计已经用户确认（`docs/plans/2026-10-16-budgetbuddy-architecture-design.md`），本变更是该设计的首次全量实现（v0.1.0 基线）。

## What Changes

- 新建 `core/` 单一源：10 个中立 agent 定义、6 个 skill（budget-workflow / budget-notify / openspec×4）、7 个命令模板（start/status/goal + opsx×4）、12 条 rule、`budget-models.json`、`personas.json`（5 主题）、`platform/*.yaml` 平台适配 DSL、`lib/` 管理脚本源、`hooks/` 通知引擎源、`docs/` 中立文档。
- 新建 `scripts/build.py`（core → dist 双平台转换，原子构建、幂等）、`scripts/scan-brand.py`（违禁词门禁）、`scripts/build-release.sh`（打包 + .sha256 校验文件）。
- 新建 `install.sh` 双平台安装器（项目级/全局级、release 下载 SHA256 强制校验、manifest 增量同步、安装清单持久化与升级差集清理、AGENTS.md 标记区块合并）。
- 新建 `dist/codebuddy/` 与 `dist/opencode/` 构建产物（提交 git）。
- 新建仓库元数据与自举说明：README / README_CN / CHANGELOG / VERSION / LICENSE / CODEBUDDY.md / AGENTS.md。
- **不做**：不重新设计架构（四项已定决策不重开）；不含参照项目品牌任何内容；不做第三个平台适配（仅保证架构可扩展）。

## Capabilities

**New Capabilities**（均无既有 spec，全部新建）：

- `neutral-source-format` — 中立源格式：agent/命令 frontmatter schema、正文模板变量、平台映射 DSL
- `build-pipeline` — 构建转换：core → dist 双平台、原子构建、幂等、选择性构建、--check/--strict
- `brand-compliance` — 违禁词扫描门禁
- `agent-roster` — 10 个 agent 中立定义与权限语义（permissions 三态）
- `workflow-orchestration` — budget-workflow：5 阶段、Coder Guard、Review Gate、Director 终裁、goal loop
- `entry-points` — 命令入口（budget:start/status/goal + opsx×4）与 openspec 4 个 skill
- `notify` — 通用 webhook 通知（四渠道 + N1-N11 通知点 + hooks）
- `model-presets` — 模型目录与三档预设（双平台）、custom 覆写
- `setup-cli` — setup.sh 子命令体系、lib 模块、budget CLI 包装器、personas、数据目录、superpowers 插件启用
- `installer` — 双平台安装器、下载完整性校验、增量同步与安装清单持久化
- `repo-docs` — README/docs/自举说明/版本元数据

**Modified Capabilities**: 无。

## Impact

- 全新仓库，无存量代码影响面；git main 已初始化。
- 产物提交进 git（`dist/`），构建门禁在本地/CI 通过 `python3 scripts/build.py --check` 执行。
- 外部依赖：Python3 stdlib only（build/scan/notify）；安装器依赖 curl/tar/python3/sha256 工具。
- 品牌合规为 P0 硬约束：所有产出（含本变更全部 openspec 产物）不得包含违禁词表中的任何词汇（词表定义与载体豁免见 design.md §5/§12-A10）。
- 任务口径：13 任务 / 24 执行单元（T1/T3/T9 各拆 3、T8 拆 2、T10 拆 4 + quickstart 单列），每执行单元 ≤2h（见 tasks.md 与 design.md §14/§16）。
