#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""persona.sh / persona_expand.py 主题管理端到端单测（design.md §8.5 / specs
setup-cli「personas 五主题」Requirement）。

覆盖:
- setup.sh persona 分发端到端（临时目录 .codebuddy 安装形态）: list 五主题
  标记当前主题 / set sanguo 写 .budget/persona-active.json（theme + 11 键
  roles + greeting，specs「主题切换」Scenario）/ 裸主题名等价 set /
  show 当前主题详情 / expand 11 键映射（--json 机器可读）/ 未知主题报错
- persona_expand.py 直调: validate 子命令（成功输出 yes）/ 自定义主题校验
  （roles 11 键缺失报错 exit 1 / 未知键 stderr 告警 / report_templates
  缺键报错）/ current / greeting 子命令 / set 原子写键排序
- bash -n 语法检查
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
CORE_PERSONAS = REPO_ROOT / 'core' / 'personas' / 'personas.json'
EXPAND_SCRIPT = CORE_LIB / 'persona_expand.py'
PERSONA_SCRIPT = CORE_LIB / 'persona.sh'

# 基础层 4 文件（setup.sh 硬依赖）+ persona 模块 2 文件
BASE_LIB_FILES = ('colors.sh', 'utils.sh', 'platform.sh', 'shell.sh')
PERSONA_LIB_FILES = ('persona.sh', 'persona_expand.py')

# 五主题（specs「personas 五主题」Requirement）
THEME_KEYS = ('default', 'genshin', 'sanguo', 'shuihu', 'tech-legends')

# 11 键角色集（design.md §8.5: leader + §6 十角色）
ROLE_KEYS = (
    'leader', 'architect', 'coder-lite', 'coder-standard', 'coder-senior',
    'reviewer', 'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
)


def _stripped_env():
    """构造剥离 BUDGET_* 与 IDE safe-delete 注入的基础环境。"""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith('BUDGET_'):
            del env[key]
    # 剥离 IDE safe-delete 注入（BASH_ENV 函数 + PATH shim + 会话 ID）：
    # 包装版 rm/rmdir/unlink 单次调用 ~150ms（python3 转义 + 回收站投递），
    # 且回收站投递失败时 rm 返回非零；测试需验证原生删除语义（对齐
    # tests/test_update.py run_setup 的剥离写法）。
    for key in ('BASH_ENV', 'CODEBUDDY_SESSION_ID', 'CLAUDE_SESSION_ID',
                'CODEBUDDY_SAFE_DELETE_BIN_DIR', 'CODEBUDDY_SAFE_DELETE_REPORT_PATH'):
        env.pop(key, None)
    env['PATH'] = ':'.join(
        p for p in env.get('PATH', '').split(':')
        if p and '/shim/safe-bin' not in p)
    return env


def run_bash(script, cwd, home, env_extra=None):
    """隔离 HOME 运行 bash（剥离 BUDGET_* 环境变量后按需注入）。"""
    env = _stripped_env()
    env['HOME'] = str(home)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ['bash', '-c', script], cwd=str(cwd), env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )


def run_expand(args, env_extra=None):
    """直调 persona_expand.py（隔离 BUDGET_* 变量后按需注入）。"""
    env = _stripped_env()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(EXPAND_SCRIPT)] + list(args),
        capture_output=True, text=True, encoding='utf-8', timeout=60, env=env,
    )


def load_personas():
    """加载 core personas.json 数据（自定义主题测试的改造基底）。"""
    return json.loads(CORE_PERSONAS.read_text(encoding='utf-8'))


class PersonaSandbox(unittest.TestCase):
    """公共沙箱: .codebuddy 项目级安装形态（setup.sh + 基础层 + persona 模块）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-persona-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir()
        self.work.mkdir()
        self.cb = self.work / '.codebuddy'
        (self.cb / 'lib').mkdir(parents=True)
        shutil.copy2(CORE_SETUP, self.cb / 'setup.sh')
        for name in BASE_LIB_FILES + PERSONA_LIB_FILES:
            shutil.copy2(CORE_LIB / name, self.cb / 'lib' / name)
        shutil.copy2(CORE_PERSONAS, self.cb / 'personas.json')

    def tearDown(self):
        self._tmp.cleanup()

    def run_setup(self, args, cwd=None, env_extra=None):
        """bash setup.sh <args>（默认 cwd=项目根，探测 codebuddy:project）。"""
        return run_bash(
            'bash "%s" %s' % (self.cb / 'setup.sh', args),
            cwd or self.work, self.home, env_extra)

    def active_path(self):
        return self.work / '.budget' / 'persona-active.json'

    def read_active(self):
        return json.loads(self.active_path().read_text(encoding='utf-8'))


class PersonaDispatchTests(PersonaSandbox):
    """setup.sh persona 分发端到端（specs「主题切换」Scenario）。"""

    def test_list_shows_five_themes(self):
        proc = self.run_setup('persona list')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for theme in THEME_KEYS:
            self.assertIn(theme, proc.stdout)
        # default 为当前主题（未设置 active 时）
        self.assertIn('当前', proc.stdout)

    def test_set_sanguo_writes_active_file(self):
        """specs「主题切换」Scenario: set 后 persona-active.json 完整 11 键。"""
        proc = self.run_setup('persona set sanguo')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.active_path().is_file())
        active = self.read_active()
        self.assertEqual(active['theme'], 'sanguo')
        self.assertEqual(active['greeting'], '主公')
        self.assertEqual(sorted(active['roles']), sorted(ROLE_KEYS))
        self.assertEqual(active['roles']['leader'], '刘备')
        self.assertEqual(active['roles']['coder-senior'], '关羽')
        # 键排序幂等（json sort_keys 纪律）
        self.assertEqual(list(active.keys()), sorted(active.keys()))
        # report_templates 5 键
        self.assertEqual(
            sorted(active['report_templates']),
            ['review_pass', 'review_reject', 'task_complete', 'test_fail', 'test_pass'])

    def test_bare_theme_equivalent_to_set(self):
        """specs Scenario: budget setup persona sanguo 等价 set sanguo。"""
        proc = self.run_setup('persona sanguo')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        active = self.read_active()
        self.assertEqual(active['theme'], 'sanguo')
        self.assertEqual(sorted(active['roles']), sorted(ROLE_KEYS))

    def test_show_displays_current_theme(self):
        self.run_setup('persona set sanguo')
        proc = self.run_setup('persona show')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('sanguo', proc.stdout)
        self.assertIn('主公', proc.stdout)
        self.assertIn('生效文件', proc.stdout)
        self.assertIn('11 键', proc.stdout)

    def test_show_without_active_uses_default(self):
        proc = self.run_setup('persona show')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('default', proc.stdout)
        self.assertIn('未设置', proc.stdout)

    def test_expand_outputs_eleven_roles(self):
        proc = self.run_setup('persona expand sanguo')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for role in ROLE_KEYS:
            self.assertIn(role, proc.stdout)
        self.assertIn('主公', proc.stdout)

    def test_expand_defaults_to_current_theme(self):
        self.run_setup('persona set shuihu')
        proc = self.run_setup('persona expand')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('shuihu', proc.stdout)
        self.assertIn('哥哥', proc.stdout)

    def test_expand_json_machine_readable(self):
        proc = self.run_setup('persona expand sanguo --json')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(payload['theme'], 'sanguo')
        self.assertEqual(payload['greeting'], '主公')
        self.assertEqual(sorted(payload['roles']), sorted(ROLE_KEYS))

    def test_list_json_machine_readable(self):
        proc = self.run_setup('persona list --json')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(payload['current'], 'default')
        self.assertEqual(
            sorted(t['key'] for t in payload['themes']), sorted(THEME_KEYS))

    def test_set_unknown_theme_fails(self):
        proc = self.run_setup('persona set nosuch')
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(self.active_path().exists())

    def test_set_without_theme_fails(self):
        proc = self.run_setup('persona set')
        self.assertEqual(proc.returncode, 1)

    def test_help_outputs_usage(self):
        proc = self.run_setup('persona help')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('用法', proc.stdout)
        self.assertIn('list', proc.stdout)

    def test_bash_n_persona_script(self):
        proc = subprocess.run(
            ['bash', '-n', str(PERSONA_SCRIPT)],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class PersonaExpandScriptTests(unittest.TestCase):
    """persona_expand.py 直调: validate / 自定义主题校验 / current / greeting。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-expand-')
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write_custom_personas(self, data):
        """写入自定义 personas.json（返回路径）。"""
        path = self.tmp / 'personas.json'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return path

    def test_validate_builtin_theme_ok(self):
        proc = run_expand(
            ['validate', '--theme', 'sanguo', '--personas', str(CORE_PERSONAS)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'yes')

    def test_custom_theme_missing_role_key_fails(self):
        """自定义主题 roles 缺键 → 报错 exit 1（11 键完整覆盖校验）。"""
        data = load_personas()
        del data['themes']['sanguo']['roles']['tester']
        path = self.write_custom_personas(data)
        proc = run_expand(['validate', '--theme', 'sanguo', '--personas', str(path)])
        self.assertEqual(proc.returncode, 1)
        self.assertIn('tester', proc.stderr)
        self.assertIn('缺失', proc.stderr)

    def test_custom_theme_missing_two_keys_reports_all(self):
        data = load_personas()
        del data['themes']['genshin']['roles']['tester']
        del data['themes']['genshin']['roles']['director']
        path = self.write_custom_personas(data)
        proc = run_expand(['validate', '--theme', 'genshin', '--personas', str(path)])
        self.assertEqual(proc.returncode, 1)
        self.assertIn('2 个键', proc.stderr)
        self.assertIn('director', proc.stderr)

    def test_custom_theme_extra_role_key_warns_but_passes(self):
        """roles 含未知键 → stderr 告警但校验通过（宽容策略）。"""
        data = load_personas()
        data['themes']['sanguo']['roles']['reviewer-a'] = {'name': 'X'}
        path = self.write_custom_personas(data)
        proc = run_expand(['validate', '--theme', 'sanguo', '--personas', str(path)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未知键', proc.stderr)
        self.assertIn('reviewer-a', proc.stderr)

    def test_custom_theme_missing_report_template_fails(self):
        data = load_personas()
        del data['themes']['shuihu']['report_templates']['test_pass']
        path = self.write_custom_personas(data)
        proc = run_expand(['validate', '--theme', 'shuihu', '--personas', str(path)])
        self.assertEqual(proc.returncode, 1)
        self.assertIn('report_templates', proc.stderr)
        self.assertIn('test_pass', proc.stderr)

    def test_set_writes_sorted_active_file(self):
        active = self.tmp / 'persona-active.json'
        proc = run_expand(
            ['set', '--personas', str(CORE_PERSONAS),
             '--active', str(active), '--theme', 'tech-legends'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(active.read_text(encoding='utf-8'))
        self.assertEqual(data['theme'], 'tech-legends')
        self.assertEqual(data['greeting'], 'Linus')
        self.assertEqual(sorted(data['roles']), sorted(ROLE_KEYS))
        self.assertEqual(list(data.keys()), sorted(data.keys()))

    def test_current_and_greeting_read_active(self):
        active = self.tmp / 'persona-active.json'
        run_expand(
            ['set', '--personas', str(CORE_PERSONAS),
             '--active', str(active), '--theme', 'sanguo'])
        proc = run_expand(
            ['current', '--personas', str(CORE_PERSONAS), '--active', str(active)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'sanguo')
        proc = run_expand(
            ['greeting', '--personas', str(CORE_PERSONAS), '--active', str(active)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '主公')

    def test_current_defaults_without_active(self):
        proc = run_expand(['current', '--personas', str(CORE_PERSONAS)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'default')

    def test_unknown_theme_lists_available(self):
        proc = run_expand(
            ['validate', '--theme', 'nosuch', '--personas', str(CORE_PERSONAS)])
        self.assertEqual(proc.returncode, 1)
        self.assertIn('不存在', proc.stderr)
        for theme in THEME_KEYS:
            self.assertIn(theme, proc.stderr)


if __name__ == '__main__':
    unittest.main()
