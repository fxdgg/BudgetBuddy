# 任务清单：claudecode-hooks-notify

> 任务分派路由（P0 三规则）：每任务完成后经 tester 验证、reviewer 审查。

## 1. 引擎与编排（hooks 三层改造）

- [x] 1.1 【coder-senior | cross_module】`core/lib/hooks_inject.py` 事件集参数化：新增 `HOOK_EVENTS_JSON` 环境变量（JSON 注入清单：event/matchers），未传时沿用现有模块常量（codebuddy 行为字节级不变）；按清单注入/幂等/移除逻辑复用；非法 JSON 报错退出不写回
- [x] 1.2 【coder-senior | cross_module】`core/hooks/budget-notify-hook.py` 事件兼容：Notification 无 `notification_type` 时 message 直通分支（200 字截断）；新增 PermissionRequest 事件处理（message/tool_name 摘要）；「请在 CodeBuddy 中确认」文案平台中性化；PreToolUse/SubagentStop 零改动验证
- [x] 1.3 【coder-senior | cross_module】`core/lib/hooks.sh` 编排扩展：`_budget_hooks_settings_file`/`_budget_hooks_hook_cmd` 支持 claudecode 形态（.claude/settings.json 项目级 / ~/.claude/settings.json 全局；.claude/hooks/ 路径）；`budget_inject_hooks` 按 kind 分派（claudecode → inject_hooks + claudecode 三事件 HOOK_EVENTS_JSON，无 superpowers；codebuddy → 现行为不变）；`budget_inject_superpowers` claudecode 跳过提示；`budget_check_hooks` claudecode 输出适配（不显示 superpowers 行）
- [x] 1.4 【tester】引擎与编排回归：codebuddy 注入/移除/幂等/备份与改动前一致（临时仓库 diff 断言）；claudecode 注入生成三事件条目（Notification/PermissionRequest/SubagentStop，matcher 形态正确）；HOOK_EVENTS_JSON 非法值报错不写回；hook 引擎单测式管道验证（echo payload | python hook.py，mock notify 路径）

## 2. 分发与安装/卸载闭环

- [x] 2.1 【coder-standard | config_edit】`core/platform/claudecode.yaml`：`routing.hook: "hooks/budget-notify-hook.py"`；验证 locate_notify_py 相对寻径在 claudecode 布局成立（.claude/{hooks,skills} 同根）
- [x] 2.2 【coder-senior | cross_module】安装/卸载/校验闭环：install.sh `install_claudecode` hooks 分发 + 注入调用（子进程模式同 codebuddy 先例，参数化）+ `sync_manifest_tree` 结构前缀增 hooks；`core/lib/uninstall.sh` claudecode 先清 settings.json 注入（复用 `_budget_uninstall_clean_settings`）再删 hooks 文件（`_budget_uninstall_collect_claudecode_platform` 枚举补 hooks 文件）；`core/lib/validate.sh` claudecode 形态增 hooks 文件与注入状态检查；`core/lib/init.sh` claudecode 形态启用注入桩（opencode 保持跳过）
- [x] 2.3 【tester】安装闭环验证：/tmp 沙盒 claudecode 项目级/全局安装（hooks 文件 + settings 注入 + 备份）；幂等重装（条目不重复、第三方 hooks 共存）；卸载（注入清理 + 第三方保留 + hooks 文件删除）；codebuddy/opencode 安装卸载回归
- [x] 2.4 【coder-lite | docs_only】文档口径：README 双语 hooks 表述（Claude Code 已支持三事件通知）、CHANGELOG Unreleased 条目、`platforms.claudecode.note` 更新、`core/docs/architecture.md` hooks 注入说明（仅 CodeBuddy → CodeBuddy/Claude Code）
## 3. 端到端真实验证与测试

- [x] 3.1 【coder-standard | test_only】tests 扩展：hooks_inject 事件集参数化用例（默认清单不变/自定义清单注入/非法 JSON）、hook 引擎新事件用例（Notification message 直通、PermissionRequest 含字段全缺失兜底）、安装器 claudecode hooks 断言
- [x] 3.2 【tester】本机端到端（Claude Code CLI 2.1.304）：/tmp 项目安装注入 → 本地 HTTP 探针（custom 渠道）→ `claude -p` 派发子代理触发 SubagentStop → 探针收到 `[budget]` 消息实证；Notification 直通观察（噪音水平记录，供 Open Questions 决策）
- [x] 3.3 【tester】全量门禁终验：三命令退出码 0 + 构建幂等 + spec 场景核对

## 4. 归档

- [x] 4.1 【recorder | docs_only】CHANGELOG 版本落位（0.2.1 patch）+ 归档准备（`openspec validate` 通过）；Leader 执行归档
