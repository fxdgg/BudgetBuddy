#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.sh 安装完整性校验单测（design.md §8.2/§10 / specs setup-cli validate）。

覆盖:
- codebuddy 项目级完整安装形态 → validate exit 0（全部检查通过）
- 抽文件删除（agent / command / skill / rule / hooks / models）→ 报缺失
  exit 1 + 失败清单
- models 坏 JSON / roles 键集不符 → JSON 数据校验失败 exit 1
- personas 坏 JSON / 主题 roles 缺键 / 内置主题缺失 → exit 1
- opencode 全局管理面 + 项目结构形态（AGENTS.fragment.md 12 区块）→
  exit 0 / 区块缺失 / fragment 缺失 / agent 缺失 → exit 1
- 未安装形态（探测失败）→ exit 1
- check 别名分发 / bash -n 语法
- 端到端链路: persona set sanguo → validate → stats（表格 + --json）→
  run_summary（markdown 摘要）
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
VALIDATE_SCRIPT = CORE_LIB / 'validate.sh'

# 基础层 4 文件（setup.sh 硬依赖）+ T10c 模块
BASE_LIB_FILES = ('colors.sh', 'utils.sh', 'platform.sh', 'shell.sh')
MODULE_LIB_FILES = ('validate.sh', 'persona.sh', 'persona_expand.py',
                    'display.py', 'run_summary.py', 'hooks.sh', 'hooks_inject.py')

# §6 十角色（agents 清单）
AGENTS = (
    'architect', 'coder-lite', 'coder-standard', 'coder-senior', 'reviewer',
    'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
)
# §11 命令（budget×3 + opsx×4）
BUDGET_COMMANDS = ('goal', 'start', 'status')
OPSX_COMMANDS = ('apply', 'archive', 'explore', 'propose')
# §8.2 skills（budget-workflow + budget-notify + openspec×4）
SKILLS = (
    'budget-workflow', 'budget-notify', 'openspec-apply-change',
    'openspec-archive-change', 'openspec-explore', 'openspec-propose',
)
# rules 12 主名（codebuddy 落点 rules/budget-<name>.mdc）
RULES = (
    'coder-guard', 'cpp-style', 'css-style', 'go-style', 'java-style',
    'leader-no-code', 'python-style', 'rtk', 'sql-style', 'trpc-style',
    'typescript-style', 'workflow-enforcement',
)


def run_bash(script, cwd, home, env_extra=None):
    """隔离 HOME 运行 bash（剥离 BUDGET_* 环境变量后按需注入）。"""
    env = dict(os.environ)
    env['HOME'] = str(home)
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
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ['bash', '-c', script], cwd=str(cwd), env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )


def write_stub(path, text='# stub\n'):
    """写入占位文件（自动创建父目录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


class ValidateSandbox(unittest.TestCase):
    """公共沙箱: 隔离 HOME + 项目目录（codebuddy/opencode 安装形态基底）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-validate-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def copy_lib(self, dest_lib):
        """复制基础层 + T10c 模块到目标 lib 目录。"""
        dest_lib.mkdir(parents=True, exist_ok=True)
        for name in BASE_LIB_FILES + MODULE_LIB_FILES:
            shutil.copy2(CORE_LIB / name, dest_lib / name)

    def make_codebuddy_install(self):
        """构造 codebuddy 项目级完整安装形态（work/.codebuddy/）。"""
        cb = self.work / '.codebuddy'
        (cb / 'lib').mkdir(parents=True)
        shutil.copy2(CORE_SETUP, cb / 'setup.sh')
        self.copy_lib(cb / 'lib')
        for agent in AGENTS:
            write_stub(cb / 'agents' / f'{agent}.md')
        for cmd in BUDGET_COMMANDS:
            write_stub(cb / 'commands' / 'budget' / f'{cmd}.md')
        for cmd in OPSX_COMMANDS:
            write_stub(cb / 'commands' / 'opsx' / f'{cmd}.md')
        for skill in SKILLS:
            write_stub(cb / 'skills' / skill / 'SKILL.md')
        for rule in RULES:
            write_stub(cb / 'rules' / f'budget-{rule}.mdc')
        write_stub(cb / 'hooks' / 'budget-notify-hook.py')
        shutil.copy2(CORE_MODELS, cb / 'budget-models.json')
        shutil.copy2(CORE_PERSONAS, cb / 'personas.json')
        return cb

    def run_setup(self, args, cwd=None, env_extra=None):
        cb = self.work / '.codebuddy'
        return run_bash(
            'bash "%s" %s' % (cb / 'setup.sh', args),
            cwd or self.work, self.home, env_extra)

    def run_validate(self, env_extra=None):
        return self.run_setup('validate', env_extra=env_extra)


class ValidateCodebuddyTests(ValidateSandbox):
    """codebuddy 项目级形态: 完整通过 / 各类缺失与坏数据报错。"""

    def test_full_install_passes(self):
        self.make_codebuddy_install()
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('全部检查通过', proc.stdout)
        self.assertIn('文件完整性', proc.stdout)
        self.assertIn('JSON 数据校验', proc.stdout)
        self.assertIn('hooks 注入状态', proc.stdout)
        # 47 项 = 43 文件（10 agents + 7 commands + 6 skills + 12 rules
        # + 1 hooks + 4 lib + 3 管理面）+ 4 JSON（models/personas 各 2）
        self.assertIn('47 项', proc.stdout)

    def test_missing_agent_reported(self):
        cb = self.make_codebuddy_install()
        (cb / 'agents' / 'architect.md').unlink()
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('agents/architect.md', proc.stdout)
        self.assertIn('缺失', proc.stdout)
        self.assertIn('失败清单', proc.stdout)

    def test_missing_command_reported(self):
        cb = self.make_codebuddy_install()
        (cb / 'commands' / 'budget' / 'goal.md').unlink()
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('commands/budget/goal.md', proc.stdout)

    def test_missing_skill_reported(self):
        cb = self.make_codebuddy_install()
        (cb / 'skills' / 'budget-workflow' / 'SKILL.md').unlink()
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('skills/budget-workflow/SKILL.md', proc.stdout)

    def test_missing_rule_reported(self):
        cb = self.make_codebuddy_install()
        (cb / 'rules' / 'budget-rtk.mdc').unlink()
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('rules/budget-rtk.mdc', proc.stdout)

    def test_missing_hooks_file_reported(self):
        cb = self.make_codebuddy_install()
        (cb / 'hooks' / 'budget-notify-hook.py').unlink()
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('hooks/budget-notify-hook.py', proc.stdout)

    def test_missing_models_file_reported(self):
        cb = self.make_codebuddy_install()
        (cb / 'budget-models.json').unlink()
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('budget-models.json', proc.stdout)

    def test_corrupted_models_json_reported(self):
        cb = self.make_codebuddy_install()
        (cb / 'budget-models.json').write_text('{broken json', encoding='utf-8')
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('解析失败', proc.stdout)
        self.assertIn('JSON 数据校验', proc.stdout)

    def test_models_roles_keyset_wrong(self):
        cb = self.make_codebuddy_install()
        data = json.loads((cb / 'budget-models.json').read_text(encoding='utf-8'))
        data['roles'].remove('tester')
        (cb / 'budget-models.json').write_text(
            json.dumps(data, ensure_ascii=False), encoding='utf-8')
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('roles 键集不符', proc.stdout)

    def test_corrupted_personas_json_reported(self):
        cb = self.make_codebuddy_install()
        (cb / 'personas.json').write_text('not json at all', encoding='utf-8')
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('personas.json', proc.stdout)
        self.assertIn('解析失败', proc.stdout)

    def test_personas_theme_missing_role_key(self):
        cb = self.make_codebuddy_install()
        data = json.loads((cb / 'personas.json').read_text(encoding='utf-8'))
        del data['themes']['sanguo']['roles']['tester']
        (cb / 'personas.json').write_text(
            json.dumps(data, ensure_ascii=False), encoding='utf-8')
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('11 键', proc.stdout)
        self.assertIn('sanguo', proc.stdout)

    def test_personas_missing_builtin_theme(self):
        cb = self.make_codebuddy_install()
        data = json.loads((cb / 'personas.json').read_text(encoding='utf-8'))
        del data['themes']['shuihu']
        (cb / 'personas.json').write_text(
            json.dumps(data, ensure_ascii=False), encoding='utf-8')
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('内置主题缺失', proc.stdout)
        self.assertIn('shuihu', proc.stdout)

    def test_check_alias_dispatches_validate(self):
        """setup.sh 分发表: check 别名与 validate 等价。"""
        self.make_codebuddy_install()
        proc = self.run_setup('check')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('全部检查通过', proc.stdout)

    def test_unknown_platform_fails(self):
        """未安装形态（三级探测未命中）→ exit 1 显式报错。"""
        # 安装形态就位（setup.sh 可执行），但 cwd 在无关目录 → 三级探测
        # （cwd 向上 .codebuddy/.opencode + HOME）均未命中 → 显式报错。
        self.make_codebuddy_install()
        proc = self.run_setup('validate', cwd=self.tmp)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未检测到', proc.stdout)

    def test_bash_n_validate_script(self):
        proc = subprocess.run(
            ['bash', '-n', str(VALIDATE_SCRIPT)],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class ValidateOpencodeTests(ValidateSandbox):
    """opencode 形态: 管理面 ~/.budgetbuddy/ + 结构 .opencode/（fragment 12 区块）。"""

    def make_opencode_install(self):
        """构造 opencode 项目级安装形态（管理面 + 结构目录）。"""
        # 管理面（design.md §10 A3: setup.sh/lib/models/personas → ~/.budgetbuddy/）
        bb = self.home / '.budgetbuddy'
        (bb / 'lib').mkdir(parents=True)
        shutil.copy2(CORE_SETUP, bb / 'setup.sh')
        self.copy_lib(bb / 'lib')
        shutil.copy2(CORE_MODELS, bb / 'budget-models.json')
        shutil.copy2(CORE_PERSONAS, bb / 'personas.json')
        # 结构目录（.opencode/agent|command|skill + AGENTS.fragment.md）
        oc = self.work / '.opencode'
        for agent in AGENTS:
            write_stub(oc / 'agent' / f'{agent}.md')
        for cmd in BUDGET_COMMANDS:
            write_stub(oc / 'command' / f'budget-{cmd}.md')
        for cmd in OPSX_COMMANDS:
            write_stub(oc / 'command' / f'opsx-{cmd}.md')
        for skill in SKILLS:
            write_stub(oc / 'skill' / skill / 'SKILL.md')
        parts = ['<!-- BudgetBuddy:begin -->', '']
        for rule in RULES:
            parts.append(f'<!-- budget-{rule}:begin -->')
            parts.append(f'# {rule}')
            parts.append(f'<!-- budget-{rule}:end -->')
            parts.append('')
        parts.append('<!-- BudgetBuddy:end -->')
        (oc / 'AGENTS.fragment.md').write_text('\n'.join(parts) + '\n', encoding='utf-8')
        return bb

    def run_validate(self):
        bb = self.home / '.budgetbuddy'
        return run_bash('bash "%s" validate' % (bb / 'setup.sh'), self.work, self.home)

    def test_full_install_passes(self):
        self.make_opencode_install()
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('全部检查通过', proc.stdout)
        self.assertIn('opencode:project', proc.stdout)
        # opencode 无 hooks 检查项（AGENTS.fragment.md 12 区块替代 12 个 .mdc）
        self.assertNotIn('hooks/budget-notify-hook.py', proc.stdout)

    def test_missing_fragment_block_reported(self):
        self.make_opencode_install()
        fragment = self.work / '.opencode' / 'AGENTS.fragment.md'
        text = fragment.read_text(encoding='utf-8')
        fragment.write_text(
            text.replace('<!-- budget-rtk:begin -->', '<!-- dropped -->'), encoding='utf-8')
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('区块 budget-rtk', proc.stdout)

    def test_missing_fragment_file_reported(self):
        self.make_opencode_install()
        (self.work / '.opencode' / 'AGENTS.fragment.md').unlink()
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('AGENTS.fragment.md', proc.stdout)

    def test_missing_agent_reported(self):
        self.make_opencode_install()
        (self.work / '.opencode' / 'agent' / 'tester.md').unlink()
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 1)
        self.assertIn('agents/tester.md', proc.stdout)


class EndToEndFlowTests(ValidateSandbox):
    """端到端链路: 安装形态 → persona set → validate → stats → run_summary。"""

    def seed_workflow_data(self):
        """构造状态机（start 模式）+ 委派日志 + Coder Guard 记录。"""
        change_dir = self.work / 'openspec' / 'changes' / 'demo-change'
        write_stub(change_dir / 'start-state.json', json.dumps({
            'agent_calls_used': 5,
            'change_id': 'demo-change',
            'completed_steps': ['2-architect', '4.1-coder-lite-task1'],
            'created_at': '2026-10-28T10:00:00Z',
            'current_step': 'pipeline-running',
            'max_agent_calls': 60,
            'updated_at': '2026-10-28T12:00:00Z',
        }, ensure_ascii=False, sort_keys=True))
        log_entries = [
            {'agent_type': 'architect', 'step': '2', 'task': '方案设计',
             'ts': '2026-10-28T10:05:00Z'},
            {'agent_type': 'coder-lite', 'step': '4.1', 'task': '实现',
             'ts': '2026-10-28T10:30:00Z'},
            {'agent_type': 'reviewer', 'step': '5', 'task': '审查',
             'ts': '2026-10-28T11:00:00Z'},
        ]
        write_stub(
            change_dir / 'agent_dispatch.log',
            '\n'.join(json.dumps(e, ensure_ascii=False, sort_keys=True)
                      for e in log_entries) + '\n')
        # Coder Guard（固定全局路径，project-name = cwd 目录名）
        guard_file = (self.home / '.budgetbuddy' / 'projects' / self.work.name
                      / 'memory' / 'coder-guard.json')
        write_stub(guard_file, json.dumps({
            'history': [
                {'coder': 'coder-lite', 'escalated_to': None, 'result': 'failure',
                 'tags': ['api_endpoint'], 'timestamp': '2026-10-28T10:20:00Z'},
                {'coder': 'coder-lite', 'escalated_to': 'coder-standard',
                 'result': 'failure', 'tags': ['api_endpoint'],
                 'timestamp': '2026-10-28T10:25:00Z'},
                {'coder': 'coder-standard', 'escalated_to': None, 'result': 'success',
                 'tags': ['api_endpoint'], 'timestamp': '2026-10-28T11:30:00Z'},
            ],
            'summary': {},
        }, ensure_ascii=False, sort_keys=True))

    def test_full_flow(self):
        cb = self.make_codebuddy_install()
        self.seed_workflow_data()

        # 1. persona set sanguo（specs「主题切换」Scenario）
        proc = self.run_setup('persona set sanguo')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        active = json.loads(
            (self.work / '.budget' / 'persona-active.json').read_text(encoding='utf-8'))
        self.assertEqual(active['theme'], 'sanguo')

        # 2. validate（安装完整性报告，exit 0）
        proc = self.run_validate()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('全部检查通过', proc.stdout)

        # 3. stats（表格输出：主题 + guard + 状态机）
        proc = self.run_setup('stats')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('工作流统计', proc.stdout)
        self.assertIn('sanguo', proc.stdout)
        self.assertIn('主公', proc.stdout)
        self.assertIn('Coder Guard', proc.stdout)
        self.assertIn('失败 2', proc.stdout)
        self.assertIn('demo-change', proc.stdout)
        self.assertIn('5/60', proc.stdout)

        # 4. stats --json（机器可读，键排序）
        proc = self.run_setup('stats --json')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(payload['project']['theme'], 'sanguo')
        self.assertEqual(payload['project']['agents'], 10)
        self.assertEqual(payload['guard']['failures'], 2)
        self.assertEqual(payload['guard']['escalations'], 1)
        self.assertEqual(payload['state']['active']['change_id'], 'demo-change')
        self.assertEqual(payload['state']['active']['agent_calls_used'], 5)

        # 5. run_summary（markdown 摘要，find 活跃 + guard 失败降级史）
        proc = run_bash(
            '"%s" "%s"' % (sys.executable, cb / 'lib' / 'run_summary.py'),
            self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('# 变更完成摘要: demo-change', proc.stdout)
        self.assertIn('模式: start', proc.stdout)
        self.assertIn('调用计数: 5 / 60', proc.stdout)
        self.assertIn('architect | 1', proc.stdout)
        self.assertIn('完成步骤（2）', proc.stdout)
        self.assertIn('2-architect', proc.stdout)
        self.assertIn('失败 2 / 降级 1', proc.stdout)
        self.assertIn('coder-lite → coder-standard', proc.stdout)
        self.assertIn('2026-10-28T10:00:00Z → 2026-10-28T12:00:00Z', proc.stdout)

    def test_run_summary_explicit_change_id(self):
        cb = self.make_codebuddy_install()
        self.seed_workflow_data()
        proc = run_bash(
            '"%s" "%s" demo-change' % (sys.executable, cb / 'lib' / 'run_summary.py'),
            self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('# 变更完成摘要: demo-change', proc.stdout)

    def test_run_summary_missing_change_errors(self):
        cb = self.make_codebuddy_install()
        proc = run_bash(
            '"%s" "%s" nosuch-change' % (sys.executable, cb / 'lib' / 'run_summary.py'),
            self.work, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未找到状态文件', proc.stderr)

    def test_run_summary_no_active_state_errors(self):
        cb = self.make_codebuddy_install()
        proc = run_bash(
            '"%s" "%s"' % (sys.executable, cb / 'lib' / 'run_summary.py'),
            self.work, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未找到活跃的状态文件', proc.stderr)

    def test_run_summary_goal_state_preferred(self):
        """goal in_progress 优先于 start（find 语义）。"""
        cb = self.make_codebuddy_install()
        self.seed_workflow_data()
        goal_dir = self.work / 'openspec' / 'changes' / 'goal-pending'
        write_stub(goal_dir / 'goal-state.json', json.dumps({
            'agent_calls_used': 3,
            'completed_steps': [],
            'created_at': '2026-10-28T09:00:00Z',
            'current_step': '0.1-clarification',
            'max_agent_calls': 80,
            'status': 'in_progress',
            'updated_at': '2026-10-28T09:30:00Z',
        }, ensure_ascii=False, sort_keys=True))
        proc = run_bash(
            '"%s" "%s"' % (sys.executable, cb / 'lib' / 'run_summary.py'),
            self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('模式: goal', proc.stdout)
        self.assertIn('状态: in_progress', proc.stdout)
        self.assertIn('goal-pending', proc.stdout)


if __name__ == '__main__':
    unittest.main()
