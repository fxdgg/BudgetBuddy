---
name: budget-notify
description: 通知调度。Leader 在关键节点通过 budget notify 发送四渠道 webhook-markdown 通知。
---

# BudgetBuddy 通知调度

## 概述

此 Skill 为 budget-workflow 提供通用 webhook 通知能力，支持四渠道：
企业微信机器人（wecom_bot）、钉钉机器人（dingtalk_bot）、飞书机器人
（feishu_bot）与自定义 webhook（custom）。消息统一 markdown 投递；
发送失败静默处理，永不阻断主流程。

## 调用方式

Leader 通过 `budget notify` 命令发送通知（自动按双级降级读取 notify.json）：

```bash
budget notify "<message>"            # 向全部已配置渠道发送
budget notify "<message>" N1         # 按事件 N1 声明的渠道列表发送
```

直接调用 notify.py（不经 budget CLI）：

```bash
python3 skills/budget-notify/notify.py "<message>" [event]
```

消息含换行时直接使用实际换行符传入。各通知节点调用形如
`budget notify "<msg>" || true`（通知失败不影响主流程）。

## 配置（notify.json）

读取优先级（双级降级，不合并）：

1. `.budget/notify.json` — 项目级（存在即生效，覆盖全局）
2. `~/.budgetbuddy/notify.json` — 全局（项目级不存在时降级使用）
3. 两者皆无或 `enabled: false` → 跳过全部通知（静默）

结构示例：

```json
{
  "enabled": true,
  "channels": {
    "wecom": {"type": "wecom_bot", "webhook": "https://qyapi.example.com/..."},
    "dingtalk": {"type": "dingtalk_bot", "webhook": "https://oapi.example.com/...", "secret": "SEC..."},
    "feishu": {"type": "feishu_bot", "webhook": "https://open.example.com/..."},
    "custom": {"type": "custom", "webhook": "https://hooks.example.com/...", "format": "raw"}
  },
  "events": {
    "N1": {"enabled": true, "channels": ["wecom", "dingtalk"]}
  }
}
```

配置文件由生成方（setup init 模板）默认 `chmod 600`，仅 owner 可读。

## 渠道格式

| 渠道 | type | 消息体 | 加签 |
|------|------|--------|------|
| 企业微信机器人 | `wecom_bot` | markdown（msgtype: markdown） | 无 |
| 钉钉机器人 | `dingtalk_bot` | markdown | HMAC-SHA256：timestamp 与 secret 以换行符拼接计算，base64 后 urlencode，附加为 URL 参数 `timestamp` 与 `sign` |
| 飞书机器人 | `feishu_bot` | interactive 卡片（msg_type: interactive，title + elements） | 无 |
| 自定义 | `custom` | `format: "raw"` 原样 POST 消息体 | 无 |

## 发送语义

- 每渠道 5 秒超时（urllib）
- 按事件声明的渠道列表顺序逐渠道发送，任一成功（HTTP 2xx 且渠道业务码通过）即停止
- 全部失败静默处理：stderr 仅记录脱敏摘要（host），脚本 exit 0

## 通知点 N1-N11 概览

| 节点 | 触发条件 | 消息模板要点 |
|------|---------|-------------|
| N1 | Phase 2 设计评审第 3 次驳回 | ⚠️ 第 3 次驳回，需用户裁决 |
| N2 | 3 轮审查全败 | ⚠️ 3 轮审查未通过 |
| N3 | 任务循环超 5 轮 | ⚠️ 循环超 5 轮，已触发暂停 |
| N4 | 自动恢复策略耗尽 | ⚠️ 所有自动恢复策略已耗尽 |
| N5 | reviewer 疑似误判 | ⚠️ reviewer 疑似误判，Leader 已介入 |
| N6 | Director 介入 | 🎯 Director 介入 + 裁决结论 |
| N7 | Phase 2 评审通过 | ✅ 设计评审通过，进入开发阶段 |
| N8 | Phase 3 代码开发完成 | ✅ {total} 个任务全部通过 |
| N9 | 需用户拍板 | ⚠️ {count} 个问题需您拍板 |
| N10 | 全流程完成（归档） | ✅ {done}/{total} 任务通过，已归档 |
| N11 | Goal Loop 达成并归档 | 🎯 经过 {N} 轮迭代，目标已达成 |

消息前缀统一 `[budget]`，模板含项目名与详情字段。

## 环境加载（load-env.sh）

Leader 在通知节点可先加载非敏感环境变量用于短路判断与定位传递：

```bash
eval "$(bash skills/budget-notify/load-env.sh)"
```

- `$BUDGET_NOTIFY_ENABLED`：`1` = 已启用；`0` = 无配置或未启用（可跳过通知调用）
- `$BUDGET_NOTIFY_CONFIG`：生效配置文件绝对路径（可传给后续子进程；
  notify.py 读取时该变量优先于自行降级定位）

敏感字段（webhook/secret）不经环境变量传递。

## CodeBuddy hooks

`hooks/budget-notify-hook.py` 由 lib/hooks.sh 注入 CodeBuddy settings.json
（Notification / PreToolUse / SubagentStop 三事件；注入前备份
`settings.json.bak-budget`；写入采用临时文件 + 原子 rename）。
hook 从 stdin 接收 JSON payload，构建 `[budget]` 前缀 markdown 消息后
调用 notify.py 发送；空/非法 JSON 静默退出。

## 安全

- webhook/secret 仅存储于 chmod 600 的 notify.json（`.budget/` 已加入 .gitignore）
- 不经环境变量传递、不出现在命令行参数与日志输出
- 发送异常信息仅含 host（脱敏），不含完整 webhook 与 secret
- 消息内容由 Leader 预构造固定模板，不含用户输入
