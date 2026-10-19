#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""update.sh / uninstall.sh 单测（design.md §8.1/§10/§12-A9/§12-A12②；
specs/setup-cli「setup.sh 子命令体系」update/uninstall/reinstall/diff 部分）。

临时 HOME + 目录构造安装形态，subprocess 驱动 bash：
- do_update：增量更新（lib 同步/管理面覆盖刷新/用户数据保留/hooks 桩/
  diff 展示/幂等/非交互三通道/探测失败显式报错）
- do_diff：当前 vs 预设对比表（一致/差异/未设置/不在安装中/非法预设名）
- do_uninstall：双路径删除（本地清单/已知结构）+ 用户数据默认保留
  （--purge 显式删除）+ 幂等 + opencode 形态（管理面/结构目录/AGENTS.md
  标记区块）
- do_reinstall：uninstall（不 purge）+ init 组合（两级回退）
- 四命令端到端（update → diff → uninstall → reinstall）
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_LIB = REPO_ROOT / 'core' / 'lib'
CORE_SETUP = REPO_ROOT / 'core' / 'setup.sh'
CORE_MODELS = REPO_ROOT / 'core' / 'models' / 'budget-models.json'
CORE_PERSONAS = REPO_ROOT / 'core' / 'personas' / 'personas.json'
CORE_AGENTS = REPO_ROOT / 'core' / 'agents'

with open(CORE_MODELS, encoding='utf-8') as _handle:
    MODELS_DATA = json.load(_handle)

# 安装形态所需 lib 文件（基础层 4 + 生命周期 3 + preset/models/resolver）
LIB_FILES = (
    'colors.sh', 'utils.sh', 'platform.sh', 'shell.sh',
    'init.sh', 'update.sh', 'uninstall.sh',
    'models.sh', 'preset.sh', 'model_resolver.py',
)

# codebuddy 已知结构产物（uninstall 已知结构清单断言基准）
SUITE_AGENTS = (
    'architect', 'coder-lite', 'coder-standard', 'coder-senior', 'reviewer',
    'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
)
SUITE_SKILLS = (
    'budget-notify', 'budget-workflow',
    'openspec-apply-change', 'openspec-archive-change',
    'openspec-explore', 'openspec-propose',
)
SUITE_COMMANDS_BUDGET = ('goal.md', 'start.md', 'status.md')
SUITE_COMMANDS_OPSX = ('apply.md', 'archive.md', 'explore.md', 'propose.md')

AGENT_TMPL = '''---
name: {name}
description: MUST BE USED — {name} 测试 agent。
model: {model}
tools: [Read, Write, Edit, Bash, Grep, Glob]
permissionMode: acceptEdits
max_turns: 35
---

{name} 的正文内容（卸载/更新不得触碰）。
'''


def expected_preset(platform, preset_name):
    """从 budget-models.json 取预设期望值：{agent 文件名: model}。"""
    preset = MODELS_DATA['platforms'][platform]['presets'][preset_name]
    return {role.replace('_', '-'): model for role, model in preset.items()}


def run_setup(setup_sh, cwd, home, args=None, stdin_text='', env_extra=None):
    """经 setup.sh 分发入口执行子命令（模拟 budget setup <cmd>）。

    注：setup.sh 分发层对 update/uninstall/reinstall 无参透传（T9a 契约），
    非交互与 purge 经 BUDGET_* 环境变量通道传递（与 BUDGET_INIT_YES 同族）。
    """
    env = dict(os.environ)
    env['HOME'] = str(home)
    env['SHELL'] = '/bin/zsh'  # rc 文件落点固定 .zshrc，断言不受本机 SHELL 影响
    for key in list(env):
        if key.startswith('BUDGET_'):
            del env[key]
    # 剥离 IDE safe-delete 注入（BASH_ENV 函数 + PATH shim + 会话 ID）：
    # 包装版 rm/rmdir/unlink 单次调用 ~150ms（python3 转义 + 回收站投递），
    # 一次 uninstall 40+ 次删除累积 ~19s；且回收站投递失败时 rm 返回非零，
    # uninstall 的删除会静默跳过（时序性断言失败）。测试需验证原生删除语义。
    for key in ('BASH_ENV', 'CODEBUDDY_SESSION_ID', 'CLAUDE_SESSION_ID',
                'CODEBUDDY_SAFE_DELETE_BIN_DIR', 'CODEBUDDY_SAFE_DELETE_REPORT_PATH'):
        env.pop(key, None)
    env['PATH'] = ':'.join(
        p for p in env.get('PATH', '').split(':')
        if p and '/shim/safe-bin' not in p)
    if env_extra:
        env.update(env_extra)
    cmd = ['bash', str(setup_sh)] + list(args or [])
    return subprocess.run(
        cmd, cwd=str(cwd), env=env, capture_output=True, text=True,
        timeout=180, input=stdin_text,
    )


def run_update(setup_sh, cwd, home, stdin_text='', env_extra=None):
    """非交互 update（BUDGET_UPDATE_YES=1 环境变量通道）。"""
    env = {'BUDGET_UPDATE_YES': '1'}
    if env_extra:
        env.update(env_extra)
    return run_setup(setup_sh, cwd, home, args=['update'],
                     stdin_text=stdin_text, env_extra=env)


def run_uninstall(setup_sh, cwd, home, purge=False, stdin_text='', env_extra=None):
    """非交互 uninstall（BUDGET_UNINSTALL_YES=1；purge 加 BUDGET_UNINSTALL_PURGE=1）。"""
    env = {'BUDGET_UNINSTALL_YES': '1'}
    if purge:
        env['BUDGET_UNINSTALL_PURGE'] = '1'
    if env_extra:
        env.update(env_extra)
    return run_setup(setup_sh, cwd, home, args=['uninstall'],
                     stdin_text=stdin_text, env_extra=env)


def run_reinstall(setup_sh, cwd, home, stdin_text='', env_extra=None):
    """非交互 reinstall（BUDGET_REINSTALL_YES=1 环境变量通道）。"""
    env = {'BUDGET_REINSTALL_YES': '1'}
    if env_extra:
        env.update(env_extra)
    return run_setup(setup_sh, cwd, home, args=['reinstall'],
                     stdin_text=stdin_text, env_extra=env)


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def copy_lib(dest_dir):
    """lib 文件集拷贝（基础层 + 生命周期 + preset/models/resolver）。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in LIB_FILES:
        shutil.copy2(CORE_LIB / name, dest_dir / name)


# hooks 清理/恢复链路模块（P1-1 用例形态所需）
HOOKS_LIB_FILES = LIB_FILES + ('hooks.sh', 'hooks_inject.py')
HOOK_MARKER = 'budget-notify-hook.py'
SUPERPOWERS_KEY = 'superpowers@codebuddy-plugins-official'
HOOK_CMD_PROJECT = ('test -f .codebuddy/hooks/budget-notify-hook.py '
                    '&& python3 .codebuddy/hooks/budget-notify-hook.py || exit 0')


def copy_lib_with_hooks(dest_dir):
    """lib 文件集拷贝（含 hooks.sh / hooks_inject.py 清理链路模块）。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in HOOKS_LIB_FILES:
        shutil.copy2(CORE_LIB / name, dest_dir / name)


def inject_hooks(settings_file):
    """引擎直调注入三事件 + superpowers（模拟安装后 settings.json 状态）。"""
    env = dict(os.environ)
    env['SETTINGS_FILE'] = str(settings_file)
    env['ACTION'] = 'inject_all'
    env['HOOK_CMD'] = HOOK_CMD_PROJECT
    proc = subprocess.run(
        [sys.executable, str(CORE_LIB / 'hooks_inject.py')],
        env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr


def suite_hook_commands(data):
    """收集 settings.json 中本套件 hook 条目的 command 串。"""
    commands = []
    for matchers in (data.get('hooks') or {}).values():
        for matcher in matchers:
            for hook in matcher.get('hooks', []):
                cmd = str(hook.get('command', ''))
                if HOOK_MARKER in cmd:
                    commands.append(cmd)
    return commands


def make_codebuddy_install(base, with_agents=False):
    """构造 .codebuddy 项目级安装形态（setup.sh + lib + models + personas
    [+ agents]；agents 缺省为空目录——diff 输出「不在安装中」）。"""
    cb = base / '.codebuddy'
    copy_lib(cb / 'lib')
    shutil.copy2(CORE_SETUP, cb / 'setup.sh')
    shutil.copy2(CORE_MODELS, cb / 'budget-models.json')
    shutil.copy2(CORE_PERSONAS, cb / 'personas.json')
    agents_dir = cb / 'agents'
    agents_dir.mkdir(parents=True, exist_ok=True)
    if with_agents:
        for name in SUITE_AGENTS:
            shutil.copy2(CORE_AGENTS / f'{name}.md', agents_dir / f'{name}.md')
    return cb


def make_full_suite_products(cb):
    """在 .codebuddy/ 下补全已知结构产物（commands/skills/rules/hooks/docs）。"""
    for name in SUITE_COMMANDS_BUDGET:
        write_text(cb / 'commands' / 'budget' / name, f'# {name}\n')
    for name in SUITE_COMMANDS_OPSX:
        write_text(cb / 'commands' / 'opsx' / name, f'# {name}\n')
    for skill in SUITE_SKILLS:
        write_text(cb / 'skills' / skill / 'SKILL.md', f'# {skill}\n')
    for rule in ('budget-coder-guard.mdc', 'budget-go-style.mdc'):
        write_text(cb / 'rules' / rule, f'# {rule}\n')
    write_text(cb / 'hooks' / 'budget-notify-hook.py', '# hook\n')
    write_text(cb / 'docs' / 'MODEL_SELECTION.md', '# models\n')
    write_text(cb / 'docs' / 'PERSONAS.md', '# personas\n')


def make_user_custom_files(cb):
    """构造用户自建文件（uninstall 后必须保留）。"""
    write_text(cb / 'agents' / 'my-agent.md', '# my agent\n')
    write_text(cb / 'commands' / 'my-cmd' / 'help.md', '# my cmd\n')
    write_text(cb / 'skills' / 'my-skill' / 'SKILL.md', '# my skill\n')
    write_text(cb / 'rules' / 'my-rule.mdc', '# my rule\n')
    write_text(cb / 'lib' / 'my-lib.sh', '# my lib\n')


def make_user_data(base, home):
    """构造用户数据（.budget/ 项目级 + ~/.budgetbuddy/ 全局）。"""
    persona = {'theme': 'sanguo', 'greeting': '主公', 'roles': {}, 'report_templates': {}}
    write_text(base / '.budget' / 'persona-active.json',
               json.dumps(persona, ensure_ascii=False, indent=2))
    write_text(base / '.budget' / 'notify.json',
               json.dumps({'enabled': True, 'channels': {}, 'events': {}},
                          ensure_ascii=False, indent=2))
    write_text(base / '.budget' / 'memory' / 'goal-state.json', '{}')
    write_text(home / '.budgetbuddy' / 'projects' / 'demo' / 'memory' / 'coder-guard.json',
               '{}')


class UpdateSandboxTestCase(unittest.TestCase):
    """公共沙箱：每个用例独立临时目录（项目区 + 隔离 HOME）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-update-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def load_json(self, path):
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)

    def read_text(self, path):
        return Path(path).read_text(encoding='utf-8')


class SyntaxTests(UpdateSandboxTestCase):
    """bash -n 语法冒烟（任务硬性约束）。"""

    def test_bash_n_update_sh(self):
        proc = subprocess.run(
            ['bash', '-n', str(CORE_LIB / 'update.sh')],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_bash_n_uninstall_sh(self):
        proc = subprocess.run(
            ['bash', '-n', str(CORE_LIB / 'uninstall.sh')],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class UpdateCodebuddyProjectTests(UpdateSandboxTestCase):
    """do_update 主场景：codebuddy 项目级形态增量更新。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp)
        self.proc = run_update(self.cb / 'setup.sh', self.tmp, self.home)

    def test_exit_zero_and_platform_detected(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertIn('codebuddy:project', self.proc.stdout)
        self.assertIn('更新完成', self.proc.stdout)

    def test_lib_synced_to_global_single_point(self):
        """lib 全局单点同步（A4：skill 引用 $HOME/.budgetbuddy/lib/）。"""
        for name in LIB_FILES:
            self.assertTrue((self.home / '.budgetbuddy' / 'lib' / name).is_file(),
                            'lib 未同步 %s' % name)
        self.assertIn('已同步 lib 模块', self.proc.stdout)

    def test_admin_data_skipped_for_project_form(self):
        """codebuddy:project 形态管理面数据在安装目录，不落全局（对齐 init）。"""
        self.assertIn('管理面数据位于安装目录', self.proc.stdout)
        self.assertFalse((self.home / '.budgetbuddy' / 'budget-models.json').exists())

    def test_user_data_preserved(self):
        """用户数据（persona-active/notify/memory）不触碰（P0）。"""
        make_user_data(self.tmp, self.home)
        proc = run_update(self.cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.load_json(self.tmp / '.budget' / 'persona-active.json')['theme'],
                         'sanguo')
        self.assertTrue(self.load_json(self.tmp / '.budget' / 'notify.json')['enabled'])
        self.assertTrue((self.tmp / '.budget' / 'memory' / 'goal-state.json').is_file())

    def test_hooks_stub_hint(self):
        """hooks 注入桩提示（hooks_inject.py 归 T10d，本任务调用点 + 桩）。"""
        self.assertIn('hooks 注入模块未安装', self.proc.stdout)

    def test_diff_rendered_in_update(self):
        """Step 5 调用 diff 展示（agent model 变化提示）。"""
        self.assertIn('agent model 配置对比', self.proc.stdout)
        self.assertIn('不在安装中', self.proc.stdout)

    def test_idempotent_rerun(self):
        """重复 update 不报错（幂等硬性约束）。"""
        proc = run_update(self.cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已同步 lib 模块', proc.stdout)


class UpdateAdminRefreshTests(UpdateSandboxTestCase):
    """do_update 管理面覆盖刷新（与 init 的「存在即保留」相反）。"""

    def _make_global_install(self):
        cb = self.home / '.codebuddy'
        copy_lib(cb / 'lib')
        shutil.copy2(CORE_SETUP, cb / 'setup.sh')
        shutil.copy2(CORE_MODELS, cb / 'budget-models.json')
        shutil.copy2(CORE_PERSONAS, cb / 'personas.json')
        return cb

    def test_admin_data_refreshed_with_overwrite_semantics(self):
        """codebuddy 全局形态：全局目录旧版 models/personas 被覆盖刷新。"""
        cb = self._make_global_install()
        # 预置全局目录旧版管理面数据（模拟用户本地修改/旧版本）
        stale = self.load_json(CORE_MODELS)
        stale['_meta']['updated_at'] = '2000-01-01'
        write_text(self.home / '.budgetbuddy' / 'budget-models.json',
                   json.dumps(stale, ensure_ascii=False, indent=2))
        stale_personas = self.load_json(CORE_PERSONAS)
        stale_personas['_meta']['default_theme'] = 'nonexistent'
        write_text(self.home / '.budgetbuddy' / 'personas.json',
                   json.dumps(stale_personas, ensure_ascii=False, indent=2))

        proc = run_update(cb / 'setup.sh', self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('codebuddy:global', proc.stdout)
        self.assertIn('已刷新 模型目录', proc.stdout)
        self.assertIn('已刷新 persona 主题数据', proc.stdout)
        # 覆盖语义：刷新为安装目录版本（与源一致）
        self.assertEqual(self.load_json(self.home / '.budgetbuddy' / 'budget-models.json'),
                         self.load_json(CORE_MODELS))
        self.assertEqual(self.load_json(self.home / '.budgetbuddy' / 'personas.json'),
                         self.load_json(CORE_PERSONAS))

    def test_admin_data_skip_when_identical(self):
        """内容一致时跳过刷新（幂等）。"""
        cb = self._make_global_install()
        run_update(cb / 'setup.sh', self.work, self.home)
        proc = run_update(cb / 'setup.sh', self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已是最新，跳过', proc.stdout)

    def test_global_mode_unknown_platform_proceeds(self):
        """BUDGET_GLOBAL=1 + 探测失败：仅全局数据同步（与 init 分支对齐）。"""
        proc = run_update(CORE_SETUP, self.work, self.home,
                          env_extra={'BUDGET_GLOBAL': '1'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('BUDGET_GLOBAL=1 全局模式', proc.stdout)
        self.assertIn('跳过 diff 展示', proc.stdout)
        # 全局同步生效：core 源 lib + 管理面数据落全局
        self.assertTrue((self.home / '.budgetbuddy' / 'lib' / 'update.sh').is_file())
        self.assertTrue((self.home / '.budgetbuddy' / 'budget-models.json').is_file())
        self.assertTrue((self.home / '.budgetbuddy' / 'personas.json').is_file())

    def test_unknown_platform_fails_with_explicit_error(self):
        """探测失败 + 非 BUDGET_GLOBAL：显式报错退出（不静默猜默认）。"""
        proc = run_update(CORE_SETUP, self.work, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未检测到 BudgetBuddy 安装形态', proc.stdout)
        self.assertFalse((self.home / '.budgetbuddy').exists())


class UpdateInteractiveTests(UpdateSandboxTestCase):
    """update 交互确认与非交互三通道。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp)

    def test_interactive_decline_no_side_effects(self):
        """stdin 回答 n：取消且不做任何修改。"""
        proc = run_setup(self.cb / 'setup.sh', self.tmp, self.home,
                         args=['update'], stdin_text='n\n')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已取消更新', proc.stdout)
        self.assertFalse((self.home / '.budgetbuddy' / 'lib').exists())

    def test_stdin_eof_defaults_to_proceed(self):
        """stdin EOF（非交互调用）走默认 Y 继续（update 非破坏用户数据）。"""
        proc = run_setup(self.cb / 'setup.sh', self.tmp, self.home,
                         args=['update'], stdin_text='')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('更新完成', proc.stdout)
        self.assertTrue((self.home / '.budgetbuddy' / 'lib' / 'update.sh').is_file())

    def test_budget_update_yes_env_skips_interaction(self):
        """BUDGET_UPDATE_YES=1 环境变量通道：stdin n 仍执行。"""
        proc = run_setup(self.cb / 'setup.sh', self.tmp, self.home,
                         args=['update'], stdin_text='n\n',
                         env_extra={'BUDGET_UPDATE_YES': '1'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已取消更新', proc.stdout)
        self.assertTrue((self.home / '.budgetbuddy' / 'lib' / 'update.sh').is_file())


class DiffTests(UpdateSandboxTestCase):
    """do_diff：当前 agent model 值 vs 预设对比表。"""

    def _make_install_with_agents(self, models_by_agent):
        cb = make_codebuddy_install(self.tmp)
        balanced = expected_preset('codebuddy', 'balanced')
        for name in SUITE_AGENTS:
            model = models_by_agent.get(name, balanced.get(name, ''))
            write_text(cb / 'agents' / f'{name}.md',
                       AGENT_TMPL.format(name=name, model=model))
        return cb

    def test_diff_table_with_same_and_diff_rows(self):
        """对比表：一致行 ✓ / 差异行 ✗ + 计数汇总。"""
        balanced = expected_preset('codebuddy', 'balanced')
        models = {'coder-lite': 'custom-model-x'}  # 其余与 balanced 一致
        cb = self._make_install_with_agents(models)
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home, args=['diff'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('当前配置 vs 预设 balanced', proc.stdout)
        self.assertIn('✓ 一致', proc.stdout)
        self.assertIn('✗ 差异', proc.stdout)
        self.assertIn('coder-lite', proc.stdout)
        self.assertIn('custom-model-x', proc.stdout)
        self.assertIn('9 个一致，1 个差异', proc.stdout)
        self.assertIn('budget setup agent preset balanced', proc.stdout)

    def test_diff_all_same_reports_fully_aligned(self):
        balanced = expected_preset('codebuddy', 'balanced')
        cb = self._make_install_with_agents({})
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home, args=['diff'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('完全一致', proc.stdout)
        self.assertNotIn('✗ 差异', proc.stdout)

    def test_diff_missing_model_field_shows_unset(self):
        """model 字段缺失的 agent 显示（未设置）。"""
        cb = make_codebuddy_install(self.tmp)
        content = AGENT_TMPL.format(name='coder-lite', model='x')
        content = '\n'.join(line for line in content.split('\n')
                            if not line.startswith('model:'))
        write_text(cb / 'agents' / 'coder-lite.md', content)
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home, args=['diff'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('（未设置）', proc.stdout)

    def test_diff_invalid_preset_name_fails(self):
        cb = self._make_install_with_agents({})
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home,
                         args=['diff', 'nonexistent'])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("预设 'nonexistent' 查询失败", proc.stdout)

    def test_diff_unknown_platform_fails(self):
        proc = run_setup(CORE_SETUP, self.work, self.home, args=['diff'])
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未检测到 BudgetBuddy 平台形态', proc.stdout)

    def test_diff_custom_preset_argument(self):
        """diff [preset] 参数透传（economic 档对比）。"""
        balanced = expected_preset('codebuddy', 'balanced')
        cb = self._make_install_with_agents({})
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home,
                         args=['diff', 'economic'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('预设 economic', proc.stdout)
        economic = expected_preset('codebuddy', 'economic')
        # balanced 与 economic 的 architect 值不同 → 差异行
        if balanced['architect'] != economic['architect']:
            self.assertIn('✗ 差异', proc.stdout)


class UninstallKnownStructureTests(UpdateSandboxTestCase):
    """do_uninstall 已知结构模式（本地无清单：source 部署/直接拷贝形态）。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp, with_agents=True)
        make_full_suite_products(self.cb)
        make_user_custom_files(self.cb)
        make_user_data(self.tmp, self.home)
        write_text(self.cb / 'settings.json', json.dumps(
            {'hooks': {'Notification': [{'hooks': [
                {'command': 'python .codebuddy/hooks/budget-notify-hook.py'}]}]}},
            ensure_ascii=False, indent=2))
        # 预置 wrapper 与 rc 注入块（模拟 init 后状态；setUp 末尾统一卸载）
        self.wrapper = self.home / '.local' / 'bin' / 'budget'
        self.wrapper.parent.mkdir(parents=True, exist_ok=True)
        self.wrapper.write_text('#!/bin/bash\n', encoding='utf-8')
        self.rc = self.home / '.zshrc'
        self.rc.write_text(
            '# user rc\n\n# BudgetBuddy shell function (fallback)\n'
            'budget() { :; }\n# end BudgetBuddy shell function\n',
            encoding='utf-8')
        self.proc = run_uninstall(self.cb / 'setup.sh', self.tmp, self.home)

    def test_exit_zero_and_strategy_reported(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertIn('卸载完成', self.proc.stdout)
        self.assertIn('按已知结构清单删除', self.proc.stdout)

    def test_suite_products_removed(self):
        """本套件产物全删（agents/commands/skills/rules/hooks/lib/docs/顶层）。"""
        cb = self.cb
        for name in SUITE_AGENTS:
            self.assertFalse((cb / 'agents' / f'{name}.md').exists(),
                             '未删除 agents/%s.md' % name)
        self.assertFalse((cb / 'commands' / 'budget').exists())
        self.assertFalse((cb / 'commands' / 'opsx').exists())
        for skill in SUITE_SKILLS:
            self.assertFalse((cb / 'skills' / skill).exists(),
                             '未删除 skills/%s' % skill)
        for rule in ('budget-coder-guard.mdc', 'budget-go-style.mdc'):
            self.assertFalse((cb / 'rules' / rule).exists())
        self.assertFalse((cb / 'hooks' / 'budget-notify-hook.py').exists())
        for name in LIB_FILES:
            self.assertFalse((cb / 'lib' / name).exists(),
                             '未删除 lib/%s' % name)
        self.assertFalse((cb / 'docs' / 'MODEL_SELECTION.md').exists())
        self.assertFalse((cb / 'docs' / 'PERSONAS.md').exists())
        self.assertFalse((cb / 'setup.sh').exists())
        self.assertFalse((cb / 'budget-models.json').exists())
        self.assertFalse((cb / 'personas.json').exists())

    def test_user_custom_files_preserved(self):
        """清单外用户自建文件一律保留（A12 原则）。"""
        cb = self.cb
        self.assertTrue((cb / 'agents' / 'my-agent.md').is_file())
        self.assertTrue((cb / 'commands' / 'my-cmd' / 'help.md').is_file())
        self.assertTrue((cb / 'skills' / 'my-skill' / 'SKILL.md').is_file())
        self.assertTrue((cb / 'rules' / 'my-rule.mdc').is_file())
        self.assertTrue((cb / 'lib' / 'my-lib.sh').is_file())
        self.assertTrue((cb / 'settings.json').is_file())

    def test_user_data_preserved_by_default(self):
        """用户数据默认保留（P0：.budget/ 与 ~/.budgetbuddy/）。"""
        self.assertTrue((self.tmp / '.budget' / 'persona-active.json').is_file())
        self.assertTrue((self.tmp / '.budget' / 'notify.json').is_file())
        self.assertTrue((self.tmp / '.budget' / 'memory' / 'goal-state.json').is_file())
        self.assertTrue((self.home / '.budgetbuddy' / 'projects').is_dir())
        self.assertIn('用户数据已保留', self.proc.stdout)
        self.assertIn('--purge', self.proc.stdout)

    def test_wrapper_and_rc_function_removed(self):
        """包装器移除 + rc fallback 函数块清理（setUp 预置 + 统一卸载）。"""
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertFalse(self.wrapper.exists())
        content = self.rc.read_text(encoding='utf-8')
        self.assertIn('# user rc', content)
        self.assertNotIn('BudgetBuddy shell function', content)

    def test_settings_hooks_manual_hint(self):
        """settings.json 含 hooks 注入时提示手动清理（T10d 未就位桩）。"""
        self.assertIn('请手动清理', self.proc.stdout)
        self.assertIn('hooks 清理模块', self.proc.stdout)


class UninstallManifestTests(UpdateSandboxTestCase):
    """do_uninstall 清单模式（<安装根>/.budget-manifest.json 按清单删除）。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp, with_agents=True)
        make_full_suite_products(self.cb)
        make_user_custom_files(self.cb)
        # 清单：部分套件文件 + 非套件文件 + 越界条目
        write_text(self.cb / 'extra.txt', 'manifest managed\n')
        write_text(self.tmp / 'evil.txt', 'outside root\n')
        manifest = {'files': {
            'agents/architect.md': 'hash-architect',
            'extra.txt': 'hash-extra',
            '../evil.txt': 'hash-evil',
        }}
        write_text(self.cb / '.budget-manifest.json',
                   json.dumps(manifest, ensure_ascii=False, indent=2))
        self.proc = run_uninstall(self.cb / 'setup.sh', self.tmp, self.home)

    def test_exit_zero_and_strategy_reported(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertIn('按本地清单', self.proc.stdout)

    def test_manifest_entries_removed(self):
        """清单内条目删除（含非套件文件——按清单删语义）。"""
        self.assertFalse((self.cb / 'agents' / 'architect.md').exists())
        self.assertFalse((self.cb / 'extra.txt').exists())

    def test_out_of_range_entry_skipped(self):
        """越界条目（../）跳过并告警（安全：不删安装根外文件）。"""
        self.assertTrue((self.tmp / 'evil.txt').is_file())
        self.assertIn('越界', self.proc.stderr)

    def test_known_structure_residual_scan(self):
        """清单外套件产物仍被已知结构残留扫描删除（幂等兜底）。"""
        self.assertFalse((self.cb / 'agents' / 'coder-lite.md').exists())
        self.assertFalse((self.cb / 'skills' / 'budget-workflow').exists())
        self.assertFalse((self.cb / 'setup.sh').exists())

    def test_manifest_file_itself_removed(self):
        self.assertFalse((self.cb / '.budget-manifest.json').exists())

    def test_user_files_outside_manifest_preserved(self):
        self.assertTrue((self.cb / 'agents' / 'my-agent.md').is_file())
        self.assertTrue((self.cb / 'rules' / 'my-rule.mdc').is_file())

    def test_corrupted_manifest_degrades_to_known_structure(self):
        """清单损坏（非法 JSON）：stderr 告警 + 退化为已知结构删除。"""
        # setUp 的 uninstall 已删除安装形态（含 setup.sh 自删）；本用例
        # 重建完整安装形态后写入损坏清单，独立验证降级路径（不经 setUp 副作用）
        self.cb = make_codebuddy_install(self.tmp, with_agents=True)
        make_full_suite_products(self.cb)
        make_user_custom_files(self.cb)
        write_text(self.cb / '.budget-manifest.json', '{not valid json')
        proc = run_uninstall(self.cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('清单解析失败', proc.stderr)
        self.assertFalse((self.cb / 'agents' / 'coder-lite.md').exists())
        self.assertTrue((self.cb / 'agents' / 'my-agent.md').is_file())


class UninstallPurgeTests(UpdateSandboxTestCase):
    """do_uninstall --purge：显式删除用户数据。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp, with_agents=True)
        make_user_data(self.tmp, self.home)

    def test_purge_removes_user_data(self):
        proc = run_uninstall(self.cb / 'setup.sh', self.tmp, self.home, purge=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('purge 模式', proc.stdout)
        self.assertFalse((self.tmp / '.budget').exists())
        self.assertFalse((self.home / '.budgetbuddy').exists())

    def test_purge_warning_shown_in_preview(self):
        proc = run_uninstall(self.cb / 'setup.sh', self.tmp, self.home, purge=True)
        self.assertIn('将被删除', proc.stdout)


class UninstallIdempotencyTests(UpdateSandboxTestCase):
    """uninstall 幂等：重复运行/已卸载状态不报错。"""

    def test_second_uninstall_exit_zero(self):
        """二次 uninstall（安装形态已删，经 core 源运行）：exit 0。"""
        cb = make_codebuddy_install(self.tmp, with_agents=True)
        first = run_uninstall(cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = run_uninstall(CORE_SETUP, self.tmp, self.home)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('可能已卸载', second.stdout)
        self.assertIn('无待删除的本套件文件', second.stdout)

    def test_unknown_platform_still_cleans_wrapper(self):
        """无安装形态时：仅全局清理（wrapper 移除）+ 正常退出。"""
        wrapper = self.home / '.local' / 'bin' / 'budget'
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text('#!/bin/bash\n', encoding='utf-8')
        proc = run_uninstall(CORE_SETUP, self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(wrapper.exists())

    def test_interactive_decline_no_side_effects(self):
        """stdin 回答 n：取消且不做任何修改（破坏性操作保守默认）。"""
        cb = make_codebuddy_install(self.tmp, with_agents=True)
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home,
                         args=['uninstall'], stdin_text='n\n')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已取消卸载', proc.stdout)
        self.assertTrue((cb / 'setup.sh').is_file())
        self.assertTrue((cb / 'agents' / 'coder-lite.md').is_file())

    def test_stdin_eof_defaults_to_cancel(self):
        """stdin EOF（非交互调用）默认取消（与 init/update 的默认 Y 相反）。"""
        cb = make_codebuddy_install(self.tmp, with_agents=True)
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home,
                         args=['uninstall'], stdin_text='')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已取消卸载', proc.stdout)
        self.assertTrue((cb / 'setup.sh').is_file())

    def test_budget_uninstall_yes_env_skips_interaction(self):
        """BUDGET_UNINSTALL_YES=1 环境变量通道：stdin n 仍执行。"""
        cb = make_codebuddy_install(self.tmp, with_agents=True)
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home,
                         args=['uninstall'], stdin_text='n\n',
                         env_extra={'BUDGET_UNINSTALL_YES': '1'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已取消卸载', proc.stdout)
        self.assertFalse((cb / 'setup.sh').exists())


class UninstallOpencodeTests(UpdateSandboxTestCase):
    """do_uninstall opencode 形态（A3 管理面 + 平台结构目录 + AGENTS.md）。"""

    def _make_opencode_install(self):
        # 管理面 ~/.budgetbuddy/（setup.sh/lib/models/personas/docs + 用户数据）
        bb = self.home / '.budgetbuddy'
        copy_lib(bb / 'lib')
        shutil.copy2(CORE_SETUP, bb / 'setup.sh')
        shutil.copy2(CORE_MODELS, bb / 'budget-models.json')
        shutil.copy2(CORE_PERSONAS, bb / 'personas.json')
        write_text(bb / 'docs' / 'MODEL_SELECTION.md', '# models\n')
        write_text(bb / 'docs' / 'PERSONAS.md', '# personas\n')
        write_text(bb / 'docs' / 'architecture.md', '# arch\n')
        write_text(bb / 'docs' / 'setup-notes.md', '# notes\n')
        make_user_data(self.work, self.home)  # 用户数据（全局目录内）
        # 平台结构目录 work/.opencode/（agent/command/skill）
        struct = self.work / '.opencode'
        for name in SUITE_AGENTS:
            write_text(struct / 'agent' / f'{name}.md', AGENT_TMPL.format(
                name=name, model='test-model'))
        for name in ('budget-start.md', 'budget-status.md', 'opsx-apply.md'):
            write_text(struct / 'command' / name, '# cmd\n')
        for skill in ('budget-notify', 'budget-workflow', 'openspec-propose'):
            write_text(struct / 'skill' / skill / 'SKILL.md', '# skill\n')
        # 用户自建结构文件（保留断言）
        write_text(struct / 'agent' / 'my-agent.md', '# my agent\n')
        write_text(struct / 'skill' / 'my-skill' / 'SKILL.md', '# my skill\n')
        # AGENTS.md 标记区块 + 用户内容
        write_text(self.work / 'AGENTS.md',
                   '# 用户内容\n\n<!-- BudgetBuddy:begin -->\n套件规则\n'
                   '<!-- BudgetBuddy:end -->\n\n# 更多用户内容\n')
        return bb, struct

    def test_opencode_uninstall_full(self):
        bb, struct = self._make_opencode_install()
        proc = run_uninstall(bb / 'setup.sh', self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('opencode:project', proc.stdout)
        # 管理面套件产物删除
        self.assertFalse((bb / 'setup.sh').exists())
        self.assertFalse((bb / 'budget-models.json').exists())
        self.assertFalse((bb / 'personas.json').exists())
        for name in LIB_FILES:
            self.assertFalse((bb / 'lib' / name).exists())
        for name in ('MODEL_SELECTION.md', 'PERSONAS.md', 'architecture.md', 'setup-notes.md'):
            self.assertFalse((bb / 'docs' / name).exists())
        # 管理面用户数据保留（P0）
        self.assertTrue((bb / 'projects' / 'demo' / 'memory' / 'coder-guard.json').is_file())
        # 平台结构目录套件产物删除
        for name in SUITE_AGENTS:
            self.assertFalse((struct / 'agent' / f'{name}.md').exists())
        self.assertFalse((struct / 'command' / 'budget-start.md').exists())
        self.assertFalse((struct / 'command' / 'opsx-apply.md').exists())
        for skill in ('budget-notify', 'budget-workflow', 'openspec-propose'):
            self.assertFalse((struct / 'skill' / skill).exists())
        # 用户自建结构文件保留
        self.assertTrue((struct / 'agent' / 'my-agent.md').is_file())
        self.assertTrue((struct / 'skill' / 'my-skill' / 'SKILL.md').is_file())
        # AGENTS.md 区块清除、区块外内容保留
        agents_md = self.read_text(self.work / 'AGENTS.md')
        self.assertIn('# 用户内容', agents_md)
        self.assertIn('# 更多用户内容', agents_md)
        self.assertNotIn('BudgetBuddy:begin', agents_md)
        self.assertNotIn('套件规则', agents_md)

    def test_opencode_agents_md_only_block_removed_entirely(self):
        """AGENTS.md 仅含标记区块时整个文件删除（安装器合并产物）。"""
        bb, struct = self._make_opencode_install()
        write_text(self.work / 'AGENTS.md',
                   '<!-- BudgetBuddy:begin -->\n套件规则\n<!-- BudgetBuddy:end -->\n')
        proc = run_uninstall(bb / 'setup.sh', self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((self.work / 'AGENTS.md').exists())

    def test_opencode_agents_md_without_block_untouched(self):
        """无标记区块的 AGENTS.md 不触碰。"""
        bb, struct = self._make_opencode_install()
        write_text(self.work / 'AGENTS.md', '# 纯用户内容\n')
        proc = run_uninstall(bb / 'setup.sh', self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.read_text(self.work / 'AGENTS.md'), '# 纯用户内容\n')


class UpdateOpencodeTests(UpdateSandboxTestCase):
    """do_update opencode 管理面形态（源即目标跳过 + hooks 跳过 + diff）。"""

    def test_opencode_update(self):
        bb = self.home / '.budgetbuddy'
        copy_lib(bb / 'lib')
        shutil.copy2(CORE_SETUP, bb / 'setup.sh')
        shutil.copy2(CORE_MODELS, bb / 'budget-models.json')
        shutil.copy2(CORE_PERSONAS, bb / 'personas.json')
        for name in SUITE_AGENTS:
            write_text(self.work / '.opencode' / 'agent' / f'{name}.md',
                       AGENT_TMPL.format(name=name, model='test-model'))
        proc = run_update(bb / 'setup.sh', self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('opencode:project', proc.stdout)
        # 管理面源即目标（~/.budgetbuddy/ 本身）→ 跳过刷新
        self.assertIn('源即目标', proc.stdout)
        # lib 源即目标 → 不重复同步
        self.assertNotIn('已同步 lib 模块', proc.stdout)
        # 非 codebuddy 形态跳过 hooks
        self.assertIn('跳过 hooks 注入', proc.stdout)
        # diff 展示（agent 目录在 .opencode/agent/）
        self.assertIn('agent model 配置对比', proc.stdout)


class ReinstallTests(UpdateSandboxTestCase):
    """do_reinstall：uninstall（不 purge 用户数据）+ init 组合。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp, with_agents=True)
        make_full_suite_products(self.cb)
        make_user_data(self.tmp, self.home)

    def test_reinstall_exit_zero_and_user_data_preserved(self):
        proc = run_reinstall(self.cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('重装完成', proc.stdout)
        # 用户数据保留（不 purge）
        self.assertEqual(self.load_json(self.tmp / '.budget' / 'persona-active.json')['theme'],
                         'sanguo')
        self.assertTrue(self.load_json(self.tmp / '.budget' / 'notify.json')['enabled'])
        # 结构文件已清除
        self.assertFalse((self.cb / 'setup.sh').exists())
        self.assertFalse((self.cb / 'agents' / 'coder-lite.md').exists())
        # Phase 2 init 回退全局初始化 → wrapper 重写
        self.assertTrue((self.home / '.local' / 'bin' / 'budget').is_file())

    def test_reinstall_falls_back_to_global_init(self):
        """卸载清除安装形态后 init 回退全局数据初始化（两级回退）。"""
        proc = run_reinstall(self.cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('回退全局数据初始化', proc.stdout)

    def test_reinstall_interactive_decline(self):
        proc = run_setup(self.cb / 'setup.sh', self.tmp, self.home,
                         args=['reinstall'], stdin_text='n\n')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已取消重装', proc.stdout)
        self.assertTrue((self.cb / 'setup.sh').is_file())

    def test_reinstall_stdin_eof_defaults_to_cancel(self):
        proc = run_setup(self.cb / 'setup.sh', self.tmp, self.home,
                         args=['reinstall'], stdin_text='')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已取消重装', proc.stdout)
        self.assertTrue((self.cb / 'setup.sh').is_file())


class UninstallHooksCleanupTests(UpdateSandboxTestCase):
    """P1-1：uninstall 清理 settings.json hooks 注入（防残留回归）。

    根因回归防护：uninstall 第 1 步删除计划已清 setup.sh → 第 2 步
    budget_remove_hooks 重新探测必然 unknown；修复前 settings_file 参数
    被忽略、误报清理成功（实际零清理，重装后 hooks「可用」依赖该残留
    巧合）。断言「零残留」直接捕获该缺陷。
    """

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp, with_agents=True)
        copy_lib_with_hooks(self.cb / 'lib')
        make_full_suite_products(self.cb)
        self.settings = self.cb / 'settings.json'
        inject_hooks(self.settings)

    def test_uninstall_cleans_hooks_and_superpowers(self):
        """卸载后 settings.json 零本套件 hooks / superpowers 残留。"""
        proc = run_uninstall(self.cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已清理 settings.json 的 BudgetBuddy hooks 注入', proc.stdout)
        self.assertNotIn('仍含 BudgetBuddy hooks 残留', proc.stdout)
        # 纯套件注入项移除后为空对象 → 引擎删除文件（恢复创建前状态）；
        # 若文件保留（用户项场景）则必须零套件残留
        if self.settings.exists():
            data = self.load_json(self.settings)
            self.assertEqual(suite_hook_commands(data), [])
            self.assertNotIn(SUPERPOWERS_KEY, data.get('enabledPlugins') or {})
        else:
            # 文件已删 → 无残留可查；备份文件不作为断言对象
            pass

    def test_user_hooks_preserved_after_cleanup(self):
        """用户自有 hooks 条目保留（精确删除，不整体清空）。"""
        data = self.load_json(self.settings)
        data['hooks']['Stop'] = [
            {'hooks': [{'type': 'command', 'command': 'echo user-stop'}]}]
        write_text(self.settings,
                   json.dumps(data, ensure_ascii=False, indent=2))
        proc = run_uninstall(self.cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.settings.is_file())
        data = self.load_json(self.settings)
        stop_commands = [
            h.get('command', '')
            for m in data['hooks'].get('Stop', [])
            for h in m.get('hooks', [])]
        self.assertIn('echo user-stop', stop_commands)
        self.assertEqual(suite_hook_commands(data), [])
        self.assertNotIn(SUPERPOWERS_KEY, data.get('enabledPlugins') or {})


class ReinstallHooksRestoreTests(UpdateSandboxTestCase):
    """P1-1 连锁：uninstall 清理 settings.json 后 reinstall 恢复 hooks。

    修复后 uninstall 真正清理注入项（不再依赖残留巧合）；reinstall 全局
    回退路径（探测 unknown → do_init 跳过 hooks 注入）需按卸载前形态
    快照恢复注入，保证 uninstall → reinstall 后 hooks 重新可用。
    """

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp, with_agents=True)
        copy_lib_with_hooks(self.cb / 'lib')
        make_full_suite_products(self.cb)
        make_user_data(self.tmp, self.home)
        self.settings = self.cb / 'settings.json'
        inject_hooks(self.settings)

    def test_reinstall_restores_hooks(self):
        """重装后 hooks 三事件 + superpowers 恢复（项目级落点）。"""
        proc = run_reinstall(self.cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('重装完成', proc.stdout)
        self.assertIn('hooks 已随重装恢复', proc.stdout)
        data = self.load_json(self.settings)
        # superpowers 插件恢复
        self.assertTrue(data.get('enabledPlugins', {}).get(SUPERPOWERS_KEY))
        # 三事件 hooks 恢复
        hooks = data.get('hooks', {})
        for event in ('Notification', 'PreToolUse', 'SubagentStop'):
            self.assertIn(event, hooks, '缺失 hooks 事件: %s' % event)
        commands = suite_hook_commands(data)
        self.assertTrue(commands, '零本套件 hook 条目')
        # 项目级形态快照恢复：hook command 相对路径（与 settings.json 同形态）
        for cmd in commands:
            self.assertIn('.codebuddy/hooks/budget-notify-hook.py', cmd)

    def test_reinstall_user_hooks_preserved(self):
        """用户自有 hooks 在重装恢复后保留（注入幂等 + 精确合并）。"""
        data = self.load_json(self.settings)
        data['hooks']['Stop'] = [
            {'hooks': [{'type': 'command', 'command': 'echo user-stop'}]}]
        write_text(self.settings,
                   json.dumps(data, ensure_ascii=False, indent=2))
        proc = run_reinstall(self.cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.load_json(self.settings)
        stop_commands = [
            h.get('command', '')
            for m in data['hooks'].get('Stop', [])
            for h in m.get('hooks', [])]
        self.assertIn('echo user-stop', stop_commands)
        self.assertTrue(suite_hook_commands(data))


class DispatchArgPassthroughTests(UpdateSandboxTestCase):
    """P2-1：setup.sh 分发层子命令参数透传（--yes / --purge 不再丢弃）。

    修复前分发调用 do_uninstall 等无 "$@"，`budget setup uninstall --yes`
    的 --yes 被丢弃（stdin EOF 走默认 N 卸载被取消）；修复后统一
    shift + do_xxx "$@" 透传。
    """

    def test_uninstall_yes_flag_executes_on_stdin_eof(self):
        """uninstall --yes：stdin EOF（</dev/null 语义）不再确认取消。"""
        cb = make_codebuddy_install(self.tmp, with_agents=True)
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home,
                         args=['uninstall', '--yes'], stdin_text='')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已取消卸载', proc.stdout)
        self.assertIn('卸载完成', proc.stdout)
        self.assertFalse((cb / 'setup.sh').exists())

    def test_uninstall_purge_flag_passthrough(self):
        """uninstall --yes --purge：purge 参数透传（用户数据删除）。"""
        cb = make_codebuddy_install(self.tmp, with_agents=True)
        make_user_data(self.tmp, self.home)
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home,
                         args=['uninstall', '--yes', '--purge'],
                         stdin_text='')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('purge 模式', proc.stdout)
        self.assertFalse((self.tmp / '.budget').exists())
        self.assertFalse((self.home / '.budgetbuddy').exists())

    def test_init_yes_flag_skips_interaction(self):
        """init --yes：stdin n 仍执行（参数通道生效）。"""
        cb = make_codebuddy_install(self.tmp, with_agents=True)
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home,
                         args=['init', '--yes'], stdin_text='n\n')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已取消初始化', proc.stdout)
        self.assertIn('初始化完成', proc.stdout)

    def test_update_yes_flag_skips_interaction(self):
        """update --yes：stdin n 仍执行（参数通道生效）。"""
        cb = make_codebuddy_install(self.tmp, with_agents=True)
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home,
                         args=['update', '--yes'], stdin_text='n\n')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已取消更新', proc.stdout)
        self.assertIn('更新完成', proc.stdout)

    def test_reinstall_yes_flag_skips_interaction(self):
        """reinstall --yes：stdin n 仍执行（参数通道生效）。"""
        cb = make_codebuddy_install(self.tmp, with_agents=True)
        make_user_data(self.tmp, self.home)
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home,
                         args=['reinstall', '--yes'], stdin_text='n\n')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已取消重装', proc.stdout)
        self.assertIn('重装完成', proc.stdout)


class EndToEndTests(UpdateSandboxTestCase):
    """四命令端到端：安装形态 → update → diff → uninstall → reinstall。"""

    def test_full_lifecycle(self):
        cb = make_codebuddy_install(self.tmp, with_agents=True)
        make_full_suite_products(cb)
        make_user_data(self.tmp, self.home)

        # 1) update：models 刷新语义（项目级形态提示）+ 用户数据保留
        proc = run_update(cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('更新完成', proc.stdout)
        self.assertTrue((self.home / '.budgetbuddy' / 'lib' / 'update.sh').is_file())
        self.assertEqual(self.load_json(self.tmp / '.budget' / 'persona-active.json')['theme'],
                         'sanguo')

        # 2) diff：对比表输出
        proc = run_setup(cb / 'setup.sh', self.tmp, self.home, args=['diff'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('当前配置 vs 预设 balanced', proc.stdout)
        self.assertIn('共 10 个 agent', proc.stdout)

        # 3) uninstall：产物删除 + 用户数据保留
        proc = run_uninstall(cb / 'setup.sh', self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('卸载完成', proc.stdout)
        self.assertFalse((cb / 'setup.sh').exists())
        self.assertFalse((cb / 'agents' / 'coder-lite.md').exists())
        self.assertTrue((self.tmp / '.budget' / 'persona-active.json').is_file())
        self.assertTrue((self.home / '.budgetbuddy' / 'projects').is_dir())

        # 4) reinstall（安装形态 setup.sh 已删，经 core 源运行）
        proc = run_reinstall(CORE_SETUP, self.tmp, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('重装完成', proc.stdout)
        self.assertEqual(self.load_json(self.tmp / '.budget' / 'persona-active.json')['theme'],
                         'sanguo')
        self.assertTrue((self.home / '.local' / 'bin' / 'budget').is_file())


if __name__ == '__main__':
    unittest.main()
