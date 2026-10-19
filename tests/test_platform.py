#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""platform.sh 三分支探测单测（design.md §8.3）+ setup.sh 分发骨架冒烟。

测试以 subprocess 驱动 bash：临时目录构造三种安装形态（codebuddy 项目级/
全局、opencode 项目级/全局），HOME 环境隔离（剥离 BUDGET_* 变量），验证
detect_platform 输出格式、全局变量副作用、向上查找 10 层边界与探测失败
显式报错；另覆盖 setup.sh 子命令分发骨架（help/show/未知子命令/未就位
模块报错/init shell 分发）与 utils.sh 数据目录、包装器写入函数。
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_LIB = REPO_ROOT / 'core' / 'lib'
CORE_SETUP = REPO_ROOT / 'core' / 'setup.sh'
CORE_MODELS = REPO_ROOT / 'core' / 'models' / 'budget-models.json'

# 本套件 agent 文件名（与 platform.sh BUDGET_SUITE_AGENTS 对齐）。
SUITE_AGENTS = (
    'architect', 'coder-lite', 'coder-standard', 'coder-senior', 'reviewer',
    'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
)

# 基础层 4 文件（setup.sh 硬依赖）。
BASE_LIB_FILES = ('colors.sh', 'utils.sh', 'platform.sh', 'shell.sh')

ALL_SCRIPTS = [CORE_SETUP] + [CORE_LIB / name for name in BASE_LIB_FILES]


def run_bash(script, cwd, home, env_extra=None, stdin_text=None):
    """在指定 cwd/HOME 下运行 bash 脚本（剥离 BUDGET_* 环境变量实现隔离）。"""
    env = dict(os.environ)
    env['HOME'] = str(home)
    for key in list(env):
        if key.startswith('BUDGET_'):
            del env[key]
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ['bash', '-c', script], cwd=str(cwd), env=env,
        capture_output=True, text=True, timeout=60,
        input=stdin_text,
    )


def detect(cwd, home, env_extra=None):
    """source platform.sh 后调用 detect_platform（stdout 为结果字符串）。"""
    script = 'source "%s"; detect_platform' % (CORE_LIB / 'platform.sh')
    return run_bash(script, cwd, home, env_extra)


def detect_vars(cwd, home):
    """当前 shell 调用 detect_platform 并输出全局变量（验证副作用）。"""
    script = (
        'source "%s"; '
        'detect_platform >/dev/null || true; '
        'echo "kind=$BUDGET_PLATFORM_KIND"; '
        'echo "scope=$BUDGET_PLATFORM_SCOPE"; '
        'echo "root=$BUDGET_PLATFORM_ROOT"; '
        'echo "agents=$BUDGET_AGENTS_DIR"'
        % (CORE_LIB / 'platform.sh')
    )
    return run_bash(script, cwd, home)


def make_deep_dir(base, depth):
    """在 base 下构造 depth 层嵌套目录并返回最深层路径。"""
    path = base
    for i in range(depth):
        path = path / ('d%02d' % (i + 1))
    path.mkdir(parents=True)
    return path


def make_codebuddy_install(base):
    """构造 .codebuddy 项目级安装形态（setup.sh + lib 基础层 + agents + models）。"""
    cb = base / '.codebuddy'
    (cb / 'lib').mkdir(parents=True)
    shutil.copy2(CORE_SETUP, cb / 'setup.sh')
    for name in BASE_LIB_FILES:
        shutil.copy2(CORE_LIB / name, cb / 'lib' / name)
    shutil.copy2(CORE_MODELS, cb / 'budget-models.json')
    agents = cb / 'agents'
    agents.mkdir()
    (agents / 'architect.md').write_text(
        '---\nname: architect\nmodel: glm-5.2\n---\n正文\n', encoding='utf-8')
    (agents / 'coder-senior.md').write_text(
        '---\nname: coder-senior\nmodel: deepseek-v4-pro\n---\n正文\n', encoding='utf-8')
    return cb


class SandboxTestCase(unittest.TestCase):
    """公共沙箱：每个用例独立临时目录（项目区 + 隔离 HOME）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-platform-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def resolved(self, path):
        """归一化物理路径（macOS /var → /private/var 符号链接对齐 bash pwd -P）。"""
        return str(Path(path).resolve())


class DetectPlatformCodebuddyTests(SandboxTestCase):
    """分支①②：codebuddy 项目级（向上查找）与全局。"""

    def test_project_level(self):
        (self.tmp / '.codebuddy').mkdir()
        (self.tmp / '.codebuddy' / 'setup.sh').write_text('#!/bin/bash\n')
        sub = self.tmp / 'sub'
        sub.mkdir()
        proc = detect(sub, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'codebuddy:project:%s' % self.resolved(self.tmp))

    def test_project_level_upward_from_deep(self):
        (self.tmp / '.codebuddy').mkdir()
        (self.tmp / '.codebuddy' / 'setup.sh').write_text('#!/bin/bash\n')
        deep = make_deep_dir(self.tmp, 5)
        proc = detect(deep, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'codebuddy:project:%s' % self.resolved(self.tmp))

    def test_project_level_upward_limit_10(self):
        """向上查找最多 10 层：9 层深度命中（第 10 次迭代检查项目根）。"""
        (self.tmp / '.codebuddy').mkdir()
        (self.tmp / '.codebuddy' / 'setup.sh').write_text('#!/bin/bash\n')
        deep9 = make_deep_dir(self.tmp, 9)
        proc = detect(deep9, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'codebuddy:project:%s' % self.resolved(self.tmp))

    def test_project_level_upward_limit_exceeded(self):
        """10 层深度不命中（第 11 层的项目根超出查找窗口）→ 显式报错。"""
        (self.tmp / '.codebuddy').mkdir()
        (self.tmp / '.codebuddy' / 'setup.sh').write_text('#!/bin/bash\n')
        deep10 = make_deep_dir(self.tmp, 10)
        proc = detect(deep10, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout.strip(), 'unknown')
        self.assertIn('未检测到', proc.stderr)

    def test_global_level(self):
        (self.home / '.codebuddy').mkdir()
        (self.home / '.codebuddy' / 'setup.sh').write_text('#!/bin/bash\n')
        proc = detect(self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'codebuddy:global')

    def test_project_preferred_over_global(self):
        (self.tmp / '.codebuddy').mkdir()
        (self.tmp / '.codebuddy' / 'setup.sh').write_text('#!/bin/bash\n')
        (self.home / '.codebuddy').mkdir()
        (self.home / '.codebuddy' / 'setup.sh').write_text('#!/bin/bash\n')
        proc = detect(self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'codebuddy:project:%s' % self.resolved(self.tmp))

    def test_project_level_sets_vars(self):
        (self.tmp / '.codebuddy').mkdir()
        (self.tmp / '.codebuddy' / 'setup.sh').write_text('#!/bin/bash\n')
        sub = self.tmp / 'sub'
        sub.mkdir()
        proc = detect_vars(sub, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = [
            'kind=codebuddy',
            'scope=project',
            'root=%s' % self.resolved(self.tmp),
            'agents=%s/.codebuddy/agents' % self.resolved(self.tmp),
        ]
        self.assertEqual(proc.stdout.splitlines(), expected)

    def test_global_sets_vars(self):
        (self.home / '.codebuddy').mkdir()
        (self.home / '.codebuddy' / 'setup.sh').write_text('#!/bin/bash\n')
        proc = detect_vars(self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = [
            'kind=codebuddy',
            'scope=global',
            'root=',
            'agents=%s/.codebuddy/agents' % self.home,
        ]
        self.assertEqual(proc.stdout.splitlines(), expected)


class DetectPlatformOpencodeTests(SandboxTestCase):
    """分支③：opencode 项目级（优先）/ 全局。"""

    def test_project_level(self):
        agent_dir = self.tmp / '.opencode' / 'agent'
        agent_dir.mkdir(parents=True)
        (agent_dir / 'architect.md').write_text('---\n---\n')
        sub = self.tmp / 'sub'
        sub.mkdir()
        proc = detect(sub, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'opencode:project')

    def test_project_level_upward_from_deep(self):
        agent_dir = self.tmp / '.opencode' / 'agent'
        agent_dir.mkdir(parents=True)
        (agent_dir / 'coder-senior.md').write_text('---\n---\n')
        deep = make_deep_dir(self.tmp, 3)
        proc = detect(deep, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'opencode:project')

    def test_global_level(self):
        agent_dir = self.home / '.config' / 'opencode' / 'agent'
        agent_dir.mkdir(parents=True)
        (agent_dir / 'reviewer.md').write_text('---\n---\n')
        proc = detect(self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'opencode:global')

    def test_project_preferred_over_global(self):
        project_agents = self.tmp / '.opencode' / 'agent'
        project_agents.mkdir(parents=True)
        (project_agents / 'architect.md').write_text('---\n---\n')
        global_agents = self.home / '.config' / 'opencode' / 'agent'
        global_agents.mkdir(parents=True)
        (global_agents / 'architect.md').write_text('---\n---\n')
        proc = detect(self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'opencode:project')

    def test_empty_agent_dir_not_matched(self):
        (self.tmp / '.opencode' / 'agent').mkdir(parents=True)
        proc = detect(self.work, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout.strip(), 'unknown')

    def test_non_suite_agent_not_matched(self):
        agent_dir = self.tmp / '.opencode' / 'agent'
        agent_dir.mkdir(parents=True)
        (agent_dir / 'some-other-agent.md').write_text('---\n---\n')
        proc = detect(self.work, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout.strip(), 'unknown')

    def test_project_level_sets_vars(self):
        agent_dir = self.tmp / '.opencode' / 'agent'
        agent_dir.mkdir(parents=True)
        (agent_dir / 'goal-evaluator.md').write_text('---\n---\n')
        sub = self.tmp / 'sub'
        sub.mkdir()
        proc = detect_vars(sub, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = [
            'kind=opencode',
            'scope=project',
            'root=%s' % self.resolved(self.tmp),
            'agents=%s/.opencode/agent' % self.resolved(self.tmp),
        ]
        self.assertEqual(proc.stdout.splitlines(), expected)

    def test_global_sets_vars(self):
        agent_dir = self.home / '.config' / 'opencode' / 'agent'
        agent_dir.mkdir(parents=True)
        (agent_dir / 'tester.md').write_text('---\n---\n')
        proc = detect_vars(self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = [
            'kind=opencode',
            'scope=global',
            'root=',
            'agents=%s/.config/opencode/agent' % self.home,
        ]
        self.assertEqual(proc.stdout.splitlines(), expected)


class DetectPlatformFailureTests(SandboxTestCase):
    """三级均未命中：显式报错并列出已检测位置，不静默猜默认。"""

    def test_unknown_returns_nonzero(self):
        proc = detect(self.work, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout.strip(), 'unknown')

    def test_stderr_lists_checked_locations(self):
        proc = detect(self.work, self.home)
        self.assertIn('未检测到', proc.stderr)
        self.assertIn('已检测位置', proc.stderr)
        self.assertIn('.codebuddy/setup.sh', proc.stderr)
        self.assertIn('.opencode/agent/', proc.stderr)
        self.assertIn('.config/opencode/agent', proc.stderr)

    def test_failure_clears_vars(self):
        proc = detect_vars(self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = ['kind=unknown', 'scope=', 'root=', 'agents=']
        self.assertEqual(proc.stdout.splitlines(), expected)


class DetectPlatformEnvOverrideTests(SandboxTestCase):
    """BUDGET_PLATFORM 显式覆盖（codebuddy|opencode；非法值忽略）。"""

    def test_budget_platform_codebuddy(self):
        proc = detect(self.work, self.home, env_extra={'BUDGET_PLATFORM': 'codebuddy'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'codebuddy:global')

    def test_budget_platform_opencode(self):
        proc = detect(self.work, self.home, env_extra={'BUDGET_PLATFORM': 'opencode'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'opencode:global')

    def test_budget_platform_invalid_ignored(self):
        proc = detect(self.work, self.home, env_extra={'BUDGET_PLATFORM': 'invalid'})
        self.assertEqual(proc.returncode, 1)
        self.assertIn('非法', proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'unknown')

    def test_budget_platform_overrides_file_detection(self):
        (self.tmp / '.codebuddy').mkdir()
        (self.tmp / '.codebuddy' / 'setup.sh').write_text('#!/bin/bash\n')
        proc = detect(self.work, self.home, env_extra={'BUDGET_PLATFORM': 'opencode'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'opencode:global')


class SetupDispatchSmokeTests(SandboxTestCase):
    """setup.sh 分发骨架冒烟：bash -n、help、show、未知子命令、未就位模块。"""

    def test_bash_n_all_scripts(self):
        for script in ALL_SCRIPTS:
            proc = subprocess.run(
                ['bash', '-n', str(script)], capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, '%s: %s' % (script, proc.stderr))

    def test_help_outputs_full_subcommand_set(self):
        proc = run_bash('bash "%s" help' % CORE_SETUP, self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for subcommand in (
                'init', 'show', 'status', 'agent', 'persona', 'validate', 'diff',
                'stats', 'update', 'reinstall', 'uninstall', 'guard', 'quickstart',
                'models', 'notify', 'help', 'tour', 'wizard'):
            self.assertIn(subcommand, proc.stdout, 'help 缺少子命令 %s' % subcommand)
        self.assertIn('BUDGET_GLOBAL', proc.stdout)
        self.assertIn('BUDGET_DIR', proc.stdout)
        self.assertIn('BUDGET_PLATFORM', proc.stdout)

    def test_no_args_defaults_to_help(self):
        proc = run_bash('bash "%s"' % CORE_SETUP, self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('子命令全集', proc.stdout)

    def test_unknown_subcommand_friendly_error(self):
        proc = run_bash('bash "%s" badcmd' % CORE_SETUP, self.work, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未知子命令: badcmd', proc.stdout)
        self.assertIn('子命令全集', proc.stdout)  # 友好报错：附带帮助

    def test_show_smoke_installed_form(self):
        """临时目录构造 .codebuddy 安装形态，show 冒烟（读 agent 与 models）。"""
        make_codebuddy_install(self.tmp)
        sub = self.tmp / 'sub'
        sub.mkdir()
        proc = run_bash('bash "%s" show' % (self.tmp / '.codebuddy' / 'setup.sh'), sub, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('codebuddy:project', proc.stdout)
        self.assertIn('architect', proc.stdout)
        self.assertIn('glm-5.2', proc.stdout)
        self.assertIn('coder-senior', proc.stdout)
        self.assertIn('deepseek-v4-pro', proc.stdout)
        self.assertIn('architect', proc.stdout.split('Model Role')[1])  # 反查角色列

    def test_show_smoke_core_source_form(self):
        """core 源形态直接跑 show（探测失败降级，仍可跑不崩溃）。"""
        proc = run_bash('bash "%s" show' % CORE_SETUP, REPO_ROOT, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('BudgetBuddy', proc.stdout)
        # core 源形态探测不到安装形态 → 降级提示；models 文件经源形态路径读取
        self.assertIn('模型目录', proc.stdout)

    def test_models_command_reads_catalog(self):
        make_codebuddy_install(self.tmp)
        proc = run_bash(
            'bash "%s" models' % (self.tmp / '.codebuddy' / 'setup.sh'),
            self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('付费模型', proc.stdout)
        self.assertIn('免费模型', proc.stdout)
        self.assertIn('别名', proc.stdout)
        self.assertIn('预设', proc.stdout)

    def test_init_module_not_installed(self):
        make_codebuddy_install(self.tmp)
        proc = run_bash(
            'bash "%s" init' % (self.tmp / '.codebuddy' / 'setup.sh'),
            self.tmp, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("子命令 'init' 的实现模块尚未安装", proc.stdout)
        self.assertIn('lib/init.sh', proc.stdout)

    def test_update_module_not_installed(self):
        make_codebuddy_install(self.tmp)
        proc = run_bash(
            'bash "%s" update' % (self.tmp / '.codebuddy' / 'setup.sh'),
            self.tmp, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("子命令 'update' 的实现模块尚未安装", proc.stdout)
        self.assertIn('lib/update.sh', proc.stdout)

    def test_uninstall_module_not_installed(self):
        make_codebuddy_install(self.tmp)
        proc = run_bash(
            'bash "%s" uninstall' % (self.tmp / '.codebuddy' / 'setup.sh'),
            self.tmp, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("子命令 'uninstall' 的实现模块尚未安装", proc.stdout)

    def test_agent_module_not_installed(self):
        make_codebuddy_install(self.tmp)
        proc = run_bash(
            'bash "%s" agent preset balanced' % (self.tmp / '.codebuddy' / 'setup.sh'),
            self.tmp, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("子命令 'agent' 的实现模块尚未安装", proc.stdout)
        self.assertIn('lib/preset.sh', proc.stdout)

    def test_notify_module_not_installed(self):
        make_codebuddy_install(self.tmp)
        proc = run_bash(
            'bash "%s" notify "msg" n8' % (self.tmp / '.codebuddy' / 'setup.sh'),
            self.tmp, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("子命令 'notify' 的实现模块尚未安装", proc.stdout)
        self.assertIn('lib/notify.sh', proc.stdout)

    def test_quickstart_module_not_installed(self):
        make_codebuddy_install(self.tmp)
        proc = run_bash(
            'bash "%s" quickstart' % (self.tmp / '.codebuddy' / 'setup.sh'),
            self.tmp, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("子命令 'quickstart' 的实现模块尚未安装", proc.stdout)
        self.assertIn('lib/quickstart.py', proc.stdout)

    def test_init_shell_dispatches_to_shell_module(self):
        """init shell 分发到 shell.sh（本任务就位）：EOF stdin 走默认选项。"""
        make_codebuddy_install(self.tmp)
        proc = run_bash(
            'bash "%s" init shell' % (self.tmp / '.codebuddy' / 'setup.sh'),
            self.tmp, self.home, stdin_text='')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rc = self.home / '.zshrc'
        if not rc.exists():  # SHELL 非 zsh 时落 .bashrc
            rc = self.home / '.bashrc'
        content = rc.read_text(encoding='utf-8')
        self.assertIn('configured by BudgetBuddy', content)
        self.assertIn('alias cbc=', content)
        self.assertIn('alias codebuddy=', content)


class UtilsDataDirTests(SandboxTestCase):
    """utils.sh 数据目录约定（design.md §8.4）与 JSON 读取。"""

    def _source_utils(self, cwd, home, env_extra=None):
        script = 'source "%s"' % (CORE_LIB / 'utils.sh')
        return run_bash(script, cwd, home, env_extra)

    def test_data_dir_env_override(self):
        proc = run_bash(
            'source "%s"; BUDGET_DIR=/tmp/custom-data budget_data_dir' % (CORE_LIB / 'utils.sh'),
            self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '/tmp/custom-data')

    def test_data_dir_project_level_preferred(self):
        (self.tmp / '.budget').mkdir()
        sub = self.tmp / 'sub'
        sub.mkdir()
        proc = run_bash(
            'source "%s"; budget_data_dir' % (CORE_LIB / 'utils.sh'), sub, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '%s/.budget' % self.resolved(self.tmp))

    def test_data_dir_fallback_to_global(self):
        proc = run_bash(
            'source "%s"; budget_data_dir' % (CORE_LIB / 'utils.sh'), self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '%s/.budgetbuddy' % self.home)

    def test_global_data_dir_fixed(self):
        proc = run_bash(
            'source "%s"; budget_global_data_dir' % (CORE_LIB / 'utils.sh'),
            self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '%s/.budgetbuddy' % self.home)

    def test_project_data_dir_not_found_empty(self):
        proc = run_bash(
            'source "%s"; budget_project_data_dir' % (CORE_LIB / 'utils.sh'),
            self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '')

    def test_json_get_nested_field(self):
        proc = run_bash(
            'source "%s"; budget_json_get "%s" platforms.codebuddy.presets.balanced.architect' % (
                CORE_LIB / 'utils.sh', CORE_MODELS),
            self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'glm-5.2')

    def test_json_get_missing_path_returns_default(self):
        proc = run_bash(
            'source "%s"; budget_json_get "%s" no.such.path fallback-val' % (
                CORE_LIB / 'utils.sh', CORE_MODELS),
            self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'fallback-val')

    def test_json_get_missing_file_returns_default(self):
        proc = run_bash(
            'source "%s"; budget_json_get "%s" a.b default-x' % (
                CORE_LIB / 'utils.sh', self.tmp / 'nope.json'),
            self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'default-x')


class UtilsWrapperTests(SandboxTestCase):
    """budget CLI 包装器写入函数（写入逻辑归 init 流程 T9b 调用，本任务提供函数）。"""

    def _install_wrapper(self, home):
        return run_bash(
            'source "%s"; budget_install_wrapper' % (CORE_LIB / 'utils.sh'),
            self.work, home)

    def test_wrapper_written_executable_with_marker(self):
        proc = self._install_wrapper(self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        wrapper = self.home / '.local' / 'bin' / 'budget'
        self.assertTrue(wrapper.is_file())
        self.assertTrue(os.access(wrapper, os.X_OK))
        content = wrapper.read_text(encoding='utf-8')
        self.assertIn('BUDGET_WRAPPER_MARKER', content)
        self.assertIn('.codebuddy/setup.sh', content)
        self.assertIn('.budgetbuddy/setup.sh', content)  # opencode 管理面 fallback

    def test_wrapper_install_idempotent(self):
        self._install_wrapper(self.home)
        wrapper = self.home / '.local' / 'bin' / 'budget'
        first = wrapper.read_text(encoding='utf-8')
        proc = self._install_wrapper(self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        second = wrapper.read_text(encoding='utf-8')
        self.assertEqual(first, second)
        # 幂等重装不产生多余文件（无坏符号链接）
        entries = sorted(p.name for p in (self.home / '.local' / 'bin').iterdir())
        self.assertEqual(entries, ['budget'])

    def test_wrapper_replaces_stale_symlink(self):
        """旧版软链接场景：先删后写，不跟随链接覆盖目标本体。"""
        bin_dir = self.home / '.local' / 'bin'
        bin_dir.mkdir(parents=True)
        target = self.home / 'setup-body.sh'
        target.write_text('#!/bin/bash\n# body\n', encoding='utf-8')
        (bin_dir / 'budget').symlink_to(target)
        proc = self._install_wrapper(self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        wrapper = bin_dir / 'budget'
        self.assertFalse(wrapper.is_symlink())
        self.assertIn('BUDGET_WRAPPER_MARKER', wrapper.read_text(encoding='utf-8'))
        # 链接目标本体未被覆盖
        self.assertEqual(target.read_text(encoding='utf-8'), '#!/bin/bash\n# body\n')


class ShellIntegrationTests(SandboxTestCase):
    """shell.sh：rc 检测与 budget() 函数幂等注入。"""

    def test_detect_shell_rc_zsh(self):
        proc = run_bash(
            'source "%s"; budget_detect_shell_rc' % (CORE_LIB / 'shell.sh'),
            self.work, self.home, env_extra={'SHELL': '/bin/zsh'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '%s/.zshrc' % self.home)

    def test_detect_shell_rc_bash(self):
        proc = run_bash(
            'source "%s"; budget_detect_shell_rc' % (CORE_LIB / 'shell.sh'),
            self.work, self.home, env_extra={'SHELL': '/bin/bash'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '%s/.bashrc' % self.home)

    def test_detect_shell_rc_unsupported(self):
        proc = run_bash(
            'source "%s"; budget_detect_shell_rc' % (CORE_LIB / 'shell.sh'),
            self.work, self.home, env_extra={'SHELL': '/usr/local/bin/fish'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '')

    def test_inject_func_idempotent(self):
        rc = self.home / '.zshrc'
        rc.write_text('# user content\n', encoding='utf-8')
        script = 'source "%s"; budget_inject_func' % (CORE_LIB / 'shell.sh')
        proc = run_bash(script, self.work, self.home, env_extra={'SHELL': '/bin/zsh'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        content = rc.read_text(encoding='utf-8')
        self.assertIn('# user content', content)  # 区块外内容不变
        self.assertEqual(content.count('budget() {'), 1)
        # 重跑幂等：函数块唯一
        proc = run_bash(script, self.work, self.home, env_extra={'SHELL': '/bin/zsh'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        content = rc.read_text(encoding='utf-8')
        self.assertEqual(content.count('budget() {'), 1)
        self.assertIn('# user content', content)


class ColorsSmokeTests(SandboxTestCase):
    """colors.sh 基础冒烟：管道重定向下颜色禁用、文本保留。"""

    def test_print_functions_output_text(self):
        script = (
            'source "%s"; '
            'budget_print_success "ok-msg"; '
            'budget_print_info "info-msg"; '
            'budget_print_warning "warn-msg"; '
            'budget_print_error "err-msg"; '
            'budget_print_header' % (CORE_LIB / 'colors.sh')
        )
        proc = run_bash(script, self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for text in ('ok-msg', 'info-msg', 'warn-msg', 'err-msg', 'BudgetBuddy'):
            self.assertIn(text, proc.stdout)
        # capture_output（非 tty）下颜色码禁用
        self.assertNotIn('\033[', proc.stdout)

    def test_detect_os_current(self):
        proc = run_bash(
            'source "%s"; budget_detect_os' % (CORE_LIB / 'platform.sh'),
            self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(proc.stdout.strip(), ('macos', 'linux', 'windows', 'unknown'))


if __name__ == '__main__':
    unittest.main()
