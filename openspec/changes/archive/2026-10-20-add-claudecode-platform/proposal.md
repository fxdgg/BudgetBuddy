# 提案：新增 Claude Code 平台支持（add-claudecode-platform）

## Why

BudgetBuddy 目前仅支持 CodeBuddy 与 OpenCode 双平台。Claude Code 用户基数大且其扩展约定（`.claude/agents/*.md` 子代理、`commands/{group}/{name}.md` 分组斜杠命令、`skills/{skill}/SKILL.md`、`permissionMode: acceptEdits/plan` 枚举、PascalCase 工具名）与 CodeBuddy 高度同构，接入成本显著低于其他平台——调研结论为 3–5 人日、难度低，是"单一中立源 + 构建期平台适配"架构的最低成本扩张。

## What Changes

- 构建系统从"双平台硬编码"泛化为"平台数据驱动"：build.py 中 5 处双平台假设（`_MODEL_PLATFORMS` 枚举、models 校验循环、`_PLATFORM_NOTE_LINES` 文案、CLI choices、默认平台列表）改为从 `core/platform/*.yaml` 与 `budget-models.json` 数据推导，新增平台不再改转换器代码
- 新增 `core/platform/claudecode.yaml` 映射 DSL，产出 `dist/claudecode/`：agents/commands/skills 落位 `.claude/` 约定（命令 `/budget:start` 与 CodeBuddy 同构），rules 经 `extra_outputs` agents_fragment 机制合并为 `CLAUDE.fragment.md`
- agent frontmatter 映射：`permissionMode`（复用 `compute_permission_mode` + DSL `permission_mode_rule`）、`maxTurns`/`permissionMode` camelCase 输出键（emit 键名任意，零 DSL 扩展）、`model` 烘焙 Claude 系模型
- `budget-models.json` 新增 `platforms.claudecode` 三档预设（economic→haiku 系 / balanced→sonnet 系 / quality→opus 系），`models.paid.claude` 条目 `platform` 数组扩展 `claudecode`
- 安装器新增 claudecode 分支：`.claude/`（项目）或 `~/.claude/`（全局）落点、`CLAUDE.fragment.md` 幂等合并进 CLAUDE.md（复用 opencode AGENTS.md 合并先例）、交互菜单与非交互 `BUDGET_PLATFORM=claudecode` 支持
- 运行时管理面兼容：`platform.sh` 探测新增 claudecode 分支；`preset`/`agent custom` 等子命令对 Claude Code agent frontmatter 读写兼容
- hooks **首发降级不分发**（同 opencode 先例，v2 变更再适配 Claude Code settings.json hooks 事件 schema）
- 文档与门禁：README/CODEBUDDY.md/AGENTS.md 同步三平台描述（CODEBUDDY.md 双入口说明扩展为三入口），MODEL_SELECTION.template 渲染三平台表格；scan-brand 范围自动覆盖 `dist/claudecode/`；单元测试三平台扩展

### 非目标（本期不做）

- Codex 平台支持（已定后续独立提案，模型别名将采用 gpt-5.6-luna/terra/sol 三档）
- Claude Code hooks 注入与通知适配
- Claude Code 插件（plugin marketplace）分发形态
- superpowers 命名空间在 Claude Code 端的等价物

## Capabilities

### New Capabilities
- `claudecode-platform`: Claude Code 平台产物形态与安装落点要求——`core/platform/claudecode.yaml` DSL 映射、`dist/claudecode/` 产物结构（`.claude` 约定落位、agents frontmatter camelCase 映射、命令 `/budget:start` 形态、CLAUDE.fragment.md 规则合并产物）、CLAUDE.md 幂等合并、hooks 降级不分发声明

### Modified Capabilities
- `build-pipeline`: 平台清单从双平台硬编码改为数据驱动（枚举 `core/platform/*.yaml` + models platforms 键推导）；`--platform` choices 与默认构建范围随之扩展；三平台 manifest/原子替换行为不变
- `installer`: 新增 claudecode 安装落点（项目 `.claude/` / 全局 `~/.claude/`）、CLAUDE.md fragment 幂等合并、本地清单 platform_files 结构、交互菜单三平台选项与非交互 `BUDGET_PLATFORM=claudecode|all`
- `model-presets`: `budget-models.json` 新增 `platforms.claudecode` 三档十角色预设；claude 系条目 `platform` 数组扩展；MODEL_SELECTION 渲染表新增 claudecode 列与平台说明段
- `entry-points`: 命令产物三平台——claudecode 与 codebuddy 同为 `commands/{group}/{name}.md`（`/budget:start`），正文六变量按 claudecode 平台值替换
- `setup-cli`: `platform.sh` 运行时探测新增 claudecode 分支（`.claude/` 项目/全局）；`agent preset|custom|inherit|show|diff` 对 claudecode frontmatter 的读写兼容
- `repo-docs`: CODEBUDDY.md/AGENTS.md 双入口指针扩展为三平台说明，README 架构与安装章节同步

## Impact

- **代码**：`scripts/build.py`（泛化 5 处硬编码 + emit 逻辑不动）、`core/platform/claudecode.yaml`（新增）、`core/models/budget-models.json`（数据扩展）、`install.sh`（新增 install_claudecode 分支）、`core/lib/platform.sh`（探测扩展）、`core/lib/preset.sh` 等管理面（frontmatter 兼容）、`core/docs/MODEL_SELECTION.template.md`（平台列）
- **数据**：`budget-models.json` 结构性扩展（`_MODEL_PLATFORMS` 枚举 + claudecode 预设段），schema（budget-models.schema.json）如约束 platform 枚举需同步
- **产物**：新增 `dist/claudecode/`（构建+门禁+发布包范围自动扩展，`scripts/build-release.sh` 无需改动则验证之）
- **测试**：`tests/`（build/installer/models 相关用例三平台扩展）
- **不受影响**：YAML 子集解析器、EMIT_EXPRESSIONS 七表达式（零扩展）、中立源格式、P0 一致性 diff、personas 体系
- **风险**：Claude Code frontmatter 演进较快，但无法识别字段静默忽略（不炸构建）；CLAUDE.md 合并幂等性复用既有标记区块机制；Claude 系模型 ID 的可用性需在本机 Claude Code 环境核对（未确认 ID 沿用 `_meta.unconfirmed_*` 机制标注）
