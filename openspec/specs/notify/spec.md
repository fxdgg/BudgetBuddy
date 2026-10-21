# notify Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
### Requirement: notify.json 配置与双级降级读取

通知配置文件 schema（design.md §9）：顶层 `enabled: bool`；`channels` 为命名渠道 map，每渠道含 `type`（`wecom_bot` / `dingtalk_bot` / `feishu_bot` / `custom`）、`webhook`、可选 `secret`、custom 渠道可选 `format: raw`；`events` 为 N1..N11 事件开关，各 `{enabled: bool, channels: [渠道名]}`。读取为**双级降级（不合并）**：项目 `.budget/notify.json` 存在即生效，否则降级用全局 `~/.budgetbuddy/notify.json`；两者皆无或 `enabled: false` 时跳过全部通知。配置文件由生成方（setup init 模板 / notify.py 首次写入）默认 `chmod 600`。【MUST】

#### Scenario: 项目级覆盖全局
- **WHEN** `.budget/notify.json` 与 `~/.budgetbuddy/notify.json` 同时存在
- **THEN** 仅项目级生效，全局配置不被读取合并

#### Scenario: 未配置时静默跳过
- **WHEN** 两级 notify.json 均不存在
- **THEN** 通知调用为 no-op，主流程不受影响

### Requirement: 四渠道格式化与发送语义

notify.py 按渠道类型构造消息体并经 `urllib` 发送（design.md §9）：wecom_bot 发 markdown 消息；dingtalk_bot 发 markdown 并以 `timestamp + "\n" + secret` 计算 HMAC-SHA256 签名（base64 + urlencode 附加到 webhook URL）；feishu_bot 发 interactive 卡片；custom 渠道按 `format: raw` 原样 POST。发送超时 5 秒；按 events 声明的渠道列表顺序发送，任一成功（exit 0）即停止；全部失败静默处理、脚本仍 exit 0。webhook/secret 仅存在于 chmod 600 的配置文件，不经环境变量传递，不出现在命令行参数与日志输出中。【MUST】

#### Scenario: 钉钉加签
- **WHEN** 以固定 timestamp/secret/内容调用钉钉格式化与 URL 构造
- **THEN** 生成的签名与官方算法一致（单测固定向量校验，mock 发送不外呼）

#### Scenario: 多渠道顺序与短路
- **WHEN** events.Nx.channels = ["wecom", "dingtalk"] 且 wecom 发送成功
- **THEN** 不再尝试 dingtalk，notify.py exit 0

#### Scenario: 全渠道失败
- **WHEN** 所有配置渠道发送均失败（网络错误/非 2xx）
- **THEN** notify.py 静默 exit 0，不向 stderr 抛出堆栈、不阻断调用方

### Requirement: load-env.sh 环境导出

`core/skills/budget-notify/load-env.sh` 定位生效配置文件（项目级 > 全局级降级，不合并），仅导出**非敏感**环境变量：`BUDGET_NOTIFY_ENABLED`（生效配置的 enabled 值，"1"/"0"；无配置时 "0"）与 `BUDGET_NOTIFY_CONFIG`（生效配置文件绝对路径）；供 Leader 在通知节点 `eval` 加载后快速短路与传递定位结果；无配置时仅导出 `BUDGET_NOTIFY_ENABLED=0` 且 exit 0。notify.py 读取优先级：`$BUDGET_NOTIFY_CONFIG`（已设置时）> 自行按同一降级规则定位；enabled 最终判定以文件内容为准。敏感字段（webhook/secret）不经环境变量传递（design.md §9）。【MUST】

#### Scenario: eval 加载
- **WHEN** `eval $(bash load-env.sh)` 在已配置环境执行
- **THEN** 后续 shell 中 `$BUDGET_NOTIFY_ENABLED` 为 1、`$BUDGET_NOTIFY_CONFIG` 指向生效配置文件

#### Scenario: 无配置短路
- **WHEN** 两级 notify.json 均不存在时 eval 加载
- **THEN** 仅导出 `BUDGET_NOTIFY_ENABLED=0`，exit 0，Leader 可据此跳过通知调用

#### Scenario: 敏感字段不经环境变量
- **WHEN** 审计 load-env.sh 的导出语句
- **THEN** 不存在 webhook/secret/token 类敏感值的 export 语句

### Requirement: 通知点 N1-N11 嵌入工作流

budget-workflow 文档（SKILL/router/phases/goal）保留参照项目全部 11 个通知节点（design.md §9 节点定义表：N1 Phase 2 第3次驳回、N2 3轮审查全败、N3 循环超5轮、N4 自动恢复耗尽、N5 reviewer 误判介入、N6 Director 介入、N7 Phase 2 通过、N8 Phase 3 完成、N9 需用户拍板、N10 全流程完成、N11 Goal 达成），消息前缀统一 `[budget]`，markdown 模板含项目名与详情字段；参照项目 voice 形式统一降级为 webhook markdown 投递（消息内容不变）；各节点调用形如 `budget notify "<msg>" || true`（design.md §9）。【MUST】

#### Scenario: 通知点齐全
- **WHEN** 审计 budget-workflow 全部文档
- **THEN** N1-N11 每个节点均有对应调用示例与消息模板，前缀为 [budget]

#### Scenario: Goal 达成通知
- **WHEN** goal loop 判定目标达成并归档
- **THEN** N11 通知发出（消息含迭代轮数与归档信息）

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

