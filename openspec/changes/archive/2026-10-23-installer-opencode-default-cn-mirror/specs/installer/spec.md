# installer Delta Spec

## MODIFIED Requirements

### Requirement: 交互与非交互模式

无参数时交互选择平台（OpenCode/CodeBuddy/Claude Code/Codex/全部，菜单序 OpenCode 为选项 1）与作用域（项目/全局），交互从 /dev/tty 读取；交互空输入/非法输入、无 tty 回退（提示「默认安装 OpenCode 平台」）、非交互初始默认值三处 SHALL 一致默认 `opencode`；`--global` 跳过交互；`BUDGET_PLATFORM`（codebuddy|opencode|claudecode|codex|both|all）与 `BUDGET_GLOBAL` 环境变量支持纯非交互；纯非交互环境（无 tty）默认项目安装（design.md §10）；`all` 分支执行顺序 SHALL 为 OpenCode → CodeBuddy → Claude Code → Codex（菜单「全部」文案同步）；`both` 为历史兼容值，帮助文本标注 `all` 为全部平台推荐值。【MUST】

#### Scenario: 环境变量非交互

- **WHEN** `BUDGET_PLATFORM=opencode BUDGET_GLOBAL=1 bash install.sh`
- **THEN** 无任何交互提示完成 opencode 全局安装

#### Scenario: claudecode 非交互

- **WHEN** `BUDGET_PLATFORM=claudecode bash install.sh`
- **THEN** 无交互提示完成 claudecode 项目级安装

#### Scenario: codex 非交互

- **WHEN** `BUDGET_PLATFORM=codex bash install.sh`
- **THEN** 无交互提示完成 codex 项目级安装

#### Scenario: 交互菜单五选项

- **WHEN** 无参数交互安装
- **THEN** 平台菜单含 OpenCode / CodeBuddy / Claude Code / Codex / 全部五选项（OpenCode 为选项 1 与默认），选择后进入作用域选择

#### Scenario: 交互默认选项

- **WHEN** 交互菜单直接回车（空输入）
- **THEN** 选择 OpenCode（选项 1）

#### Scenario: 无 tty 默认 OpenCode

- **WHEN** 纯非交互环境（无控制终端）执行 install.sh 且未设置 BUDGET_PLATFORM
- **THEN** 提示「默认安装 OpenCode 平台」，落点为 OpenCode 项目级安装（作用域默认项目不变）

#### Scenario: all 执行顺序

- **WHEN** 选择「全部」安装
- **THEN** 依次执行 OpenCode、CodeBuddy、Claude Code 与 Codex 安装，各平台产物落点与集成前逐平台一致

### Requirement: 版本定位与下载包完整性校验

版本定位（design.md §10/A9）：默认经 `$BUDGET_REPO_URL/releases/latest`（release 托管方 latest 固定别名）解析最新版本 zip 下载 URL；`BUDGET_VERSION` 环境变量可指定具体 tag；`budget setup update` 沿同一约定重新发现版本。**镜像回退链**：当 `BUDGET_REPO_URL` 的 host 为 `github.com`（含用户 fork，谓词为 host 匹配而非完整 URL 相等）时，版本发现与 zip/.sha256 下载 SHALL 依次尝试 直连（`--retry 2`，共 3 次尝试）→ `https://ghfast.top` → `https://gh-proxy.com`（各级同参数），URL 变换规则为 `<镜像前缀>/<完整原始 https URL>`（ghproxy 类代理格式）；**级别失败** SHALL 包含两种形态——网络请求失败、或版本发现阶段 `url_effective` 未能解析出非 `latest` 的有效 tag（代理可能自行跟随重定向返回 200，尾段为 `latest`）——均打印降级提示（含第三方通道与 SHA256 校验说明）后进入下一级；三级全败保持既有错误语义报错，错误信息 SHALL 提示 `BUDGET_VERSION` 显式指定为逃生通道（直达 `releases/download/<tag>` 资产路径，无重定向）。版本发现命中的镜像 SHALL 优先用于后续下载；下载阶段 zip 与 .sha256 SHALL 整对在同一镜像上完成（任一失败整对回落下一级，不产生跨镜像混对），全链失败按既有错误语义报错。`BUDGET_MIRROR` 环境变量三态：`https://<mirror>` 钉死单镜像（跳过直连）；`none`/`off`/`direct`（大小写不敏感）仅直连；未设置且 `BUDGET_REPO_URL` host 非 `github.com` 时 MUST NOT 自动叠加镜像链（用户已接管下载源）。下载完整性（A12）语义 MUST NOT 改变：release 附 `budgetbuddy-<version>.zip.sha256`；install.sh 下载 zip 后强制执行 SHA256 校验（sha256sum / shasum -a 256 自动探测），**校验失败即中止、不进入安装**；校验工具缺失列为依赖检查错误。【MUST】

#### Scenario: 校验失败中止

- **WHEN** 下载的 zip SHA256 与 .sha256 文件不一致（或 .sha256 文件缺失）
- **THEN** 安装中止并明确报错，不复制任何文件到安装目录

#### Scenario: 指定版本安装

- **WHEN** 设置 BUDGET_VERSION=<tag> 执行安装
- **THEN** 跳过 latest 发现，直接下载该 tag 的 zip（镜像链同样适用）

#### Scenario: 版本发现

- **WHEN** 执行 `budget setup update`（沿同一约定重新发现版本）
- **THEN** 复用 install.sh 同一版本发现链路（镜像链同样适用）

#### Scenario: 直连失败自动回退镜像

- **WHEN** 直连 github.com 网络失败（如大陆内网环境）
- **THEN** 依次尝试 ghfast.top 与 gh-proxy.com（各级打印降级提示），任一命中则完成版本发现与下载，SHA256 校验照常执行

#### Scenario: 镜像重定向语义失败同级的级联回退

- **WHEN** 某镜像对 releases/latest 自行跟随重定向返回 200（url_effective 尾段为 latest，无法解析 tag）
- **THEN** 该级视为失败并打印降级提示，进入下一级；三级全败时报错并提示 BUDGET_VERSION 显式指定逃生

#### Scenario: 钉死单镜像

- **WHEN** 设置 BUDGET_MIRROR=https://<某镜像> 执行安装
- **THEN** 跳过直连，仅经该镜像发现版本与下载（URL 变换规则同上；tag 解析失败语义同上）

#### Scenario: 禁用镜像

- **WHEN** 设置 BUDGET_MIRROR=none（或 off/direct）
- **THEN** 仅直连 github.com，不尝试任何第三方镜像

#### Scenario: 自定义下载源不叠加

- **WHEN** 设置 BUDGET_REPO_URL 指向 host 非 github.com 的自建镜像站且未设置 BUDGET_MIRROR
- **THEN** 直连该自定义源，不自动叠加 ghproxy 镜像链
