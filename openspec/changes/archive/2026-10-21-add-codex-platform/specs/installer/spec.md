# installer Delta

## MODIFIED Requirements

### Requirement: 双平台安装落点

install.sh 支持多平台安装（design.md §10）：codebuddy → dist/codebuddy/ 结构文件复制到 `.codebuddy/`（项目）或 `~/.codebuddy/`（全局），写 `~/.local/bin/budget` 包装器，hooks 注入 settings.json（含 superpowers 插件启用）；opencode → `dist/opencode/{agent,command,skill}` 复制到 `~/.config/opencode/`（全局）或 `.opencode/`（项目），AGENTS.fragment.md 幂等合并进对应 AGENTS.md；claudecode → `dist/claudecode/{agents,commands,skills}` 复制到 `.claude/`（项目）或 `~/.claude/`（全局），CLAUDE.fragment.md 幂等合并进对应 CLAUDE.md，hooks 注入（claudecode-hooks-notify 变更落地后）；codex → `dist/codex/skills/` 复制到 `.codex/skills/`（项目）或 `~/.codex/skills/`（全局），AGENTS.fragment.md 轻量区块合并进项目根/`~/.codex/AGENTS.md`（**既有区块为 opencode 全文形态时告警**），config.toml `[features] multi_agent = true` 幂等注入（显式 false 尊重用户配置仅告警）；管理面（setup.sh/lib/models/personas/docs）统一装 `~/.budgetbuddy/`（A3）。`both` 历史兼容不变，`all` 扩为四平台依次执行；codex 本地清单 mode `codex`（`codex:` 前缀 platform_files 合并写，结构前缀 `skills/`）。【MUST】

#### Scenario: codebuddy 项目级安装

- **WHEN** 在空目录以项目模式安装 codebuddy 平台
- **THEN** 生成 .codebuddy/{agents×10,commands(budget×3+opsx×4),skills×6,rules×12,hooks,lib,setup.sh,docs,budget-models.json,personas.json}，且 `budget setup show` 可执行

#### Scenario: opencode 全局安装

- **WHEN** 以全局模式安装 opencode 平台
- **THEN** ~/.config/opencode/ 下出现 agent/command/skill 结构文件，~/.budgetbuddy/ 出现管理面（含 docs/），AGENTS.md 含标记区块

#### Scenario: claudecode 项目级安装

- **WHEN** 在空目录以项目模式安装 claudecode 平台
- **THEN** 生成 .claude/{agents×10,commands×7,skills×6} + CLAUDE.md 标记区块 + 管理面，`budget setup show` 可执行

#### Scenario: codex 项目级安装

- **WHEN** 在空目录以项目模式安装 codex 平台
- **THEN** 生成 .codex/skills/budget-workflow/{SKILL.md,agents×10,commands×7,rules×12,codex-runtime.md} 与 **其余 5 个 skill（含 budget-notify）**、项目根 AGENTS.md 轻量区块；`.codex/config.toml` 含 `multi_agent = true`（备份已生成）；`~/.budgetbuddy/` 管理面就位；`budget setup show` 可执行

#### Scenario: codex 全局安装

- **WHEN** 全局模式安装 codex
- **THEN** `~/.codex/skills/`（6 个 skill）结构就位，`~/.codex/AGENTS.md` 轻量区块，`~/.codex/config.toml` 注入生效

#### Scenario: all 模式四平台

- **WHEN** `BUDGET_PLATFORM=all` 安装
- **THEN** 四平台依次完成，管理面仅一份（幂等）

### Requirement: 交互与非交互模式

无参数时交互选择平台（CodeBuddy/OpenCode/Claude Code/Codex/全部）与作用域（项目/全局），交互从 /dev/tty 读取；`--global` 跳过交互；`BUDGET_PLATFORM`（codebuddy|opencode|claudecode|codex|both|all）与 `BUDGET_GLOBAL` 环境变量支持纯非交互；纯非交互环境（无 tty）默认项目安装（design.md §10）；`both` 为历史兼容值，帮助文本标注 `all` 为全部平台推荐值。【MUST】

#### Scenario: 环境变量非交互

- **WHEN** `BUDGET_PLATFORM=opencode BUDGET_GLOBAL=1 bash install.sh`
- **THEN** 无任何交互提示完成 opencode 全局安装

#### Scenario: codex 非交互

- **WHEN** `BUDGET_PLATFORM=codex bash install.sh`
- **THEN** 无交互提示完成 codex 项目级安装

#### Scenario: 交互菜单五选项

- **WHEN** 无参数交互安装
- **THEN** 平台菜单含 CodeBuddy / OpenCode / Claude Code / Codex / 全部五选项，选择后进入作用域选择
