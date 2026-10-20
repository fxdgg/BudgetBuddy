# setup-cli Delta

## MODIFIED Requirements

### Requirement: platform.sh 运行时平台探测

`core/lib/platform.sh` 按序探测：① 向上查找 `.codebuddy/setup.sh` → codebuddy 项目级；② `~/.codebuddy/setup.sh` → codebuddy 全局；③ 向上查找 `.claude/agents/` 含本套件 agent → claudecode 项目级；④ `~/.claude/agents/` 含本套件 agent → claudecode 全局；⑤ `.opencode/agent/`（项目级，优先）或 `~/.config/opencode/agent/`（全局）存在本套件 agent → opencode；全部未命中 → 显式报错并列出已检测位置（不静默猜默认）。同时命中多个形态时按探测序取先（codebuddy > claudecode > opencode）。探测结果驱动 `agent preset/custom` 与 hooks 注入的落点（claudecode 形态下 hooks 注入跳过）；`BUDGET_PLATFORM=claudecode` 显式覆盖分支与现有模式一致。【MUST】

#### Scenario: codebuddy 项目级探测

- **WHEN** 在含 `.codebuddy/setup.sh` 的项目子目录执行 setup
- **THEN** 探测结果为该项目根，agent 重写落在该 .codebuddy/agents/

#### Scenario: opencode 探测

- **WHEN** 仅存在 `~/.config/opencode/agent/` 本套件 agent 文件
- **THEN** 探测为 opencode 全局，agent 重写落在该目录且 hooks 注入被跳过

#### Scenario: claudecode 项目级探测

- **WHEN** 在含 `.claude/agents/architect.md`（本套件 agent）的项目子目录执行 setup

- **THEN** 探测为 claudecode 项目级（BUDGET_AGENTS_DIR 指向该项目 .claude/agents），agent 重写落在该目录且 hooks 注入被跳过

#### Scenario: claudecode 全局探测

- **WHEN** 仅存在 `~/.claude/agents/` 本套件 agent 文件
- **THEN** 探测为 claudecode 全局，`BUDGET_PLATFORM_KIND=claudecode`

#### Scenario: 探测失败显式报错

- **WHEN** 全部探测均未命中本套件安装形态
- **THEN** 报错并列出已检测路径（含 .claude 两级），不以默认值静默继续
