# setup-cli Delta

## ADDED Requirements

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
