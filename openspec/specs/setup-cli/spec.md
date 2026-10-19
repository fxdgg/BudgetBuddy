# setup-cli Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
### Requirement: setup.sh 子命令体系

`core/setup.sh`（产物平移至 dist 双平台）提供子命令全集（design.md §8.1/A11）：`init`（初始化安装/注入；`init shell` 注入 shell 别名）、`show`（展示当前 agent 模型配置）、`agent preset|inherit|custom`（模型预设切换/覆写）、`persona list|set|expand|show`（主题管理）、`validate`（完整性校验）、`diff [preset]`（当前 vs 预设对比）、`stats`（工作流统计）、`update`（增量更新）、`reinstall`（uninstall+init 组合重装）、`uninstall`（卸载）、`guard`（Coder Guard 查询/重置）、`quickstart`（别名 tour/wizard，快速上手引导）、`models`（模型目录查看）、`help`；独立入口 `budget notify` 与 `budget status`；`budget update` 为 `budget setup update` 的顶层快捷别名。环境变量前缀统一 `BUDGET_*`（BUDGET_GLOBAL/BUDGET_DIR/BUDGET_PLATFORM）。【MUST】

#### Scenario: show 输出
- **WHEN** 在已安装项目执行 `budget setup show`
- **THEN** 列出每个 agent 的当前 model 与对应 model_role，格式人类可读

#### Scenario: 环境变量前缀
- **WHEN** 审计 setup.sh 与 lib 全部脚本
- **THEN** 无参照项目前缀的环境变量残留，统一使用 BUDGET_*

#### Scenario: quickstart 入口可用
- **WHEN** 执行 `budget setup quickstart`（或别名 tour/wizard）
- **THEN** 启动 lib/quickstart.py 快速上手引导（lib 模块有对应入口，无死代码）

### Requirement: budget CLI 包装器

安装器/setup init 写入 `~/.local/bin/budget` 包装脚本，转发 `setup`/`notify`/`status`/`update` 子命令到实际脚本；幂等重装不产生坏符号链接（design.md §8.1）。【MUST】

#### Scenario: 包装器可用
- **WHEN** 安装完成后执行 `budget setup show` 与 `budget status`
- **THEN** 两个子命令均正常执行并输出

### Requirement: platform.sh 运行时平台探测

`core/lib/platform.sh` 按序探测：① 向上查找 `.codebuddy/setup.sh` → codebuddy 项目级；② `~/.codebuddy/setup.sh` → codebuddy 全局；③ `.opencode/agent/`（项目级，优先）或 `~/.config/opencode/agent/`（全局）存在本套件 agent → opencode；三级均未命中 → 显式报错并列出已检测位置（不静默猜默认）。探测结果驱动 `agent preset/custom` 与 hooks 注入的落点（design.md §8.3）。【MUST】

#### Scenario: codebuddy 项目级探测
- **WHEN** 在含 `.codebuddy/setup.sh` 的项目子目录执行 setup
- **THEN** 探测结果为该项目根，agent 重写落在该 .codebuddy/agents/

#### Scenario: opencode 探测
- **WHEN** 仅存在 `~/.config/opencode/agent/` 本套件 agent 文件
- **THEN** 探测为 opencode 全局，agent 重写落在该目录且 hooks 注入被跳过

#### Scenario: 探测失败显式报错
- **WHEN** 三级探测均未命中本套件安装形态
- **THEN** 报错并列出已检测路径，不以默认值静默继续

### Requirement: lib 24 文件模块化

`core/lib/` 全量 24 文件按六组组织（design.md §8.2）：基础层（colors/utils/platform/shell）、生命周期（init/update/uninstall）、模型与护栏（models/preset/model_resolver/guard/rtk）、persona 与校验（persona/persona_expand/validate/budget-state/display）、交互与汇总（interactive/quickstart/run_summary/banner）、通知与 hooks（notify/hooks/hooks_inject）。状态机 `budget-state.py` 全仓单份（A4），skill 文档经 `$HOME/.budgetbuddy/lib/budget-state.py` 引用。lib 不随产物分发内嵌测试，测试统一在仓库根 `tests/`。【MUST】

#### Scenario: 状态机单份
- **WHEN** 审计 core/ 与 dist/ 产物
- **THEN** budget-state.py 仅存在于 lib 路径一处，skill 目录无副本

#### Scenario: 禁 pyc 分发
- **WHEN** 检查 dist/ 产物
- **THEN** 无 __pycache__、*.pyc 文件

### Requirement: 数据目录与优先级

项目级 `.budget/`（persona-active.json、notify.json、memory/ 项目态运行数据，gitignore）与全局 `~/.budgetbuddy/`（同名文件 + `projects/<project-name>/memory/coder-guard.json` + `bin/` + `lib/` + `docs/` + 模型/persona 数据）；读取优先级项目级 > 全局级；皆无时 persona 用 default、通知跳过。Coder Guard 固定读写全局路径（跨会话汇总降级判定，design.md §8.4）。项目 `.gitignore` 的 `.budget/` 忽略项由 install.sh（项目级安装）与 `setup init` 以 `# BudgetBuddy:begin/end` 标记区块幂等追加（区块外内容不触碰）（design.md §8.4）。【MUST】

#### Scenario: persona 优先级
- **WHEN** 项目 `.budget/persona-active.json` 存在且与全局不同
- **THEN** agent 启动读取项目级主题

#### Scenario: gitignore 幂等追加
- **WHEN** 在无标记区块的项目执行项目级安装/setup init 后重跑
- **THEN** .gitignore 含且仅含一个 BudgetBuddy 标记区块，区块外用户内容不变

### Requirement: personas 五主题

`core/personas/personas.json` 含 default、tech-legends、sanguo、shuihu、genshin 五主题（剔除参照项目品牌主题），结构沿用 `_meta` + `themes.<name>.{name,greeting,roles.*,report_templates}`；**roles 键集 = leader + agent 清单十角色（共 11 键）**——保留 leader 键（主会话称呼与角色化调度依赖 roles.leader + greeting，design.md §8.5）；reviewer-a 键改名 reviewer、新增 goal-evaluator 键（各主题新造角色名）；`persona set` 切换写 persona-active.json（design.md §8.5）。【MUST】

#### Scenario: 主题切换
- **WHEN** `budget setup persona sanguo` 后读取 persona-active.json
- **THEN** theme 为 sanguo 且 roles 映射完整覆盖 11 键（leader + 十角色）

#### Scenario: 无品牌主题
- **WHEN** 审计 personas.json 主题键
- **THEN** 不存在参照项目品牌主题及其角色变体

#### Scenario: persona 引用一致
- **WHEN** 审计 agent 正文的 `roles.<name>` 引用与 personas.json 键集
- **THEN** 全部可解析：无 reviewer-a 残留、无缺失键（含 goal-evaluator）

### Requirement: Coder Guard 护栏

`core/lib/guard.sh` 提供 coder-guard.json 的查询/追加/汇总更新（固定路径 `$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json`），记录结构与降级阈值语义对齐工作流文档 router 的定义（最近 5 次窗口、失败 ≥2 触发降级）（design.md §8.2/§8.4）。【MUST】

#### Scenario: 失败记录
- **WHEN** 某次 coder 任务被 review 驳回后触发记录
- **THEN** guard.json 的 history 追加条目且 summary 计数同步更新

### Requirement: superpowers 插件启用

`core/lib/hooks.sh` 在 hooks 注入同时检测并启用 CodeBuddy superpowers 插件：检查 settings.json 的 `enabledPlugins`，未启用则注入 `"superpowers@codebuddy-plugins-official": true` 并提示重启或手动执行 `/plugin superpowers`；`setup init` 与安装器 codebuddy 路径均调用该启用流程；`SKILL_NS="superpowers:"` 前缀的 skill 引用依赖该插件（design.md §9/§12-A11）。【MUST】

#### Scenario: 安装后插件启用
- **WHEN** codebuddy 平台完成安装/init 且 settings.json 未启用 superpowers
- **THEN** enabledPlugins 含 superpowers 条目，用户收到重启或手动启用提示

#### Scenario: 已启用幂等跳过
- **WHEN** settings.json 已启用 superpowers 时重跑注入
- **THEN** 该条目不重复注入（幂等），settings.json 其余内容不变

