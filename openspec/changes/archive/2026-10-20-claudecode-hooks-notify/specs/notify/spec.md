# notify Delta

## MODIFIED Requirements

### Requirement: CodeBuddy hooks 三事件通知

跨平台 hooks 通知（原 CodeBuddy 三事件扩展）：`dist/{codebuddy,claudecode}/hooks/budget-notify-hook.py` 从 stdin 接收 hook JSON payload，按事件类型构建 markdown 消息并调用 notify 发送——codebuddy：Notification（permission_prompt/idle_prompt）/PreToolUse（Bash 沙箱越权）/SubagentStop；claudecode：Notification（message 直通）/PermissionRequest（权限确认卡点）/SubagentStop。引擎 payload 驱动、平台无关：无法识别的字段/事件静默跳过。hooks 由 lib/hooks*.sh 注入各平台 settings.json（`.codebuddy/` 或 `.claude/`，全局或项目级），注入事件集经 `HOOK_EVENTS_JSON` 环境变量数据驱动（引擎默认值 = codebuddy 现三事件，行为不变）；claudecode 不注入 superpowers 插件。注入前必须先备份 `settings.json.bak-budget`；注入幂等，条目级追加/移除（用户已有 hooks 保留），settings.json 写入采用临时文件 + 原子 rename（design.md §9）。【MUST】

#### Scenario: 非法输入静默

- **WHEN** hook 收到空 stdin 或非法 JSON
- **THEN** 进程静默退出（exit 0），不产生错误输出

#### Scenario: 注入前备份

- **WHEN** 执行 hooks 注入修改 settings.json
- **THEN** 注入前生成 `settings.json.bak-budget` 备份文件

#### Scenario: Claude Code Notification 直通

- **WHEN** hook 收到 `hook_event_name=Notification` 且 payload 无 `notification_type` 但有 `message`
- **THEN** 构建提醒通知（正文含 message 摘要）并发送

#### Scenario: PermissionRequest 卡点通知

- **WHEN** hook 收到 `hook_event_name=PermissionRequest`
- **THEN** 构建权限确认卡点通知（正文含 message 或工具摘要）并发送

#### Scenario: 用户 hooks 共存

- **WHEN** 目标 settings.json 已含第三方 hook 条目（同事件或不同事件）后注入与移除
- **THEN** 第三方条目原样保留，本套件条目按 `budget-notify-hook.py` 标记精确增删

#### Scenario: codebuddy 回归不变

- **WHEN** codebuddy 形态执行注入（不传 HOOK_EVENTS_JSON）
- **THEN** 注入事件集与改动前完全一致（Notification 两 matcher + PreToolUse Bash + SubagentStop）
