# installer Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
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

### Requirement: 交互与非交互模式

无参数时交互选择平台（CodeBuddy/OpenCode/Claude Code/全部）与作用域（项目/全局），交互从 /dev/tty 读取；`--global` 跳过交互；`BUDGET_PLATFORM`（codebuddy|opencode|claudecode|both|all）与 `BUDGET_GLOBAL` 环境变量支持纯非交互；纯非交互环境（无 tty）默认项目安装（design.md §10）；`both` 为历史兼容值（语义 = codebuddy+opencode），帮助文本标注 `all` 为全部平台推荐值。【MUST】

#### Scenario: 环境变量非交互

- **WHEN** `BUDGET_PLATFORM=opencode BUDGET_GLOBAL=1 bash install.sh`
- **THEN** 无任何交互提示完成 opencode 全局安装

#### Scenario: claudecode 非交互

- **WHEN** `BUDGET_PLATFORM=claudecode bash install.sh`
- **THEN** 无交互提示完成 claudecode 项目级安装

#### Scenario: 交互菜单四选项

- **WHEN** 无参数交互安装
- **THEN** 平台菜单含 CodeBuddy / OpenCode / Claude Code / 全部四选项，选择后进入作用域选择

### Requirement: 版本定位与下载包完整性校验

版本定位（design.md §10/A9）：默认经 `$BUDGET_REPO_URL/releases/latest`（release 托管方 latest 固定别名）解析最新版本 zip 下载 URL；`BUDGET_VERSION` 环境变量可指定具体 tag；`budget setup update` 沿同一约定重新发现版本。下载完整性（A12）：release 附 `budgetbuddy-<version>.zip.sha256`；install.sh 下载 zip 后强制执行 SHA256 校验（sha256sum / shasum -a 256 自动探测），**校验失败即中止、不进入安装**；校验工具缺失列为依赖检查错误。【MUST】

#### Scenario: 校验失败中止
- **WHEN** 下载的 zip SHA256 与 .sha256 文件不一致（或 .sha256 文件缺失）
- **THEN** 安装中止并明确报错，不复制任何文件到安装目录

#### Scenario: 指定版本安装
- **WHEN** `BUDGET_VERSION=v0.1.0 bash install.sh`
- **THEN** 下载该 tag 对应的 zip 与 .sha256 并完成校验后安装

#### Scenario: 版本发现
- **WHEN** `budget setup update` 执行
- **THEN** 按 releases/latest 约定重新发现最新版本并进入升级流程

### Requirement: AGENTS.md 标记区块幂等合并

opencode 安装将 AGENTS.fragment.md 合并进目标 AGENTS.md（项目根或 `~/.config/opencode/AGENTS.md`）：整体以 `<!-- BudgetBuddy:begin -->` / `<!-- BudgetBuddy:end -->` 包裹，每条 rule 另有 `<!-- budget-<rule-name>:begin/end -->` 二级标记；重复安装仅替换区块内部，区块外用户内容永不触碰；目标文件不存在时创建（design.md §3.5/§10）。【MUST】

#### Scenario: 幂等重装
- **WHEN** 连续两次执行 opencode 安装
- **THEN** AGENTS.md 区块内容不变（无重复追加），区块外内容保持原样

#### Scenario: 用户内容保护
- **WHEN** 用户在区块外追加了自定义指令后重装
- **THEN** 用户追加内容原样保留

### Requirement: manifest 增量同步与安装清单持久化

增量同步以 `dist/<platform>/.manifest.json`（构建侧 SHA256 清单，A7）为唯一同步依据：目标文件哈希与清单一致则跳过，不一致则覆盖，清单外文件一律保留。安装清单持久化（A12）：安装/升级成功后写 `<安装根>/.budget-manifest.json`（本地已装文件与哈希，最后原子写）；**升级**按「本地旧清单 − 新 manifest」差集清理旧版文件（清单内文件的用户本地修改会被升级覆盖）；**卸载**按本地清单删除（离线可用，不依赖 dist manifest）。安装各步骤幂等（哈希跳过/合并幂等/清单原子写），中断后重跑安装即恢复（design.md §10）。【MUST】

#### Scenario: 用户自建 agent 保留
- **WHEN** 用户在 .codebuddy/agents/ 放了自定义 agent 文件后执行更新安装
- **THEN** 该自定义文件被完整保留

#### Scenario: 变更文件覆盖
- **WHEN** 清单内某文件在新版构建产物中哈希变化
- **THEN** 安装时被新版本覆盖

#### Scenario: 升级差集清理
- **WHEN** 新版 manifest 不含本地旧清单中的某文件（该文件由旧版本安装）
- **THEN** 升级时该旧文件被清理；清单外用户自建文件不受影响

#### Scenario: 卸载按本地清单
- **WHEN** 执行卸载
- **THEN** 仅删除本地 .budget-manifest.json 清单内文件，清单外文件一律保留

#### Scenario: 安装中断恢复
- **WHEN** 安装在某步骤中断后重新执行安装
- **THEN** 已完成的文件复制按哈希跳过、AGENTS.md 合并幂等，安装恢复完成且无重复副作用

### Requirement: 依赖检查与平台兼容

安装前检查 curl/tar/python3（python 或 python3 自动探测）与 sha256 校验工具（sha256sum 或 shasum -a 256）；缺失时明确报错并列出缺失项；Windows 环境提示使用 Git Bash 或 WSL（不照抄内部镜像 URL，下载源为可配置的 `BUDGET_REPO_URL`，默认 GitHub raw 占位地址，design.md §10/§15-Q1）。【MUST】

#### Scenario: 缺依赖报错
- **WHEN** python3 不可用
- **THEN** 安装中止并提示安装 Python 3

#### Scenario: 仓库地址可配置
- **WHEN** `BUDGET_REPO_URL` 指向自建镜像
- **THEN** 在线安装从该地址拉取 install.sh 与产物 zip

### Requirement: 安装后 AutoRun 状态重放

`install.sh` 的 `install_codebuddy` 分支在 manifest 增量同步（含升级差集清理）完成后、写入本地清单前（钩子落点：`upgrade_diff_cleanup` 调用之后、`write_local_manifest` 调用之前；install.sh L929/L936，行号随文件演进以锚点函数名称为准），若全局状态文件 `~/.budgetbuddy/auto-run.json` 存在，则以刚同步的 `lib/autorun.py` 执行 `apply`（清单内 agent 确保 `enabledAutoRun: true`、清单外确保删除该行），将用户持久化选择重放到本次同步可能被 dist 默认值覆盖的 agent 文件上；重放失败（含状态文件损坏）仅告警（提示 `budget setup autorun` 修复），不阻断安装主流程、不影响本地清单写入、不覆盖写状态文件。状态文件不存在时不执行重放（dist 默认值 = 4 个执行类 agent 免审批）。opencode/claudecode 分支无此钩子（两平台不映射 auto-run）。【MUST】

#### Scenario: 升级安装后用户选择保持

- **WHEN** 用户状态文件为「默认 4 个 + reviewer」，重新运行新版本 install.sh（agent 文件被新 dist 覆盖）
- **THEN** 同步后重放执行：reviewer 恢复 `enabledAutoRun: true`，4 个默认 agent 仍在位，其余 5 个不含该键

#### Scenario: 无状态文件不重放

- **WHEN** 首次安装且 `~/.budgetbuddy/auto-run.json` 不存在
- **THEN** 安装不执行 apply，agent 文件保持 dist 原样（4 个执行类 agent 含 `enabledAutoRun: true`）

#### Scenario: apply 失败降级告警

- **WHEN** 状态文件存在但内容损坏（JSON 解析失败）导致 apply 非零退出
- **THEN** 安装流程继续（本地清单正常写入），输出告警提示用户运行 `budget setup autorun list` 检查状态；状态文件字节保持原样（apply 不得覆盖写）

#### Scenario: 重放不影响安装幂等性

- **WHEN** 连续两次运行 install.sh：无状态文件、或状态与 dist 默认一致（默认 4 个执行类 agent）时，第二次同步全部哈希跳过（SYNC_SKIPPED，SYNC_UPDATED=0）；非默认状态（如「默认 4 个 + reviewer」）下，reviewer 经 apply 补丁后其文件哈希 ≠ dist 清单哈希，第二次同步先以 dist 重覆盖该偏差 agent（SYNC_UPDATED>0，`enabledAutoRun` 被 dist 默认值冲掉），再由 apply 重放恢复
- **THEN** 两种路径终态均与首次一致（reviewer 恢复 `enabledAutoRun: true`、默认 4 个仍在位、其余不含该键），且 apply 为字节级幂等（重复执行文件字节不变），安装主流程正常完成

