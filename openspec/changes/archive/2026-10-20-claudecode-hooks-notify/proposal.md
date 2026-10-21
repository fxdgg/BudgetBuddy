# 提案：Claude Code hooks 通知适配（claudecode-hooks-notify）

## Why

`add-claudecode-platform`（v0.2.0）将 claudecode 平台的 hooks 首发降级不注入（同 opencode 先例），Claude Code 用户无卡点/完成通知。事实上 Claude Code 拥有与 CodeBuddy 同构的 hooks 机制（settings.json 三段式结构 + stdin JSON payload 事件 schema 几乎一致——`hook_event_name`/`notification_type`/`tool_input`/`stop_hook_active` 均同名），且本机已装 Claude Code CLI 2.1.304，可真实端到端验证。适配成本低（引擎近复用），收益是三平台通知能力对齐。

## What Changes

- `budget-notify-hook.py` 事件兼容扩展（payload 驱动、平台无关）：Notification 事件在无 `notification_type` 字段时按 `message` 直通通知（Claude Code 形态）；新增 `PermissionRequest` 事件处理（Claude Code 权限确认卡点）；`SubagentStop` 原样复用；`PreToolUse` Bash 越权检测保留（Claude Code payload 无 `dangerouslyDisableSandbox` 字段时自然跳过，零改动兼容）
- `core/lib/hooks.sh` 编排扩展：`_budget_hooks_settings_file` 支持 claudecode 形态（项目 `.claude/settings.json` / 全局 `~/.claude/settings.json`）；`_budget_hooks_hook_cmd` 构造 `.claude/hooks/` 路径；按 `BUDGET_PLATFORM_KIND` 选择注入事件集与 action（claudecode 不含 superpowers 插件注入）
- `core/lib/hooks_inject.py` 引擎事件集参数化：注入事件清单由编排层经环境变量传入（claudecode：Notification + PermissionRequest + SubagentStop；codebuddy：现三事件不变），注入/移除/幂等/备份机制全部复用
- `core/platform/claudecode.yaml`：`routing.hook` 从空串改为 `hooks/budget-notify-hook.py`（取消降级）
- `install.sh`：`install_claudecode` 增加 hooks 文件分发与 settings.json 注入调用；`uninstall.sh` claudecode 形态清理 settings.json 注入项（复用 `_budget_uninstall_clean_settings`）与 hooks 文件
- 文档同步：README 双语 / CHANGELOG / claudecode 平台说明（hooks 降级表述改为已支持）

### 非目标（本期不做）

- opencode 平台 hooks（无机制，维持降级）
- Claude Code 其他 hook 事件（PostToolUse/SessionStart/PreCompact 等）——只做预算通知相关三事件
- Codex 平台（独立变更 `add-codex-platform` 并行推进）

## Capabilities

### New Capabilities

（无）

### Modified Capabilities
- `notify`: 「CodeBuddy hooks 三事件通知」requirement 扩展为跨平台 hooks 通知——claudecode 端 Notification/PermissionRequest/SubagentStop 三事件注入 `.claude/settings.json`，引擎 payload 驱动兼容两平台
- `claudecode-platform`: hooks 降级不分发声明改为支持分发与注入（R1 产物结构 + 新增注入场景）
- `installer`: claudecode 安装增加 hooks 分发与注入步骤（MODIFIED 双平台安装落点 requirement 的 claudecode 段）
- `setup-cli`: hooks.sh claudecode 形态注入/移除/卸载清理（MODIFIED「superpowers 插件启用」相关边界——claudecode 跳过插件仅注入 hooks）

## Impact

- **代码**：`core/hooks/budget-notify-hook.py`（事件兼容）、`core/lib/hooks.sh`（编排扩展）、`core/lib/hooks_inject.py`（事件集参数化）、`core/lib/uninstall.sh`（claudecode 清理）、`install.sh`（claudecode hooks 分发+注入）、`core/platform/claudecode.yaml`（routing.hook）
- **产物**：dist/claudecode 新增 `hooks/budget-notify-hook.py`；`~/.claude/settings.json`（全局）或项目 `.claude/settings.json` 被注入（备份 + 幂等 + 移除精确，机制复用）
- **测试**：hooks_inject 事件集参数化用例、hook 引擎新事件用例、安装器/卸载用例扩展
- **风险**：用户 settings.json 已有第三方 hooks（本机实测存在）——注入条目级幂等追加/移除，互不干扰（引擎既有语义）；Claude Code 事件字段演进——无法识别字段静默跳过
