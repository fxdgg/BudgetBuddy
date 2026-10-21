# agent-autorun Specification

## Purpose
TBD - created by archiving change agent-autorun. Update Purpose after archive.
## Requirements
### Requirement: 中立源 auto_run 字段与 CodeBuddy enabledAutoRun 映射

`core/agents/*.md` frontmatter 支持可选布尔字段 `auto_run`（缺省 = 不声明免审批）；该字段语义为「subagent 调用工具时是否需逐条人工确认」的交互策略声明，与 `permissions`（允许什么操作）正交。构建期仅 CodeBuddy 平台经 emit 表达式 `{auto_run}` 将其映射为产物 frontmatter 的 `enabledAutoRun: true`，且仅源存在该字段时输出（与 `max_turns` 同构）；OpenCode 与 Claude Code 平台不映射该字段（OpenCode 的 permission map `allow` 值即其免审批机制，4 个执行类 agent 的既有权限映射已等价；Claude Code 子代理无 per-subagent auto-run 开关，无等效机制，走文档降级指引）。【MUST】

#### Scenario: 执行类 agent 产物含 enabledAutoRun

- **WHEN** 构建 CodeBuddy 平台且 `core/agents/{coder-lite,coder-senior,coder-standard,tester}.md` 声明 `auto_run: true`
- **THEN** `dist/codebuddy/agents/` 对应四个产物文件 frontmatter 含 `enabledAutoRun: true`，IDE 调度这些 subagent 时不再逐条弹审批

#### Scenario: 保留确认的 agent 产物不含该字段

- **WHEN** 构建 CodeBuddy 平台且 architect/director/goal-evaluator/recorder/reviewer/reviewer-b 六个 agent 未声明 `auto_run`
- **THEN** 对应产物 frontmatter 不含 `enabledAutoRun` 键，维持逐条人工确认（「允许一次」为 IDE 弹窗既有能力）

#### Scenario: OpenCode 与 Claude Code 产物零变化

- **WHEN** 构建 opencode/claudecode 平台
- **THEN** 两平台 agent 产物不含任何 auto-run 相关字段，与本次变更前逐字节一致（既有 permission map / permissionMode 映射不变）

#### Scenario: auto_run 非布尔值构建失败

- **WHEN** 某 agent 源文件 `auto_run` 值为字符串 `"true"`、整数 `1` 等非布尔形态
- **THEN** build.py 校验失败并指出该文件与合法形态（布尔）

### Requirement: budget setup autorun 用户选择机制

提供 `budget setup autorun list|on <agent>...|off <agent>...` 子命令（实现 `core/lib/autorun.py`，stdlib only），作为 6 个保留逐条确认的 agent 的「允许全部」持久化选择机制（与开启 AutoRun 等效）：「允许一次」仍由 IDE 弹窗 ✓ 承担，不在此机制内。子命令分两层：**用户可见层**为 `list|on|off`（进 setup.sh help 与用户文档）；`apply` 为**内部/修复命令**（供 install.sh 安装重放与状态修复调用，不面向用户日常使用，不进 help 与用户文档）。用户选择持久化于全局状态文件 `~/.budgetbuddy/auto-run.json`（`{"agents": [...]}` agent 名清单，全局单点，全局固定路径先例 `~/.budgetbuddy/notify.json`）；`on`/`off` 对已安装 CodeBuddy agent 文件做 frontmatter 行级补丁——仅触碰 `enabledAutoRun` 一行（新增/删除/改值），锚点、行尾保留与原子写策略同 `model_resolver.py` 的 `rewrite_agent_file`，frontmatter 其余字段与正文逐字节保留。【MUST】

**安全边界**：本机制使目标 agent 权限范围内所有工具调用免人工审批——审批是最后一道人工闸门。`on` 执行时的输出必须列出该 agent 将免审批的 bash 模式（`bash_allow: ["*"]` 或含 `git *` 等模式的给醒目提示），确保用户知情后自主选择。**bash 模式数据来源**：build 期从 `core/agents/*.md` frontmatter `permissions.bash_allow` 生成数据文件 `agents/.bash-patterns.json`（`{"agents": {"<name>": {"bash_allow": [...]}}}`）随 CodeBuddy dist 分发（安装态落 `<install_root>/agents/.bash-patterns.json`，随 manifest 同步自动落位），仅映射 `{auto_run}` 的平台生成（opencode/claudecode 不生成、产物零变化）；`on` 从该文件读取目标 agent 模式，文件缺失（旧安装未重建 dist）时降级为通用知情提示（明示免审批语义、不列具体模式），不得因此阻断开启。

**作用域（多安装形态）**：`on`/`off` 的补丁作用域为当前探测到的安装态（`detect_platform` 注入的 kind/agents 目录，setup.sh 分发前 export 传入子进程；探测优先级项目级 codebuddy > 全局 codebuddy > claudecode > opencode）。同一机器多个项目级安装时，全局状态文件记录选择、补丁只落当前项目——**多项目需逐项目各执行一次** `on`/`off`；`list` 双栏输出（全局状态清单 + 当前安装态实况）暴露两者差异。`detect_platform` 五级均未命中（kind=unknown，不阻断、unknown 流入子进程）时：`on`/`off`/`apply` 非零退出并提示先安装或 `BUDGET_PLATFORM=codebuddy|claudecode|opencode` 显式指定；`list` 仍以退出码 0 输出全局清单并提示未检测到安装形态。

**种子化与真源**：状态文件缺失时 `on`/`off` 先从已安装 agent 文件扫描种子化——**仅「`enabledAutoRun` 行存在且值解析为 `true`」的 agent 进基线**（`false` 行视为用户显式关闭，不进基线，防止 install 重放把手动关闭翻转为开启；IDE 关闭态写入形态经端到端验证确认前，按值判定为唯一安全口径）。状态文件存在后为唯一真源：此后经 IDE 设置页的手动变更不再被种子化吸收，且可能被下次 install 重放覆盖（差异经 `list` 双栏暴露）。

**损坏状态文件**：`on`/`off`/`apply` 遇状态文件 JSON 解析失败时非零退出并提示修复（编辑或删除 `~/.budgetbuddy/auto-run.json`），**绝不覆盖写**（否则用户基线永久丢失）；install 路径上该非零退出仅触发告警、不阻断安装。`list` 只读不受此限：遇损坏状态栏明示损坏并提示修复路径、退出码 0、不改写文件（install 告警引导用户运行 `autorun list` 检查即依赖此只读行为）。

非 codebuddy 平台（opencode/claudecode）执行 `on`/`off`/`apply` 时输出平台替代指引（opencode：permission map / 会话级 always / `--auto`；claudecode：settings.json permissions 规则 / 权限模式）并以退出码 0 结束，不修改任何文件。

#### Scenario: on 开启指定 agent

- **WHEN** 在已安装 CodeBuddy 形态执行 `budget setup autorun on reviewer`
- **THEN** `~/.budgetbuddy/auto-run.json` 的 agents 清单含 reviewer（种子化基线 + reviewer），已安装 `agents/reviewer.md` frontmatter 含 `enabledAutoRun: true`

#### Scenario: off 关闭指定 agent

- **WHEN** 执行 `budget setup autorun off coder-lite`
- **THEN** 状态清单移除 coder-lite，已安装 `agents/coder-lite.md` 的 `enabledAutoRun` 行被删除，该 agent 恢复逐条确认

#### Scenario: list 双栏查看状态与实况

- **WHEN** 执行 `budget setup autorun list`
- **THEN** 双栏输出：全局状态清单（`~/.budgetbuddy/auto-run.json` 的 agents，缺失时提示未初始化）+ 当前安装态实况（逐 agent 的 `enabledAutoRun` 实际值）；两栏差异（如状态文件存在后的 IDE 手动变更）如实展示，退出码 0

#### Scenario: list 遇损坏状态文件只读展示

- **WHEN** 执行 `budget setup autorun list` 且 `~/.budgetbuddy/auto-run.json` 内容损坏（JSON 解析失败）
- **THEN** 状态栏明示状态文件损坏并提示修复路径（运行 `autorun on/off` 修复，或编辑/删除该文件），实况栏照常展示当前安装态，退出码 0，状态文件字节不被改写（list 只读，不承担修复职责——install 重放告警即引导用户运行 list 检查）

#### Scenario: 种子化保留手动开启

- **WHEN** 用户此前在 IDE 设置页手动为 reviewer 开启 Auto Run（安装态文件含 `enabledAutoRun: true`）且状态文件不存在，随后执行 `budget setup autorun on tester`
- **THEN** 种子化基线含 reviewer（不丢失），最终清单为默认 4 个 + reviewer + tester

#### Scenario: 种子化不翻转手动关闭

- **WHEN** 用户此前在 IDE 设置页手动关闭 coder-lite 的 Auto Run（安装态文件为 `enabledAutoRun: false`）且状态文件不存在，随后执行 `budget setup autorun on reviewer`
- **THEN** coder-lite 不进基线（仅值 `true` 进基线，`false` 行视为显式关闭），最终清单不含 coder-lite；后续 install 重放亦不会将 coder-lite 重新开启

#### Scenario: on 输出安全知情提示

- **WHEN** 执行 `budget setup autorun on architect`
- **THEN** 输出明示 AutoRun 使 architect 权限范围内所有工具调用免人工审批（审批是最后一道人工闸门），并列出其 bash 模式（`git *`、`openspec *`，醒目提示可无审批执行 git 等高危命令；模式取自 `agents/.bash-patterns.json`，该文件缺失时降级为通用知情提示且不阻断开启），随后正常完成开启

#### Scenario: unknown 形态非零退出

- **WHEN** 未检测到任何安装形态（`detect_platform` kind=unknown）时执行 `budget setup autorun on reviewer`（或 off/apply）
- **THEN** 非零退出并提示先安装 BudgetBuddy 或以 `BUDGET_PLATFORM=codebuddy|claudecode|opencode` 显式指定，不写状态文件、不补丁任何文件；同形态下 `list` 仍退出码 0 输出全局清单并提示未检测到安装形态

#### Scenario: 损坏状态文件拒绝执行且不覆盖写

- **WHEN** `~/.budgetbuddy/auto-run.json` 内容损坏（JSON 解析失败）时执行 `budget setup autorun on tester`（或 off/apply）
- **THEN** 非零退出并提示修复路径（编辑或删除该文件），状态文件字节不被改写、agent 文件不被补丁

#### Scenario: 未知 agent 名报错

- **WHEN** `budget setup autorun on not-exist`
- **THEN** 以非零退出并列出可用 agent 名（已安装 agents 目录中的 .md 主名），不写状态文件、不补丁任何文件

#### Scenario: 补丁幂等

- **WHEN** 对已开启 agent 重复执行 `budget setup autorun on <agent>`（或对未开启 agent 重复 off）
- **THEN** 文件不累积重复行、内容与首次执行后一致（字节级稳定），退出码 0

#### Scenario: 非 codebuddy 平台降级

- **WHEN** 在 opencode 或 claudecode 安装形态执行 `budget setup autorun on reviewer`
- **THEN** 输出该平台的替代审批机制指引，退出码 0，不创建/修改状态文件与任何 agent 文件

### Requirement: 安装后 AutoRun 状态重放

`install.sh` 的 CodeBuddy 安装分支在 manifest 增量同步（含升级差集清理）完成后、写入本地清单前（钩子落点：`upgrade_diff_cleanup` 之后、`write_local_manifest` 之前），若 `~/.budgetbuddy/auto-run.json` 存在则调用 `autorun.py apply` 将状态重放到已安装 agent 文件（先全量对齐：清单内 on、清单外 off），保证用户选择跨升级安装不丢失；apply 非零退出（含状态文件损坏）时仅告警并提示修复、不阻断安装主流程、不覆盖写状态文件。`budget setup update` 不刷新 agent 文件（现状：仅同步 lib 与管理面数据），用户切换在 update 路径天然存活。【MUST】

#### Scenario: 状态存在时升级安装后选择保持

- **WHEN** 用户状态文件含「默认 4 个 + reviewer」，重新运行新版本 install.sh（同步以新 dist 覆盖 agent 文件）
- **THEN** 同步后 reviewer 的 `enabledAutoRun` 被重放恢复，默认 4 个仍在位，用户选择不丢失

#### Scenario: 无状态文件时 dist 默认值成立

- **WHEN** 首次安装且 `~/.budgetbuddy/auto-run.json` 不存在
- **THEN** 不执行重放，4 个执行类 agent 的 `enabledAutoRun: true` 直接来自 dist 产物

#### Scenario: 重放失败不阻断安装

- **WHEN** 同步成功但 apply 执行失败（如状态文件损坏）
- **THEN** 安装主流程继续完成并输出告警，提示用户运行 `budget setup autorun` 修复

