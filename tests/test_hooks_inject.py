#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks_inject.py 注入引擎单测（specs/notify「CodeBuddy hooks 三事件通知」）。

覆盖：注入（三事件 + superpowers、用户已有 hooks 保留、键序保持、备份
生成与跳过重备份、幂等重入）、移除（本套件项精确删除、用户项保留、
空文件删除）、解析失败不写回、查询状态、hooks.sh 编排链路端到端
（bash 子进程，含 do_notify 转发与 do_status 冒烟）。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_INJECT_PY = REPO_ROOT / 'core' / 'lib' / 'hooks_inject.py'
HOOKS_SH = REPO_ROOT / 'core' / 'lib' / 'hooks.sh'
NOTIFY_SH = REPO_ROOT / 'core' / 'lib' / 'notify.sh'
SETUP_SH = REPO_ROOT / 'core' / 'setup.sh'

HOOK_MARKER = 'budget-notify-hook.py'
SUPERPOWERS_KEY = 'superpowers@codebuddy-plugins-official'
HOOK_CMD = 'test -f .codebuddy/hooks/budget-notify-hook.py && python3 .codebuddy/hooks/budget-notify-hook.py || exit 0'


def run_engine(action: str, settings_file: Path, hook_cmd: str = HOOK_CMD,
               extra_env=None) -> subprocess.CompletedProcess:
    """以环境变量传参驱动注入引擎子进程。"""
    env = dict(os.environ)
    env.pop('SETTINGS_FILE', None)
    env['SETTINGS_FILE'] = str(settings_file)
    env['ACTION'] = action
    env['HOOK_CMD'] = hook_cmd
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(HOOKS_INJECT_PY)], env=env,
        capture_output=True, text=True, encoding='utf-8', check=False, timeout=30)


def load_json(path: Path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


class EngineTestCase(unittest.TestCase):
    """公共沙箱：每用例独立临时目录（settings.json + HOME 隔离）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='budget-hooks-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.project = self.root / 'project'
        self.home.mkdir()
        self.project.mkdir()
        self.settings = self.project / '.codebuddy' / 'settings.json'
        self.settings.parent.mkdir(parents=True)

    def write_settings(self, data) -> None:
        self.settings.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    def read_settings(self):
        return load_json(self.settings)

    def suite_hook_commands(self, data) -> list:
        """收集全部本套件 hook 条目的 command 串。"""
        commands = []
        for matchers in (data.get('hooks') or {}).values():
            for matcher in matchers:
                for hook in matcher.get('hooks', []):
                    cmd = str(hook.get('command', ''))
                    if HOOK_MARKER in cmd:
                        commands.append(cmd)
        return commands


class InjectionTests(EngineTestCase):
    """三事件注入、备份、幂等与用户内容保留。"""

    def test_inject_all_from_missing_file(self):
        """settings.json 不存在 → 创建并注入三事件 + superpowers。"""
        proc = run_engine('inject_all', self.settings)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('injected', proc.stdout)
        data = self.read_settings()
        self.assertTrue(data['enabledPlugins'][SUPERPOWERS_KEY])
        hooks = data['hooks']
        self.assertEqual(
            [m.get('matcher') for m in hooks['Notification']],
            ['permission_prompt', 'idle_prompt'])
        self.assertEqual(hooks['PreToolUse'][0]['matcher'], 'Bash')
        self.assertNotIn('matcher', hooks['SubagentStop'][0])
        for event in ('Notification', 'PreToolUse', 'SubagentStop'):
            for matcher in hooks[event]:
                entry = matcher['hooks'][0]
                self.assertEqual(entry['type'], 'command')
                self.assertIn(HOOK_MARKER, entry['command'])
                self.assertEqual(entry['timeout'], 10)

    def test_inject_all_preserves_user_hooks_and_fields(self):
        """用户已有 hooks（同/异事件）与其余顶层字段全部保留。"""
        user_settings = {
            'theme': 'dark',
            'enabledPlugins': {'another@plugins': True},
            'hooks': {
                'Notification': [
                    {'matcher': 'permission_prompt',
                     'hooks': [{'type': 'command', 'command': 'echo user-notify'}]},
                ],
                'Stop': [
                    {'hooks': [{'type': 'command', 'command': 'echo user-stop'}]},
                ],
            },
        }
        self.write_settings(user_settings)
        proc = run_engine('inject_all', self.settings)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('injected', proc.stdout)
        data = self.read_settings()
        self.assertEqual(data['theme'], 'dark')
        self.assertTrue(data['enabledPlugins']['another@plugins'])
        self.assertTrue(data['enabledPlugins'][SUPERPOWERS_KEY])
        notification = data['hooks']['Notification']
        user_matchers = [m for m in notification if 'user-notify' in str(m['hooks'])]
        self.assertEqual(len(user_matchers), 1)
        stop_commands = [str(h.get('command')) for m in data['hooks']['Stop']
                         for h in m.get('hooks', [])]
        self.assertIn('echo user-stop', stop_commands)
        self.assertFalse(any(HOOK_MARKER in c for c in stop_commands))

    def test_inject_creates_backup_and_skips_when_identical(self):
        """注入前生成 .bak-budget；重跑幂等（no_change）不重复备份。"""
        self.write_settings({'theme': 'light'})
        proc = run_engine('inject_all', self.settings)
        self.assertIn('injected', proc.stdout)
        backup = Path(str(self.settings) + '.bak-budget')
        self.assertTrue(backup.is_file())
        self.assertEqual(load_json(backup), {'theme': 'light'})

        proc2 = run_engine('inject_all', self.settings)
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertIn('no_change', proc2.stdout)
        # 幂等重入：hooks/superpowers 不重复
        data = self.read_settings()
        self.assertEqual(len(self.suite_hook_commands(data)), 4)
        self.assertEqual(
            len(data['hooks']['Notification']), 2)  # 两条 suite matcher，无重复
        self.assertEqual(load_json(backup), {'theme': 'light'})

    def test_backup_not_overwritten_after_suite_marks_present(self):
        """备份存在且当前已含套件痕迹 → 跳过重备份（保护原始恢复点）。"""
        self.write_settings({'a': 1})
        run_engine('inject_superpowers', self.settings)
        backup = Path(str(self.settings) + '.bak-budget')
        original_backup = load_json(backup)
        # 修改 settings 后再注入 hooks：备份不应被覆盖（当前已含套件痕迹）
        data = self.read_settings()
        data['b'] = 2
        self.write_settings(data)
        proc = run_engine('inject_hooks', self.settings)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('injected', proc.stdout)
        self.assertEqual(load_json(backup), original_backup)

    def test_key_order_preserved(self):
        """写入保持原键序，注入项（hooks/enabledPlugins）追加在尾部。"""
        self.write_settings({'alpha': 1, 'beta': 2})
        run_engine('inject_all', self.settings)
        text = self.settings.read_text(encoding='utf-8')
        keys = list(load_json(self.settings).keys())
        self.assertEqual(keys, ['alpha', 'beta', 'enabledPlugins', 'hooks'])
        self.assertIn('"alpha": 1', text)

    def test_inject_hooks_only_without_superpowers(self):
        """inject_hooks 仅注入 hooks，不动 enabledPlugins。"""
        self.write_settings({'x': 1})
        proc = run_engine('inject_hooks', self.settings)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('injected', proc.stdout)
        data = self.read_settings()
        self.assertEqual(len(self.suite_hook_commands(data)), 4)
        self.assertNotIn('enabledPlugins', data)

    def test_inject_superpowers_only(self):
        """inject_superpowers 仅注入插件，不动 hooks。"""
        self.write_settings({'x': 1})
        proc = run_engine('inject_superpowers', self.settings)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_settings()
        self.assertTrue(data['enabledPlugins'][SUPERPOWERS_KEY])
        self.assertNotIn('hooks', data)


class RemovalTests(EngineTestCase):
    """移除精确性：本套件项删除、用户项保留、空文件删除。"""

    def _injected_state(self):
        """构造「用户内容 + 本套件注入」混合状态。"""
        self.write_settings({
            'theme': 'dark',
            'hooks': {
                'Notification': [
                    {'matcher': 'permission_prompt',
                     'hooks': [{'type': 'command', 'command': 'echo user-a'}]},
                ],
            },
        })
        run_engine('inject_all', self.settings)

    def test_remove_keeps_user_hooks_and_fields(self):
        """移除后：本套件 hook 条目与 superpowers 键删除，用户项完整保留。"""
        self._injected_state()
        proc = run_engine('remove_hooks', self.settings)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('removed', proc.stdout)
        data = self.read_settings()
        self.assertEqual(data['theme'], 'dark')
        self.assertNotIn('enabledPlugins', data)
        notification = data['hooks']['Notification']
        self.assertEqual(len(notification), 1)
        self.assertIn('user-a', str(notification[0]['hooks']))

    def test_remove_drops_empty_events_and_file(self):
        """无用户内容时：事件键清空删除；settings 只剩套件痕迹 → 文件删除。"""
        self.write_settings({})
        run_engine('inject_all', self.settings)
        proc = run_engine('remove_hooks', self.settings)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('removed', proc.stdout)
        self.assertFalse(self.settings.exists())

    def test_remove_preserves_file_with_user_content(self):
        """有用户内容时移除后文件保留（不误删用户 settings.json）。"""
        self.write_settings({'theme': 'dark'})
        run_engine('inject_all', self.settings)
        run_engine('remove_hooks', self.settings)
        data = self.read_settings()
        self.assertEqual(data, {'theme': 'dark'})

    def test_remove_without_injection_is_noop(self):
        """未注入过 → no_change，文件不动。"""
        self.write_settings({'theme': 'dark'})
        before = self.settings.read_text(encoding='utf-8')
        proc = run_engine('remove_hooks', self.settings)
        self.assertIn('no_change', proc.stdout)
        self.assertEqual(self.settings.read_text(encoding='utf-8'), before)

    def test_remove_missing_file_is_noop(self):
        """settings.json 不存在 → no_change。"""
        proc = run_engine('remove_hooks', self.settings)
        self.assertIn('no_change', proc.stdout)
        self.assertEqual(proc.returncode, 0)

    def test_remove_keeps_user_hook_in_same_matcher(self):
        """同一 matcher 下用户自有 hook 与套件 hook 并存 → 仅删套件条目。"""
        self.write_settings({'hooks': {'PreToolUse': [
            {'matcher': 'Bash', 'hooks': [
                {'type': 'command', 'command': 'echo user-bash'},
                {'type': 'command', 'command': HOOK_CMD},
            ]},
        ]}})
        proc = run_engine('remove_hooks', self.settings)
        self.assertIn('removed', proc.stdout)
        data = self.read_settings()
        matcher = data['hooks']['PreToolUse'][0]
        commands = [str(h.get('command')) for h in matcher['hooks']]
        self.assertEqual(commands, ['echo user-bash'])

    def test_remove_does_not_touch_backup(self):
        """移除不覆盖 .bak-budget（保留注入前原始恢复点）。"""
        self.write_settings({'theme': 'light'})
        run_engine('inject_all', self.settings)
        backup = Path(str(self.settings) + '.bak-budget')
        backup_text = backup.read_text(encoding='utf-8')
        run_engine('remove_hooks', self.settings)
        self.assertEqual(backup.read_text(encoding='utf-8'), backup_text)


class FailureModeTests(EngineTestCase):
    """JSON 语法破坏保护：解析失败不写回、原文件保留、非零退出。"""

    def test_inject_invalid_json_preserves_file(self):
        """非法 JSON → 报错 exit 1，原文件一字不动。"""
        original = '{broken json'
        self.settings.write_text(original, encoding='utf-8')
        proc = run_engine('inject_all', self.settings)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('解析失败', proc.stderr)
        self.assertEqual(self.settings.read_text(encoding='utf-8'), original)
        self.assertFalse(Path(str(self.settings) + '.bak-budget').exists())

    def test_inject_non_object_top_level_preserves_file(self):
        """顶层非 JSON 对象（数组）→ 报错 exit 1 不写回。"""
        original = '[1, 2]'
        self.settings.write_text(original, encoding='utf-8')
        proc = run_engine('inject_all', self.settings)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.settings.read_text(encoding='utf-8'), original)

    def test_remove_invalid_json_preserves_file(self):
        """移除操作遇非法 JSON 同样不写回。"""
        original = '{oops'
        self.settings.write_text(original, encoding='utf-8')
        proc = run_engine('remove_hooks', self.settings)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.settings.read_text(encoding='utf-8'), original)

    def test_missing_action_errors(self):
        """ACTION 未设置 → exit 1 + stderr 提示。"""
        env = dict(os.environ)
        env.pop('ACTION', None)
        env.pop('SETTINGS_FILE', None)
        proc = subprocess.run(
            [sys.executable, str(HOOKS_INJECT_PY)], env=env,
            capture_output=True, text=True, encoding='utf-8', check=False, timeout=30)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('ACTION', proc.stderr)

    def test_unknown_action_errors(self):
        proc = run_engine('bogus_action', self.settings)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未知 ACTION', proc.stderr)

    def test_missing_settings_file_env_errors(self):
        env = dict(os.environ)
        env.pop('SETTINGS_FILE', None)
        env.pop('ACTION', None)
        env['ACTION'] = 'inject_all'
        proc = subprocess.run(
            [sys.executable, str(HOOKS_INJECT_PY)], env=env,
            capture_output=True, text=True, encoding='utf-8', check=False, timeout=30)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('SETTINGS_FILE', proc.stderr)


class QueryTests(EngineTestCase):
    """查询类 action（check / check_hooks）。"""

    def test_check_reports_false_without_file(self):
        proc = run_engine('check', self.settings)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), 'false')

    def test_check_reports_true_after_injection(self):
        run_engine('inject_all', self.settings)
        proc = run_engine('check', self.settings)
        self.assertEqual(proc.stdout.strip(), 'true')

    def test_check_hooks_reports_injection_state(self):
        proc = run_engine('check_hooks', self.settings)
        self.assertEqual(json.loads(proc.stdout.strip()),
                         {'hooks': False, 'superpowers': False})
        run_engine('inject_all', self.settings)
        proc = run_engine('check_hooks', self.settings)
        self.assertEqual(json.loads(proc.stdout.strip()),
                         {'hooks': True, 'superpowers': True})

    def test_check_hooks_partial_state(self):
        """仅注入 hooks（未启插件）→ hooks=true / superpowers=false。"""
        run_engine('inject_hooks', self.settings)
        proc = run_engine('check_hooks', self.settings)
        self.assertEqual(json.loads(proc.stdout.strip()),
                         {'hooks': True, 'superpowers': False})

    def test_check_tolerates_corrupted_file(self):
        """查询类 action 对损坏文件容错（false 而非崩溃）。"""
        self.settings.write_text('{broken', encoding='utf-8')
        proc = run_engine('check', self.settings)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), 'false')


class HooksShEndToEndTests(EngineTestCase):
    """hooks.sh / notify.sh 编排链路端到端（bash 子进程，经 setup.sh 分发）。"""

    # 完整 lib 清单（setup.sh optional source 列表全量；缺失模块仅跳过）
    LIB_FILES = (
        'colors.sh', 'utils.sh', 'platform.sh', 'shell.sh',
        'init.sh', 'models.sh', 'preset.sh', 'model_resolver.py',
        'notify.sh', 'hooks.sh', 'hooks_inject.py',
    )

    def make_install(self):
        """构造 codebuddy 项目级安装形态（setup.sh + lib + skills + hooks）。"""
        cb = self.project / '.codebuddy'
        (cb / 'lib').mkdir(parents=True, exist_ok=True)
        (cb / 'skills' / 'budget-notify').mkdir(parents=True, exist_ok=True)
        (cb / 'hooks').mkdir(parents=True, exist_ok=True)
        (cb / 'agents').mkdir(parents=True, exist_ok=True)
        shutil.copy2(SETUP_SH, cb / 'setup.sh')
        for name in self.LIB_FILES:
            shutil.copy2(REPO_ROOT / 'core' / 'lib' / name, cb / 'lib' / name)
        shutil.copy2(REPO_ROOT / 'core' / 'skills' / 'budget-notify' / 'notify.py',
                    cb / 'skills' / 'budget-notify' / 'notify.py')
        shutil.copy2(REPO_ROOT / 'core' / 'hooks' / 'budget-notify-hook.py',
                    cb / 'hooks' / 'budget-notify-hook.py')
        # models/personas（notify status 的 agent 概览依赖 preset.sh + models）
        shutil.copy2(REPO_ROOT / 'core' / 'models' / 'budget-models.json',
                    cb / 'budget-models.json')
        shutil.copy2(REPO_ROOT / 'core' / 'personas' / 'personas.json',
                    cb / 'personas.json')
        # 一个 agent 产物（概览展示用）
        (cb / 'agents' / 'architect.md').write_text(
            '---\nname: architect\ndescription: x\nmodel: glm-5.2\n---\nbody\n',
            encoding='utf-8')
        return cb

    def setUp(self):
        super().setUp()
        cb = self.make_install()
        self.setup_sh = cb / 'setup.sh'

    def run_setup(self, *args, stdin_text=''):
        """经 setup.sh 分发入口执行（模拟 budget <子命令>）。"""
        env = dict(os.environ)
        env['HOME'] = str(self.home)
        for key in list(env):
            if key.startswith('BUDGET_'):
                del env[key]
        return subprocess.run(
            ['bash', str(self.setup_sh), *args], cwd=str(self.project), env=env,
            capture_output=True, text=True, encoding='utf-8', check=False,
            timeout=60, input=stdin_text)

    def run_setup_shell(self, script):
        """source setup.sh 后直调 lib 函数（变量副作用在同一 shell 生效）。"""
        env = dict(os.environ)
        env['HOME'] = str(self.home)
        for key in list(env):
            if key.startswith('BUDGET_'):
                del env[key]
        return subprocess.run(
            ['bash', '-c', script], cwd=str(self.project), env=env,
            capture_output=True, text=True, encoding='utf-8', check=False,
            timeout=60)

    def test_inject_via_shell_end_to_end(self):
        """经 setup.sh 自动加载 hooks.sh：inject → 备份 + 三事件 + superpowers。"""
        self.write_settings({'theme': 'dark'})
        script = f'''
source "{self.setup_sh}"
budget_inject_hooks
'''
        proc = self.run_setup_shell(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_settings()
        self.assertEqual(len(self.suite_hook_commands(data)), 4)
        self.assertTrue(data['enabledPlugins'][SUPERPOWERS_KEY])
        backup = Path(str(self.settings) + '.bak-budget')
        self.assertTrue(backup.is_file())
        self.assertEqual(load_json(backup), {'theme': 'dark'})

    def test_idempotent_reinject_via_shell(self):
        """重跑注入 → no_change 语义（无重复条目）。"""
        self.test_inject_via_shell_end_to_end()
        script = f'''
source "{self.setup_sh}"
budget_inject_hooks
'''
        proc = self.run_setup_shell(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_settings()
        self.assertEqual(len(self.suite_hook_commands(data)), 4)

    def test_check_and_remove_via_shell(self):
        """check → 注入状态正确；remove → 用户 hooks 保留。"""
        self.write_settings({'hooks': {'Notification': [
            {'matcher': 'permission_prompt',
             'hooks': [{'type': 'command', 'command': 'echo keepme'}]},
        ]}})
        script = f'''
source "{self.setup_sh}"
budget_inject_hooks
budget_remove_hooks
'''
        proc = self.run_setup_shell(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_settings()
        self.assertEqual(self.suite_hook_commands(data), [])
        notification = data['hooks']['Notification']
        self.assertEqual(len(notification), 1)
        self.assertIn('keepme', str(notification[0]['hooks']))
        self.assertNotIn('enabledPlugins', data)

    def test_superpowers_enable_flow_via_shell(self):
        """未启用 → 提示；启用注入 → enabledPlugins 写入；重跑不重复。"""
        script = f'''
source "{self.setup_sh}"
budget_inject_superpowers
'''
        proc = self.run_setup_shell(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('superpowers', proc.stdout)
        data = self.read_settings()
        self.assertTrue(data['enabledPlugins'][SUPERPOWERS_KEY])
        # 再跑一次：已启用 → 提示已启用，无重复写入
        proc2 = self.run_setup_shell(script)
        self.assertIn('已在 settings.json 中启用', proc2.stdout)
        data = self.read_settings()
        self.assertEqual(len(data['enabledPlugins']), 1)

    def test_check_hooks_via_shell(self):
        """budget_check_hooks 输出注入状态两行。"""
        script = f'''
source "{self.setup_sh}"
budget_check_hooks
'''
        proc = self.run_setup_shell(script)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未注入', proc.stdout)
        self.test_inject_via_shell_end_to_end()
        proc = self.run_setup_shell(script)
        self.assertIn('已注入', proc.stdout)
        self.assertIn('已启用', proc.stdout)

    def test_notify_dispatch_via_setup(self):
        """`budget notify` 转发链路：custom 渠道 → 本机回环 mock server 收到消息。"""
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                received.append(self.rfile.read(length).decode('utf-8'))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            notify_cfg = self.project / '.budget' / 'notify.json'
            notify_cfg.parent.mkdir(parents=True, exist_ok=True)
            notify_cfg.write_text(json.dumps({
                'enabled': True,
                'channels': {
                    'mock': {'type': 'custom',
                             'webhook': f'http://127.0.0.1:{port}/hook',
                             'format': 'raw'},
                },
                'events': {'N1': {'enabled': True, 'channels': ['mock']}},
            }), encoding='utf-8')
            proc = self.run_setup('notify', '测试消息 N1', 'N1')
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(received, ['测试消息 N1'])
        finally:
            server.shutdown()
            server.server_close()

    def test_notify_no_config_silent_skip(self):
        """无 notify.json → 静默跳过（提示 + exit 0，不报错）。"""
        proc = self.run_setup('notify', '测试消息', 'N1')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未配置通知', proc.stdout)

    def test_notify_missing_message_usage_error(self):
        """空消息 → 用法报错 exit 1。"""
        proc = self.run_setup('notify')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('用法', proc.stdout)

    def test_status_via_setup(self):
        """`budget status` → do_status 状态查询（平台/数据目录/guard/agent 概览）。"""
        proc = self.run_setup('status')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('codebuddy:project', proc.stdout)
        self.assertIn('Coder Guard', proc.stdout)
        self.assertIn('工作流状态机', proc.stdout)
        self.assertIn('Agent 模型配置', proc.stdout)

    def test_hooks_injection_via_init_stub(self):
        """init.sh 桩契约：budget_inject_hooks 存在时 init 自动调用（T9b 桩生效）。"""
        proc = self.run_setup('init', stdin_text='\n')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_settings()
        self.assertEqual(len(self.suite_hook_commands(data)), 4)
        self.assertTrue(data['enabledPlugins'][SUPERPOWERS_KEY])
        self.assertIn('已注入', proc.stdout)


if __name__ == '__main__':
    unittest.main()
