# Design — installer-opencode-default-cn-mirror

## Context

- install.sh 交互菜单（179-197 行）：1) CodeBuddy 默认（`*)` 分支 + 无 tty 回退 + 30 行初始变量 `BUDGET_INSTALL_PLATFORM="codebuddy"` 三处）；`all` 分支（1465 行）执行序 codebuddy → opencode → claudecode → codex；`both` 历史值（1464 行）。
- 在线下载：`resolve_latest_tag`（curl 重定向解析 `$BUDGET_REPO_URL/releases/latest`）与 `download_release`（zip + .sha256）均直连 github.com；`BUDGET_REPO_URL`（26 行）为整体仓库 URL 覆盖（可指向自建镜像）。
- 本地模式（仓库内运行）跳过下载，不受影响；curl|bash 入口经 raw.githubusercontent.com 取 main 分支 install.sh（大陆通常可达），失败段集中在 release 下载。
- tests/test_installer.py 64 用例含 `test_no_tty_defaults_to_project`（断言「默认安装 CodeBuddy 平台」+ .codebuddy 项目级落点）。

## Goals / Non-Goals

**Goals:** OpenCode 成为安装默认；大陆网络下在线安装自动经镜像完成版本发现与下载；镜像链可钉死/可禁用；SHA256 信任语义明示。

**Non-Goals:** 不新增自建镜像托管（不引入我们控制的下载源）；不改 release 资产结构（仍 zip + .sha256 单对）；不做 jsDelivr/raw 文件级分发（release 资产不适用）；不动 `both` 历史兼容语义。

## Decisions

### D1：菜单默认三处统一改 OpenCode

交互 `*)` 分支、无 tty 回退（提示语「默认安装 OpenCode 平台」）、30 行初始变量三处同步 `opencode`；菜单编号 OpenCode=1 / CodeBuddy=2 / Claude Code=3 / Codex=4 / 全部=5；`all` 分支调用序改 `install_opencode; install_codebuddy; install_claudecode; install_codex`（与菜单序一致，安装函数相互独立、共享管理面幂等，顺序无功能耦合——`both` 模式已验证共存）；菜单文案「依次执行 OpenCode、CodeBuddy、Claude Code 与 Codex」。
**备选**：仅改菜单不改执行序——rejected：菜单序与实际执行序不一致的认知摩擦。

### D2：镜像链 = 直连 → ghfast.top → gh-proxy.com，三级各 2 次重试

默认链（顺序即优先级）：`""`（直连 github.com）→ `https://ghfast.top` → `https://gh-proxy.com`。每级 `curl --retry 2`；级别失败打印 `[i] 直连 GitHub 失败，尝试镜像源 <X>（第三方传输通道，SHA256 校验仍然执行）` 后进入下一级；三级全败按既有错误语义报错（提示 BUDGET_VERSION / 网络）。
**级别失败语义（含 tag 解析失败）**：某级失败 = 网络请求失败，**或版本发现阶段 `url_effective` 尾段为 `latest`（代理自行跟随重定向返回 200，302 语义丢失）**——两种形态均打印降级提示进入下一级；三级全败按既有语义报错并提示 `BUDGET_VERSION` 显式指定逃生（直达 `releases/download/<tag>` 资产路径，无重定向段，不受代理 302 行为影响）。
**技术假设明示**：ghproxy 类代理对 releases/latest 有两种行为——①保留 302 并改写 Location（尾段仍为 tag，解析成立）；②自行跟随返回 200（解析失败，按级别失败回落）。设计不依赖任一特定行为，两种均有回落路径；若所有镜像均为行为②，latest 自动发现不可用，BUDGET_VERSION 是唯一逃生（错误信息与 README 均明示）。
**理由**：直连优先（海外用户零感知零延迟）；ghproxy 类代理格式统一（前缀 + 完整 URL）可承载 releases/latest 与 releases/download 资产两个面；双镜像冗余应对单镜像波动。
**备选**：①默认即镜像（rejected：牺牲海外直连速度且引入默认第三方依赖）；②api.github.com 做版本发现（rejected：大陆同样不稳，且多一套解析逻辑）。

### D3：BUDGET_MIRROR 三态 + 自定义 BUDGET_REPO_URL 不叠加

- `BUDGET_MIRROR=https://<mirror>`：链表仅含该镜像（跳过直连）
- `BUDGET_MIRROR=none|off|direct`（大小写不敏感）：仅直连（禁第三方通道）
- 未设置 + `BUDGET_REPO_URL` 的 host 为 `github.com`（**谓词 = host 匹配**，默认值与用户 fork 均命中）：走 D2 默认链
- 未设置 + host 非 `github.com`（自建镜像站等）：仅直连该源（用户已接管下载源，不自动叠加第三方镜像）
**理由**：三态覆盖「自动 / 钉死 / 禁用」；自定义源叠加镜像会产生 `<镜像>/<自建源URL>` 的无意义拼接。

### D4：版本发现与下载共用链路，命中镜像优先传递

`resolve_latest_tag` 与 `download_release` 经同一链迭代函数取数；发现阶段命中的镜像写入 `BUDGET_EFFECTIVE_MIRROR` **全局变量**（函数内赋值不加 `local`；**链迭代须在函数主体直接执行、不得置于 `$(...)` 命令替换子 shell 内**——子 shell 赋值不传播父 shell，会静默丢失「命中优先」特性），下载阶段把它置于链首（减少二次探测）；**下载阶段 zip 与 .sha256 整对在同一镜像上完成，任一失败整对回落下一级**（保持 D6 成对篡改论证的同镜像前提，不产生跨镜像混对）；全链失败按既有错误语义报错。
**理由**：两个面（重定向页 + 资产）可达性高度相关，传递命中结果省一半探测；回落保证鲁棒。

### D5：可测性——纯函数 + main guard + 沙盒子进程隔离

`mirror_candidates()`（按 env 生成链表，纯函数）与 `apply_mirror <url> <prefix>`（URL 拼接，纯函数，空前缀原样返回）独立可测。

**可测前提——install.sh 顶层执行段改 bash main guard**：`[[ "${BASH_SOURCE[0]:-$0}" == "$0" ]] && main "$@"`。**`:-$0` 默认值兜底是硬性要求**：`curl | bash` 管道入口下 bash 从 stdin 读脚本，`BASH_SOURCE` 为空数组，`set -u`（install.sh:23）下裸引用 `${BASH_SOURCE[0]}` 触发 unbound variable 崩溃（实测复现，exit 1、main 不执行）；stdin 场景 `$0=bash` 回退后 `bash==bash` 成立、main 正常触发；直行 `bash install.sh` 下 `BASH_SOURCE[0]==$0` 成立、行为不变；source 下不相等不执行（安全先例：install.sh:105 show_version 已用 `${BASH_SOURCE[0]:-$0}` 写法）。install.sh 单文件结构保持，无 lib 拆分。

**测试 harness 须子进程隔离**：`bash -c 'source install.sh; mirror_candidates ...'` 形态（先例 test_guard.py 的 run_bash 即 `subprocess.run(['bash','-c',...])`）——规避 source 传染外层 shell 的 `set -euo pipefail` 与 trap 副作用。链迭代与网络相关逻辑不设自动化用例（沙盒本地模式不走在线路径），实测归 tester 手工（BUDGET_MIRROR 钉死 + 直连禁用两态冒烟）。

### D6：信任边界明示（README + 降级提示双处）

镜像仅作传输通道，SHA256 校验强制不变；但 zip 与 .sha256 同链获取——恶意代理理论上可成对篡改。README 安装章节与降级提示均明示该边界及 `BUDGET_MIRROR=none` 退出通道。

## Risks / Trade-offs

- [镜像服务波动/停服] → 双镜像 + 直连三级链 + BUDGET_MIRROR 可钉死任意自选镜像（README 示例）
- [第三方通道信任] → D6 双处明示 + none 退出 + 校验不变（对诚实镜像有效；对成对篡改的恶意代理无防御——与社区 ghproxy 用法一致的既有权衡）
- [all 顺序变更影响既有用户脚本？] → all 分支仅顺序变化无路径/产物变化；both 不动
- [update.sh 是否有独立下载需同步镜像] → 实施时核对（Open Questions）；若有则同链复用，若无则 scope 不含
- [菜单文案/测试断言遗漏] → 全仓 grep「默认安装 CodeBuddy」「默认 1」清点

## Migration Plan

1. 实施顺序：菜单与默认（install.sh）→ 镜像链与 BUDGET_MIRROR（install.sh）→ README 双语 → 测试更新 → 门禁实测
2. 回滚：`git revert`；无数据/产物迁移；install.sh 从 raw 即时生效同样即时回滚

## Open Questions

- `core/lib/update.sh` 是否含独立 release 下载逻辑需同步镜像链？→ 实施第一步核对：若有则纳入本变更（同链复用），若其仅调用 install.sh 或无下载则 scope 不变
- ghfast/gh-proxy 之外的镜像要不要进默认链？→ 默认链保持两级（探测时间可控），其余镜像用户经 BUDGET_MIRROR 自选（README 给示例）
