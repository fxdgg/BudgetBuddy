#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""budget-notify-hook.py hook 引擎新事件单测（specs claudecode-hooks-notify D1）。

test_notify.py 的 HookTests 覆盖 codebuddy 既有事件；本文件补齐
claudecode 形态新分支：Notification message 直通（含 200 字截断）、
notification_type 既有两分支回归、PermissionRequest 三级摘要与全缺失
兜底、SubagentStop stop_hook_active 跳过、未知事件 None、stdin 非法
payload 静默（子进程级）。全程 mock subprocess，不外呼。
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PY = REPO_ROOT / 'core' / 'hooks' / 'budget-notify-hook.py'


def load_module(path: Path, name: str):
    """按文件路径加载模块（core 下非包结构，模块级代码无副作用）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook_module = load_module(HOOK_PY, 'budget_notify_hook_engine_under_test')


class HookEngineTestCase(unittest.TestCase):
    """公共沙盒：每用例独立临时项目目录（cwd 断言用）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='budget-hook-engine-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()

    def notification_passthrough_payload(self, message: str = '权限确认等待中') -> dict:
        """Claude Code 形态 Notification payload（无 notification_type，仅 message）。"""
        return {
            'hook_event_name': 'Notification',
            'message': message,
            'cwd': str(self.project),
        }

    def permission_request_payload(self, **extra) -> dict:
        """Claude Code 形态 PermissionRequest payload（按需覆盖字段）。"""
        payload = {'hook_event_name': 'PermissionRequest', 'cwd': str(self.project)}
        payload.update(extra)
        return payload


class NotificationPassthroughTests(HookEngineTestCase):
    """Notification message 直通分支（D1：无 notification_type → 直载）。"""

    def test_passthrough_message_direct(self):
        """无 notification_type 且 message 非空 → 会话提醒直通（含项目名与文案）。"""
        message = hook_module.build_message(self.notification_passthrough_payload())
        self.assertIsNotNone(message)
        self.assertIn('[budget]', message)
        self.assertIn('会话提醒', message)
        self.assertIn('权限确认等待中', message)
        self.assertIn(self.project.name, message)
        self.assertIn('请回到当前会话查看', message)

    def test_passthrough_truncates_message_to_200_chars(self):
        """超长 message → 详情截断至 200 字（尾部丢弃）。"""
        long_message = 'x' * 500
        message = hook_module.build_message(
            self.notification_passthrough_payload(long_message))
        self.assertIsNotNone(message)
        self.assertIn('x' * 200, message)
        self.assertNotIn('x' * 201, message)

    def test_passthrough_boundary_message_not_truncated(self):
        """200 字整 message → 原样包含（边界不截）。"""
        message = hook_module.build_message(
            self.notification_passthrough_payload('y' * 200))
        self.assertIn('y' * 200, message)

    def test_passthrough_missing_all_fields_returns_none(self):
        """无 notification_type 也无 message → None（不构造空详情消息）。"""
        result = hook_module.build_message({
            'hook_event_name': 'Notification',
            'cwd': str(self.project),
        })
        self.assertIsNone(result)

    def test_passthrough_via_main_calls_notify(self):
        """直通消息经 main 全链路调用 notify.py（含 [budget] 前缀）。"""
        stdin = io.StringIO(json.dumps(self.notification_passthrough_payload()))
        with mock.patch('sys.stdin', stdin):
            with mock.patch.object(hook_module.subprocess, 'run') as mock_run:
                hook_module.main()
        mock_run.assert_called_once()
        sent = mock_run.call_args[0][0][2]
        self.assertIn('[budget]', sent)
        self.assertIn('会话提醒', sent)


class NotificationTypeRegressionTests(HookEngineTestCase):
    """notification_type 既有两分支回归（codebuddy 形态，零改动验证）。"""

    def test_permission_prompt_branch(self):
        """notification_type=permission_prompt → 流程卡点文案（含 message 详情）。"""
        message = hook_module.build_message({
            'hook_event_name': 'Notification',
            'notification_type': 'permission_prompt',
            'message': '需要确认文件写入',
            'cwd': str(self.project),
        })
        self.assertIsNotNone(message)
        self.assertIn('流程卡点', message)
        self.assertIn('需要确认文件写入', message)
        self.assertIn('请在当前会话中确认操作', message)

    def test_idle_prompt_branch(self):
        """notification_type=idle_prompt → 等待输入文案（空闲 60 秒）。"""
        message = hook_module.build_message({
            'hook_event_name': 'Notification',
            'notification_type': 'idle_prompt',
            'cwd': str(self.project),
        })
        self.assertIsNotNone(message)
        self.assertIn('等待您的输入', message)
        self.assertIn('已空闲超过 60 秒', message)

    def test_known_type_overrides_message_passthrough(self):
        """notification_type 存在（未知值）+ message → 不走直通（None）。"""
        result = hook_module.build_message({
            'hook_event_name': 'Notification',
            'notification_type': 'other',
            'message': '有消息但类型未知',
            'cwd': str(self.project),
        })
        self.assertIsNone(result)


class PermissionRequestTests(HookEngineTestCase):
    """PermissionRequest 新事件（D1：三级摘要与全缺失兜底）。"""

    def test_message_priority_over_tool_summary(self):
        """message 优先于 tool_name/tool_input（详情取 message）。"""
        message = hook_module.build_message(self.permission_request_payload(
            message='Claude 需要确认 Bash 执行',
            tool_name='Bash',
            tool_input={'command': 'rm -rf /tmp'}))
        self.assertIsNotNone(message)
        self.assertIn('[budget]', message)
        self.assertIn('流程卡点', message)
        self.assertIn('Claude 需要确认 Bash 执行', message)
        self.assertNotIn('工具 `Bash`', message)
        self.assertIn('请在当前会话中确认操作', message)

    def test_message_truncated_to_200_chars(self):
        """超长 message → 截断 200 字。"""
        message = hook_module.build_message(self.permission_request_payload(
            message='m' * 500))
        self.assertIn('m' * 200, message)
        self.assertNotIn('m' * 201, message)

    def test_tool_name_without_input_summary(self):
        """无 message 有 tool_name（无 tool_input）→ 工具请求确认摘要。"""
        message = hook_module.build_message(self.permission_request_payload(
            tool_name='Write'))
        self.assertIsNotNone(message)
        self.assertIn('工具 `Write` 请求确认', message)

    def test_tool_name_with_command_summary(self):
        """无 message 有 tool_name + tool_input.command → 工具 + 命令摘要。"""
        message = hook_module.build_message(self.permission_request_payload(
            tool_name='Bash',
            tool_input={'command': 'git push origin main'}))
        self.assertIsNotNone(message)
        self.assertIn('工具 `Bash`', message)
        self.assertIn('git push origin main', message)

    def test_tool_input_non_dict_ignored(self):
        """tool_input 非 dict → 回落 tool_name 摘要（不崩溃）。"""
        message = hook_module.build_message(self.permission_request_payload(
            tool_name='Edit', tool_input='not-a-dict'))
        self.assertIsNotNone(message)
        self.assertIn('工具 `Edit` 请求确认', message)

    def test_all_fields_missing_fallback_not_none(self):
        """message/tool_name/tool_input 全缺失 → 通用卡点兜底文案（非 None）。"""
        message = hook_module.build_message(self.permission_request_payload())
        self.assertIsNotNone(message)
        self.assertIn('收到权限确认请求', message)
        self.assertIn('请在当前会话中确认操作', message)

    def test_via_main_calls_notify(self):
        """PermissionRequest 经 main 全链路调用 notify.py。"""
        stdin = io.StringIO(json.dumps(self.permission_request_payload(
            message='确认外部网络访问')))
        with mock.patch('sys.stdin', stdin):
            with mock.patch.object(hook_module.subprocess, 'run') as mock_run:
                hook_module.main()
        mock_run.assert_called_once()
        sent = mock_run.call_args[0][0][2]
        self.assertIn('[budget]', sent)
        self.assertIn('确认外部网络访问', sent)


class SubagentStopTests(HookEngineTestCase):
    """SubagentStop 防循环跳过（既有行为，claudecode 形态复用）。"""

    def test_stop_hook_active_skips_notification(self):
        """stop_hook_active=true → None（防循环）。"""
        result = hook_module.build_message({
            'hook_event_name': 'SubagentStop',
            'stop_hook_active': True,
            'cwd': str(self.project),
        })
        self.assertIsNone(result)

    def test_without_stop_hook_active_notifies(self):
        """stop_hook_active 缺失 → 正常完成通知。"""
        message = hook_module.build_message({
            'hook_event_name': 'SubagentStop',
            'cwd': str(self.project),
        })
        self.assertIsNotNone(message)
        self.assertIn('子代理任务完成', message)


class UnknownEventTests(HookEngineTestCase):
    """未知事件静默（payload 驱动，引擎对未知事件零副作用）。"""

    def test_unknown_event_returns_none(self):
        result = hook_module.build_message({
            'hook_event_name': 'SessionStart',
            'cwd': str(self.project),
        })
        self.assertIsNone(result)

    def test_missing_event_name_returns_none(self):
        result = hook_module.build_message({'cwd': str(self.project)})
        self.assertIsNone(result)


class StdinPayloadSafetySubprocessTests(unittest.TestCase):
    """stdin 非法 payload 静默（子进程级，防堆栈外泄）。"""

    def run_hook_subprocess(self, stdin_text: str) -> subprocess.CompletedProcess:
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith('BUDGET_NOTIFY')
        }
        return subprocess.run(
            [sys.executable, str(HOOK_PY)], input=stdin_text,
            capture_output=True, text=True, encoding='utf-8', check=False, env=env,
        )

    def test_empty_stdin_silent_exit_zero(self):
        proc = self.run_hook_subprocess('')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '')

    def test_invalid_json_silent_exit_zero(self):
        proc = self.run_hook_subprocess('not-json {')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '')

    def test_non_object_json_silent_exit_zero(self):
        proc = self.run_hook_subprocess('[{"hook_event_name": "Notification"}]')
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '')


if __name__ == '__main__':
    unittest.main()
