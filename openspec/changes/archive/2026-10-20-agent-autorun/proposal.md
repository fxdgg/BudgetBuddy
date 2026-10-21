# 提案：子代理 AutoRun 免审批（agent-autorun）

## Why

用户在 CodeBuddy IDE 中通过 Task 工具调度子 agent（coder-lite/coder-senior/coder-standard/tester 等）时，子 agent 的每个工具调用（尤其是 Execute Shell Command）都会弹出 "Are you sure you want to execute..." 审批框，且只有「允许一次 / 拒绝」两选项，没有「始终允许」——高频调度的执行类 agent 被逐条人工确认严重拖慢工作流。官方文档确认 CodeBuddy IDE 的 Subagent 支持 frontmatter 字段 `enabledAutoRun: true`（设置页 Agent Tab 中对应 "Auto Run — Subagents 调用工具时是否需要用户的同意"），开启后该 subagent 调用工具不再逐条弹审批。

## What Changes

- **中立源新增可选字段 `auto_run`**（布尔，缺省不输出）：`core/agents/{coder-lite,coder-senior,coder-standard,tester}.md` 四个执行类 agent 标注 `auto_run: true`，其余 6 个 agent（architect/director/goal-evaluator/recorder/reviewer/reviewer-b）不标注，维持逐条人工确认
- **CodeBuddy 平台映射**：`core/platform/codebuddy.yaml` 的 `agent_frontmatter.emit` 新增 `enabledAutoRun: "{auto_run}"`（与 `permissionMode` camelCase 键先例一致，emit 输出键名任意、零 schema 扩展）；产物中仅源存在该字段的 agent 输出 `enabledAutoRun: true`（与 `max_turns` 的「仅源存在时输出」同构）
- **build.py emit 白名单扩展**：`EMIT_EXPRESSIONS` 由七表达式扩为八表达式（新增 `auto_run`），`rewrite_agent` 新增对应分支，`validate_agent` 新增布尔类型校验（拒绝字符串 `"true"` 等非法形态）；YAML 序列化层零改动（`parse_yaml` 已支持 `true`→bool、`_dump_scalar` 已支持 bool→`true`，双向 round-trip 既有能力）；**另新增 `_build_agent_bash_patterns`（A1 修订）**：build 期从 `core/agents/*.md` 的 `permissions.bash_allow` 生成轻量数据文件 `dist/codebuddy/agents/.bash-patterns.json` 随 dist 分发，为 `autorun on` 的安全知情提示提供 bash 模式数据（仅映射 `{auto_run}` 的平台生成，opencode/claudecode 零变化；autorun.py 零硬编码权限表，design D7）
- **OpenCode / Claude Code 不映射（明确降级策略）**：OpenCode 的审批机制即 permission map（`ask`/`allow`/`deny`），4 个目标 agent 的既有权限映射（coder 三者 edit/bash 全 allow、tester bash allow）已等价免逐条确认，无需新字段；Claude Code 子代理 frontmatter 无 per-subagent auto-run 开关（审批由会话权限模式 / settings.json permissions 承担），无等效机制——两平台均在文档中明确降级路径
- **「允许全部」用户选择机制 `budget setup autorun`**：新模块 `core/lib/autorun.py`（先例：model_resolver.py 行级补丁），维护全局状态文件 `~/.budgetbuddy/auto-run.json`（agent 清单），子命令 `list`（双栏查看：全局状态清单 + 当前安装态实况）/ `on <agent>...`（开启，等效「允许全部」）/ `off <agent>...`（关闭）；on/off 作用域为**当前探测到的安装态**（多项目级安装需逐项目执行）；未检测到安装形态（kind=unknown）时 on/off/apply 非零退出并提示先安装；对已安装 agent 文件做 frontmatter 行级补丁（仅触碰 `enabledAutoRun` 一行，锚点与原子写策略同 `rewrite_agent_file`）；「允许一次」为 IDE 弹窗既有能力（✓），无需改动
- **安全语义显式声明**：AutoRun（`enabledAutoRun: true`）使该 agent **权限范围内所有工具调用免人工审批**——审批是最后一道人工闸门。4 个执行类 agent（`bash_allow: ["*"]`）默认开启意味着其子代理可无审批执行任意 shell 命令（`rm -rf` / `git push -f` 均命中 `*`）；`autorun on architect`/`on recorder`（reviewer/reviewer-b 同为 git 类）可对 `bash_allow` 含 `git *` 的 agent 开启，可无审批执行 `git push --force` / `git clean -fd` / `git checkout -- .` 等高危 git 命令。README 与 `autorun on` 输出将列出该 agent 免审批的 bash 模式（`*` / git 类醒目提示），用户知情后自主选择。**数据来源（A1 修订）**：bash 模式由 build 期从 `core/agents/*.md` 的 `permissions.bash_allow` 生成轻量数据文件 `dist/codebuddy/agents/.bash-patterns.json` 随 dist 分发（安装态 `<install_root>/agents/.bash-patterns.json`），仅映射 auto_run 的平台生成，`autorun.py` 零硬编码权限表、单一中立源不漂移；文件缺失（旧安装）时 `on` 输出降级为通用知情提示，不列具体模式但不阻断开启（design D7）
- **安装后状态重放**：`install.sh` CodeBuddy 分支在 manifest 增量同步后，若状态文件存在则重放（`autorun.py apply`），保证用户选择跨升级/重装不丢失；`budget setup update` 不触碰 agent 文件（现状核实：update.sh 仅同步 lib 与管理面数据），用户切换天然存活
- **存量兼容**：首次运行新版本 install.sh 时 4 个 agent 经 dist 获得 `enabledAutoRun: true`；状态文件缺失时 `autorun on/off` 从已安装文件扫描种子化——**仅「`enabledAutoRun` 行存在且值解析为 `true`」进基线**（若 IDE 关闭态写入 `enabledAutoRun: false`，按行判定会把用户手动关闭翻转为开启；写入形态经端到端验证确认前，按值判定是唯一安全口径），用户此前的 IDE 设置页手动开启被保留为基线、手动关闭不被翻转

### 非目标（本期不做）

- 不为 OpenCode / Claude Code 新增任何 AutoRun 字段或权限映射改动（既有 permission map / settings 机制已覆盖，仅文档化降级路径）
- 不改 IDE 弹窗本身（「允许一次」为 CodeBuddy IDE 既有能力）
- 不做 per-task 粒度的临时授权（如「本次会话允许」），仅持久化开关
- 不改动 6 个保留逐条确认的 agent 的默认值（architect/director/goal-evaluator/recorder/reviewer/reviewer-b 仍无 `auto_run`）

## Capabilities

### New Capabilities

- `agent-autorun`: 子代理免审批能力——中立源 `auto_run` 字段语义、CodeBuddy `enabledAutoRun` 平台映射、`budget setup autorun` 用户选择机制（状态文件 + 行级补丁 + 种子化 + 平台降级）、安装后状态重放

### Modified Capabilities

- `neutral-source-format`: agent 中立 frontmatter schema 新增可选 `auto_run`（布尔）字段及构建期校验
- `build-pipeline`: agent frontmatter emit 合法表达式集合七→八（新增 `{auto_run}`），「仅源存在时输出」语义
- `agent-roster`: 4 个执行类 agent（coder-lite/coder-senior/coder-standard/tester）默认 `auto_run: true`，角色清单仍为 10 个不变
- `setup-cli`: 新增 `budget setup autorun list|on|off` 子命令（含 list 双栏、unknown 形态非零退出、损坏状态文件不覆盖写、非 codebuddy 平台降级指引）
- `installer`: CodeBuddy 安装同步后重放 `~/.budgetbuddy/auto-run.json` 状态

## Impact

- **代码**：`core/agents/{coder-lite,coder-senior,coder-standard,tester}.md`（各加一行 frontmatter）、`core/platform/codebuddy.yaml`（emit 加一项）、`scripts/build.py`（`EMIT_EXPRESSIONS` L88-91、`rewrite_agent` L871-901 新分支、`validate_agent` L765-803 新校验、新增 `_build_agent_bash_patterns` 与 `_build_all` 一行调用生成 bash 模式数据文件——D3 由三处锚点扩为四处，均在本文件内）、`core/lib/autorun.py`（新增，stdlib only）、`core/setup.sh`（分发 case + help 文案）、`install.sh`（`install_codebuddy` 同步后重放钩子；数据文件随 manifest 同步自动落位，无需额外安装逻辑）、`README.md` / `README_CN.md` / `CHANGELOG.md`（文档，品牌门禁扫描范围内）
- **产物**：`dist/codebuddy/agents/{coder-lite,coder-senior,coder-standard,tester}.md` 获得 `enabledAutoRun: true`，并新增 `dist/codebuddy/agents/.bash-patterns.json`（10 agent 免审批 bash 模式数据，仅 codebuddy 生成）；`dist/opencode/`、`dist/claudecode/` 产物逐字节不变（不映射 auto_run，按 D7 门控不生成数据文件）
- **测试**：`tests/test_build.py`（emit 白名单 / rewrite 分支 / validate 校验 / 真实 yaml 断言 / 数据文件生成与门控用例）；新增 `tests/test_autorun.py`（复刻 `tests/test_preset.py` `RewriteUnitTests` 沙盒模式，补丁锚点 / CRLF 保留 / 幂等 / 种子化按值判定 / 损坏 JSON 降级 / unknown 与降级形态 / list 双栏与损坏态 / 数据文件读取与缺失降级，全部转自动化用例）；`tests/test_installer.py` 增补 install.sh 重放集成用例（钩子落点、无状态不重放、损坏告警不阻断、二次安装 apply 幂等——该文件已有 41 例 subprocess 驱动 install.sh 端到端先例，mini 仓库 + HOME 隔离沙盒与 test_autorun 同构，installer spec 的 4 个 MUST 场景自动化完全可行；「tests 不分发内嵌测试的纪律」管 dist 分发面，不构成仓库内 installer 测试留手动的理由）
- **风险**：① 用户手动编辑安装态 agent 与状态文件的双写一致性 → 种子化按值判定扫描 + 单一重放入口（install.sh）消解；② 非 codebuddy 平台用户误期待 AutoRun → 子命令降级指引 + 文档明示；③ emit 白名单扩充的拼写漂移 → 复用既有 `_EMIT_PATTERN` 校验与白名单测试先例；④ **AutoRun = 权限范围内免审批（审批是最后一道人工闸门）**——coder 三类与 tester `bash_allow: ["*"]` 可无审批执行任意 shell 命令，architect/recorder 等 git 类可无审批执行高危 git 命令 → README 与 `autorun on` 输出知情提示（列 bash 模式，`*`/git 类醒目）；⑤ 多项目级安装 × 全局状态文件语义差 → on/off 作用域明示当前探测安装态 + list 双栏 + 文档明示逐项目执行
