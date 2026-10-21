# 设计：Claude Code hooks 通知适配

## Context

CodeBuddy 的 hooks 体系（事件名/payload schema/settings.json 结构）与 Claude Code 官方 hooks 高度同构（CodeBuddy 沿用该约定）：

| 维度 | CodeBuddy | Claude Code | 复用度 |
|---|---|---|---|
| settings.json 结构 | `hooks.<Event>[{matcher, hooks:[{type,command,timeout}]}]` | 同 | 100%（引擎零结构改动） |
| settings 落点 | `.codebuddy/` 或 `~/.codebuddy/` | `.claude/` 或 `~/.claude/` | 路径参数化 |
| payload 公共字段 | `hook_event_name`/`cwd` | 同 | 100% |
| Notification | `notification_type`（permission_prompt/idle_prompt） | 无 `notification_type`，`message` 直载（权限等待/空闲提醒） | 需 message 直通分支 |
| PermissionRequest | （无） | 有（权限确认卡点，本机 settings 实证存在该事件） | 新增处理 |
| PreToolUse Bash 越权 | `tool_input.dangerouslyDisableSandbox` | 无该字段（沙箱语义不同） | 条件不满足自然跳过，零改动 |
| SubagentStop | `stop_hook_active` 防循环 | 同 | 100% |
| 插件机制 | superpowers（enabledPlugins） | 无 | claudecode 跳过 |

本机 Claude Code CLI 2.1.304 可端到端验证（注入 → 派发子代理 → SubagentStop 触发 → notify 收到）。

## Goals / Non-Goals

**Goals:**
- claudecode 平台 hooks 通知与 codebuddy 能力对齐：卡点（Notification/PermissionRequest）与子代理完成（SubagentStop）通知
- 引擎单份复用：hook 引擎与注入引擎平台无关化，事件集由编排层数据驱动

**Non-Goals:**
- opencode hooks、Claude Code 其余 hook 事件、superpowers 在 Claude Code 端的等价物
- 通知渠道/配置机制变更（notify.py/notify.json 零改动）

## Decisions

### D1 hook 引擎 payload 驱动兼容（`budget-notify-hook.py`）

不按平台分支，按 payload 事实分派：
- `Notification`：`notification_type` 存在 → 现有两分支（codebuddy）；缺失但 `message` 非空 → 新分支「会话提醒直通」（标题平台中性 🤖「会话提醒」，正文 message 截断 200 字——Claude Code 权限等待与空闲提醒均以 message 直载）；两者皆无 → None
- `PermissionRequest`：新增事件处理（标题 🤖「流程卡点，需要您确认」，正文 message 或 tool_name/tool_input 摘要；**字段全缺失时输出通用卡点文案而非静默**——卡点漏通知违背本变更初衷），`stop_hook_active` 不适用
- `SubagentStop` / `PreToolUse`：零改动（PreToolUse 的 dangerouslyDisableSandbox 条件在 Claude Code payload 上不成立，自然静默）
- 文案中「请在 CodeBuddy 中确认」改为「请在当前会话中确认」（两平台通用）
- 备选被否：按 hook 脚本所在平台目录分支——payload 驱动更简单且两平台产物本就同源平移

### D2 注入事件集参数化（`hooks_inject.py`）

引擎 action `inject_hooks`/`inject_all`/`remove_hooks` 保持；新增环境变量 `HOOK_EVENTS_JSON`（编排层传入注入事件清单，JSON 形态 `[{"event":"Notification","matchers":["permission_prompt","idle_prompt"]},{"event":"PreToolUse","matchers":["Bash"]},{"event":"SubagentStop","matchers":[]}]`）。**适配范围仅 `inject_hooks`/`inject_all`**（注入路径按清单展开）；`remove_hooks`（marker 驱动，全事件扫描删除）与 `check_hooks`（存在性判定）无需事件集适配，不改动：
- 未传 → 使用现有模块常量（codebuddy 默认，行为字节级不变）
- 传入 → 按清单注入（matcher 为空数组的.event 注入无 matcher 条目）
- `HOOK_MARKER` 幂等判定/移除精确性/备份/原子写全复用
- claudecode 清单：`Notification(matcher "*")` + `PermissionRequest(matcher "*")` + `SubagentStop(无 matcher)`
- 备选被否：引擎内 if platform 硬编码——事件集是平台数据，编排层提供更符合 D1 泛化精神（后续 Codex/新平台零引擎改动）

### D3 hooks.sh 编排扩展

- `_budget_hooks_settings_file`：kind == claudecode → 项目级 `${BUDGET_PLATFORM_ROOT}/.claude/settings.json`、全局 `$HOME/.claude/settings.json`（探测序同现有 codebuddy 分支模式）
- `_budget_hooks_hook_cmd`：claudecode 路径 `.claude/hooks/budget-notify-hook.py`（项目相对）/ `$BUDGET_SETUP_DIR/hooks/`（源与全局形态）
- `budget_inject_hooks`：kind == claudecode → 引擎调 `inject_hooks`（非 `inject_all`，跳过 superpowers）+ 传 `HOOK_EVENTS_JSON`（claudecode 三事件清单）；kind == codebuddy → 现行为不变
- `budget_inject_superpowers`：claudecode 形态跳过（提示无插件机制）

### D4 分发与安装/卸载闭环

- `core/platform/claudecode.yaml`：`routing.hook: "hooks/budget-notify-hook.py"`；`locate_notify_py`（hook 引擎内）寻 `../skills/budget-notify/notify.py`——claudecode 布局 `.claude/{hooks,skills}` 同根，零改动成立
- `install.sh install_claudecode`：hooks 文件分发后调用 `budget_inject_hooks`（子进程形态同 `inject_hooks_codebuddy` 先例，参数化平台）；**`sync_manifest_tree` 的 `struct_prefixes` 增 `hooks` 前缀**（结构文件分类含 hooks/）
- `uninstall.sh`：claudecode 形态先清 settings.json 注入（复用 `_budget_uninstall_clean_settings`，路径取 `.claude/settings.json`）再删 hooks 文件（**`_budget_uninstall_collect_claudecode_platform` 枚举补 `hooks/budget-notify-hook.py`** + 清单/枚举两路径）
- `validate.sh`：claudecode 形态增加 hooks 文件与注入状态检查项；`hooks.sh budget_check_hooks` claudecode 输出适配（不显示 superpowers 行，显示三事件注入状态）
- `init.sh`：claudecode 形态的注入桩调用启用（现非 codebuddy 跳过 → 改为 codebuddy/claudecode 均注入、opencode 跳过）

### D5 文档口径

README 双语「Claude Code hooks 通知首发不支持」表述更新为已支持（v0.2.1）；CHANGELOG 增条目；`platforms.claudecode.note` 同步。

## Risks / Trade-offs

- [用户 settings.json 已含第三方 hooks（本机实证 vibe-island）] → 条目级注入/移除幂等（既有引擎语义），matcher 下并行共存；注入前备份
- [Claude Code 事件 schema 演进（PermissionRequest 为新事件，旧版本无）] → 注入后旧版本忽略未知事件 hook（无副作用）；引擎无法识别 payload 静默退出
- [Notification message 直通可能通知过频（Claude Code 会把各种提醒走 Notification）] → v1 直通全部 message；若实测噪音大，后续按 message 前缀过滤（记入 Open Questions 观察项）
- [同一次权限等待双发（PermissionRequest 先发、等待期间 Notification 再发）] → v1 接受双发（观察项）；噪音显著时后续加 60s 内同项目卡点去重（记入 Open Questions）
- [全局注入 ~/.claude/settings.json 影响所有项目] → 与 codebuddy 全局注入同语义（用户已选全局安装）；卸载精确清理

## Migration Plan

1. 引擎与编排改造（D1-D3）→ codebuddy 回归（注入字节级不变）→ claudecode 注入
2. 安装/卸载/validate 闭环（D4）
3. 本机端到端验证：/tmp 项目安装 → 注入项目 `.claude/settings.json` → `claude -p` 派发子代理 → SubagentStop hook 触发 → custom 渠道指向本地 HTTP 探针验证收到 `[budget]` 消息
4. 门禁三命令 + 真实 ~/.claude 全局注入验证（本机用户同意后）
5. 回滚：纯增量，revert 即回；已注入 settings 经 `budget setup uninstall` 精确清理

## Open Questions

- Notification 直通的噪音水平（本机端到端观察后定是否加过滤）
- PermissionRequest/Notification 双发叠加的去重阈值（观察后定 60s 窗口或事件互斥）
- PermissionRequest 在 Claude Code 各版本的可用性（2.1.304 实证存在）
