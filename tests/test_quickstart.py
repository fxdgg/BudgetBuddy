#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quickstart.py 快速上手向导单测（design.md §8.1/§8.2；specs/setup-cli
「quickstart 入口可用」Scenario）。

临时 HOME + 项目目录隔离环境，subprocess 驱动：
- 非交互模式（--non-interactive / 管道 stdin 非 tty / stdin EOF 耗尽）:
  全流程默认值走通 exit 0、8 步输出断言、零副作用（不执行 setup.sh
  子命令、不产生任何文件）
- 交互模式（--interactive + stdin 注入）: 默认值回车、主题/预设选择经
  setup.sh 命令面执行（记录型 mock setup.sh 验证 argv 与 BUDGET_INIT_YES
  透传）、init 引导确认/跳过、EOF 容错走默认
- setup.sh 分发集成: quickstart/tour/wizard 别名启动向导、lib 缺失报错
- 模块单元: personas.json 动态主题清单与降级、notify.json 双级检测、
  BUDGET_PLATFORM 显式探测
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_LIB = REPO_ROOT / 'core' / 'lib'
CORE_SETUP = REPO_ROOT / 'core' / 'setup.sh'
CORE_MODELS = REPO_ROOT / 'core' / 'models' / 'budget-models.json'
CORE_PERSONAS = REPO_ROOT / 'core' / 'personas' / 'personas.json'
QUICKSTART = CORE_LIB / 'quickstart.py'

# 安装形态所需 lib 文件（基础层 4 + quickstart.py；setup.sh 硬依赖基础层）
BASE_LIB_FILES = ('colors.sh', 'utils.sh', 'platform.sh', 'shell.sh')

# 8 步标题（顺序即向导流程顺序）
STEP_TITLES = (
    '步骤 1/8: 欢迎与项目简介',
    '步骤 2/8: 环境检查',
    '步骤 3/8: 初始化引导',
    '步骤 4/8: 角色主题选择',
    '步骤 5/8: 模型预设选择',
    '步骤 6/8: 通知配置引导',
    '步骤 7/8: 工作流演示',
    '步骤 8/8: 完成',
)

# 内嵌降级主题清单键集（与 core/personas/personas.json 五主题一致）
FALLBACK_THEME_KEYS = {'default', 'genshin', 'sanguo', 'shuihu', 'tech-legends'}


def run_quickstart(args, cwd, home, env_extra=None, stdin_text=None, timeout=60):
    """隔离 HOME 运行 quickstart.py（剥离 BUDGET_* 环境变量后按需注入）。"""
    env = dict(os.environ)
    env['HOME'] = str(home)
    for key in list(env):
        if key.startswith('BUDGET_'):
            del env[key]
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(QUICKSTART)] + list(args),
        cwd=str(cwd), env=env, capture_output=True, text=True,
        timeout=timeout, input=stdin_text,
    )


def make_install(base, with_quickstart=True):
    """构造 .codebuddy 项目级安装形态（setup.sh + lib 基础层 + 数据文件）。"""
    cb = base / '.codebuddy'
    (cb / 'lib').mkdir(parents=True)
    shutil.copy2(CORE_SETUP, cb / 'setup.sh')
    for name in BASE_LIB_FILES:
        shutil.copy2(CORE_LIB / name, cb / 'lib' / name)
    if with_quickstart:
        shutil.copy2(QUICKSTART, cb / 'lib' / 'quickstart.py')
    shutil.copy2(CORE_MODELS, cb / 'budget-models.json')
    shutil.copy2(CORE_PERSONAS, cb / 'personas.json')
    return cb


def make_recording_setup(directory, log_path):
    """写入记录型 mock setup.sh：argv 逐行与 BUDGET_INIT_YES 标记落 log。"""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / 'setup.sh'
    script.write_text(
        '#!/bin/bash\n'
        'printf \'%s\\n\' "$*" >> "$BUDGET_CALL_LOG"\n'
        'if [[ "${BUDGET_INIT_YES:-}" == "1" ]]; then\n'
        '    echo "INIT_YES=1" >> "$BUDGET_CALL_LOG"\n'
        'fi\n'
        'exit 0\n',
        encoding='utf-8',
    )
    script.chmod(0o755)
    return script


def write_json(path, data):
    """写 JSON 文件（父目录自动创建）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def read_calls(log_path):
    """读取 mock setup.sh 调用记录（每行一条 argv 串联或 INIT_YES 标记）。"""
    if not log_path.exists():
        return []
    return [line for line in log_path.read_text(encoding='utf-8').splitlines() if line]


class NonInteractiveTests(unittest.TestCase):
    """非交互模式：默认值走完全流程、零副作用、输出断言。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.home = self.base / 'home'
        self.project = self.base / 'project'
        self.home.mkdir()
        self.project.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_noninteractive_flag_full_flow(self):
        """--non-interactive：exit 0 + 8 步标题 + 非交互说明 + 默认值输出。"""
        result = run_quickstart(['--non-interactive'], self.project, self.home)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('非交互模式（未检测到终端输入）', result.stdout)
        self.assertIn('不执行任何配置变更', result.stdout)
        for title in STEP_TITLES:
            self.assertIn(title, result.stdout, msg=f'缺少步骤标题: {title}')
        # 各步骤默认值输出
        self.assertIn('使用默认选项 1（default）', result.stdout)
        self.assertIn('使用默认选项 2（balanced）', result.stdout)
        self.assertIn('已选择默认主题 default，未执行', result.stdout)
        self.assertIn('已选择默认预设 balanced，未执行', result.stdout)
        self.assertIn('如需应用: budget setup persona set default', result.stdout)
        self.assertIn('如需应用: budget setup agent preset balanced', result.stdout)
        # 非交互不执行子命令：不出现 setup.sh 子命令执行痕迹
        self.assertNotIn('应用角色主题: ', result.stdout)

    def test_pipe_eof_defaults(self):
        """管道 stdin（非 tty）自动进入非交互模式走默认（即使管道有数据）。"""
        result = run_quickstart([], self.project, self.home, stdin_text='y\n3\n3\ny\n')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('非交互模式（未检测到终端输入）', result.stdout)
        self.assertIn('已选择默认主题 default，未执行', result.stdout)
        self.assertIn('已选择默认预设 balanced，未执行', result.stdout)
        # 管道数据不被消费：仍走默认而非用户输入的 3/3
        self.assertNotIn('已选择默认主题 sanguo', result.stdout)

    def test_stdin_immediate_eof_defaults(self):
        """stdin 立即 EOF（空输入）：非交互模式走默认全流程。"""
        result = run_quickstart([], self.project, self.home, stdin_text='')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('非交互模式（未检测到终端输入）', result.stdout)
        for title in STEP_TITLES:
            self.assertIn(title, result.stdout)

    def test_no_side_effects(self):
        """非交互运行零副作用：不产生任何文件、不调用 setup.sh 子命令。"""
        mock_dir = self.base / 'mock-setup'
        log = self.base / 'calls.log'
        make_recording_setup(mock_dir, log)
        env = {'BUDGET_SETUP_DIR': str(mock_dir), 'BUDGET_CALL_LOG': str(log)}
        result = run_quickstart(['--non-interactive'], self.project, self.home, env_extra=env)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # 不调用任何子命令
        self.assertEqual(read_calls(log), [])
        # 不产生任何数据文件（HOME 与项目目录保持空）
        self.assertEqual(list(self.home.rglob('*')), [])
        self.assertEqual(list(self.project.rglob('*')), [])

    def test_step_output_assertions(self):
        """各步骤关键输出：欢迎 banner、四平台、三档预设、五阶段、完成指引。"""
        result = run_quickstart(['--non-interactive'], self.project, self.home)
        self.assertEqual(result.returncode, 0)
        output = result.stdout
        # 步骤 1: 欢迎与简介
        self.assertIn('BudgetBuddy 快速上手向导', output)
        self.assertIn('多 Agent 省钱研发工作流套件', output)
        self.assertIn('四平台支持 — CodeBuddy / OpenCode / Claude Code / Codex', output)
        # 步骤 2: 环境检查（干净环境 → unknown 提示 + 依赖检查）
        self.assertIn('未检测到 BudgetBuddy 安装形态', output)
        self.assertIn('依赖检查：', output)
        # 步骤 3: 初始化引导（未 init → 指引）
        self.assertIn('初始化状态: 未完成', output)
        self.assertIn('如需初始化: budget setup init', output)
        # 步骤 4: 主题清单（core 源 personas.json 动态读取，5 主题）
        for key in FALLBACK_THEME_KEYS:
            self.assertIn(key, output)
        # 步骤 5: 三档预设
        for preset in ('economic', 'balanced', 'quality'):
            self.assertIn(preset, output)
        # 步骤 6: 通知引导
        self.assertIn('未检测到通知配置', output)
        self.assertIn('webhook', output)
        # 步骤 7: 工作流演示（五阶段 + /budget:start）
        self.assertIn('/budget:start', output)
        self.assertIn('/budget-start', output)
        for phase in ('Phase 1', 'Phase 2', 'Phase 3', 'Phase 4', 'Phase 5'):
            self.assertIn(phase, output)
        # 步骤 8: 完成页指引
        self.assertIn('快速上手完成', output)
        self.assertIn('budget setup help', output)
        self.assertIn('budget status', output)

    def test_step_titles_in_order(self):
        """8 步标题按流程顺序出现。"""
        result = run_quickstart(['--non-interactive'], self.project, self.home)
        self.assertEqual(result.returncode, 0)
        positions = [result.stdout.find(title) for title in STEP_TITLES]
        self.assertTrue(all(pos >= 0 for pos in positions), msg=str(positions))
        self.assertEqual(positions, sorted(positions), msg='步骤标题顺序错乱')


class InteractiveTests(unittest.TestCase):
    """交互模式（--interactive + stdin 注入）：选择执行与容错。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.home = self.base / 'home'
        self.project = self.base / 'project'
        self.home.mkdir()
        self.project.mkdir()
        # mock setup.sh（记录 argv）+ 构造 personas.json（default + sanguo 两主题，
        # 主题清单确定可控：1 default、2 sanguo）
        self.mock_dir = self.base / 'mock-setup'
        self.log = self.base / 'calls.log'
        make_recording_setup(self.mock_dir, self.log)
        write_json(self.mock_dir / 'personas.json', {
            'themes': {
                'default': {'description': '专业模式'},
                'sanguo': {'description': '三国主题'},
            },
        })
        self.env = {
            'BUDGET_SETUP_DIR': str(self.mock_dir),
            'BUDGET_CALL_LOG': str(self.log),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_interactive_defaults(self):
        """全回车走默认值：persona set default + agent preset balanced，不执行 init。"""
        # 交互点：init 确认(默认否)、主题(默认1)、预设(默认2)、通知说明(默认是)
        result = run_quickstart(['--interactive'], self.project, self.home,
                                env_extra=self.env, stdin_text='\n\n\n\n')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        calls = read_calls(self.log)
        self.assertIn('persona set default', calls)
        self.assertIn('agent preset balanced', calls)
        self.assertNotIn('init', calls)
        self.assertNotIn('INIT_YES=1', calls)

    def test_interactive_selection(self):
        """显式选择：init 确认 y（透传 BUDGET_INIT_YES=1）+ sanguo + quality。"""
        # init y → 主题 2(sanguo) → 预设 3(quality) → 通知说明回车
        result = run_quickstart(['--interactive'], self.project, self.home,
                                env_extra=self.env, stdin_text='y\n2\n3\n\n')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        calls = read_calls(self.log)
        self.assertIn('init', calls)
        self.assertIn('INIT_YES=1', calls)
        self.assertIn('persona set sanguo', calls)
        self.assertIn('agent preset quality', calls)
        # 调用顺序：init → persona → preset
        self.assertLess(calls.index('init'), calls.index('persona set sanguo'))
        self.assertLess(calls.index('persona set sanguo'), calls.index('agent preset quality'))

    def test_interactive_init_skip(self):
        """init 确认 n：跳过初始化（无 init 调用），其余步骤正常执行。"""
        result = run_quickstart(['--interactive'], self.project, self.home,
                                env_extra=self.env, stdin_text='n\n\n\n\n')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        calls = read_calls(self.log)
        self.assertNotIn('init', calls)
        self.assertIn('已跳过初始化', result.stdout)
        self.assertIn('persona set default', calls)

    def test_interactive_eof_graceful(self):
        """交互模式 stdin 立即 EOF：每步取默认值继续走完全流程 exit 0。"""
        result = run_quickstart(['--interactive'], self.project, self.home,
                                env_extra=self.env, stdin_text='')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for title in STEP_TITLES:
            self.assertIn(title, result.stdout)
        # EOF 默认值同样经命令面执行
        calls = read_calls(self.log)
        self.assertIn('persona set default', calls)
        self.assertIn('agent preset balanced', calls)

    def test_interactive_initialized_shows_config(self):
        """已 init：展示当前配置（persona 主题 + 通知状态），无 init 交互点。"""
        write_json(self.home / '.budgetbuddy' / 'persona-active.json',
                   {'theme': 'sanguo', 'greeting': '主公', 'roles': {}})
        write_json(self.home / '.budgetbuddy' / 'notify.json',
                   {'enabled': True, 'channels': {'bot': {'type': 'custom'}}, 'events': {}})
        # 已 init 无 init 确认点：主题、预设、通知说明共 3 个交互点
        result = run_quickstart(['--interactive'], self.project, self.home,
                                env_extra=self.env, stdin_text='\n\n\n')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('初始化状态: 已完成', result.stdout)
        self.assertIn('角色主题: sanguo', result.stdout)
        self.assertIn('通知配置: 已启用', result.stdout)
        self.assertIn('1 个渠道', result.stdout)

    def test_interactive_invalid_choice_falls_back(self):
        """无效选项输入：回退默认值继续（容错）。"""
        result = run_quickstart(['--interactive'], self.project, self.home,
                                env_extra=self.env, stdin_text='n\n99\nabc\n\n')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('无效输入，使用默认选项 1', result.stdout)
        self.assertIn('无效输入，使用默认选项 2', result.stdout)
        calls = read_calls(self.log)
        self.assertIn('persona set default', calls)
        self.assertIn('agent preset balanced', calls)


class SetupDispatchTests(unittest.TestCase):
    """setup.sh 分发集成：quickstart/tour/wizard 入口与模块缺失报错。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.home = self.base / 'home'
        self.project = self.base / 'project'
        self.home.mkdir()
        self.project.mkdir()
        self.install = make_install(self.project)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_setup(self, subcommand, stdin_text='', extra_args=None):
        """经 setup.sh 分发入口运行（模拟 budget setup <子命令> [参数]）。"""
        env = dict(os.environ)
        env['HOME'] = str(self.home)
        for key in list(env):
            if key.startswith('BUDGET_'):
                del env[key]
        return subprocess.run(
            ['bash', str(self.install / 'setup.sh'), subcommand]
            + list(extra_args or []),
            cwd=str(self.project), env=env, capture_output=True, text=True,
            timeout=60, input=stdin_text,
        )

    def test_setup_dispatch_quickstart(self):
        """budget setup quickstart：exec 启动向导，非交互 stdin 走默认全流程。"""
        result = self._run_setup('quickstart')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('BudgetBuddy 快速上手向导', result.stdout)
        for title in STEP_TITLES:
            self.assertIn(title, result.stdout)
        self.assertIn('非交互模式（未检测到终端输入）', result.stdout)
        # 非交互零副作用：不执行 init/persona/agent 子命令、不产生数据文件
        self.assertNotIn('初始化完成', result.stdout)
        self.assertFalse((self.home / '.budgetbuddy').exists())
        self.assertFalse((self.project / '.budget').exists())

    def test_setup_dispatch_aliases(self):
        """别名 tour / wizard 与 quickstart 同分发分支。"""
        for alias in ('tour', 'wizard'):
            result = self._run_setup(alias)
            self.assertEqual(result.returncode, 0, msg=f'{alias}: {result.stderr}')
            self.assertIn('BudgetBuddy 快速上手向导', result.stdout)
            self.assertIn('步骤 1/8: 欢迎与项目简介', result.stdout)

    def test_setup_dispatch_missing_module(self):
        """lib 无 quickstart.py：显式报错 exit 1（无死代码入口）。"""
        broken = self.base / 'broken' / '.codebuddy'
        broken.mkdir(parents=True)
        shutil.copy2(CORE_SETUP, broken / 'setup.sh')
        (broken / 'lib').mkdir()
        for name in BASE_LIB_FILES:
            shutil.copy2(CORE_LIB / name, broken / 'lib' / name)
        env = dict(os.environ)
        env['HOME'] = str(self.home)
        for key in list(env):
            if key.startswith('BUDGET_'):
                del env[key]
        result = subprocess.run(
            ['bash', str(broken / 'setup.sh'), 'quickstart'],
            cwd=str(self.base / 'broken'), env=env, capture_output=True, text=True,
            timeout=60, input='',
        )
        self.assertEqual(result.returncode, 1)
        combined = result.stdout + result.stderr
        self.assertIn('quickstart', combined)
        self.assertIn('尚未安装', combined)

    def test_setup_dispatch_passes_interactive_flag(self):
        """P2-1：quickstart --interactive 参数透传（stdin pipe 下仍进交互模式）。

        修复前分发层丢弃参数 → quickstart.py 走 stdin 非 tty 检测自动进入
        非交互模式（输出非交互横幅 + 「未执行」）；修复后 --interactive
        生效 → 交互模式（stdin 注入驱动选择，尝试执行 persona set）。
        """
        result = self._run_setup('quickstart', extra_args=['--interactive'],
                                 stdin_text='\n\n\n\n')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # 参数透传证明：交互模式不输出非交互横幅
        self.assertNotIn('非交互模式（未检测到终端输入）', result.stdout)
        # 交互模式执行痕迹：尝试执行 persona set（模块未装时容错告警，
        # 但「应用角色主题」动作输出证明交互分支真实走到）
        self.assertIn('应用角色主题: default', result.stdout)
        self.assertNotIn('已选择默认主题 default，未执行', result.stdout)

    def test_setup_dispatch_passes_noninteractive_flag(self):
        """P2-1：quickstart --non-interactive 参数透传（显式非交互横幅）。"""
        result = self._run_setup('quickstart',
                                 extra_args=['--non-interactive'])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('非交互模式（未检测到终端输入）', result.stdout)
        for title in STEP_TITLES:
            self.assertIn(title, result.stdout)
        # 非交互零副作用
        self.assertFalse((self.home / '.budgetbuddy').exists())


class UnitTests(unittest.TestCase):
    """模块单元：主题清单、通知检测、平台显式探测。"""

    def setUp(self):
        sys.path.insert(0, str(CORE_LIB))
        import quickstart  # noqa: F401  # 延迟导入并缓存
        self.quickstart = quickstart

    def tearDown(self):
        sys.path.remove(str(CORE_LIB))
        sys.modules.pop('quickstart', None)

    def test_load_persona_themes_dynamic(self):
        """personas.json 存在：动态清单，default 首位、描述取自文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            write_json(Path(tmp) / 'personas.json', {
                'themes': {
                    'sanguo': {'description': '三国主题'},
                    'default': {'description': '专业模式'},
                    'shuihu': {'name': '水浒'},
                },
            })
            with mock.patch.dict(os.environ, {'BUDGET_SETUP_DIR': tmp}):
                themes = self.quickstart._load_persona_themes()
        self.assertEqual(themes[0][0], 'default')
        self.assertEqual(dict(themes)['sanguo'], '三国主题')
        # 无 description 时降级取 name
        self.assertEqual(dict(themes)['shuihu'], '水浒')

    def test_load_persona_themes_fallback(self):
        """personas.json 探测失败：降级内嵌五主题清单。"""
        with mock.patch.object(self.quickstart, '_locate_personas_file', return_value=''):
            themes = self.quickstart._load_persona_themes()
        self.assertEqual({key for key, _ in themes}, FALLBACK_THEME_KEYS)
        self.assertEqual(themes[0][0], 'default')

    def test_load_persona_themes_invalid_json(self):
        """personas.json 损坏（非法 JSON）：降级内嵌清单。"""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'personas.json').write_text('{invalid', encoding='utf-8')
            with mock.patch.dict(os.environ, {'BUDGET_SETUP_DIR': tmp}):
                themes = self.quickstart._load_persona_themes()
        self.assertEqual({key for key, _ in themes}, FALLBACK_THEME_KEYS)

    def test_detect_notify_config_levels(self):
        """notify.json 双级降级：项目级优先于全局级；皆无返回空 dict。"""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / 'proj-budget'
            global_dir = Path(tmp) / 'global-bb'
            write_json(project_dir / 'notify.json',
                       {'enabled': True, 'channels': {'a': {}, 'b': {}}, 'events': {}})
            write_json(global_dir / 'notify.json', {'enabled': False, 'channels': {}})
            with mock.patch.object(self.quickstart, '_project_data_dir',
                                   return_value=str(project_dir)), \
                 mock.patch.object(self.quickstart, '_global_data_dir',
                                   return_value=str(global_dir)):
                notify = self.quickstart._detect_notify_config()
            self.assertEqual(notify['path'], str(project_dir / 'notify.json'))
            self.assertTrue(notify['enabled'])
            self.assertEqual(notify['channels'], 2)
            # 项目级不存在 → 降级全局级
            with mock.patch.object(self.quickstart, '_project_data_dir',
                                   return_value=str(Path(tmp) / 'missing')), \
                 mock.patch.object(self.quickstart, '_global_data_dir',
                                   return_value=str(global_dir)):
                notify = self.quickstart._detect_notify_config()
            self.assertEqual(notify['path'], str(global_dir / 'notify.json'))
            self.assertFalse(notify['enabled'])
            # 皆无 → 空 dict
            with mock.patch.object(self.quickstart, '_project_data_dir',
                                   return_value=str(Path(tmp) / 'missing')), \
                 mock.patch.object(self.quickstart, '_global_data_dir',
                                   return_value=str(Path(tmp) / 'missing2')):
                self.assertEqual(self.quickstart._detect_notify_config(), {})

    def test_detect_platform_explicit(self):
        """BUDGET_PLATFORM 显式指定：跳过探测直接返回对应全局形态。"""
        with mock.patch.dict(os.environ, {'BUDGET_PLATFORM': 'opencode'}):
            platform = self.quickstart._detect_platform()
        self.assertEqual(platform['kind'], 'opencode')
        self.assertEqual(platform['scope'], 'global')
        with mock.patch.dict(os.environ, {'BUDGET_PLATFORM': 'codebuddy'}):
            platform = self.quickstart._detect_platform()
        self.assertEqual(platform['kind'], 'codebuddy')
        self.assertEqual(platform['scope'], 'global')

    def test_locate_setup_script_priority(self):
        """setup.sh 定位：BUDGET_SETUP_DIR 优先，其次 lib 同级。"""
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 's' / 'setup.sh'
            marker.parent.mkdir(parents=True)
            marker.write_text('#!/bin/bash\n', encoding='utf-8')
            with mock.patch.dict(os.environ, {'BUDGET_SETUP_DIR': str(marker.parent)}):
                self.assertEqual(self.quickstart._locate_setup_script(), str(marker))
        # lib 同级（core 源形态：core/setup.sh）
        self.assertEqual(self.quickstart._locate_setup_script(), str(CORE_SETUP))


if __name__ == '__main__':
    unittest.main()
