# claudecode-platform Specification

## Purpose
TBD - created by archiving change add-claudecode-platform. Update Purpose after archive.
## Requirements
### Requirement: claudecode 平台 DSL 映射与产物结构

`core/platform/claudecode.yaml` 遵循 §3.5 DSL schema（七顶层必填字段 + routing 九键 + emit 表达式白名单），产出 `dist/claudecode/`：agent 落位 `agents/{name}.md`、命令落位 `commands/{group}/{name}.md`（调用形式 `/budget:start`，与 codebuddy 同构）、skill 落位 `skills/{skill}/`、rules 经 `extra_outputs` agents_fragment 合并为 `CLAUDE.fragment.md`（routing.rule 与 dest 一致）、`routing.hook` 为空串（hooks 首发不分发，同 opencode 先例）、models/personas/lib/setup/docs 平移。`EMIT_EXPRESSIONS` 七表达式零扩展，camelCase 输出键（`permissionMode`/`maxTurns`）经 emit 键名实现。【MUST】

#### Scenario: 构建产出三平台

- **WHEN** 运行 `python3 scripts/build.py` 且 core/ 内容齐备
- **THEN** dist/claudecode/ 生成完整产物（agents×10、commands×7、skills×6、CLAUDE.fragment.md、models、personas、lib、setup.sh、docs），manifest 覆盖全部产物文件

#### Scenario: agent frontmatter 映射

- **WHEN** 检查 dist/claudecode/agents/{name}.md 的 frontmatter
- **THEN** 含 `name`、`description`、`model`（balanced 预设烘焙值）、`tools`（PascalCase 列表）、`permissionMode`（edit 全放开→acceptEdits、受限→plan）、`maxTurns`（源存在时），且不含 `model_role`/`permissions` 中立键

#### Scenario: hooks 降级不分发

- **WHEN** 检查 dist/claudecode/ 产物树
- **THEN** 不存在 hooks 文件，构建不因 core/hooks/ 有文件而失败（空串 routing.hook 走既有告警路径）

### Requirement: CLAUDE.md 标记区块幂等合并

claudecode 安装将 `CLAUDE.fragment.md` 合并进目标 CLAUDE.md（项目级 → 项目根 `CLAUDE.md`；全局级 → `~/.claude/CLAUDE.md`）：整体以 `<!-- BudgetBuddy:begin -->` / `<!-- BudgetBuddy:end -->` 包裹，每条 rule 另有二级标记；重复安装仅替换区块内部，区块外用户内容永不触碰；目标文件不存在时创建；合并实现复用 opencode AGENTS.md 的幂等合并机制（标记区块 + 临时文件原子写）。【MUST】

#### Scenario: 幂等重装

- **WHEN** 连续两次执行 claudecode 安装

- **THEN** 目标 CLAUDE.md 区块内容不变（无重复追加），区块外内容保持原样

#### Scenario: 全局落点

- **WHEN** 以全局模式安装 claudecode 平台
- **THEN** `~/.claude/` 下出现 agents/commands/skills 结构文件，`~/.claude/CLAUDE.md` 含标记区块

#### Scenario: 卸载清理区块

- **WHEN** 执行 claudecode 形态卸载
- **THEN** CLAUDE.md 的 BudgetBuddy 标记区块被清理（含区块外内容保留；目标文件仅含区块时移除区块后保留文件），.claude/ 平台结构文件按本地清单本平台段删除

### Requirement: 正文模板变量 claudecode 值

claudecode 平台 `body_variables` 六变量替换值：`TASK_TOOL` = `Task`（Claude Code 子代理派发工具名）、`SKILL_NS` = 空串、`AGENT_DIR`/`RULES_DIR`/`PROJECT_DOC`/`GUARD_PATH` 指向 `.claude/` 与 CLAUDE.md 标记区块对应表述；命令与 skill 正文经变量替换后语义与双平台一致（不硬编码平台路径）。【MUST】

#### Scenario: TASK_TOOL 替换

- **WHEN** 检查 dist/claudecode 的命令与 skill 正文
- **THEN** 全部 `{{TASK_TOOL}}` 替换为 `Task`，无残留模板变量（未知变量除外，走既有告警路径）

