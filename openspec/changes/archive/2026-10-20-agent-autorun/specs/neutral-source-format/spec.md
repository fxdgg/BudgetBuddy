# neutral-source-format Delta

## MODIFIED Requirements

### Requirement: Agent 中立 frontmatter schema

`core/agents/*.md` 必须使用统一中立 frontmatter：`name`（必填，kebab-case 且与文件主名一致）、`description`（必填，一句话职责含触发时机）、`model_role`（必填，取值 ∈ budget-models.json roles）、`tools`（必填，中立小写白名单 read/write/edit/bash/grep/glob/webfetch/websearch 的子集，且与权限语义一致）、`permissions`（可选，`edit_allow` glob 列表 + `bash_allow` 命令模式列表，各键值为三态之一：`["*"]` 全放开 / 非空条目列表受限 / `[]` 显式全禁止，缺省 `["*"]`）、`max_turns`（可选正整数）、`auto_run`（可选布尔，缺省不输出；语义为「subagent 调用工具是否需逐条人工确认」的交互策略声明，与 permissions 允许范围正交；仅 CodeBuddy 平台映射为 `enabledAutoRun`，OpenCode/Claude Code 不映射）；frontmatter 之后必须有非空正文（design.md §3.1/§6）。【MUST】

#### Scenario: name 与文件主名不一致

- **WHEN** 构建时发现某 agent 文件 frontmatter 的 name 与文件主名不同
- **THEN** build.py 校验失败退出非零，输出该文件路径与原因

#### Scenario: model_role 非法

- **WHEN** 某文件的 model_role 不在 budget-models.json 的 roles 键中
- **THEN** build 失败并指出非法角色键

#### Scenario: tools 含白名单外工具

- **WHEN** tools 列表出现白名单之外的任何工具名
- **THEN** build 失败并列出非法工具名

#### Scenario: tools 与权限语义矛盾

- **WHEN** 某 agent `bash_allow: []` 但 tools 含 bash，或 `edit_allow: []` 但 tools 含 write/edit
- **THEN** build 失败并指出 tools 与 permissions 语义不一致

#### Scenario: permissions 值形态非法

- **WHEN** `edit_allow` 或 `bash_allow` 的值为 `["*"]` 与具体条目的混合，或为非列表形态
- **THEN** build 失败并说明合法三态（`["*"]` 全放开 / 非空条目列表 / `[]` 显式全禁止，不允许混合）

#### Scenario: 空列表为合法显式禁止形态

- **WHEN** 某 agent 的 `edit_allow: []`（如 reviewer/director）或 `bash_allow: []`（如 director/goal-evaluator）
- **THEN** 通过构建期校验，语义为显式全禁止（edit 只读 / bash 禁止），不判非法

#### Scenario: auto_run 非布尔形态

- **WHEN** 某 agent 声明 `auto_run` 但值为字符串 `"true"`、整数 `1` 等非布尔形态
- **THEN** build 失败并指出该文件与合法形态（布尔），防止交互策略声明被静默误解

#### Scenario: auto_run 缺省合法

- **WHEN** 某 agent 未声明 `auto_run`（如 architect/reviewer/director 等 6 个保留逐条确认的 agent）
- **THEN** 通过构建期校验，产物不输出 `enabledAutoRun`，维持逐条人工确认

#### Scenario: 合法文件通过校验

- **WHEN** 某文件满足全部 schema 约束且正文非空
- **THEN** 该文件通过构建期校验并进入双平台产物生成
