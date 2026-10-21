# 提案：新增 Codex 平台支持（add-codex-platform）

## Why

BudgetBuddy 已支持 CodeBuddy/OpenCode/Claude Code 三平台。Codex 平台机制经调研已齐备（`spawn_agent`/`wait_agent`/`close_agent` 多代理工具，需 `config.toml [features] multi_agent = true` 启用；`~/.codex/skills/` 与项目级 `.codex/skills/` SKILL.md 原生加载；AGENTS.md 指令链）。参照项目（Codex 形态，MIT）实证了「Leader 现场组装角色 prompt + spawn 派工 + 风险分级路由」的 Codex 原生工作流形态。本机已装 codex-cli 0.163.0，可端到端验证。

## What Changes

- 新增 `core/platform/codex.yaml`：产出 `dist/codex/` 为 **skill 目录形态**——`skills/budget-workflow/`（SKILL.md + 现有子文档 + `agents/` 角色素材 + `rules/` 规范文件 + `codex-runtime.md` 派工契约）+ AGENTS.fragment.md **轻量规则索引**（规避 Codex AGENTS.md 32KiB 上限：只注入规则清单与按需读取指引，不注入全文）+ 管理面
- **不使用 Codex 子代理 TOML 定义**（参照项目实证不可移植）：10 角色 agent md 平移为 skill 内素材（emit 仅 name/description 元数据，drop 模型/权限键），Leader 按 `codex-runtime.md` 契约组装 spawn prompt
- build.py 新增 `extra_outputs` kind `rules_index`（从 core/rules/ 文件名生成轻量索引 fragment）；其余泛化机制零改动
- `budget-models.json` 新增 `platforms.codex` 三档预设：economic→`gpt-5.6-luna`、balanced→`gpt-5.6-terra`、quality→`gpt-5.6-sol`（部署别名，note 说明本地映射前提 + unconfirmed 标注）
- install.sh 新增 `install_codex`：`.codex/skills/`（项目）或 `~/.codex/skills/`（全局）落点、AGENTS.md 轻量区块幂等合并、**`config.toml` `[features] multi_agent = true` 幂等注入**（spawn 工具启用前提）、管理面 `~/.budgetbuddy/`、本地清单 `codex:` 前缀段
- 运行时管理面：platform.sh 探测 codex 分支；preset 切换在 codex 形态降级为档位查询提示（模型由 Leader spawn 时查表，无 frontmatter 烘焙）
- 派工语义：`{{TASK_TOOL}}` → `spawn_agent`；skill 内 `codex-runtime.md`（经 routing.docs 分发）承载 spawn 调用模板、prompt 组装规则、三档模型查表、并行规则
- hooks：不分发（Codex hooks 实验态，维持降级；`budget notify` CLI 可用）

### 非目标（本期不做）

- Codex 插件 marketplace 分发形态
- Codex hooks/notify 事件适配（实验态）
- 任务标签→风险分级（L1/L2/L3）自动路由（保留 BudgetBuddy 既有 coder-lite/standard/senior 分级派工语义，参照项目的确定性评分路由记为后续演进候选）

## Capabilities

### New Capabilities
- `codex-platform`: Codex 平台产物形态与安装落点——DSL 映射、skill 目录结构（agents/rules/codex-runtime 素材）、AGENTS.fragment.md 轻量索引、config.toml multi_agent 注入、派工契约要求

### Modified Capabilities
- `build-pipeline`: `extra_outputs` 新增 `rules_index` kind（轻量索引 fragment 生成）
- `installer`: 新增 codex 安装落点（.codex/skills/、AGENTS.md 合并、config.toml 注入、本地清单）
- `setup-cli`: platform.sh codex 探测分支；preset 子命令 codex 形态降级语义
- `model-presets`: platforms.codex 三档（gpt-5.6-luna/terra/sol 部署别名）+ unconfirmed 标注
- `entry-points`: 命令产物 codex 形态（skill 触发指引，/budget:start 不适用——命令并入 skill 参考文档）
- `repo-docs`: README 双语四平台口径

## Impact

- **代码**：`scripts/build.py`（rules_index kind + `_has_agents_fragment` 扩展为 fragment 类 kind 统一判定）、`core/platform/codex.yaml`、**`core/platform/{codebuddy,claudecode,opencode}.yaml` 三份同步加 `codex-runtime.md: null` docs 声明（新源文件必须全平台声明，否则构建失败）**、`core/docs/codex-runtime.md`（新增，经 docs 分发）、`core/models/budget-models.json`、`install.sh`、`core/lib/{platform.sh, preset.sh, uninstall.sh, validate.sh, notify.sh, quickstart.py, models.sh}`（codex 兼容）
- **设计约束**：Codex AGENTS.md 默认 32KiB（`project_doc_max_bytes`）→ 规则全文不进 AGENTS.md；skill 素材 frontmatter 保留 name/description 元数据；模型为部署别名（用户环境映射前提）
- **测试**：build/installer/preset/platform codex 用例
- **风险**：spawn 编排可靠性靠 prompt 契约（无结构化 Task 工具强约束）→ 本机 codex 0.163.0 端到端验证派工；config.toml 注入幂等（TOML 无现成引擎，写最小追加逻辑）；别名模型 ID 无法本机核对 → unconfirmed 标注 + 逃生门为「编辑 budget-models.json `platforms.codex.presets`（`budget setup models` 指引）或 spawn 时显式传 model」
