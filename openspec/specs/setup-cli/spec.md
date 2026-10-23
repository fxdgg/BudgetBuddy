# setup-cli Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
### Requirement: setup.sh 子命令体系

`core/setup.sh`（产物平移至 dist 四平台）提供子命令全集（design.md §8.1/A11）：`init`（初始化安装/注入；`init shell` 注入 shell 别名）、`show`（展示当前 agent 模型配置）、`agent preset|inherit|custom`（模型预设切换/覆写）、`persona list|set|expand|show`（主题管理）、`validate`（完整性校验）、`diff [preset]`（当前 vs 预设对比）、`stats`（工作流统计）、`update`（增量更新）、`reinstall`（uninstall+init 组合重装）、`uninstall`（卸载）、`guard`（Coder Guard 查询/重置）、`quickstart`（别名 tour/wizard，快速上手引导）、`models`（模型目录查看）、`ocr`（OCR 预审集成安装与状态检测——行为细节见「budget setup ocr 子命令」requirement）、`help`；独立入口 `budget notify` 与 `budget status`；`budget update` 为 `budget setup update` 的顶层快捷别名。环境变量前缀统一 `BUDGET_*`（BUDGET_GLOBAL/BUDGET_DIR/BUDGET_PLATFORM）。codex 探测形态下 `agent preset|custom|inherit` 降级为提示语（「codex 平台模型档位由 Leader 在 spawn 派工时按 budget-models.json 查询，无 agent frontmatter 可切换；档位查看 `budget setup show`/`budget setup models`」，exit 0 不报错）；`show` 在 codex 形态输出三档映射表（economic/balanced/quality → gpt-5.6-luna/terra/sol）；其余子命令（models/persona/guard/notify/validate/uninstall）codex 形态正常工作。【MUST】

#### Scenario: show 输出
- **WHEN** 在已安装项目执行 `budget setup show`
- **THEN** 列出每个 agent 的当前 model 与对应 model_role，格式人类可读

#### Scenario: 环境变量前缀
- **WHEN** 审计 setup.sh 与 lib 全部脚本
- **THEN** 无参照项目前缀的环境变量残留，统一使用 BUDGET_*

#### Scenario: quickstart 入口可用
- **WHEN** 执行 `budget setup quickstart`（或别名 tour/wizard）
- **THEN** 启动 lib/quickstart.py 快速上手引导（lib 模块有对应入口，无死代码）

#### Scenario: ocr 入口可用
- **WHEN** 执行 `budget setup ocr`
- **THEN** 启动 lib/ocr-setup.py 安装与检测流程（lib 模块有对应入口，无死代码；help 文案含 `ocr` 子命令说明）

#### Scenario: help 文案覆盖 ocr 子命令
- **WHEN** 执行 `budget setup help`
- **THEN** 用法行与子命令说明含 `ocr`（安装与检测语义一句话，形态先例同 autorun 的 help 覆盖）

#### Scenario: codex preset 降级提示
- **WHEN** codex 形态执行 `budget setup agent preset balanced`
- **THEN** 输出降级提示并 exit 0（无文件被修改）

#### Scenario: codex show 三档表
- **WHEN** codex 形态执行 `budget setup show`
- **THEN** 输出 codex 三档模型映射与查表说明

### Requirement: budget CLI 包装器

安装器/setup init 写入 `~/.local/bin/budget` 包装脚本，转发 `setup`/`notify`/`status`/`update` 子命令到实际脚本；幂等重装不产生坏符号链接（design.md §8.1）。【MUST】

#### Scenario: 包装器可用
- **WHEN** 安装完成后执行 `budget setup show` 与 `budget status`
- **THEN** 两个子命令均正常执行并输出

### Requirement: platform.sh 运行时平台探测

`core/lib/platform.sh` 按序探测：① 向上查找 `.codebuddy/setup.sh` → codebuddy 项目级；② `~/.codebuddy/setup.sh` → codebuddy 全局；③ 向上查找 `.claude/agents/` 含本套件 agent → claudecode 项目级；④ `~/.claude/agents/` → claudecode 全局；⑤ 向上查找 `.codex/skills/budget-workflow/`（**SKILL.md 套件签名校验**）→ codex:project；⑥ `~/.codex/skills/budget-workflow/`（同签名校验）→ codex:global；⑦ `.opencode/agent/`（项目级，优先）或 `~/.config/opencode/agent/`（全局）存在本套件 agent → opencode；全部未命中 → 显式报错并列出已检测位置（不静默猜默认）。同时命中多个形态时按探测序取先（codebuddy > claudecode > codex > opencode）。探测结果驱动管理面落点（codex 形态 agent 目录语义 = skill 内 agents/ 素材目录；claudecode 形态下 hooks 注入跳过）；`BUDGET_PLATFORM=codex` 显式覆盖分支同现有模式。【MUST】

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

#### Scenario: codex 项目级探测

- **WHEN** 在含 `.codex/skills/budget-workflow/SKILL.md` 的项目子目录执行 setup
- **THEN** 探测为 codex:project，BUDGET_AGENTS_DIR 指向该项目 skill 内 agents/ 目录

#### Scenario: codex 全局探测

- **WHEN** 仅存在 `~/.codex/skills/budget-workflow/SKILL.md`
- **THEN** 探测为 codex:global

#### Scenario: 探测失败显式报错

- **WHEN** 全部探测均未命中本套件安装形态
- **THEN** 报错并列出已检测路径（含 .claude 与 .codex 各两级），不以默认值静默继续

### Requirement: lib 24 文件模块化

`core/lib/` 代码模块按六组组织（design.md §8.2）：基础层（colors/utils/platform/shell，4）、生命周期（init/update/uninstall，3）、模型与护栏（models/preset/model_resolver/guard/guard_metrics/rtk/ocr-setup，7）、persona 与校验（persona/persona_expand/validate/budget-state/display，5）、交互与汇总（interactive/quickstart/run_summary/banner/autorun，5）、通知与 hooks（notify/hooks/hooks_inject，3）——共 **27 个代码模块**（16 .sh + 11 .py）另含 1 个数据模板（ocr-rule.json，非模块，经 `_build_lib` 分发的规则模板；标题「24」为归档合并锚点保留的历史计数，正文计数已修正）。状态机 `budget-state.py` 全仓单份（A4），skill 文档经 `$HOME/.budgetbuddy/lib/budget-state.py` 引用。lib 不随产物分发内嵌测试，测试统一在仓库根 `tests/`。【MUST】

#### Scenario: guard_metrics 归组

- **WHEN** 检查 core/lib/ 目录
- **THEN** guard_metrics.py 存在且与 guard.sh、ocr-setup.py 同属「模型与护栏」组，autorun.py 归「交互与汇总」组；模块计数为 27（.sh/.py）+ ocr-rule.json 数据模板，六组枚举与目录文件一一对应无缺漏

#### Scenario: dist 同步

- **WHEN** 构建完成后核对四平台 dist 的 lib/
- **THEN** guard_metrics.py 经 `_build_lib` 字节平移分发，display.py/run_summary.py 与其同目录（import 路径成立）

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

`core/lib/guard.sh` 提供 coder-guard.json 的查询/追加/汇总/重置（固定路径 `$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json`），记录结构与降级阈值语义对齐工作流文档 router 的定义（最近 5 次窗口、失败 ≥2 触发降级）（design.md §8.2/§8.4）。`guard query`（概览模式与判定模式）与 `guard summary`（含顶层 `budget status` 经 notify.sh `do_status` 复用的链路，notify.sh 零改动）SHALL 在既有输出之上展示「保鲜与置信」参考信息：经 `core/lib/guard_metrics.py`（新增，Python stdlib only，import + CLI 双形态，单一实现源）计算时间加权统计——指数半衰期权重 `0.5^(age_days/half_life)`（默认 30 天，`BUDGET_GUARD_HALF_LIFE_DAYS` 覆盖）、`n_eff` 有效样本数、加权失败数、加权成功率、置信档（`n_eff` < 2 低 / < 4 中 / ≥ 4 高）、陈旧标注（最新记录年龄 > 90 天，`BUDGET_GUARD_STALE_DAYS` 覆盖）；当 `n_eff` < 2 或陈旧标注命中时，guard query 判定输出 MUST 附加「记录陈旧/样本不足，降级建议仅供参考」标注（标注不改变硬规则结论的强制性）。降级硬规则（最近 5 次失败 ≥2 降级、连续 3 败建议 Director）语义 MUST NOT 改变；写入端（append/reset）与 coder-guard.json 格式 MUST NOT 改变（加权为读取时计算，不落盘）。`budget setup stats`（`core/lib/display.py` 的 Coder Guard 段）与 run summary（`core/lib/run_summary.py` 的 guard 段）SHALL 展示同一实现的置信摘要，且 `import guard_metrics` MUST 延迟导入（函数内 import 或 try/except），import 失败时降级为不展示置信摘要、其余段照常输出退出码 0（与子进程容错两层对称）。timestamp 无法解析的 history 条目 MUST 按权重 0 计（不计入 `n_eff`、不参与陈旧判定）。环境变量非法值时 MUST 回退默认值并 stderr 提示、不阻断查询；guard.sh 调用 guard_metrics.py 子进程失败时 MUST 跳过保鲜段、主查询照常返回。【MUST】

#### Scenario: 失败记录

- **WHEN** 某次 coder 任务被 review 驳回后触发记录
- **THEN** guard.json 的 history 追加条目且 summary 计数同步更新（写入端行为不变）

#### Scenario: 半衰期权重数学

- **WHEN** guard_metrics.py 计算 age 为 0 / 30 / 90 天记录的权重（默认半衰期 30 天）
- **THEN** 权重分别为 1.0 / 0.5 / 0.125，`n_eff` 为匹配条目权重之和

#### Scenario: 置信档分界

- **WHEN** 某 coder×tag 组合的 `n_eff` 分别为 1.9 / 2.0 / 3.9 / 4.0
- **THEN** 置信档分别为 low / medium / medium / high

#### Scenario: 陈旧标注与低置信参考提示

- **WHEN** 某 coder 的记录全部为 120 天前（默认阈值 90 天）
- **THEN** 陈旧标注命中（stale）；guard_query 判定输出附加「记录陈旧/样本不足，降级建议仅供参考」一行，且既有降级判定文案不变

#### Scenario: 样本不足独立触发参考提示

- **WHEN** 某 coder 仅有一条 1 天前的记录（`n_eff` = 1.0 < 2 且 stale = false）
- **THEN** 不触发陈旧标注，但 guard_query 判定输出仍附加「记录陈旧/样本不足，降级建议仅供参考」（n_eff < 2 与 stale 二者之一命中即触发）

#### Scenario: timestamp 异常条目容错

- **WHEN** history 中某条目 timestamp 缺失或格式无法解析
- **THEN** 该条目权重按 0 计（不计入 n_eff），陈旧判定不受其影响（newest_age_days 只取可解析条目）

#### Scenario: 硬规则语义不变

- **WHEN** 最近 5 次窗口内失败 ≥2（无论记录新旧）
- **THEN** 降级判定结论与集成前逐字一致（次数窗口判定不受加权影响）

#### Scenario: 四读取面一致

- **WHEN** 同一 coder-guard.json 分别经 `budget setup guard query <coder>`（不带 tag）、`budget status`（guard_summary 链路）、`budget setup stats`（display.py）、run summary（run_summary.py）查看
- **THEN** 四处展示的 n_eff / 置信档 / 陈旧标注数值一致（无 tag 的 coder 全量口径，同一实现源渲染，与 guard_metrics.py CLI `--json` 基准值相等）；带 tag 的 guard_query 判定模式为 coder×tag 交集口径，属明细查询不参与本断言

#### Scenario: 环境变量容错

- **WHEN** `BUDGET_GUARD_HALF_LIFE_DAYS` 设为非法值（如 `abc` / `0` / `-5`）
- **THEN** 回退默认 30 天，stderr 输出提示，查询正常完成退出码 0

### Requirement: superpowers 插件启用

`core/lib/hooks.sh` 在 hooks 注入同时检测并启用 CodeBuddy superpowers 插件：检查 settings.json 的 `enabledPlugins`，未启用则注入 `"superpowers@codebuddy-plugins-official": true` 并提示重启或手动执行 `/plugin superpowers`；`setup init` 与安装器 codebuddy 路径均调用该启用流程；`SKILL_NS="superpowers:"` 前缀的 skill 引用依赖该插件（design.md §9/§12-A11）。claudecode 形态注入 hooks 但**跳过**插件启用（Claude Code 无插件机制，仅注入 Notification/PermissionRequest/SubagentStop 三事件）；opencode 形态两者均跳过。【MUST】

#### Scenario: 安装后插件启用

- **WHEN** codebuddy 平台完成安装/init 且 settings.json 未启用 superpowers
- **THEN** enabledPlugins 含 superpowers 条目，用户收到重启或手动启用提示

#### Scenario: 已启用幂等跳过

- **WHEN** settings.json 已启用 superpowers 时重跑注入
- **THEN** 该条目不重复注入（幂等），settings.json 其余内容不变

#### Scenario: claudecode 注入不含插件

- **WHEN** claudecode 形态执行 hooks 注入
- **THEN** settings.json 含三事件 hook 条目、无 enabledPlugins 变更

#### Scenario: claudecode 卸载清理注入

- **WHEN** claudecode 形态执行卸载
- **THEN** settings.json 的本套件 hook 条目被精确移除（用户第三方 hooks 保留）、`.claude/hooks/` 文件删除

### Requirement: budget setup autorun 子命令

`budget setup` 子命令全集新增 `autorun list|on <agent>...|off <agent>...`（design.md §8.1 扩充；`apply` 为内部/修复命令，供安装重放与状态修复，不进 help 与用户文档，用户可见层仅 `list|on|off`）：实现为 `core/lib/autorun.py`（Python stdlib only，经 setup.sh 分发层直调 python，形态同 `quickstart`/`stats`；分发前经 `detect_platform` 注入形态变量并 export 传入子进程）。状态文件为全局单点 `~/.budgetbuddy/auto-run.json`（`{"agents": [...]}`，排序确定、JSON indent 2 落盘；全局固定路径先例 `~/.budgetbuddy/notify.json`，不设项目级覆盖）。`on`/`off` 对已安装 CodeBuddy agent 文件做 frontmatter 行级补丁：`on` 在 frontmatter 插入或更新 `enabledAutoRun: true`（锚点：name/description 最后出现行之后，同 `model_resolver.py` `rewrite_agent_file`），`off` 删除该行；均保留原行尾（CRLF/LF）、临时文件原子写、仅触碰该一行；重复执行为幂等 no-op。状态文件缺失时 `on`/`off` 先扫描已安装 agent 种子化基线（**仅 `enabledAutoRun` 行存在且值解析为 `true` 者进基线**；`false` 行视为用户显式关闭不进基线，防 install 重放翻转）。`on`/`off` 作用域为当前探测到的安装态（多项目级安装需逐项目执行）；`list` 双栏输出（全局状态清单 + 当前安装态实况），且 `list` 遇状态文件损坏时只读展示（状态栏明示损坏与修复路径、退出码 0、不改写文件）。`detect_platform` 未命中（kind=unknown）时 `on`/`off`/`apply` 非零退出并提示先安装或 `BUDGET_PLATFORM=` 显式指定，`list` 仍 exit 0。状态文件损坏（JSON 解析失败）时 `on`/`off`/`apply` 非零退出并提示修复、绝不覆盖写。`on` 输出列出目标 agent 将免审批的 bash 模式（`*`/git 类醒目提示），模式数据来自 build 期生成、随 CodeBuddy dist 分发的 `<install_root>/agents/.bash-patterns.json`（源自 `core/agents/*.md` 的 `permissions.bash_allow`；文件缺失时降级为通用知情提示，不列具体模式且不阻断开启）。有效 agent 名 = 已安装 agents 目录中的 .md 主名，未知名非零退出并列出可用名。非 codebuddy 平台（opencode/claudecode）执行 `on`/`off` 时输出平台替代审批机制指引并以退出码 0 结束、零文件修改；`list` 只读，任何平台可用。【MUST】

#### Scenario: on 后 agent 免审批生效

- **WHEN** 在已安装 CodeBuddy 形态执行 `budget setup autorun on reviewer`
- **THEN** 状态文件含 reviewer，安装态 `agents/reviewer.md` frontmatter 含 `enabledAutoRun: true`，其余字段与正文逐字节不变

#### Scenario: off 后恢复逐条确认

- **WHEN** 执行 `budget setup autorun off tester`
- **THEN** 状态文件移除 tester，安装态 `agents/tester.md` 的 `enabledAutoRun` 行被删除

#### Scenario: 分发层模块缺失报错

- **WHEN** `lib/autorun.py` 未就位（旧安装）时执行 `budget setup autorun list`
- **THEN** 报错提示模块未安装并指引 `budget setup update`，退出码非零（与 quickstart 分发先例一致）

#### Scenario: opencode 形态降级指引

- **WHEN** 在 opencode 安装形态执行 `budget setup autorun on architect`
- **THEN** 输出 OpenCode 替代机制指引（permission map allow 值 / 审批弹窗 always / `--auto` 全局模式），退出码 0，无任何文件修改

#### Scenario: claudecode 形态降级指引

- **WHEN** 在 claudecode 安装形态执行 `budget setup autorun off reviewer`
- **THEN** 输出 Claude Code 替代机制指引（settings.json permissions 规则 / 权限模式），退出码 0，无任何文件修改

#### Scenario: list 双栏输出

- **WHEN** 在 codebuddy 形态执行 `budget setup autorun list`（状态文件含 reviewer，而安装态 reviewer 实为关闭）
- **THEN** 输出全局状态清单与当前安装态实况两栏，差异如实展示，退出码 0

#### Scenario: unknown 形态提示先安装

- **WHEN** 未检测到安装形态（kind=unknown）时执行 `budget setup autorun on architect`
- **THEN** 非零退出，提示先安装 BudgetBuddy 或以 `BUDGET_PLATFORM=` 显式指定，不写状态文件、不补丁任何文件

#### Scenario: 损坏状态文件拒绝执行

- **WHEN** 状态文件 JSON 损坏时执行 `budget setup autorun off tester`
- **THEN** 非零退出并提示修复路径，状态文件字节不被覆盖写、无文件被补丁

#### Scenario: 种子化不纳入手动关闭

- **WHEN** 状态文件缺失且安装态 `coder-lite.md` 为 `enabledAutoRun: false`，执行 `budget setup autorun on reviewer`
- **THEN** 基线不含 coder-lite（仅值 `true` 进基线），reviewer 进清单并补丁 `enabledAutoRun: true`

#### Scenario: help 文案覆盖新子命令

- **WHEN** 执行 `budget setup help`
- **THEN** 用法行与子命令说明含 `autorun`（list/on/off 语义一句话；`apply` 为内部/修复命令，不进 help 与用户文档）

#### Scenario: list 遇损坏状态文件只读展示

- **WHEN** 执行 `budget setup autorun list` 且状态文件 JSON 损坏
- **THEN** 状态栏明示损坏并提示修复路径（运行 `autorun on/off` 修复或编辑/删除该文件），实况栏照常展示，退出码 0，状态文件字节不被改写

#### Scenario: on 输出列出来自数据文件的 bash 模式

- **WHEN** 在 CodeBuddy 形态执行 `budget setup autorun on coder-lite`（安装态 `<install_root>/agents/.bash-patterns.json` 存在）
- **THEN** 输出列出 coder-lite 的 bash 模式（`*`，醒目提示可无审批执行任意 shell 命令）；若数据文件缺失（旧安装），输出降级为通用知情提示且开启照常完成

### Requirement: budget setup ocr 子命令

`budget setup ocr`（实现为 `core/lib/ocr-setup.py`，Python stdlib only，经 setup.sh 分发层直调 python，形态同 `autorun`/`quickstart`）职责为 OCR 预审集成的安装与状态检测：① 检测 `ocr` CLI（`command -v ocr`），缺失时输出 `npm i -g @alibaba-group/open-code-review` 安装指引并继续后续步骤、退出码 0（不强制安装）；② 检测模型配置可用性（存在 `ocr` 时）：检查环境变量 `OCR_LLM_URL`/`OCR_LLM_TOKEN`/`OCR_LLM_MODEL` 或 `~/.opencodereview/` 配置文件任一命中即视为已配置；未命中仅输出「未检测到模型配置——若使用 delegate 模式可忽略」提示、不阻断（退出码 0，安装步骤照常——delegate 模式无需配置，不能据此断定不可用）；③ 将规则模板安装到 OCR 全局层 `~/.opencodereview/rule.json`——模板定位优先 `ocr-setup.py` 自身 `__file__` 同目录的 `ocr-rule.json`（源自 `core/lib/ocr-rule.json`，经 `_build_lib` 字节平移至四平台 dist 的 `lib/`，与 `ocr-setup.py` 天然同目录；环境变量 `BUDGET_LIB_DIR` 可显式覆盖，正常安装态两者等价）；目标目录 `~/.opencodereview/` 不存在时 `os.makedirs` 自动创建（权限失败非零退出并提示手动创建）；写文件采用同目录临时文件原子写（参照 `core/lib/autorun.py` `_atomic_write` 先例：`tempfile.mkstemp` + `os.replace`，写失败不留半截文件）；目标不存在则写入；内容相同则幂等 no-op；内容不同则先备份并展示差异摘要、用户确认后覆盖、取消则保持原文件（绝不静默覆盖；备份默认名 `~/.opencodereview/rule.json.bak`，`.bak` 已存在时改用时间戳后缀 `rule.json.bak.<YYYYMMDDHHMMSS>`，不覆盖任何既有文件；stdin 非 TTY 的非交互环境默认跳过覆盖、输出手动路径、退出码 0）；④ 输出降级语义说明（未装 CLI / 未装规则时 BudgetBuddy 全流程照常）。模板源文件缺失（旧安装未含 `lib/ocr-rule.json`）时报错提示模块未安装并指引 `budget setup update`，退出码非零（与 autorun 分发先例一致）。子命令不依赖特定平台安装态（不补丁 agent 文件、不写 auto-run.json），codebuddy/opencode/claudecode/codex 四形态行为一致；`detect_platform` 未命中（kind=unknown）时规则安装仍可执行（模板路径按 `__file__`/`BUDGET_LIB_DIR` 解析，无安装态时提示先安装或 `BUDGET_PLATFORM=` 显式指定）。【MUST】

#### Scenario: 全新安装规则

- **WHEN** 执行 `budget setup ocr` 且 `~/.opencodereview/rule.json` 不存在
- **THEN** 模板写入该路径（目录不存在时先自动创建），输出安装结果与降级语义说明，退出码 0

#### Scenario: 幂等重装

- **WHEN** 再次执行 `budget setup ocr` 且目标文件与模板内容相同
- **THEN** no-op，不重写文件，退出码 0

#### Scenario: 用户已有规则保护

- **WHEN** 目标文件已存在且与模板内容不同
- **THEN** 生成 `.bak` 备份并展示差异，确认后覆盖、取消则原文件逐字节不变；`.bak` 已存在时本次备份用时间戳后缀路径，既有备份不被覆盖

#### Scenario: CLI 缺失不阻断

- **WHEN** 环境无 `ocr` CLI 时执行 `budget setup ocr`
- **THEN** 输出安装指引后规则安装照常完成，退出码 0

#### Scenario: 模型配置未检出不阻断

- **WHEN** CLI 已安装但环境变量与 `~/.opencodereview/` 配置文件均未检出模型配置
- **THEN** 输出「delegate 模式可忽略」提示，安装步骤照常完成，退出码 0

#### Scenario: 模板缺失报错

- **WHEN** 旧安装的模板源（`__file__` 同目录与 `BUDGET_LIB_DIR` 均无 `ocr-rule.json`）未就位
- **THEN** 非零退出并提示 `budget setup update`，不触碰 `~/.opencodereview/rule.json`

#### Scenario: 原子写不留半截文件

- **WHEN** 安装写入过程中发生 I/O 错误
- **THEN** 目标路径不出现部分内容（临时文件被清理或未被替换），重试后可正常安装

#### Scenario: 四平台行为一致

- **WHEN** 分别在 codebuddy / opencode / claudecode / codex 安装形态执行 `budget setup ocr`
- **THEN** 检测、安装、备份、提示行为一致，均不修改任何 agent 文件与平台状态文件

