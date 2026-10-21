#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy 通知发送 — 四渠道通用 webhook（markdown 投递）。

用法:
    python3 notify.py "<message>" [event]

配置读取（双级降级，不合并）:
    1. $BUDGET_NOTIFY_CONFIG（已设置且文件存在时优先）
    2. 项目级 .budget/notify.json（存在即生效）
    3. 全局 ~/.budgetbuddy/notify.json（项目级不存在时降级使用）
    皆无或 enabled 非 true → 静默跳过（exit 0）。

发送语义:
    每渠道 5 秒超时；按事件声明的渠道列表顺序发送，任一成功即停；
    全部失败静默（stderr 仅记录脱敏摘要），脚本始终 exit 0。

安全:
    webhook/secret 仅存储于 chmod 600 的配置文件；不经环境变量传递，
    不出现在命令行参数与日志输出（发送异常信息仅含 host）。
    webhook URL scheme 白名单：仅允许 https（localhost/127.0.0.1 主机
    放行 http 供本地调试），其余一律拒绝发送（防 secret 经明文通道外泄）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 5
PROJECT_CONFIG_PATH = '.budget/notify.json'
GLOBAL_CONFIG_SUBPATH = '.budgetbuddy/notify.json'
DEFAULT_TITLE = '[budget] 通知'
ALLOWED_SCHEMES = ('https',)
LOCAL_ALLOWED_SCHEMES = ('https', 'http')
LOCAL_HOSTS = ('localhost', '127.0.0.1', '::1')


def _log(message: str) -> None:
    """向 stderr 输出脱敏摘要（简单记录不算失败传播，不阻断调用方）。"""
    print(f'[budget-notify] {message}', file=sys.stderr)


def _safe_host(url: str) -> str:
    """提取 URL 的 host 用于错误信息（脱敏：不输出完整 webhook 与参数）。"""
    try:
        return urllib.parse.urlsplit(url).netloc or 'unknown-host'
    except ValueError:
        return 'unknown-host'


def validate_webhook_scheme(webhook: str) -> bool:
    """校验 webhook URL 的 scheme（白名单：https；本机回环放行 http）。

    - https → 放行
    - http 且 host ∈ {localhost, 127.0.0.1, ::1} → 放行（本地调试通道）
    - 其余（远程 http / 无 scheme / 其他 scheme）→ 拒绝
    """
    try:
        parts = urllib.parse.urlsplit(webhook)
    except ValueError:
        return False
    if parts.scheme in ALLOWED_SCHEMES:
        return True
    if parts.scheme in LOCAL_ALLOWED_SCHEMES:
        host = parts.hostname
        return isinstance(host, str) and host.lower() in LOCAL_HOSTS
    return False


def locate_config() -> str | None:
    """定位生效配置文件：$BUDGET_NOTIFY_CONFIG > 项目级 > 全局级（不合并）。"""
    env_path = os.environ.get('BUDGET_NOTIFY_CONFIG', '')
    if env_path and os.path.isfile(env_path):
        return env_path
    if os.path.isfile(PROJECT_CONFIG_PATH):
        return PROJECT_CONFIG_PATH
    global_path = os.path.join(os.path.expanduser('~'), GLOBAL_CONFIG_SUBPATH)
    if os.path.isfile(global_path):
        return global_path
    return None


def load_config() -> dict | None:
    """读取并解析生效配置；无配置或解析失败返回 None（静默跳过）。"""
    path = locate_config()
    if path is None:
        return None
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        _log(f'配置文件解析失败: {path}')
        return None
    if not isinstance(data, dict):
        _log('配置文件顶层必须是 JSON 对象（跳过通知）')
        return None
    return data


def dingtalk_sign(timestamp: str, secret: str) -> str:
    """钉钉加签：HMAC-SHA256(timestamp 与 secret 以换行符拼接) → base64 → urlencode。

    与钉钉官方机器人加签算法一致：以 secret 为 key、timestamp 与 secret
    以换行符拼接为消息计算 HMAC-SHA256，结果 base64 编码后 urlencode。
    """
    string_to_sign = f'{timestamp}\n{secret}'
    digest = hmac.new(
        secret.encode('utf-8'), string_to_sign.encode('utf-8'), digestmod=hashlib.sha256,
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest))


def build_dingtalk_url(webhook: str, secret: str, timestamp: str) -> str:
    """构造钉钉加签 URL：附加 timestamp 与 sign 参数（保留原有 query）。"""
    sign = dingtalk_sign(timestamp, secret)
    separator = '&' if '?' in webhook else '?'
    return f'{webhook}{separator}timestamp={timestamp}&sign={sign}'


def build_wecom_payload(message: str) -> dict:
    """企微机器人消息体：markdown 类型。"""
    return {'msgtype': 'markdown', 'markdown': {'content': message}}


def build_dingtalk_payload(message: str, title: str = DEFAULT_TITLE) -> dict:
    """钉钉机器人消息体：markdown 类型（title + text）。"""
    return {'msgtype': 'markdown', 'markdown': {'title': title, 'text': message}}


def build_feishu_payload(message: str, title: str = DEFAULT_TITLE) -> dict:
    """飞书机器人消息体：interactive 卡片（header + elements）。"""
    return {
        'msg_type': 'interactive',
        'card': {
            'header': {
                'title': {'tag': 'plain_text', 'content': title},
                'template': 'blue',
            },
            'elements': [
                {'tag': 'div', 'text': {'tag': 'lark_md', 'content': message}},
            ],
        },
    }


def _body_errcode_ok(data: object) -> bool:
    """企微/钉钉业务码判定：errcode == 0。"""
    return isinstance(data, dict) and data.get('errcode') == 0


def _body_feishu_ok(data: object) -> bool:
    """飞书业务码判定：code == 0 或 StatusCode == 0。"""
    if not isinstance(data, dict):
        return False
    return data.get('code') == 0 or data.get('StatusCode') == 0


def _response_status(response: object) -> int:
    """读取响应状态码（status 属性优先，getcode 回退）。"""
    status = getattr(response, 'status', None)
    if isinstance(status, int):
        return status
    getcode = getattr(response, 'getcode', None)
    return getcode() if callable(getcode) else 0


def _check_response_body(response: object, body_ok, host: str) -> bool:
    """读取并校验响应体业务码（渠道特定成功码判定）。"""
    try:
        data = json.loads(response.read().decode('utf-8'))
    except (OSError, ValueError):
        _log(f'响应体解析失败 @ {host}')
        return False
    if body_ok(data):
        return True
    _log(f'渠道业务码未通过 @ {host}')
    return False


def _send_request(request: urllib.request.Request, body_ok=None) -> bool:
    """发送请求：5s 超时；HTTP 2xx 且（无 body_ok 或 body_ok 通过）为成功。

    失败仅向 stderr 输出脱敏摘要（host + 状态码/异常类型名），
    不输出完整 webhook URL 与 secret。
    """
    host = _safe_host(request.full_url)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = _response_status(response)
            if not 200 <= status < 300:
                _log(f'HTTP {status} @ {host}')
                return False
            if body_ok is None:
                return True
            return _check_response_body(response, body_ok, host)
    except urllib.error.HTTPError as exc:
        _log(f'HTTP {exc.code} @ {host}')
        return False
    except Exception as exc:  # pylint: disable=broad-except
        # 网络错误/超时等：仅输出异常类型名（str 可能含 URL，脱敏不输出）。
        _log(f'发送失败 @ {host}: {type(exc).__name__}')
        return False


def _post_json(url: str, payload: dict, body_ok=None) -> bool:
    """POST JSON 消息体并按渠道业务码判定成功。"""
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    return _send_request(request, body_ok)


def _send_dingtalk(channel_cfg: dict, webhook: str, message: str) -> bool:
    """钉钉发送：markdown 消息 + HMAC-SHA256 加签（secret 存在时）。"""
    payload = build_dingtalk_payload(message)
    secret = channel_cfg.get('secret')
    if not isinstance(secret, str) or not secret:
        return _post_json(webhook, payload, _body_errcode_ok)
    timestamp = str(int(time.time() * 1000))
    url = build_dingtalk_url(webhook, secret, timestamp)
    return _post_json(url, payload, _body_errcode_ok)


def _send_custom(channel_cfg: dict, webhook: str, message: str) -> bool:
    """custom 渠道：format=raw 时原样 POST 消息体。"""
    if channel_cfg.get('format', 'raw') != 'raw':
        _log('custom 渠道仅支持 format=raw（跳过）')
        return False
    body = message.encode('utf-8')
    request = urllib.request.Request(
        webhook, data=body,
        headers={'Content-Type': 'text/plain; charset=utf-8'}, method='POST')
    return _send_request(request)


def send_channel(name: str, channel_cfg: object, message: str) -> bool:
    """按渠道类型格式化并发送；返回是否成功（渠道级，不抛异常）。"""
    if not isinstance(channel_cfg, dict):
        _log(f'渠道 {name} 配置非法（跳过）')
        return False
    channel_type = channel_cfg.get('type')
    webhook = channel_cfg.get('webhook')
    if not isinstance(webhook, str) or not webhook:
        _log(f'渠道 {name} 缺少 webhook（跳过）')
        return False
    if not validate_webhook_scheme(webhook):
        _log(f'渠道 {name} webhook scheme 不在白名单（https；http 仅限本机回环）（跳过）')
        return False
    if channel_type == 'wecom_bot':
        return _post_json(webhook, build_wecom_payload(message), _body_errcode_ok)
    if channel_type == 'dingtalk_bot':
        return _send_dingtalk(channel_cfg, webhook, message)
    if channel_type == 'feishu_bot':
        return _post_json(webhook, build_feishu_payload(message), _body_feishu_ok)
    if channel_type == 'custom':
        return _send_custom(channel_cfg, webhook, message)
    _log(f'渠道 {name} 类型未知: {channel_type}（跳过）')
    return False


def _resolve_channel_names(config: dict, event: str) -> list[str]:
    """解析发送渠道顺序：指定事件 → events[event].channels；缺省 → 全部渠道。"""
    if not event:
        channels_cfg = config.get('channels')
        if not isinstance(channels_cfg, dict):
            return []
        return list(channels_cfg.keys())
    events_cfg = config.get('events')
    if not isinstance(events_cfg, dict):
        return []
    event_cfg = events_cfg.get(event)
    if not isinstance(event_cfg, dict) or event_cfg.get('enabled') is not True:
        return []
    channel_names = event_cfg.get('channels')
    if not isinstance(channel_names, list):
        return []
    return channel_names


def notify(message: str, event: str = '') -> bool:
    """发送通知：定位配置 → 事件开关 → 按渠道顺序发送，任一成功即停。"""
    config = load_config()
    if config is None or config.get('enabled') is not True:
        return False
    channels_cfg = config.get('channels')
    if not isinstance(channels_cfg, dict):
        return False
    for name in _resolve_channel_names(config, event):
        if not isinstance(name, str):
            continue
        channel_cfg = channels_cfg.get(name)
        if channel_cfg is None:
            _log(f'事件引用的渠道 {name} 未在 channels 声明（跳过）')
            continue
        if send_channel(name, channel_cfg, message):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：消息为第一个位置参数，事件名可选；通知永不以非零退出。"""
    args = sys.argv[1:] if argv is None else argv
    message = args[0] if args else ''
    event = args[1] if len(args) > 1 else ''
    if not message:
        return 0
    try:
        notify(message, event)
    except Exception as exc:  # pylint: disable=broad-except
        # 兜底：任何内部错误仅记录异常类型名，不阻断调用方。
        _log(f'内部错误: {type(exc).__name__}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
