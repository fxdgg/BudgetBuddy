## Why

两处安装体验问题：
1. **交互菜单以 CodeBuddy 为默认**（选项 1 / 无 tty 回退 / 非交互初始值三处均为 codebuddy）——用户主力平台为 OpenCode，每次安装都要手动选择，默认值错位。
2. **在线安装的 release 下载直连 `github.com`**——大陆内网用户在「版本发现（releases/latest 重定向）」与「zip 下载（releases/download/）」两步均超时失败，curl|bash 入口的 raw.githubusercontent.com 可达而 release 段不可达，安装成本高。注：raw.githubusercontent.com 只能承载仓库文件、无法承载 release 资产，因此镜像需走可代理完整 GitHub URL 的 ghproxy 类通道。

## What Changes

- **安装菜单重排**：OpenCode 升为选项 1 与默认（交互 `*)` 分支、无 tty 回退、非交互初始变量 `BUDGET_INSTALL_PLATFORM` 三处同步）；CodeBuddy/Claude Code/Codex 顺延为 2/3/4；「全部」执行顺序对齐为 OpenCode 优先（`all` 分支调用序与菜单文案同步）；`both` 历史兼容值不动
- **镜像下载链**：`install.sh` 在线模式新增 ghproxy 类镜像回退链——直连 `github.com`（2 次重试）→ `ghfast.top` → `gh-proxy.com`（各 2 次重试）；版本发现与 zip/.sha256 下载共用同一链路；某级失败打印降级提示（含第三方通道信任说明）；版本发现命中的镜像优先用于后续下载
- **`BUDGET_MIRROR` 环境变量**：`https://<mirror>` 钉死单镜像（跳过直连）；`none`/`off`/`direct` 仅直连（信任敏感用户可禁第三方通道）；自定义 `BUDGET_REPO_URL`（自建镜像站）时不自动叠加镜像链（用户已接管下载源）
- **URL 变换规则**：`<镜像前缀>/<完整原始 https URL>`（ghproxy 类代理通用格式）；纯函数 `mirror_candidates`（链表生成）与 `apply_mirror`（URL 变换）可独立测试
- **SHA256 校验链路零改动**：下载完整性语义不变（校验失败即中止）；README 双语明示第三方镜像的信任边界（代理理论上可同时篡改 zip 与 .sha256，`BUDGET_MIRROR=none` 可退直连）
- **README 双语**：安装章节补「大陆网络与镜像」说明（自动回退 + BUDGET_MIRROR 用法 + 信任提示）
- **测试**：test_installer.py 无 tty 默认断言更新（codebuddy→opencode）；新增镜像纯函数用例（链表组合 / URL 变换 / BUDGET_MIRROR 三态 / 自定义 REPO_URL 不叠加）；全量回归

## Capabilities（ADDED/MODIFIED Requirements）

- `installer`（MODIFIED 两条）：「交互与非交互模式」（菜单序与默认 OpenCode）、「版本定位与下载包完整性校验」（镜像回退链与 BUDGET_MIRROR）
- `repo-docs`（MODIFIED）：README 双语安装说明补镜像段（双语对等）

## Impact

- **代码**：`install.sh`（菜单三处 + all 分支序 + 镜像链 + 环境变量）；README.md / README_CN.md（安装章节）
- **不触碰**：`budget setup update` 的版本发现约定（同一 install.sh 函数复用则同享镜像链——`core/lib/update.sh` 若有独立下载逻辑需核对，见 design Open Questions）；SHA256 校验逻辑；dist/ 产物（install.sh 不入 zip，raw 入口即时生效）
- **发布**：无需重打 release（zip 不含 install.sh；curl|bash 从 main 分支 raw 取脚本，合并即生效）
- **风险**：第三方镜像可用性随时间波动（链表可经 BUDGET_MIRROR 覆盖；默认链含两个镜像 + 直连三级）；镜像信任边界已在 README 与降级提示中明示
