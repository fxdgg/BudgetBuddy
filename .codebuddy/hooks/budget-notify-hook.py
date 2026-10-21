#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy Hook 通知引擎 — stdin JSON → markdown 消息 → notify.py。

由 lib/hooks.sh 注入各平台 settings.json（codebuddy：Notification /
PreToolUse / SubagentStop；claudecode：Notification（message 直通）/
PermissionRequest / SubagentStop；注入前备份 settings.json.bak-budget，
写入采用临时文件 + 原子 rename）。引擎 payload 驱动、平台无关（design.md
D1）：无法识别的字段/事件静默跳过。空/非法 JSON 静默退出；通知失败不
阻塞 hook。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

SUBPROCESS_TIMEOUT_SECONDS = 15  # notify.py 内部每渠道 5s 超时的总防护。


def _read_payload() -> dict | None:
    """安全读取 stdin JSON；空/非法/非对象输入返回 None（静默）。"""
    try:
        text = sys.stdin.read()
        if not text.strip():
            return None
        payload = json.loads(text)
    except (ValueError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _wrap_message(title: str, body: str) -> str:
    """组装最终消息：[budget] 前缀 + 标题 + 正文。"""
    return f'[budget] ### {title}\n\n{body}'


def _build_notification_message(payload: dict, project: str) -> str | None:
    """Notification 事件：权限确认卡点、空闲等待与会话提醒（message 直通）。

    payload 驱动兼容（design.md D1）：notification_type 存在 → codebuddy
    两分支；缺失但 message 非空 → Claude Code 会话提醒直通（权限等待/
    空闲提醒均以 message 直载，平台中性文案）；两者皆无 → None。
    """
    notification_type = payload.get('notification_type', '')
    if notification_type == 'permission_prompt':
        title = '🤖 流程卡点，需要您确认'
        detail = str(payload.get('message', ''))
        body = (
            f'> **项目**：`{project}`\n'
            f'> **详情**：{detail}\n\n'
            '请在当前会话中确认操作'
        )
    elif notification_type == 'idle_prompt':
        title = '⏳ 等待您的输入'
        body = f'> **项目**：`{project}`\n\n已空闲超过 60 秒，请回到对话继续'
    elif not notification_type and str(payload.get('message', '')):
        title = '🤖 会话提醒'
        detail = str(payload.get('message', ''))[:200]
        body = (
            f'> **项目**：`{project}`\n'
            f'> **详情**：{detail}\n\n'
            '请回到当前会话查看'
        )
    else:
        return None
    return _wrap_message(title, body)


def _build_permissionrequest_message(payload: dict, project: str) -> str:
    """PermissionRequest 事件：权限确认卡点通知（Claude Code 形态）。

    正文优先 message、次 tool_name/tool_input 摘要；字段全缺失时输出
    通用卡点文案而非返回 None（卡点漏通知违背通知初衷，design.md D1）。
    """
    title = '🤖 流程卡点，需要您确认'
    message = str(payload.get('message', '') or '')
    tool_name = str(payload.get('tool_name', '') or '')
    tool_input = payload.get('tool_input')
    if message:
        detail = message[:200]
    elif tool_name:
        detail = f'工具 `{tool_name}` 请求确认'
        if isinstance(tool_input, dict):
            command = str(tool_input.get('command', '') or '')[:200]
            if command:
                detail = f'工具 `{tool_name}`：`{command}`'
    else:
        detail = '收到权限确认请求'
    body = (
        f'> **项目**：`{project}`\n'
        f'> **详情**：{detail}\n\n'
        '请在当前会话中确认操作'
    )
    return _wrap_message(title, body)


def _build_pretooluse_message(payload: dict, project: str) -> str | None:
    """PreToolUse 事件：仅通知沙箱越权命令（真正的高危卡点）。"""
    if payload.get('tool_name') != 'Bash':
        return None
    tool_input = payload.get('tool_input')
    if not isinstance(tool_input, dict) or tool_input.get('dangerouslyDisableSandbox') is not True:
        return None
    command = str(tool_input.get('command') or '')[:200]
    title = '⚠️ 沙箱越权命令，需要您确认'
    body = (
        f'> **项目**：`{project}`\n'
        f'> **命令**：`{command}`\n\n'
        '此命令将在沙箱外执行，请在当前会话中确认操作'
    )
    return _wrap_message(title, body)


def _build_subagentstop_message(payload: dict, project: str) -> str | None:
    """SubagentStop 事件：子代理完成通知（stop_hook_active 时跳过防循环）。"""
    if payload.get('stop_hook_active') is True:
        return None
    title = '✅ 子代理任务完成'
    body = f'> **项目**：`{project}`\n\n子代理已结束，可回主会话查看结果'
    return _wrap_message(title, body)


def build_message(payload: dict) -> str | None:
    """按事件类型构建 [budget] 前缀 markdown 消息；无匹配事件返回 None。"""
    event = payload.get('hook_event_name', '')
    cwd = payload.get('cwd', '')
    project = os.path.basename(cwd) if isinstance(cwd, str) and cwd else 'unknown'
    if event == 'Notification':
        return _build_notification_message(payload, project)
    if event == 'PermissionRequest':
        return _build_permissionrequest_message(payload, project)
    if event == 'PreToolUse':
        return _build_pretooluse_message(payload, project)
    if event == 'SubagentStop':
        return _build_subagentstop_message(payload, project)
    return None


def locate_notify_py() -> str:
    """定位 notify.py：hooks 同级的 skills/budget-notify/notify.py。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(
        os.path.join(script_dir, os.pardir, 'skills', 'budget-notify', 'notify.py'))


def resolve_python() -> str:
    """解析 python 命令（Windows 下 python3 不可用时回退 python）。"""
    if sys.platform != 'win32':
        return 'python3'
    try:
        subprocess.check_output(
            ['python3', '--version'], stderr=subprocess.DEVNULL, timeout=3)
        return 'python3'
    except Exception:  # pylint: disable=broad-except
        return 'python'


def send_notification(message: str, cwd: str = '') -> None:
    """调用 notify.py 发送；任何失败静默（通知永不阻塞 hook）。"""
    notify_py = locate_notify_py()
    if not os.path.isfile(notify_py):
        return
    try:
        subprocess.run(
            [resolve_python(), notify_py, message],
            cwd=cwd or None,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:  # pylint: disable=broad-except
        pass  # 通知失败不阻塞 Hook。


def main() -> None:
    """入口：读 payload → 构建消息 → 发送；全程静默兜底。"""
    payload = _read_payload()
    if payload is None:
        return
    message = build_message(payload)
    if message is None:
        return
    cwd = payload.get('cwd')
    send_notification(message, cwd if isinstance(cwd, str) else '')


if __name__ == '__main__':
    main()
