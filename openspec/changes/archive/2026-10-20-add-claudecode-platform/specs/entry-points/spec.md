# entry-points Delta

## MODIFIED Requirements

### Requirement: budget 组三命令（start / status / goal）

`core/commands/budget/` 提供 `start.md`、`status.md`、`goal.md` 三个中立命令模板（design.md §11）：start 触发加载 `budget-workflow` skill 并透传 `$ARGUMENTS` 需求描述，正文重申「主会话为 Leader、只编排不编码、必须指定 subagent_type」；status 调用 budget 状态机（`budget-state.py`）查询当前 openspec change 与任务进度；goal 启动 goal loop（goal-evaluator 验收判定流程）。命令正文使用 §3.3 模板变量表达平台差异，不硬编码平台路径。三平台产物：codebuddy `commands/budget/start.md`（`/budget:start`）、opencode `command/budget-start.md`（`/budget-start`）、claudecode `commands/budget/start.md`（`/budget:start`）。【MUST】

#### Scenario: start 命令产物

- **WHEN** 构建完成后检查三平台产物

- **THEN** dist/codebuddy 与 dist/claudecode 产物为 `commands/budget/start.md`（调用形式 `/budget:start`），dist/opencode 产物为 `command/budget-start.md`（调用形式 `/budget-start`），三者正文语义一致（仅六变量替换值不同）

#### Scenario: start 缺少需求参数

- **WHEN** 用户执行 /budget:start（或 /budget-start）未带 `$ARGUMENTS`
- **THEN** 命令文档指导 Leader 先澄清需求再进入流程

#### Scenario: claudecode 命令 frontmatter

- **WHEN** 检查 dist/claudecode/commands/{group}/{name}.md 的 frontmatter

- **THEN** 仅含 `description` 与 `argument-hint` 字段（命令名由产物文件路径承载），不含 name 字段

### Requirement: opsx 组四命令（apply / archive / explore / propose）

`core/commands/opsx/` 提供 `apply.md`、`archive.md`、`explore.md`、`propose.md` 四个命令模板（design.md §11、§12-A2），分别作为 openspec 四个 skill 的命令入口；产物调用形式为 `/opsx:apply` 等（opencode 为 `/opsx-apply` 等，claudecode 与 codebuddy 同为 `/opsx:apply`）。【MUST】

#### Scenario: opsx 命令产物

- **WHEN** 构建完成后检查三平台产物

- **THEN** 三平台各有 4 个 opsx 命令文件，命名与调用形式符合各平台 routing 规则
