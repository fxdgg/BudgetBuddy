# setup-cli Delta

## MODIFIED Requirements

### Requirement: platform.sh 运行时平台探测

`core/lib/platform.sh` 按序探测：① 向上查找 `.codebuddy/setup.sh` → codebuddy 项目级；② `~/.codebuddy/setup.sh` → codebuddy 全局；③ 向上查找 `.claude/agents/` 含本套件 agent → claudecode 项目级；④ `~/.claude/agents/` → claudecode 全局；⑤ 向上查找 `.codex/skills/budget-workflow/`（**SKILL.md 套件签名校验**）→ codex:project；⑥ `~/.codex/skills/budget-workflow/`（同签名校验）→ codex:global；⑦ `.opencode/agent/`（项目级，优先）或 `~/.config/opencode/agent/`（全局）存在本套件 agent → opencode；全部未命中 → 显式报错并列出已检测位置（不静默猜默认）。探测结果驱动管理面落点（codex 形态 agent 目录语义 = skill 内 agents/ 素材目录）；`BUDGET_PLATFORM=codex` 显式覆盖分支同现有模式。【MUST】

#### Scenario: codebuddy 项目级探测

- **WHEN** 在含 `.codebuddy/setup.sh` 的项目子目录执行 setup
- **THEN** 探测结果为该项目根，agent 重写落在该 .codebuddy/agents/

#### Scenario: opencode 探测

- **WHEN** 仅存在 `~/.config/opencode/agent/` 本套件 agent 文件
- **THEN** 探测为 opencode 全局，agent 重写落在该目录且 hooks 注入被跳过

#### Scenario: claudecode 探测

- **WHEN** 仅存在 `~/.claude/agents/` 本套件 agent 文件
- **THEN** 探测为 claudecode 全局，`BUDGET_PLATFORM_KIND=claudecode`

#### Scenario: codex 项目级探测

- **WHEN** 在含 `.codex/skills/budget-workflow/SKILL.md` 的项目子目录执行 setup
- **THEN** 探测为 codex:project，BUDGET_AGENTS_DIR 指向该项目 skill 内 agents/ 目录

#### Scenario: codex 全局探测

- **WHEN** 仅存在 `~/.codex/skills/budget-workflow/SKILL.md`
- **THEN** 探测为 codex:global

#### Scenario: 探测失败显式报错

- **WHEN** 全部探测均未命中本套件安装形态
- **THEN** 报错并列出已检测路径（含 .codex 两级），不以默认值静默继续

### Requirement: setup.sh 子命令体系（preset codex 降级语义）

`core/setup.sh` 子命令全集不变；codex 探测形态下 `agent preset|custom|inherit` 降级为提示语（「codex 平台模型档位由 Leader 在 spawn 派工时按 budget-models.json 查询，无 agent frontmatter 可切换；档位查看 `budget setup show`/`budget setup models`」，exit 0 不报错）；`show` 在 codex 形态输出三档映射表（economic/balanced/quality → gpt-5.6-luna/terra/sol）。其余子命令（models/persona/guard/notify/validate/uninstall）codex 形态正常工作。【MUST】

#### Scenario: codex preset 降级提示

- **WHEN** codex 形态执行 `budget setup agent preset balanced`
- **THEN** 输出降级提示并 exit 0（无文件被修改）

#### Scenario: codex show 三档表

- **WHEN** codex 形态执行 `budget setup show`
- **THEN** 输出 codex 三档模型映射与查表说明
