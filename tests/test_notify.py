#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""budget-notify 单测：四渠道格式化与签名、双级配置、load-env、事件开关、hook。

全部网络发送均 mock（patch urllib.request.urlopen / subprocess.run），不外呼。
钉钉签名固定向量按官方算法（HMAC-SHA256 + base64 + urlencode）预计算。
"""

import base64
import hashlib
import hmac
import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTIFY_PY = REPO_ROOT / 'core' / 'skills' / 'budget-notify' / 'notify.py'
LOAD_ENV_SH = REPO_ROOT / 'core' / 'skills' / 'budget-notify' / 'load-env.sh'
HOOK_PY = REPO_ROOT / 'core' / 'hooks' / 'budget-notify-hook.py'

# 钉钉签名固定向量（timestamp/secret → 期望 sign，按官方算法预计算）。
DINGTALK_TS = '1600000000000'
DINGTALK_SECRET = 'SEC1234567890abcdef'
DINGTALK_EXPECTED_SIGN = 'JE4Qwn5uW8ezwMf3yMAJj3Yuw3a1YkV4RfPVBN6DuXc%3D'

# 敏感样本值（仅用于脱敏断言，不出现在任何被测输出中）。
SAMPLE_WEBHOOK = 'https://oapi.example.com/robot/send?access_token=token-abc123'
SAMPLE_SECRET = 'SEC-secret-value-xyz'


def load_module(path: Path, name: str):
    """按文件路径加载模块（core 下非包结构，模块级代码无副作用）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


notify_module = load_module(NOTIFY_PY, 'budget_notify_under_test')
hook_module = load_module(HOOK_PY, 'budget_notify_hook_under_test')


class FakeResponse:
    """urlopen mock 返回的假响应（支持 with 上下文）。"""

    def __init__(self, status: int = 200, body: bytes = b'{"errcode": 0}'):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def make_config(channels=None, events=None, enabled=True) -> dict:
    """构造 notify.json 配置对象。"""
    return {
        'enabled': enabled,
        'channels': channels if channels is not None else {},
        'events': events if events is not None else {},
    }


def make_channel(channel_type: str = 'wecom_bot', webhook: str = SAMPLE_WEBHOOK, **extra) -> dict:
    """构造渠道配置对象。"""
    channel = {'type': channel_type, 'webhook': webhook}
    channel.update(extra)
    return channel


class NotifyIsolatedEnvTests(unittest.TestCase):
    """隔离 HOME/CWD 的 notify 行为测试基类（双级配置定位依赖两者）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # resolve() 统一 macOS /var → /private/var 符号链接形态，保证路径断言一致。
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.project = self.root / 'project'
        self.home.mkdir()
        self.project.mkdir()
        env_patch = mock.patch.dict(os.environ, {'HOME': str(self.home)})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        old_cwd = os.getcwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, old_cwd)

    def write_project_config(self, config: dict) -> Path:
        target = self.project / '.budget' / 'notify.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(config), encoding='utf-8')
        return target

    def write_global_config(self, config: dict) -> Path:
        target = self.home / '.budgetbuddy' / 'notify.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(config), encoding='utf-8')
        return target


class DingTalkSignTests(unittest.TestCase):
    """钉钉 HMAC-SHA256 签名固定向量（specs/notify「钉钉加签」Scenario）。"""

    def test_fixed_vector_matches_official_algorithm(self):
        """固定 timestamp/secret → sign 与官方算法预计算值一致。"""
        sign = notify_module.dingtalk_sign(DINGTALK_TS, DINGTALK_SECRET)
        self.assertEqual(sign, DINGTALK_EXPECTED_SIGN)

    def test_sign_recomputed_independently(self):
        """独立重算校验（HMAC-SHA256 → base64 → quote_plus）与实现一致。"""
        string_to_sign = (DINGTALK_TS + '\n' + DINGTALK_SECRET).encode('utf-8')
        digest = hmac.new(
            DINGTALK_SECRET.encode('utf-8'), string_to_sign, digestmod=hashlib.sha256,
        ).digest()
        expected = urllib.parse.quote_plus(base64.b64encode(digest))
        self.assertEqual(
            notify_module.dingtalk_sign(DINGTALK_TS, DINGTALK_SECRET), expected)

    def test_sign_output_is_urlencoded_base64(self):
        """输出形态：urlencode 后的 base64（解码回 32 字节 HMAC 摘要）。"""
        sign = notify_module.dingtalk_sign(DINGTALK_TS, DINGTALK_SECRET)
        raw = base64.b64decode(urllib.parse.unquote_plus(sign))
        self.assertEqual(len(raw), 32)


class PayloadBuildTests(unittest.TestCase):
    """四渠道消息体构造断言（specs/notify「四渠道格式化」）。"""

    def test_wecom_payload_structure(self):
        payload = notify_module.build_wecom_payload('hello\nworld')
        self.assertEqual(payload['msgtype'], 'markdown')
        self.assertEqual(payload['markdown']['content'], 'hello\nworld')

    def test_dingtalk_payload_structure(self):
        payload = notify_module.build_dingtalk_payload('line1\nline2')
        self.assertEqual(payload['msgtype'], 'markdown')
        self.assertEqual(payload['markdown']['text'], 'line1\nline2')
        self.assertIn('[budget]', payload['markdown']['title'])

    def test_feishu_payload_structure(self):
        payload = notify_module.build_feishu_payload('line1\nline2')
        self.assertEqual(payload['msg_type'], 'interactive')
        card = payload['card']
        self.assertEqual(card['header']['title']['tag'], 'plain_text')
        self.assertIn('[budget]', card['header']['title']['content'])
        element = card['elements'][0]
        self.assertEqual(element['tag'], 'div')
        self.assertEqual(element['text']['tag'], 'lark_md')
        self.assertEqual(element['text']['content'], 'line1\nline2')

    def test_dingtalk_url_appends_params_with_existing_query(self):
        """webhook 已含 query → 以 & 附加 timestamp 与 sign。"""
        url = notify_module.build_dingtalk_url(SAMPLE_WEBHOOK, DINGTALK_SECRET, DINGTALK_TS)
        self.assertTrue(url.startswith(SAMPLE_WEBHOOK + '&'))
        self.assertIn(f'timestamp={DINGTALK_TS}', url)
        self.assertIn(f'sign={DINGTALK_EXPECTED_SIGN}', url)

    def test_dingtalk_url_appends_params_without_query(self):
        """webhook 无 query → 以 ? 附加 timestamp 与 sign。"""
        bare_webhook = 'https://oapi.example.com/robot/send'
        url = notify_module.build_dingtalk_url(bare_webhook, DINGTALK_SECRET, DINGTALK_TS)
        self.assertTrue(url.startswith(bare_webhook + '?'))
        self.assertIn(f'timestamp={DINGTALK_TS}', url)
        self.assertIn(f'sign={DINGTALK_EXPECTED_SIGN}', url)


class ConfigPriorityTests(NotifyIsolatedEnvTests):
    """双级降级读取（不合并）与无配置静默（specs/notify 第一 Requirement）。"""

    def test_project_config_overrides_global_no_merge(self):
        """项目级存在即生效：全局配置不被读取合并（项目级无渠道 → 不发送）。"""
        self.write_global_config(make_config(channels={'g': make_channel()}))
        self.write_project_config(make_config(channels={}))
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            result = notify_module.notify('msg')
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_fallback_to_global_config(self):
        """项目级不存在 → 降级用全局配置发送。"""
        self.write_global_config(make_config(channels={'g': make_channel()}))
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = FakeResponse(200, b'{"errcode": 0}')
            result = notify_module.notify('msg')
        self.assertTrue(result)
        self.assertEqual(mock_urlopen.call_args[0][0].full_url, SAMPLE_WEBHOOK)

    def test_env_var_config_takes_priority(self):
        """$BUDGET_NOTIFY_CONFIG 已设置且文件存在 → 优先于降级定位。"""
        self.write_global_config(make_config(
            channels={'g': make_channel('wecom_bot', 'https://global.example.com/hook')}))
        env_config = self.root / 'env-notify.json'
        env_config.write_text(
            json.dumps(make_config(channels={'c': make_channel()})), encoding='utf-8')
        with mock.patch.dict(os.environ, {'BUDGET_NOTIFY_CONFIG': str(env_config)}):
            with mock.patch('urllib.request.urlopen') as mock_urlopen:
                mock_urlopen.return_value = FakeResponse(200, b'{"errcode": 0}')
                result = notify_module.notify('msg')
        self.assertTrue(result)
        self.assertEqual(mock_urlopen.call_args[0][0].full_url, SAMPLE_WEBHOOK)

    def test_no_config_skips_sending(self):
        """两级 notify.json 均不存在 → no-op，不发起任何请求。"""
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            result = notify_module.notify('msg')
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_disabled_config_skips_sending(self):
        """enabled: false → 跳过全部通知。"""
        self.write_project_config(
            make_config(channels={'wecom': make_channel()}, enabled=False))
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            result = notify_module.notify('msg')
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_invalid_json_config_skips_sending(self):
        """配置文件非法 JSON → 静默跳过（stderr 记录、无堆栈）。"""
        target = self.project / '.budget' / 'notify.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{not valid json', encoding='utf-8')
        stderr = io.StringIO()
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            with mock.patch('sys.stderr', stderr):
                result = notify_module.notify('msg')
        self.assertFalse(result)
        mock_urlopen.assert_not_called()
        self.assertNotIn('Traceback', stderr.getvalue())


class EventSwitchTests(NotifyIsolatedEnvTests):
    """事件开关与渠道列表语义（specs/notify events 配置）。"""

    def test_event_disabled_not_sent(self):
        """events.Nx.enabled=false → 不发送。"""
        config = make_config(
            channels={'wecom': make_channel()},
            events={'N1': {'enabled': False, 'channels': ['wecom']}},
        )
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            result = notify_module.notify('msg', 'N1')
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_event_enabled_sends_to_declared_channels(self):
        """events.Nx.enabled=true → 仅向声明的渠道列表发送。"""
        config = make_config(
            channels={
                'wecom': make_channel(),
                'dingtalk': make_channel('dingtalk_bot', secret=SAMPLE_SECRET),
            },
            events={'N1': {'enabled': True, 'channels': ['dingtalk']}},
        )
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = FakeResponse(200, b'{"errcode": 0}')
            result = notify_module.notify('msg', 'N1')
        self.assertTrue(result)
        mock_urlopen.assert_called_once()
        url = mock_urlopen.call_args[0][0].full_url
        self.assertIn('timestamp=', url)
        self.assertIn('sign=', url)

    def test_undeclared_event_not_sent(self):
        """events 中未声明的事件 → 不发送。"""
        config = make_config(
            channels={'wecom': make_channel()},
            events={'N1': {'enabled': True, 'channels': ['wecom']}},
        )
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            result = notify_module.notify('msg', 'N2')
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_no_event_sends_all_channels_in_order(self):
        """未指定事件 → 按 channels 声明顺序向全部渠道发送（任一成功即停）。"""
        config = make_config(channels={
            'wecom': make_channel(),
            'dingtalk': make_channel('dingtalk_bot', secret=SAMPLE_SECRET),
        })
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = [
                FakeResponse(200, b'{"errcode": 1}'),
                FakeResponse(200, b'{"errcode": 0}'),
            ]
            result = notify_module.notify('msg')
        self.assertTrue(result)
        self.assertEqual(mock_urlopen.call_count, 2)
        first_url = mock_urlopen.call_args_list[0][0][0].full_url
        self.assertEqual(first_url, SAMPLE_WEBHOOK)


class SendSemanticsTests(NotifyIsolatedEnvTests):
    """发送语义：5s 超时、任一成功即停、全失败静默 exit 0。"""

    def test_first_success_stops_remaining_channels(self):
        """第一渠道成功 → 后续渠道不再调用（短路）。"""
        config = make_config(
            channels={
                'wecom': make_channel(),
                'dingtalk': make_channel('dingtalk_bot', secret=SAMPLE_SECRET),
            },
            events={'N1': {'enabled': True, 'channels': ['wecom', 'dingtalk']}},
        )
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = FakeResponse(200, b'{"errcode": 0}')
            result = notify_module.notify('msg', 'N1')
        self.assertTrue(result)
        mock_urlopen.assert_called_once()

    def test_all_channels_fail_exit_zero_without_traceback(self):
        """全部渠道失败（网络错误）→ main 返回 0，stderr 无堆栈。"""
        config = make_config(
            channels={'wecom': make_channel()},
            events={'N1': {'enabled': True, 'channels': ['wecom']}},
        )
        self.write_project_config(config)
        stderr = io.StringIO()
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError('timed out')
            with mock.patch('sys.stderr', stderr):
                exit_code = notify_module.main(['msg', 'N1'])
        self.assertEqual(exit_code, 0)
        self.assertNotIn('Traceback', stderr.getvalue())

    def test_timeout_is_five_seconds(self):
        """urlopen 调用带 5 秒超时。"""
        self.write_project_config(make_config(channels={'wecom': make_channel()}))
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = FakeResponse(200, b'{"errcode": 0}')
            notify_module.notify('msg')
        self.assertEqual(mock_urlopen.call_args.kwargs['timeout'], 5)

    def test_channel_business_code_failure_continues(self):
        """渠道业务码未通过（errcode!=0）→ 继续尝试下一渠道。"""
        config = make_config(
            channels={
                'wecom': make_channel(),
                'feishu': make_channel('feishu_bot'),
            },
            events={'N1': {'enabled': True, 'channels': ['wecom', 'feishu']}},
        )
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = [
                FakeResponse(200, b'{"errcode": 1}'),
                FakeResponse(200, b'{"code": 0}'),
            ]
            result = notify_module.notify('msg', 'N1')
        self.assertTrue(result)
        self.assertEqual(mock_urlopen.call_count, 2)

    def test_custom_raw_posts_message_body(self):
        """custom 渠道 format=raw：原样 POST 消息体。"""
        config = make_config(
            channels={'custom': make_channel('custom', format='raw')},
            events={'N1': {'enabled': True, 'channels': ['custom']}},
        )
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = FakeResponse(200, b'ok')
            result = notify_module.notify('raw body\nline2', 'N1')
        self.assertTrue(result)
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.data, 'raw body\nline2'.encode('utf-8'))
        self.assertEqual(request.full_url, SAMPLE_WEBHOOK)

    def test_custom_unsupported_format_skipped(self):
        """custom 渠道 format 非 raw → 该渠道跳过（不发送）。"""
        config = make_config(
            channels={'custom': make_channel('custom', format='xml')},
            events={'N1': {'enabled': True, 'channels': ['custom']}},
        )
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            result = notify_module.notify('msg', 'N1')
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_unknown_channel_type_skipped(self):
        """未知渠道类型 → 跳过该渠道。"""
        config = make_config(
            channels={'mystery': make_channel('sms_bot')},
            events={'N1': {'enabled': True, 'channels': ['mystery']}},
        )
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            result = notify_module.notify('msg', 'N1')
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_event_channel_not_declared_skipped(self):
        """事件引用的渠道未在 channels 声明 → 跳过并继续。"""
        config = make_config(
            channels={'wecom': make_channel()},
            events={'N1': {'enabled': True, 'channels': ['ghost', 'wecom']}},
        )
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = FakeResponse(200, b'{"errcode": 0}')
            result = notify_module.notify('msg', 'N1')
        self.assertTrue(result)
        self.assertEqual(mock_urlopen.call_count, 1)


class SecretMaskingTests(NotifyIsolatedEnvTests):
    """secret/webhook 脱敏：错误输出仅含 host（specs/notify 安全条款）。"""

    def test_http_error_output_masks_webhook_and_secret(self):
        """HTTP 错误：输出含 host、不含完整 webhook 与 secret。"""
        dingtalk_webhook = 'https://oapi.example.com/robot/send?access_token=token-xyz789'
        config = make_config(channels={
            'dingtalk': make_channel('dingtalk_bot', webhook=dingtalk_webhook, secret=SAMPLE_SECRET),
        })
        self.write_project_config(config)
        stderr = io.StringIO()
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError('timed out')
            with mock.patch('sys.stderr', stderr):
                result = notify_module.notify('msg')
        self.assertFalse(result)
        output = stderr.getvalue()
        self.assertIn('oapi.example.com', output)
        self.assertNotIn('token-xyz789', output)
        self.assertNotIn(SAMPLE_SECRET, output)
        self.assertNotIn(dingtalk_webhook, output)

    def test_network_error_output_masks_webhook(self):
        """网络错误：输出不含 webhook 敏感部分。"""
        self.write_project_config(make_config(channels={'wecom': make_channel()}))
        stderr = io.StringIO()
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = TimeoutError('timed out')
            with mock.patch('sys.stderr', stderr):
                result = notify_module.notify('msg')
        self.assertFalse(result)
        output = stderr.getvalue()
        self.assertNotIn('token-abc123', output)
        self.assertNotIn(SAMPLE_WEBHOOK, output)


class WebhookSchemeWhitelistTests(unittest.TestCase):
    """webhook scheme 白名单纯函数断言（https / 本机 http 放行，其余拒绝）。"""

    def test_https_allowed(self):
        self.assertTrue(notify_module.validate_webhook_scheme(
            'https://oapi.example.com/robot/send?access_token=token-abc123'))

    def test_remote_http_rejected(self):
        self.assertFalse(notify_module.validate_webhook_scheme(
            'http://oapi.example.com/robot/send'))

    def test_localhost_http_allowed(self):
        self.assertTrue(notify_module.validate_webhook_scheme(
            'http://localhost:8080/hook'))

    def test_loopback_ip_http_allowed(self):
        self.assertTrue(notify_module.validate_webhook_scheme(
            'http://127.0.0.1:9000/hook'))

    def test_ipv6_loopback_http_allowed(self):
        self.assertTrue(notify_module.validate_webhook_scheme(
            'http://[::1]:8080/hook'))

    def test_no_scheme_rejected(self):
        self.assertFalse(notify_module.validate_webhook_scheme(
            'oapi.example.com/robot/send'))

    def test_other_scheme_rejected(self):
        self.assertFalse(notify_module.validate_webhook_scheme(
            'ftp://example.com/hook'))

    def test_empty_string_rejected(self):
        self.assertFalse(notify_module.validate_webhook_scheme(''))


class WebhookSchemeSendTests(NotifyIsolatedEnvTests):
    """scheme 校验与发送链路集成（specs/notify「四渠道格式化与发送语义」）。"""

    def _config_with_webhook(self, webhook: str) -> None:
        config = make_config(
            channels={'wecom': make_channel('wecom_bot', webhook)},
            events={'N1': {'enabled': True, 'channels': ['wecom']}},
        )
        self.write_project_config(config)

    def test_https_webhook_sends(self):
        """https webhook → 正常发送（mock urlopen 命中）。"""
        self._config_with_webhook('https://oapi.example.com/hook')
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = FakeResponse(200, b'{"errcode": 0}')
            result = notify_module.notify('msg', 'N1')
        self.assertTrue(result)
        mock_urlopen.assert_called_once()

    def test_remote_http_webhook_rejected_no_request(self):
        """远程 http webhook → 拒绝发送（不发起任何请求）。"""
        self._config_with_webhook('http://oapi.example.com/hook')
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            result = notify_module.notify('msg', 'N1')
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_localhost_http_webhook_sends(self):
        """localhost http webhook（本地调试通道）→ 放行发送。"""
        self._config_with_webhook('http://localhost:8080/hook')
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = FakeResponse(200, b'{"errcode": 0}')
            result = notify_module.notify('msg', 'N1')
        self.assertTrue(result)
        mock_urlopen.assert_called_once()

    def test_webhook_without_scheme_rejected_no_request(self):
        """无 scheme webhook（形如 host/path）→ 拒绝发送。"""
        self._config_with_webhook('oapi.example.com/hook')
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            result = notify_module.notify('msg', 'N1')
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    def test_rejected_channel_does_not_block_others(self):
        """非法 scheme 渠道跳过后继续尝试下一合法渠道（任一成功即停）。"""
        config = make_config(
            channels={
                'bad': make_channel('wecom_bot', 'http://remote.example.com/hook'),
                'good': make_channel('wecom_bot', 'https://oapi.example.com/hook'),
            },
            events={'N1': {'enabled': True, 'channels': ['bad', 'good']}},
        )
        self.write_project_config(config)
        with mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = FakeResponse(200, b'{"errcode": 0}')
            result = notify_module.notify('msg', 'N1')
        self.assertTrue(result)
        mock_urlopen.assert_called_once()
        self.assertEqual(
            mock_urlopen.call_args[0][0].full_url, 'https://oapi.example.com/hook')


class LoadEnvTests(unittest.TestCase):
    """load-env.sh 导出集与短路语义（子进程 bash，HOME/CWD 隔离）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.project = self.root / 'project'
        self.home.mkdir()
        self.project.mkdir()
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith('BUDGET_NOTIFY')
        }
        self.env['HOME'] = str(self.home)

    def run_load_env(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ['bash', str(LOAD_ENV_SH)], cwd=str(self.project),
            capture_output=True, text=True, encoding='utf-8', check=False, env=self.env,
        )

    def eval_load_env(self) -> subprocess.CompletedProcess:
        """以 bash eval 语义加载并回显两个变量（验证 export 语句可执行）。"""
        script = (
            f'eval "$(bash {shlex.quote(str(LOAD_ENV_SH))})"; '
            'printf "%s\\037%s" "$BUDGET_NOTIFY_ENABLED" "$BUDGET_NOTIFY_CONFIG"'
        )
        return subprocess.run(
            ['bash', '-c', script], cwd=str(self.project),
            capture_output=True, text=True, encoding='utf-8', check=False, env=self.env,
        )

    def write_project_config(self, config: dict) -> Path:
        target = self.project / '.budget' / 'notify.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(config), encoding='utf-8')
        return target

    def write_global_config(self, config: dict) -> Path:
        target = self.home / '.budgetbuddy' / 'notify.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(config), encoding='utf-8')
        return target

    def test_with_config_exports_both_variables(self):
        """已配置环境 eval 加载 → ENABLED=1 且 CONFIG 指向生效配置文件。"""
        target = self.write_project_config(make_config(enabled=True))
        proc = self.eval_load_env()
        self.assertEqual(proc.returncode, 0)
        enabled, config_path = proc.stdout.split('\037')
        self.assertEqual(enabled, '1')
        self.assertEqual(Path(config_path), target)

    def test_no_config_exports_disabled_only(self):
        """两级均无配置 → 仅导出 ENABLED=0，exit 0（Leader 短路依据）。"""
        proc = self.run_load_env()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), 'export BUDGET_NOTIFY_ENABLED=0')
        eval_proc = self.eval_load_env()
        self.assertEqual(eval_proc.returncode, 0)
        enabled, config_path = eval_proc.stdout.split('\037')
        self.assertEqual(enabled, '0')
        self.assertEqual(config_path, '')

    def test_disabled_config_exports_zero_and_path(self):
        """有配置但 enabled=false → ENABLED=0 且 CONFIG 仍指向生效文件。"""
        target = self.write_project_config(make_config(enabled=False))
        proc = self.eval_load_env()
        enabled, config_path = proc.stdout.split('\037')
        self.assertEqual(enabled, '0')
        self.assertEqual(Path(config_path), target)

    def test_no_sensitive_values_exported(self):
        """导出语句不含 webhook/secret（敏感字段不经环境变量）。"""
        self.write_project_config(make_config(channels={
            'wecom': make_channel(),
            'dingtalk': make_channel('dingtalk_bot', secret=SAMPLE_SECRET),
        }))
        proc = self.run_load_env()
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn(SAMPLE_WEBHOOK, proc.stdout)
        self.assertNotIn('token-abc123', proc.stdout)
        self.assertNotIn(SAMPLE_SECRET, proc.stdout)
        export_lines = [line for line in proc.stdout.strip().splitlines() if line]
        self.assertEqual(len(export_lines), 2)
        for line in export_lines:
            self.assertTrue(line.startswith('export BUDGET_NOTIFY_'))

    def test_project_config_priority(self):
        """项目级优先于全局级（不合并）。"""
        self.write_global_config(make_config(enabled=False))
        target = self.write_project_config(make_config(enabled=True))
        proc = self.eval_load_env()
        enabled, config_path = proc.stdout.split('\037')
        self.assertEqual(enabled, '1')
        self.assertEqual(Path(config_path), target)

    def test_invalid_json_config_exports_disabled(self):
        """配置文件非法 JSON → 按无配置处理（ENABLED=0）。"""
        target = self.project / '.budget' / 'notify.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{broken', encoding='utf-8')
        proc = self.eval_load_env()
        self.assertEqual(proc.returncode, 0)
        enabled, _ = proc.stdout.split('\037')
        self.assertEqual(enabled, '0')


class HookTests(unittest.TestCase):
    """hook 三事件、stdin 安全解析与 notify 调用（mock subprocess，不外呼）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name).resolve() / 'project'
        self.project.mkdir()

    def run_hook_subprocess(self, stdin_text: str) -> subprocess.CompletedProcess:
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith('BUDGET_NOTIFY')
        }
        return subprocess.run(
            [sys.executable, str(HOOK_PY)], input=stdin_text,
            capture_output=True, text=True, encoding='utf-8', check=False, env=env,
        )

    def call_main_with_payload(self, payload: dict) -> None:
        stdin = io.StringIO(json.dumps(payload))
        with mock.patch('sys.stdin', stdin):
            hook_module.main()

    def notification_payload(self) -> dict:
        return {
            'hook_event_name': 'Notification',
            'notification_type': 'permission_prompt',
            'message': '需要确认文件写入',
            'cwd': str(self.project),
        }

    def test_empty_stdin_exits_zero_silently(self):
        """空 stdin → 静默 exit 0，无任何输出。"""
        proc = self.run_hook_subprocess('')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '')

    def test_invalid_json_exits_zero_silently(self):
        """非法 JSON → 静默 exit 0，无任何输出。"""
        proc = self.run_hook_subprocess('not-json {')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '')

    def test_non_object_json_exits_zero_silently(self):
        """合法 JSON 但非对象（数组）→ 静默 exit 0。"""
        proc = self.run_hook_subprocess('[1, 2, 3]')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '')

    def test_valid_notification_payload_calls_notify(self):
        """合法 Notification payload → 调用 notify.py，消息含 [budget] 前缀。"""
        with mock.patch.object(hook_module.subprocess, 'run') as mock_run:
            self.call_main_with_payload(self.notification_payload())
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        command = args[0]
        self.assertEqual(command[0], 'python3')
        self.assertTrue(command[1].endswith('notify.py'))
        self.assertIn('[budget]', command[2])
        self.assertIn('流程卡点', command[2])
        self.assertEqual(kwargs['cwd'], str(self.project))
        # webhook/secret 不经命令行参数传递（argv 仅 python + 脚本 + 消息）。
        command_text = ' '.join(command)
        self.assertNotIn('http', command_text)
        self.assertNotIn(SAMPLE_WEBHOOK, command_text)

    def test_pretooluse_sandbox_bypass_calls_notify(self):
        """PreToolUse 沙箱越权命令 → 调用 notify.py（消息含命令摘要）。"""
        payload = {
            'hook_event_name': 'PreToolUse',
            'tool_name': 'Bash',
            'tool_input': {'command': 'rm -rf /tmp/cache', 'dangerouslyDisableSandbox': True},
            'cwd': str(self.project),
        }
        with mock.patch.object(hook_module.subprocess, 'run') as mock_run:
            self.call_main_with_payload(payload)
        mock_run.assert_called_once()
        message = mock_run.call_args[0][0][2]
        self.assertIn('[budget]', message)
        self.assertIn('沙箱越权', message)
        self.assertIn('rm -rf /tmp/cache', message)

    def test_subagentstop_calls_notify(self):
        """SubagentStop 事件 → 调用 notify.py（子代理完成通知）。"""
        payload = {'hook_event_name': 'SubagentStop', 'cwd': str(self.project)}
        with mock.patch.object(hook_module.subprocess, 'run') as mock_run:
            self.call_main_with_payload(payload)
        mock_run.assert_called_once()
        message = mock_run.call_args[0][0][2]
        self.assertIn('[budget]', message)
        self.assertIn('子代理', message)

    def test_stop_hook_active_skipped(self):
        """SubagentStop 且 stop_hook_active=true → 防循环跳过。"""
        payload = {
            'hook_event_name': 'SubagentStop',
            'stop_hook_active': True,
            'cwd': str(self.project),
        }
        with mock.patch.object(hook_module.subprocess, 'run') as mock_run:
            self.call_main_with_payload(payload)
        mock_run.assert_not_called()

    def test_unknown_event_not_sent(self):
        """未知事件类型 → 不调用 notify。"""
        payload = {'hook_event_name': 'SomethingElse', 'cwd': str(self.project)}
        with mock.patch.object(hook_module.subprocess, 'run') as mock_run:
            self.call_main_with_payload(payload)
        mock_run.assert_not_called()

    def test_build_message_notification_variants(self):
        """Notification 子类型：idle_prompt 通知、未知类型返回 None。"""
        idle = hook_module.build_message({
            'hook_event_name': 'Notification',
            'notification_type': 'idle_prompt',
            'cwd': str(self.project),
        })
        self.assertIsNotNone(idle)
        self.assertIn('等待您的输入', idle)

        unknown_type = hook_module.build_message({
            'hook_event_name': 'Notification',
            'notification_type': 'other',
        })
        self.assertIsNone(unknown_type)

    def test_build_message_pretooluse_variants(self):
        """PreToolUse 子类型：非 Bash 或未越权 → None。"""
        no_bypass = hook_module.build_message({
            'hook_event_name': 'PreToolUse',
            'tool_name': 'Bash',
            'tool_input': {'command': 'ls'},
        })
        self.assertIsNone(no_bypass)

        not_bash = hook_module.build_message({
            'hook_event_name': 'PreToolUse',
            'tool_name': 'Edit',
            'tool_input': {'dangerouslyDisableSandbox': True},
        })
        self.assertIsNone(not_bash)

    def test_build_message_includes_project_name(self):
        """消息含项目名（cwd 的 basename）。"""
        message = hook_module.build_message(self.notification_payload())
        self.assertIn(self.project.name, message)


class CliSmokeTests(unittest.TestCase):
    """notify.py CLI 冒烟（无配置环境不外呼，真实子进程）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.project = self.root / 'project'
        self.home.mkdir()
        self.project.mkdir()
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith('BUDGET_NOTIFY')
        }
        self.env['HOME'] = str(self.home)

    def run_notify(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(NOTIFY_PY), *args], cwd=str(self.project),
            capture_output=True, text=True, encoding='utf-8', check=False, env=self.env,
        )

    def test_no_config_exit_zero_silent(self):
        """无配置环境 → exit 0 且无任何输出（验收冒烟项）。"""
        proc = self.run_notify('hello message')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '')

    def test_empty_message_exit_zero(self):
        """空消息 → exit 0。"""
        proc = self.run_notify()
        self.assertEqual(proc.returncode, 0)

    def test_multiline_message_no_config_exit_zero(self):
        """多行消息（实际换行符）无配置 → exit 0。"""
        proc = self.run_notify('line1\nline2')
        self.assertEqual(proc.returncode, 0)


if __name__ == '__main__':
    unittest.main()
