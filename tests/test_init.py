#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""init.sh 初始化全流程单测（design.md §8.1/§8.4/§9/§10；specs/setup-cli
「数据目录与优先级」+ specs/notify「CodeBuddy hooks 三事件通知」注入桩部分）。

临时 HOME + 目录构造安装形态，subprocess 驱动 bash：
- codebuddy 项目级形态完整冒烟（全局骨架/lib 同步/管理面数据落位/
  persona 展开/notify 模板 chmod 600/gitignore 区块/包装器/rc fallback/
  hooks 桩提示/superpowers 提示）
- 幂等重跑（用户数据不覆盖、gitignore 区块唯一、lib 不重复同步）
- 非交互三通道（--yes 参数直调 / BUDGET_INIT_YES 环境变量 / stdin EOF）
  与交互确认（mock stdin：y 确认 / n 取消）
- 全局模式（BUDGET_GLOBAL=1）/ 探测失败显式报错 / opencode 形态（A3
  管理面落位 + lib 自同步跳过）/ codebuddy 全局形态 / BUDGET_DIR 覆盖
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_LIB = REPO_ROOT / 'core' / 'lib'
CORE_SETUP = REPO_ROOT / 'core' / 'setup.sh'
CORE_MODELS = REPO_ROOT / 'core' / 'models' / 'budget-models.json'
CORE_PERSONAS = REPO_ROOT / 'core' / 'personas' / 'personas.json'

# lib 全部文件（基础层 4 + init.sh；安装形态拷贝全集）
INIT_LIB_FILES = ('colors.sh', 'utils.sh', 'platform.sh', 'shell.sh', 'init.sh')

# notify.json 模板的事件键全集（N1..N11，specs/notify R1）
NOTIFY_EVENT_KEYS = ['N%d' % i for i in range(1, 12)]

# persona-active.json 的 roles 键集（leader + 十角色，design.md §8.5）
PERSONA_ROLE_KEYS = {
    'leader', 'architect', 'coder-lite', 'coder-standard', 'coder-senior',
    'reviewer', 'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
}


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
        capture_output=True, text=True, timeout=120,
        input=stdin_text,
    )


def run_init(setup_sh, cwd, home, args=None, stdin_text='', env_extra=None):
    """经 setup.sh 分发入口执行 init（模拟 budget setup init）。"""
    env = dict(os.environ)
    env['HOME'] = str(home)
    env['SHELL'] = '/bin/zsh'  # rc 文件落点固定 .zshrc，断言不受本机 SHELL 影响
    for key in list(env):
        if key.startswith('BUDGET_'):
            del env[key]
    if env_extra:
        env.update(env_extra)
    cmd = ['bash', str(setup_sh), 'init'] + list(args or [])
    return subprocess.run(
        cmd, cwd=str(cwd), env=env, capture_output=True, text=True,
        timeout=120, input=stdin_text,
    )


def make_codebuddy_install(base):
    """构造 .codebuddy 项目级安装形态（setup.sh + lib 全集 + models + personas）。"""
    cb = base / '.codebuddy'
    (cb / 'lib').mkdir(parents=True)
    shutil.copy2(CORE_SETUP, cb / 'setup.sh')
    for name in INIT_LIB_FILES:
        shutil.copy2(CORE_LIB / name, cb / 'lib' / name)
    shutil.copy2(CORE_MODELS, cb / 'budget-models.json')
    shutil.copy2(CORE_PERSONAS, cb / 'personas.json')
    return cb


def make_opencode_mgmt_install(home, project):
    """构造 opencode 管理面形态（~/.budgetbuddy/ 含 setup.sh/lib/models/personas，A3）
    + 项目 .opencode/agent/ 本套件 agent 文件（探测分支③项目级）。"""
    bb = home / '.budgetbuddy'
    (bb / 'lib').mkdir(parents=True)
    shutil.copy2(CORE_SETUP, bb / 'setup.sh')
    for name in INIT_LIB_FILES:
        shutil.copy2(CORE_LIB / name, bb / 'lib' / name)
    shutil.copy2(CORE_MODELS, bb / 'budget-models.json')
    shutil.copy2(CORE_PERSONAS, bb / 'personas.json')
    agent_dir = Path(project) / '.opencode' / 'agent'
    agent_dir.mkdir(parents=True)
    (agent_dir / 'architect.md').write_text('---\n---\n', encoding='utf-8')
    return bb


class InitSandboxTestCase(unittest.TestCase):
    """公共沙箱：每个用例独立临时目录（项目区 + 隔离 HOME）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-init-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def resolved(self, path):
        """归一化物理路径（macOS /var → /private/var 对齐 bash pwd -P）。"""
        return str(Path(path).resolve())

    def file_mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def load_json(self, path):
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)


class InitSyntaxTests(InitSandboxTestCase):
    """bash -n 语法冒烟（任务硬性约束）。"""

    def test_bash_n_init_sh(self):
        proc = subprocess.run(
            ['bash', '-n', str(CORE_LIB / 'init.sh')],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class InitCodebuddyProjectTests(InitSandboxTestCase):
    """codebuddy 项目级形态完整冒烟（任务验证要求的主场景）。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp)
        self.proc = run_init(
            self.cb / 'setup.sh', self.tmp, self.home, args=['--yes'])

    def test_exit_zero_and_platform_detected(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertIn('codebuddy:project', self.proc.stdout)

    def test_global_data_dir_skeleton(self):
        """~/.budgetbuddy/ 骨架：bin/lib/projects/docs（design.md §8.4）。"""
        for sub in ('bin', 'lib', 'projects', 'docs'):
            self.assertTrue((self.home / '.budgetbuddy' / sub).is_dir(),
                            '缺少 ~/.budgetbuddy/%s' % sub)

    def test_lib_synced_to_global_single_point(self):
        """lib 全局单点同步（A4：skill 引用 $HOME/.budgetbuddy/lib/）。"""
        for name in INIT_LIB_FILES:
            self.assertTrue((self.home / '.budgetbuddy' / 'lib' / name).is_file(),
                            'lib 未同步 %s' % name)
        self.assertIn('已同步 lib 模块', self.proc.stdout)

    def test_project_budget_dir_created(self):
        """项目 .budget/ 数据目录：memory/ + persona + notify。"""
        budget = self.tmp / '.budget'
        self.assertTrue((budget / 'memory').is_dir())
        self.assertTrue((budget / 'persona-active.json').is_file())
        self.assertTrue((budget / 'notify.json').is_file())

    def test_notify_template_content_and_permission(self):
        """notify.json 模板：enabled=false + N1..N11 + chmod 600（specs/notify R1）。"""
        notify = self.tmp / '.budget' / 'notify.json'
        data = self.load_json(notify)
        self.assertFalse(data['enabled'])
        self.assertEqual(data['channels'], {})
        self.assertEqual(set(data['events']), set(NOTIFY_EVENT_KEYS))
        for cfg in data['events'].values():
            self.assertFalse(cfg['enabled'])
            self.assertEqual(cfg['channels'], [])
        self.assertEqual(self.file_mode(notify), 0o600)
        self.assertIn('权限 600', self.proc.stdout)

    def test_persona_active_content(self):
        """persona-active.json：default 主题 + 11 键 roles + 模板（design.md §8.5）。"""
        data = self.load_json(self.tmp / '.budget' / 'persona-active.json')
        self.assertEqual(data['theme'], 'default')
        self.assertEqual(set(data['roles']), PERSONA_ROLE_KEYS)
        self.assertEqual(data['roles']['leader'], 'Leader')
        self.assertIn('report_templates', data)
        self.assertIn('greeting', data)

    def test_gitignore_block_appended_preserves_user_content(self):
        """gitignore 区块追加且区块外用户内容不变（specs/setup-cli Scenario）。"""
        gitignore = self.tmp / '.gitignore'
        gitignore.write_text('# user content\nnode_modules/\n', encoding='utf-8')
        proc = run_init(self.cb / 'setup.sh', self.tmp, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        content = gitignore.read_text(encoding='utf-8')
        self.assertIn('# user content', content)
        self.assertIn('node_modules/', content)
        self.assertIn('# BudgetBuddy:begin', content)
        self.assertIn('.budget/', content)
        self.assertIn('# BudgetBuddy:end', content)
        # 区块位于用户内容之后（仅追加，不触碰区块外内容）
        self.assertLess(content.index('node_modules/'),
                        content.index('# BudgetBuddy:begin'))

    def test_gitignore_created_when_absent(self):
        """.gitignore 不存在时创建并写入区块。"""
        gitignore = self.tmp / '.gitignore'
        if gitignore.exists():  # setUp 预跑 init 已生成，删除还原「无文件」场景
            gitignore.unlink()
        self.assertFalse(gitignore.exists())
        proc = run_init(self.cb / 'setup.sh', self.tmp, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        content = gitignore.read_text(encoding='utf-8')
        self.assertIn('# BudgetBuddy:begin', content)
        self.assertIn('.budget/', content)

    def test_wrapper_written_executable(self):
        """包装器写入 ~/.local/bin/budget（utils.sh budget_install_wrapper）。"""
        wrapper = self.home / '.local' / 'bin' / 'budget'
        self.assertTrue(wrapper.is_file())
        self.assertTrue(os.access(wrapper, os.X_OK))
        self.assertIn('BUDGET_WRAPPER_MARKER', wrapper.read_text(encoding='utf-8'))

    def test_rc_fallback_function_injected(self):
        """rc 文件注入 budget() fallback 函数（shell.sh budget_inject_func）。"""
        rc = self.home / '.zshrc'
        content = rc.read_text(encoding='utf-8')
        self.assertEqual(content.count('budget() {'), 1)

    def test_hooks_stub_hint(self):
        """hooks 注入桩提示（hooks_inject.py 归 T10d，本任务调用点 + 桩）。"""
        self.assertIn('hooks 注入模块未安装，可稍后运行 budget setup init 补全',
                      self.proc.stdout)

    def test_superpowers_disabled_hint(self):
        """superpowers 未启用时输出提示（A11；注入归 T10d，本任务只提示）。"""
        self.assertIn('superpowers 插件未启用', self.proc.stdout)
        self.assertIn('/plugin superpowers', self.proc.stdout)

    def test_admin_data_not_copied_for_project_form(self):
        """codebuddy:project 形态不拷贝管理面数据（结构文件在 .codebuddy/）。"""
        self.assertFalse((self.home / '.budgetbuddy' / 'budget-models.json').exists())
        self.assertFalse((self.home / '.budgetbuddy' / 'personas.json').exists())


class InitIdempotencyTests(InitSandboxTestCase):
    """幂等重跑：用户数据不覆盖、区块唯一、无报错（任务硬性约束 4）。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp)
        first = run_init(self.cb / 'setup.sh', self.tmp, self.home, args=['--yes'])
        self.assertEqual(first.returncode, 0, first.stderr)

    def test_rerun_exit_zero_without_errors(self):
        proc = run_init(self.cb / 'setup.sh', self.tmp, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_rerun_preserves_user_data(self):
        """用户修改 persona/notify 后重跑：已存在跳过，不覆盖。"""
        persona = self.tmp / '.budget' / 'persona-active.json'
        notify = self.tmp / '.budget' / 'notify.json'
        persona_data = self.load_json(persona)
        persona_data['theme'] = 'sanguo'
        with open(persona, 'w', encoding='utf-8') as handle:
            json.dump(persona_data, handle, ensure_ascii=False, indent=2)
        notify_data = self.load_json(notify)
        notify_data['enabled'] = True
        with open(notify, 'w', encoding='utf-8') as handle:
            json.dump(notify_data, handle, ensure_ascii=False, indent=2)

        proc = run_init(self.cb / 'setup.sh', self.tmp, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('persona 配置已存在，跳过', proc.stdout)
        self.assertIn('通知配置已存在，跳过', proc.stdout)
        self.assertEqual(self.load_json(persona)['theme'], 'sanguo')
        self.assertTrue(self.load_json(notify)['enabled'])

    def test_rerun_gitignore_block_unique(self):
        gitignore = self.tmp / '.gitignore'
        gitignore.write_text('# user\n', encoding='utf-8')
        for _ in range(2):
            proc = run_init(self.cb / 'setup.sh', self.tmp, self.home, args=['--yes'])
            self.assertEqual(proc.returncode, 0, proc.stderr)
        content = gitignore.read_text(encoding='utf-8')
        self.assertEqual(content.count('# BudgetBuddy:begin'), 1)
        self.assertEqual(content.count('# BudgetBuddy:end'), 1)
        self.assertEqual(content.count('.budget/'), 1)

    def test_rerun_lib_not_resynced(self):
        """lib 内容一致时重跑跳过同步（无「已同步」输出）。"""
        proc = run_init(self.cb / 'setup.sh', self.tmp, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已同步 lib 模块', proc.stdout)

    def test_rerun_rc_function_unique(self):
        proc = run_init(self.cb / 'setup.sh', self.tmp, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        content = (self.home / '.zshrc').read_text(encoding='utf-8')
        self.assertEqual(content.count('budget() {'), 1)


class InitInteractiveTests(InitSandboxTestCase):
    """交互确认与 --yes 非交互（mock stdin；任务职责 6）。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp)

    def test_interactive_decline_no_side_effects(self):
        """stdin 回答 n：取消且不做任何修改。"""
        proc = run_init(self.cb / 'setup.sh', self.tmp, self.home, stdin_text='n\n')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已取消初始化', proc.stdout)
        self.assertFalse((self.home / '.budgetbuddy').exists())
        self.assertFalse((self.tmp / '.budget').exists())
        self.assertFalse((self.tmp / '.gitignore').exists())

    def test_interactive_confirm_executes(self):
        proc = run_init(self.cb / 'setup.sh', self.tmp, self.home, stdin_text='y\n')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('初始化完成', proc.stdout)
        self.assertTrue((self.tmp / '.budget' / 'notify.json').is_file())

    def test_stdin_eof_defaults_to_proceed(self):
        """stdin EOF（非交互调用）走默认 Y 继续（read || true 兜底）。"""
        proc = run_init(self.cb / 'setup.sh', self.tmp, self.home, stdin_text='')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('初始化完成', proc.stdout)
        self.assertTrue((self.tmp / '.budget' / 'notify.json').is_file())

    def test_budget_init_yes_env_skips_interaction(self):
        """BUDGET_INIT_YES=1 环境变量通道：stdin n 仍执行（跳过交互）。"""
        proc = run_init(self.cb / 'setup.sh', self.tmp, self.home,
                        stdin_text='n\n', env_extra={'BUDGET_INIT_YES': '1'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已取消初始化', proc.stdout)
        self.assertTrue((self.tmp / '.budget' / 'notify.json').is_file())

    def test_do_init_yes_argument_skips_interaction(self):
        """do_init --yes 参数通道（直调；setup.sh 分发层透传后直接生效）。"""
        script = (
            'BUDGET_SETUP_DIR="%s"; '
            'BUDGET_LIB_DIR="%s"; '
            'BUDGET_MODELS_FILE="%s"; '
            'BUDGET_GLOBAL=0; '
            'source "%s"; '
            'source "%s"; '
            'source "%s"; '
            'source "%s"; '
            'source "%s"; '
            'do_init --yes'
            % (REPO_ROOT / 'core', CORE_LIB, CORE_MODELS,
               CORE_LIB / 'colors.sh', CORE_LIB / 'utils.sh',
               CORE_LIB / 'platform.sh', CORE_LIB / 'shell.sh',
               CORE_LIB / 'init.sh')
        )
        proc = run_bash(script, self.tmp, self.home, stdin_text='n\n')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已取消初始化', proc.stdout)
        self.assertTrue((self.tmp / '.budget' / 'notify.json').is_file())


class InitGlobalModeTests(InitSandboxTestCase):
    """BUDGET_GLOBAL=1 全局模式（探测失败时仅全局初始化，不静默猜默认）。"""

    def test_global_mode_unknown_platform_proceeds(self):
        proc = run_init(CORE_SETUP, self.work, self.home,
                        env_extra={'BUDGET_GLOBAL': '1'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('BUDGET_GLOBAL=1 全局模式', proc.stdout)
        self.assertIn('初始化完成', proc.stdout)

    def test_global_mode_data_in_global_dir(self):
        """全局模式：persona/notify/memory 落 ~/.budgetbuddy/。"""
        run_init(CORE_SETUP, self.work, self.home, env_extra={'BUDGET_GLOBAL': '1'})
        bb = self.home / '.budgetbuddy'
        self.assertTrue((bb / 'persona-active.json').is_file())
        self.assertTrue((bb / 'notify.json').is_file())
        self.assertTrue((bb / 'memory').is_dir())
        self.assertEqual(self.load_json(bb / 'persona-active.json')['theme'], 'default')

    def test_global_mode_admin_data_from_core_source(self):
        """全局模式：管理面数据从 core 源形态落位 ~/.budgetbuddy/。"""
        run_init(CORE_SETUP, self.work, self.home, env_extra={'BUDGET_GLOBAL': '1'})
        bb = self.home / '.budgetbuddy'
        self.assertTrue((bb / 'budget-models.json').is_file())
        self.assertTrue((bb / 'personas.json').is_file())
        # 落位内容与源一致
        self.assertEqual(self.load_json(bb / 'personas.json'),
                         self.load_json(CORE_PERSONAS))

    def test_global_mode_skips_hooks_and_superpowers(self):
        proc = run_init(CORE_SETUP, self.work, self.home,
                        env_extra={'BUDGET_GLOBAL': '1'})
        self.assertIn('跳过 hooks 注入', proc.stdout)
        self.assertIn('跳过 superpowers 插件检测', proc.stdout)


class InitUnknownPlatformTests(InitSandboxTestCase):
    """探测失败 + 非 BUDGET_GLOBAL：显式报错退出（design.md §8.3）。"""

    def test_unknown_fails_with_explicit_error(self):
        proc = run_init(CORE_SETUP, self.work, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未检测到 BudgetBuddy 安装形态', proc.stdout)
        self.assertIn('BUDGET_PLATFORM', proc.stdout)

    def test_unknown_fails_without_side_effects(self):
        run_init(CORE_SETUP, self.work, self.home)
        self.assertFalse((self.home / '.budgetbuddy').exists())
        self.assertFalse((self.work / '.budget').exists())


class InitOpencodeTests(InitSandboxTestCase):
    """opencode 形态：A3 管理面统一 ~/.budgetbuddy/，无 hooks/superpowers。"""

    def test_opencode_project_form(self):
        """opencode 项目级：管理面数据落位 + 项目 .budget/ 数据。"""
        make_opencode_mgmt_install(self.home, self.work)
        setup_sh = self.home / '.budgetbuddy' / 'setup.sh'
        proc = run_init(setup_sh, self.work, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('opencode:project', proc.stdout)
        # 项目数据目录（.opencode/agent 探测命中项目根 = work）
        budget = self.work / '.budget'
        self.assertTrue((budget / 'persona-active.json').is_file())
        self.assertTrue((budget / 'notify.json').is_file())
        # hooks/superpowers 跳过（OpenCode 无此机制）
        self.assertIn('跳过 hooks 注入', proc.stdout)
        self.assertIn('跳过 superpowers 插件检测', proc.stdout)

    def test_opencode_admin_data_already_present_kept(self):
        """opencode 管理面已就位（安装器 A3 装好）：落位跳过不覆盖。"""
        make_opencode_mgmt_install(self.home, self.work)
        setup_sh = self.home / '.budgetbuddy' / 'setup.sh'
        proc = run_init(setup_sh, self.work, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('模型目录 已存在，保留不覆盖', proc.stdout)
        self.assertIn('persona 主题数据 已存在，保留不覆盖', proc.stdout)

    def test_opencode_lib_no_self_copy(self):
        """lib 源即目标（~/.budgetbuddy/lib 管理面形态）：同步跳过。"""
        make_opencode_mgmt_install(self.home, self.work)
        before = sorted(p.name for p in (self.home / '.budgetbuddy' / 'lib').iterdir())
        setup_sh = self.home / '.budgetbuddy' / 'setup.sh'
        proc = run_init(setup_sh, self.work, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('已同步 lib 模块', proc.stdout)
        after = sorted(p.name for p in (self.home / '.budgetbuddy' / 'lib').iterdir())
        self.assertEqual(before, after)


class InitCodebuddyGlobalTests(InitSandboxTestCase):
    """codebuddy 全局形态：数据落全局 + 管理面数据落位 + settings 检测全局。"""

    def _make_global_install(self, settings=None):
        cb = self.home / '.codebuddy'
        (cb / 'lib').mkdir(parents=True)
        shutil.copy2(CORE_SETUP, cb / 'setup.sh')
        for name in INIT_LIB_FILES:
            shutil.copy2(CORE_LIB / name, cb / 'lib' / name)
        shutil.copy2(CORE_MODELS, cb / 'budget-models.json')
        shutil.copy2(CORE_PERSONAS, cb / 'personas.json')
        if settings is not None:
            (cb / 'settings.json').write_text(
                json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
        return cb

    def test_codebuddy_global_form(self):
        cb = self._make_global_install()
        proc = run_init(cb / 'setup.sh', self.work, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('codebuddy:global', proc.stdout)
        # 数据目录 = 全局（codebuddy:global 形态）
        bb = self.home / '.budgetbuddy'
        self.assertTrue((bb / 'persona-active.json').is_file())
        self.assertTrue((bb / 'notify.json').is_file())
        # 管理面数据落位（codebuddy 全局形态条件）
        self.assertTrue((bb / 'budget-models.json').is_file())
        self.assertTrue((bb / 'personas.json').is_file())
        # lib 同步（~/.codebuddy/lib → ~/.budgetbuddy/lib）
        self.assertTrue((bb / 'lib' / 'init.sh').is_file())
        # hooks 桩提示（codebuddy 形态）
        self.assertIn('hooks 注入模块未安装', proc.stdout)

    def test_superpowers_enabled_message(self):
        """settings.json 已启用 superpowers：输出已启用且无未启用警告。"""
        settings = {'enabledPlugins': {
            'superpowers@codebuddy-plugins-official': True}}
        cb = self._make_global_install(settings=settings)
        proc = run_init(cb / 'setup.sh', self.work, self.home, args=['--yes'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('superpowers 插件: 已在 settings.json 中启用', proc.stdout)
        self.assertNotIn('superpowers 插件未启用', proc.stdout)


class InitBudgetDirTests(InitSandboxTestCase):
    """BUDGET_DIR 运行时数据目录覆盖（design.md §8.3）。"""

    def test_budget_dir_override(self):
        cb = make_codebuddy_install(self.tmp)
        custom = self.tmp / 'custom-data'
        proc = run_init(cb / 'setup.sh', self.tmp, self.home,
                        args=['--yes'], env_extra={'BUDGET_DIR': str(custom)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((custom / 'persona-active.json').is_file())
        self.assertTrue((custom / 'notify.json').is_file())
        self.assertTrue((custom / 'memory').is_dir())
        # BUDGET_DIR 覆盖时项目 .budget/ 不再创建
        self.assertFalse((self.tmp / '.budget').exists())


if __name__ == '__main__':
    unittest.main()
