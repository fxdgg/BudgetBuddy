# installer Delta

## MODIFIED Requirements

### Requirement: 双平台安装落点

install.sh 支持多平台安装（design.md §10）：codebuddy → dist/codebuddy/ 结构文件复制到 `.codebuddy/`（项目）或 `~/.codebuddy/`（全局），写 `~/.local/bin/budget` 包装器，hooks 注入 settings.json（含 superpowers 插件启用）；opencode → `dist/opencode/{agent,command,skill}` 复制到 `~/.config/opencode/`（全局）或 `.opencode/`（项目），AGENTS.fragment.md 幂等合并进对应 AGENTS.md；claudecode → `dist/claudecode/{agents,commands,skills,hooks}` 复制到 `.claude/`（项目）或 `~/.claude/`（全局），CLAUDE.fragment.md 幂等合并进对应 CLAUDE.md，**hooks/budget-notify-hook.py 分发后注入 settings.json（Notification/PermissionRequest/SubagentStop 三事件，不含 superpowers）**；管理面（setup.sh/lib/models/personas/docs）统一装 `~/.budgetbuddy/`（A3，docs → `~/.budgetbuddy/docs/`）。`both` 模式依次执行 codebuddy+opencode（历史兼容语义不变），`all` 模式依次执行全部平台；claudecode 本地清单 mode `claudecode` 合并写（files 管理面幂等 + platform_files 按平台命名空间合并）。【MUST】

#### Scenario: codebuddy 项目级安装

- **WHEN** 在空目录以项目模式安装 codebuddy 平台
- **THEN** 生成 .codebuddy/{agents×10,commands(budget×3+opsx×4),skills×6,rules×12,hooks,lib,setup.sh,docs,budget-models.json,personas.json}，且 `budget setup show` 可执行

#### Scenario: opencode 全局安装

- **WHEN** 以全局模式安装 opencode 平台
- **THEN** ~/.config/opencode/ 下出现 agent/command/skill 结构文件，~/.budgetbuddy/ 出现管理面（含 docs/），AGENTS.md 含标记区块

#### Scenario: claudecode 项目级安装（hooks 注入）

- **WHEN** 在空目录以项目模式安装 claudecode 平台
- **THEN** 生成 .claude/{agents×10,commands×7,skills×6,hooks/budget-notify-hook.py,CLAUDE.fragment.md 合并入项目根 CLAUDE.md}，`.claude/settings.json` 含三事件 hook 条目（备份 `.bak-budget` 已生成），~/.budgetbuddy/ 出现管理面，`budget setup show` 可执行

#### Scenario: all 模式三平台

- **WHEN** 以 `BUDGET_PLATFORM=all` 执行安装
- **THEN** 三平台落点依次完成安装，管理面仅装一份（幂等）
