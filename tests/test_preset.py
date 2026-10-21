#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preset.sh / models.sh / model_resolver.py 单测（design.md §3.2/§7/§8.1/§8.3）。

临时目录构造三平台安装形态（codebuddy 项目级/全局、opencode 项目级/全局、
claudecode 项目级），验证 preset/custom/inherit 三命令的 frontmatter 重写、
角色名映射（连字符→下划线全 10 角色锁定，防未来新角色名静默失配）、
provider_map 转换与未知角色报错；claudecode 形态下 camelCase 键结构
（permissionMode/maxTurns）无损（specs/model-presets「claudecode preset
切换」）；另覆盖 budget setup models 完整表格与 do_diff 查询函数契约。
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
RESOLVER = CORE_LIB / 'model_resolver.py'

with open(CORE_MODELS, encoding='utf-8') as _handle:
    MODELS_DATA = json.load(_handle)

# 全 10 角色锁定清单（辅审 P3-1：json roles 键集与本清单漂移时，锁定用例
# 必须失败而非静默通过——防未来新角色名在文件名↔model_role 映射中失配）。
LOCKED_AGENTS = (
    'architect', 'coder-lite', 'coder-standard', 'coder-senior', 'reviewer',
    'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
)
LOCKED_ROLES = tuple(name.replace('-', '_') for name in LOCKED_AGENTS)

# 安装形态所需 lib 文件（基础层 4 + 本任务 3）。
LIB_FILES = (
    'colors.sh', 'utils.sh', 'platform.sh', 'shell.sh',
    'models.sh', 'preset.sh', 'model_resolver.py',
)

# 双平台 agent 产物 frontmatter 模板（结构对齐 dist 构建产物）。
CODEBUDDY_AGENT_TMPL = '''---
name: {name}
description: MUST BE USED — {name} 测试 agent。
model: {model}
tools: [Read, Write, Edit, Bash, Grep, Glob]
permissionMode: acceptEdits
max_turns: 35
---

{name} 的正文内容（重写不得触碰）。
'''

OPENCODE_AGENT_TMPL = '''---
description: MUST BE USED — {name} 测试 agent。
mode: subagent
model: {model}
permission:
  edit:
    "*": "allow"
  bash:
    "*": "allow"
max_turns: 35
---

{name} 的正文内容（重写不得触碰）。
'''

# claudecode agent 产物 frontmatter 模板（camelCase 键结构，对齐 dist/claudecode）。
CLAUDECODE_AGENT_TMPL = '''---
name: {name}
description: MUST BE USED — {name} 测试 agent。
model: {model}
tools: [Read, Write, Edit, Bash, Grep, Glob]
permissionMode: acceptEdits
maxTurns: 35
---

{name} 的正文内容（重写不得触碰）。
'''


def run_bash(script, cwd, home, env_extra=None):
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
    )


def run_resolver(args, cwd=None):
    """直接调用 model_resolver.py（python 单测路径）。"""
    return subprocess.run(
        [sys.executable, str(RESOLVER), '--models', str(CORE_MODELS)] + args,
        cwd=str(cwd or REPO_ROOT), capture_output=True, text=True, timeout=60,
    )


def expected_preset(platform, preset_name):
    """从 budget-models.json 取预设期望值：{agent 文件名: model}。"""
    preset = MODELS_DATA['platforms'][platform]['presets'][preset_name]
    return {role.replace('_', '-'): model for role, model in preset.items()}


def read_model_field(path):
    """读取 agent 文件 frontmatter 顶层 model 值；无 frontmatter/字段时 None。"""
    lines = path.read_text(encoding='utf-8').split('\n')
    if not lines or lines[0].strip() != '---':
        return None
    for line in lines[1:]:
        if line.strip() == '---':
            break
        if line.startswith('model:'):
            return line.split(':', 1)[1].strip()
    return None


def read_agent(path):
    """读取 agent 文件 frontmatter 顶层键值映射（跳过嵌套缩进行）。

    用于 camelCase 键结构断言（permissionMode/maxTurns 等无损校验）；
    无 frontmatter 时返回空映射。
    """
    lines = path.read_text(encoding='utf-8').split('\n')
    if not lines or lines[0].strip() != '---':
        return {}
    fields = {}
    for line in lines[1:]:
        if line.strip() == '---':
            break
        if line.startswith(' ') or ':' not in line:
            continue
        key, _, value = line.partition(':')
        fields[key.strip()] = value.strip()
    return fields


def _copy_management_plane(root):
    """管理面落位：setup.sh + lib（基础层 + models/preset/resolver）+ models json。"""
    (root / 'lib').mkdir(parents=True)
    shutil.copy2(CORE_SETUP, root / 'setup.sh')
    for name in LIB_FILES:
        shutil.copy2(CORE_LIB / name, root / 'lib' / name)
    shutil.copy2(CORE_MODELS, root / 'budget-models.json')


def make_codebuddy_install(base, models=None):
    """构造 .codebuddy 项目级安装形态（管理面 + agents 同根）。"""
    cb = base / '.codebuddy'
    _copy_management_plane(cb)
    agents = cb / 'agents'
    agents.mkdir()
    for name in LOCKED_AGENTS:
        model = (models or {}).get(name, 'glm-5.2')
        (agents / (name + '.md')).write_text(
            CODEBUDDY_AGENT_TMPL.format(name=name, model=model), encoding='utf-8')
    return cb


def make_opencode_install(base, home, models=None):
    """构造 opencode 项目级安装形态（管理面 ~/.budgetbuddy/ + 项目 .opencode/agent/）。"""
    _copy_management_plane(home / '.budgetbuddy')
    agents = base / '.opencode' / 'agent'
    agents.mkdir(parents=True)
    for name in LOCKED_AGENTS:
        model = (models or {}).get(name, 'zhipu/glm-5.2')
        (agents / (name + '.md')).write_text(
            OPENCODE_AGENT_TMPL.format(name=name, model=model), encoding='utf-8')
    return agents


def make_claudecode_install(base, home, models=None):
    """构造 claudecode 项目级安装形态（管理面 ~/.budgetbuddy/ + 项目 .claude/agents/）。"""
    _copy_management_plane(home / '.budgetbuddy')
    agents = base / '.claude' / 'agents'
    agents.mkdir(parents=True)
    for name in LOCKED_AGENTS:
        model = (models or {}).get(name, 'claude-sonnet-4.6')
        (agents / (name + '.md')).write_text(
            CLAUDECODE_AGENT_TMPL.format(name=name, model=model), encoding='utf-8')
    return agents


class SandboxTestCase(unittest.TestCase):
    """公共沙箱：每个用例独立临时目录（项目区 + 隔离 HOME）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-preset-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()


class RoleMappingLockTests(unittest.TestCase):
    """角色名映射锁定（辅审 P3-1）：json roles 键集与 10 角色清单一致。"""

    def test_models_json_roles_locked(self):
        self.assertEqual(sorted(MODELS_DATA.get('roles', [])), sorted(LOCKED_ROLES))

    def test_every_preset_covers_all_ten_roles(self):
        """双平台三档预设每档覆盖全部 10 角色键（specs/model-presets 双平台预设齐全）。"""
        for platform in ('codebuddy', 'opencode'):
            presets = MODELS_DATA['platforms'][platform]['presets']
            for name, preset in presets.items():
                self.assertEqual(
                    sorted(preset), sorted(LOCKED_ROLES),
                    '%s/%s 预设角色键集失配' % (platform, name))


class ResolverResolveTests(unittest.TestCase):
    """resolve 子命令：别名/裸 ID/provider-model 解析与 provider_map 转换。"""

    def test_codebuddy_alias(self):
        proc = run_resolver(['resolve', '--input', 'kimi', '--platform', 'codebuddy'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'kimi-k2.7')

    def test_codebuddy_bare_id(self):
        proc = run_resolver(['resolve', '--input', 'glm-5.2', '--platform', 'codebuddy'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'glm-5.2')

    def test_codebuddy_alias_case_insensitive(self):
        proc = run_resolver(['resolve', '--input', 'Kimi', '--platform', 'codebuddy'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'kimi-k2.7')

    def test_codebuddy_provider_model_input_stripped(self):
        proc = run_resolver(['resolve', '--input', 'zhipu/glm-5.2', '--platform', 'codebuddy'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'glm-5.2')

    def test_opencode_alias_via_provider_map(self):
        proc = run_resolver(['resolve', '--input', 'kimi', '--platform', 'opencode'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'moonshotai/kimi-k2.7')

    def test_opencode_bare_id_via_provider_map(self):
        proc = run_resolver(['resolve', '--input', 'glm-5.2', '--platform', 'opencode'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'zhipu/glm-5.2')

    def test_opencode_provider_model_passthrough(self):
        proc = run_resolver(['resolve', '--input', 'zhipu/glm-5.2', '--platform', 'opencode'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), 'zhipu/glm-5.2')

    def test_opencode_provider_map_pairs_locked(self):
        """provider_map 转换锁定：多组厂商（claude→anthropic / gemini→google / deepseek）。"""
        for raw, expected in (
                ('haiku', 'anthropic/claude-haiku-4.5'),
                ('gemini-flash', 'google/gemini-3.5-flash'),
                ('deepseek', 'deepseek/deepseek-v3.2')):
            proc = run_resolver(['resolve', '--input', raw, '--platform', 'opencode'])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), expected, '输入 %s' % raw)

    def test_unknown_name_errors_with_alias_list(self):
        proc = run_resolver(['resolve', '--input', 'no-such-model', '--platform', 'codebuddy'])
        self.assertEqual(proc.returncode, 2)
        self.assertIn('未知模型名: no-such-model', proc.stderr)
        self.assertIn('可用别名', proc.stderr)
        self.assertIn('kimi', proc.stderr)


class ResolverPresetTests(unittest.TestCase):
    """preset / list-presets 子命令：预设查询与角色键集锁定。"""

    def test_preset_lines_codebuddy_economic(self):
        proc = run_resolver(['preset', '--name', 'economic', '--platform', 'codebuddy'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = dict(line.split('=', 1) for line in proc.stdout.strip().splitlines())
        self.assertEqual(lines, expected_preset('codebuddy', 'economic'))

    def test_preset_lines_opencode_balanced(self):
        proc = run_resolver(['preset', '--name', 'balanced', '--platform', 'opencode'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = dict(line.split('=', 1) for line in proc.stdout.strip().splitlines())
        self.assertEqual(lines, expected_preset('opencode', 'balanced'))

    def test_preset_keys_lock_all_ten_agent_filenames(self):
        """角色名映射锁定：preset 输出键集恰为全 10 agent 文件名（连字符形态）。"""
        for platform in ('codebuddy', 'opencode'):
            proc = run_resolver(['preset', '--name', 'balanced', '--platform', platform])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            keys = sorted(line.split('=', 1)[0] for line in proc.stdout.strip().splitlines())
            self.assertEqual(keys, sorted(LOCKED_AGENTS), '平台 %s 键集漂移' % platform)

    def test_unknown_preset_errors(self):
        proc = run_resolver(['preset', '--name', 'ultra', '--platform', 'codebuddy'])
        self.assertEqual(proc.returncode, 1)
        self.assertIn('预设 "ultra" 不存在', proc.stderr)
        self.assertIn('economic', proc.stderr)

    def test_list_presets_outputs_three_tiers(self):
        proc = run_resolver(['list-presets', '--platform', 'codebuddy'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for tier in ('economic', 'balanced', 'quality'):
            self.assertIn(tier, proc.stdout)
        self.assertIn('coder-lite → hy3', proc.stdout)


class RewriteUnitTests(SandboxTestCase):
    """rewrite 子命令单元级：frontmatter 重写的字段保留/插入/删除/幂等。"""

    def _make_agent(self, content):
        path = self.tmp / 'coder-lite.md'
        path.write_text(content, encoding='utf-8')
        return path

    def _rewrite(self, agents_dir, action, platform='codebuddy', preset='', model=''):
        return run_resolver([
            'rewrite', '--agents-dir', str(agents_dir), '--platform', platform,
            '--mode', action, '--preset', preset, '--model', model,
        ], cwd=str(self.tmp))

    def test_replace_preserves_other_fields_and_body(self):
        content = (
            '---\n'
            'name: coder-lite\n'
            'description: 测试 agent。\n'
            'model: glm-5.2\n'
            'tools: [Read, Write]\n'
            'permissionMode: acceptEdits\n'
            'max_turns: 35\n'
            '---\n'
            '\n'
            '正文第一行。\n'
            '正文第二行。\n'
        )
        path = self._make_agent(content)
        proc = self._rewrite(self.tmp, 'custom', model='kimi-k2.7')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = path.read_text(encoding='utf-8')
        self.assertIn('model: kimi-k2.7', text)
        self.assertNotIn('model: glm-5.2', text)
        for preserved in ('name: coder-lite', 'description: 测试 agent。',
                          'tools: [Read, Write]', 'permissionMode: acceptEdits',
                          'max_turns: 35', '正文第一行。', '正文第二行。'):
            self.assertIn(preserved, text)

    def test_insert_when_model_absent(self):
        content = (
            '---\n'
            'name: coder-lite\n'
            'description: 测试 agent。\n'
            'tools: [Read]\n'
            '---\n'
            '正文。\n'
        )
        path = self._make_agent(content)
        proc = self._rewrite(self.tmp, 'custom', model='hy3')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = path.read_text(encoding='utf-8').split('\n')
        # 插入锚点：description 行之后
        self.assertEqual(lines[3], 'model: hy3')
        self.assertIn('tools: [Read]', lines)

    def test_inherit_removes_model_line(self):
        content = (
            '---\n'
            'name: coder-lite\n'
            'description: 测试。\n'
            'model: glm-5.2\n'
            'tools: [Read]\n'
            '---\n'
            '正文。\n'
        )
        path = self._make_agent(content)
        proc = self._rewrite(self.tmp, 'inherit')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = path.read_text(encoding='utf-8')
        self.assertNotIn('model:', text)
        for preserved in ('name: coder-lite', 'description: 测试。',
                          'tools: [Read]', '正文。'):
            self.assertIn(preserved, text)

    def test_inherit_idempotent_when_no_model(self):
        content = '---\nname: coder-lite\ndescription: 测试。\n---\n正文。\n'
        path = self._make_agent(content)
        proc = self._rewrite(self.tmp, 'inherit')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(path.read_text(encoding='utf-8'), content)

    def test_rewrite_idempotent_bytes(self):
        content = '---\nname: coder-lite\ndescription: 测试。\nmodel: glm-5.2\n---\n正文。\n'
        path = self._make_agent(content)
        self._rewrite(self.tmp, 'custom', model='hy3')
        first = path.read_text(encoding='utf-8')
        self._rewrite(self.tmp, 'custom', model='hy3')
        second = path.read_text(encoding='utf-8')
        self.assertEqual(first, second)

    def test_nested_yaml_preserved(self):
        content = (
            '---\n'
            'description: 测试。\n'
            'mode: subagent\n'
            'model: zhipu/glm-5.2\n'
            'permission:\n'
            '  edit:\n'
            '    "*": "deny"\n'
            '    "docs/**": "allow"\n'
            '  bash:\n'
            '    "*": "ask"\n'
            'max_turns: 35\n'
            '---\n'
            '正文。\n'
        )
        path = self._make_agent(content)
        proc = self._rewrite(self.tmp, 'custom', platform='opencode',
                             model='moonshotai/kimi-k2.7')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = path.read_text(encoding='utf-8')
        self.assertIn('model: moonshotai/kimi-k2.7', text)
        self.assertNotIn('model: zhipu/glm-5.2', text)
        for preserved in ('mode: subagent', '    "*": "deny"', '    "docs/**": "allow"',
                          '    "*": "ask"', 'max_turns: 35', '正文。'):
            self.assertIn(preserved, text)

    def test_no_frontmatter_skipped(self):
        path = self._make_agent('正文而已，没有 frontmatter。\n')
        before = path.read_text(encoding='utf-8')
        proc = self._rewrite(self.tmp, 'custom', model='hy3')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('无 frontmatter', proc.stderr)
        self.assertEqual(path.read_text(encoding='utf-8'), before)

    def test_unknown_role_agent_skipped_with_error(self):
        """未知角色报错跳过：非套件 agent 不触碰，已知 agent 正常重写。"""
        (self.tmp / 'mystery-agent.md').write_text(
            '---\nname: mystery-agent\ndescription: 未知。\nmodel: glm-5.2\n---\n正文。\n',
            encoding='utf-8')
        (self.tmp / 'coder-lite.md').write_text(
            '---\nname: coder-lite\ndescription: 测试。\nmodel: glm-5.2\n---\n正文。\n',
            encoding='utf-8')
        proc = self._rewrite(self.tmp, 'custom', model='hy3')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('跳过未知角色 agent: mystery-agent', proc.stderr)
        self.assertIn('model: hy3', (self.tmp / 'coder-lite.md').read_text(encoding='utf-8'))
        self.assertIn('model: glm-5.2',
                      (self.tmp / 'mystery-agent.md').read_text(encoding='utf-8'))

    def test_all_unknown_agents_fail(self):
        (self.tmp / 'other.md').write_text('---\n---\n正文。\n', encoding='utf-8')
        proc = self._rewrite(self.tmp, 'custom', model='hy3')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('roles 映射零命中', proc.stderr)

    def test_preset_action_unknown_preset_fails(self):
        (self.tmp / 'coder-lite.md').write_text(
            '---\nname: coder-lite\ndescription: 测试。\n---\n正文。\n', encoding='utf-8')
        proc = self._rewrite(self.tmp, 'preset', preset='ultra')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('预设 "ultra" 不存在', proc.stderr)

    def test_missing_agents_dir_fails(self):
        proc = self._rewrite(self.tmp / 'nope', 'custom', model='hy3')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('agent 目录不存在', proc.stderr)

    def test_current_subcommand_outputs_lines(self):
        (self.tmp / 'coder-lite.md').write_text(
            '---\nname: coder-lite\ndescription: 测试。\nmodel: glm-5.2\n---\n正文。\n',
            encoding='utf-8')
        (self.tmp / 'not-suite.md').write_text(
            '---\nname: not-suite\ndescription: 其他。\nmodel: x\n---\n正文。\n',
            encoding='utf-8')
        proc = run_resolver(['current', '--agents-dir', str(self.tmp)], cwd=str(self.tmp))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip().splitlines(), ['coder-lite=glm-5.2'])


class AgentCommandCodebuddyTests(SandboxTestCase):
    """codebuddy 项目级端到端：agent preset/custom/inherit 三命令重写验证。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp)
        self.agents = self.cb / 'agents'

    def _run(self, args, cwd=None):
        script = 'bash "%s" agent %s' % (self.cb / 'setup.sh', args)
        return run_bash(script, cwd or self.work, self.home)

    def test_preset_economic_rewrites_all_ten_agents(self):
        """preset 切换：10 agent 逐文件 model 值 = economic 档映射（角色名映射全量锁定）。"""
        proc = self._run('preset economic')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = expected_preset('codebuddy', 'economic')
        for agent in LOCKED_AGENTS:
            self.assertEqual(
                read_model_field(self.agents / (agent + '.md')), expected[agent],
                'agent %s 的 model 值失配' % agent)

    def test_preset_balanced_rewrites_all_ten_agents(self):
        proc = self._run('preset balanced')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = expected_preset('codebuddy', 'balanced')
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')), expected[agent])

    def test_preset_quality_rewrites_all_ten_agents(self):
        proc = self._run('preset quality')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = expected_preset('codebuddy', 'quality')
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')), expected[agent])

    def test_preset_idempotent(self):
        self._run('preset economic')
        first = {name: (self.agents / (name + '.md')).read_text(encoding='utf-8')
                 for name in LOCKED_AGENTS}
        proc = self._run('preset economic')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        second = {name: (self.agents / (name + '.md')).read_text(encoding='utf-8')
                  for name in LOCKED_AGENTS}
        self.assertEqual(first, second)

    def test_preset_preserves_other_frontmatter_and_body(self):
        proc = self._run('preset economic')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = (self.agents / 'coder-lite.md').read_text(encoding='utf-8')
        for preserved in ('name: coder-lite', 'tools: [Read, Write, Edit, Bash, Grep, Glob]',
                          'permissionMode: acceptEdits', 'max_turns: 35',
                          'coder-lite 的正文内容（重写不得触碰）。'):
            self.assertIn(preserved, text)

    def test_custom_alias_rewrites_all(self):
        proc = self._run('custom kimi')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('别名解析: kimi → kimi-k2.7', proc.stdout)
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')), 'kimi-k2.7')

    def test_custom_bare_id_rewrites_all(self):
        proc = self._run('custom glm-5.2')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')), 'glm-5.2')

    def test_custom_third_party_model_accepted(self):
        """custom 接受第三方模型 ID（方舟/Presence 等），原样写入 frontmatter。"""
        proc = self._run('custom presence-glm/glm-5.3')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        combined = proc.stdout + proc.stderr
        self.assertNotIn('未知模型名', combined)
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')),
                             'presence-glm/glm-5.3',
                             'agent %s 未覆写为第三方模型' % agent)

    def test_custom_alias_still_resolved(self):
        """custom 仍正常解析已知别名（如 kimi → kimi-k2.7）。"""
        proc = self._run('custom kimi')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        combined = proc.stdout + proc.stderr
        self.assertNotIn('未知模型名', combined)
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')),
                             'kimi-k2.7', 'agent %s 别名未解析' % agent)

    def test_custom_missing_argument_errors(self):
        proc = self._run('custom')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('请指定模型', proc.stdout)

    def test_inherit_removes_model_field(self):
        proc = self._run('inherit')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for agent in LOCKED_AGENTS:
            self.assertIsNone(read_model_field(self.agents / (agent + '.md')),
                              'agent %s 仍残留 model 字段' % agent)

    def test_inherit_then_preset_reinserts_model(self):
        self._run('inherit')
        proc = self._run('preset balanced')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = expected_preset('codebuddy', 'balanced')
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')), expected[agent])

    def test_unknown_preset_name_errors(self):
        proc = self._run('preset ultra')
        self.assertEqual(proc.returncode, 1)
        combined = proc.stdout + proc.stderr
        self.assertIn('预设 "ultra" 不存在', combined)

    def test_preset_without_argument_lists_tiers(self):
        proc = self._run('preset')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for tier in ('economic', 'balanced', 'quality'):
            self.assertIn(tier, proc.stdout)

    def test_unknown_mode_errors(self):
        proc = self._run('bogus')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未知模式: bogus', proc.stdout)

    def test_unknown_agent_reported_and_known_rewritten(self):
        (self.agents / 'mystery-agent.md').write_text(
            '---\nname: mystery-agent\ndescription: 未知。\nmodel: glm-5.2\n---\n正文。\n',
            encoding='utf-8')
        proc = self._run('preset economic')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('跳过未知角色 agent: mystery-agent', proc.stderr)
        expected = expected_preset('codebuddy', 'economic')
        self.assertEqual(read_model_field(self.agents / 'coder-lite.md'),
                         expected['coder-lite'])
        self.assertIn('model: glm-5.2',
                      (self.agents / 'mystery-agent.md').read_text(encoding='utf-8'))


class AgentCommandCodebuddyGlobalTests(SandboxTestCase):
    """codebuddy 全局形态（~/.codebuddy/）：探测分支②下的重写。"""

    def test_global_form_rewrites_agents(self):
        cb = self.home / '.codebuddy'
        _copy_management_plane(cb)
        agents = cb / 'agents'
        agents.mkdir()
        for name in LOCKED_AGENTS:
            (agents / (name + '.md')).write_text(
                CODEBUDDY_AGENT_TMPL.format(name=name, model='glm-5.2'), encoding='utf-8')
        proc = run_bash('bash "%s" agent preset economic' % (cb / 'setup.sh'),
                        self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = expected_preset('codebuddy', 'economic')
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(agents / (agent + '.md')), expected[agent])


class AgentCommandOpencodeTests(SandboxTestCase):
    """opencode 项目级端到端：provider/model 形态重写验证。"""

    def setUp(self):
        super().setUp()
        self.agents = make_opencode_install(self.tmp, self.home)
        self.setup_sh = self.home / '.budgetbuddy' / 'setup.sh'

    def _run(self, args, cwd=None):
        script = 'bash "%s" agent %s' % (self.setup_sh, args)
        return run_bash(script, cwd or self.tmp, self.home)

    def test_preset_economic_provider_model_values(self):
        proc = self._run('preset economic')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = expected_preset('opencode', 'economic')
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')), expected[agent])

    def test_custom_alias_converted_to_provider_model(self):
        proc = self._run('custom kimi')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('别名解析: kimi → moonshotai/kimi-k2.7', proc.stdout)
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')),
                             'moonshotai/kimi-k2.7')

    def test_custom_provider_model_form_used_as_is(self):
        proc = self._run('custom zhipu/glm-5.2')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')), 'zhipu/glm-5.2')

    def test_inherit_removes_model_field(self):
        proc = self._run('inherit')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for agent in LOCKED_AGENTS:
            self.assertIsNone(read_model_field(self.agents / (agent + '.md')),
                              'agent %s 仍残留 model 字段' % agent)

    def test_preset_preserves_nested_permission_map(self):
        proc = self._run('preset balanced')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = (self.agents / 'coder-lite.md').read_text(encoding='utf-8')
        for preserved in ('mode: subagent', 'permission:', '"*": "allow"',
                          'max_turns: 35', 'coder-lite 的正文内容（重写不得触碰）。'):
            self.assertIn(preserved, text)

    def test_preset_idempotent(self):
        self._run('preset economic')
        first = {name: (self.agents / (name + '.md')).read_text(encoding='utf-8')
                 for name in LOCKED_AGENTS}
        self._run('preset economic')
        second = {name: (self.agents / (name + '.md')).read_text(encoding='utf-8')
                  for name in LOCKED_AGENTS}
        self.assertEqual(first, second)


class AgentCommandOpencodeGlobalEnvTests(SandboxTestCase):
    """opencode 全局形态（BUDGET_PLATFORM 显式指定）：探测覆盖分支下的重写。"""

    def test_env_override_global_form(self):
        agents = self.home / '.config' / 'opencode' / 'agent'
        agents.mkdir(parents=True)
        for name in LOCKED_AGENTS:
            (agents / (name + '.md')).write_text(
                OPENCODE_AGENT_TMPL.format(name=name, model='zhipu/glm-5.2'),
                encoding='utf-8')
        _copy_management_plane(self.home / '.budgetbuddy')
        proc = run_bash(
            'bash "%s" agent preset economic' % (self.home / '.budgetbuddy' / 'setup.sh'),
            self.work, self.home, env_extra={'BUDGET_PLATFORM': 'opencode'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = expected_preset('opencode', 'economic')
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(agents / (agent + '.md')), expected[agent])


class AgentCommandClaudecodeTests(SandboxTestCase):
    """claudecode 项目级端到端：camelCase 键结构下的 preset 重写验证。

    specs/model-presets Scenario「claudecode preset 切换」：.claude/agents/
    全部产物 model 重写为 quality 预设 ID，其余 camelCase 键（permissionMode/
    maxTurns）与正文不受影响（diff 仅 model 行）。
    """

    def setUp(self):
        super().setUp()
        self.agents = make_claudecode_install(self.tmp, self.home)
        self.setup_sh = self.home / '.budgetbuddy' / 'setup.sh'

    def _run(self, args, cwd=None):
        script = 'bash "%s" agent %s' % (self.setup_sh, args)
        return run_bash(script, cwd or self.tmp, self.home)

    def test_preset_quality_rewrites_only_model_line(self):
        """quality 重写后逐文件 diff 仅 model 行变化，camelCase 键无损。"""
        before = {name: (self.agents / (name + '.md')).read_text(encoding='utf-8')
                  for name in LOCKED_AGENTS}
        proc = self._run('preset quality')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = expected_preset('claudecode', 'quality')
        for agent in LOCKED_AGENTS:
            path = self.agents / (agent + '.md')
            after = path.read_text(encoding='utf-8')
            before_lines = before[agent].split('\n')
            after_lines = after.split('\n')
            self.assertEqual(len(before_lines), len(after_lines), agent)
            diff = [i for i, (old, new) in enumerate(zip(before_lines, after_lines))
                    if old != new]
            self.assertEqual(len(diff), 1, 'agent %s 变化行数 %s' % (agent, diff))
            self.assertTrue(before_lines[diff[0]].startswith('model:'), agent)
            self.assertEqual(after_lines[diff[0]], 'model: %s' % expected[agent], agent)
            # camelCase 键与正文无损（read_agent 提取断言）。
            fields = read_agent(path)
            self.assertEqual(fields['name'], agent)
            self.assertEqual(fields['permissionMode'], 'acceptEdits')
            self.assertEqual(fields['maxTurns'], '35')
            self.assertEqual(fields['tools'], '[Read, Write, Edit, Bash, Grep, Glob]')
            self.assertIn('%s 的正文内容（重写不得触碰）。' % agent, after)
            self.assertNotIn('model_role', after)
            self.assertNotIn('permissions', after)

    def test_preset_economic_rewrites_all_ten_agents(self):
        """economic 档：10 agent model 值 = claudecode economic 预设映射。"""
        proc = self._run('preset economic')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = expected_preset('claudecode', 'economic')
        for agent in LOCKED_AGENTS:
            self.assertEqual(read_model_field(self.agents / (agent + '.md')), expected[agent])

    def test_preset_idempotent(self):
        self._run('preset quality')
        first = {name: (self.agents / (name + '.md')).read_text(encoding='utf-8')
                 for name in LOCKED_AGENTS}
        proc = self._run('preset quality')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        second = {name: (self.agents / (name + '.md')).read_text(encoding='utf-8')
                  for name in LOCKED_AGENTS}
        self.assertEqual(first, second)

    def test_inherit_removes_model_field(self):
        proc = self._run('inherit')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for agent in LOCKED_AGENTS:
            self.assertIsNone(read_model_field(self.agents / (agent + '.md')),
                              'agent %s 仍残留 model 字段' % agent)


class AgentCommandCodexTests(SandboxTestCase):
    """codex 形态降级（add-codex-platform D5/D7，任务 4.1）。

    agent 素材文档无 model 烘焙：preset/custom/inherit 均不修改任何文件，
    仅打印提示并 exit 0；show 渲染三档映射表；未知模式仍报错。
    """

    CODEX_AGENT_TMPL = '''---
name: {name}
description: MUST BE USED — {name} 测试素材。
---

{name} 的正文内容（无 model 字段，降级不得新增）。
'''

    def setUp(self):
        super().setUp()
        _copy_management_plane(self.home / '.budgetbuddy')
        self.agents = self.work / '.codex' / 'skills' / 'budget-workflow' / 'agents'
        self.agents.mkdir(parents=True)
        for name in LOCKED_AGENTS:
            (self.agents / (name + '.md')).write_text(
                self.CODEX_AGENT_TMPL.format(name=name), encoding='utf-8')
        (self.agents.parent / 'SKILL.md').write_text(
            '---\nname: budget-workflow\ndescription: 测试。\n---\n正文\n',
            encoding='utf-8')
        self.setup_sh = self.home / '.budgetbuddy' / 'setup.sh'

    def _run(self, args):
        script = 'bash "%s" agent %s' % (self.setup_sh, args)
        return run_bash(script, self.work, self.home)

    def _snapshot(self):
        return {path.name: path.read_bytes() for path in sorted(self.agents.glob('*.md'))}

    def test_preset_downgraded_no_file_change(self):
        """preset：exit 0 + 降级提示，agent 素材逐字节不变。"""
        before = self._snapshot()
        proc = self._run('preset economic')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('codex 平台模型档位由 Leader spawn 时按 budget-models.json 查询',
                      proc.stdout)
        self.assertIn('budget setup show', proc.stdout)
        self.assertEqual(self._snapshot(), before)

    def test_custom_downgraded_no_file_change(self):
        """custom：exit 0 + 降级提示，不解析模型、不写文件。"""
        before = self._snapshot()
        proc = self._run('custom glm-5.2')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('codex 平台模型档位由 Leader spawn 时按 budget-models.json 查询',
                      proc.stdout)
        self.assertEqual(self._snapshot(), before)

    def test_inherit_downgraded_no_file_change(self):
        """inherit：exit 0 + 降级提示，无文件修改。"""
        before = self._snapshot()
        proc = self._run('inherit')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('codex 平台模型档位由 Leader spawn 时按 budget-models.json 查询',
                      proc.stdout)
        self.assertEqual(self._snapshot(), before)

    def test_no_mode_prints_platform_info(self):
        """无模式：打印 codex 形态与素材目录定位。"""
        proc = self._run('')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('当前平台: codex:project', proc.stdout)
        self.assertIn('无 agent frontmatter 模型烘焙', proc.stdout)

    def test_unknown_mode_still_errors(self):
        """未知模式不降级：报错 rc 1（非档位类命令）。"""
        proc = self._run('bogus')
        self.assertEqual(proc.returncode, 1)
        combined = proc.stdout + proc.stderr
        self.assertIn('未知模式: bogus', combined)

    def test_show_renders_three_tier_table(self):
        """show：codex 形态渲染三档映射表（数据源 platforms.codex.presets）+
        spawn 查表指引与逃生门说明。"""
        proc = run_bash('bash "%s" show' % self.setup_sh, self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('Codex 模型档位映射', proc.stdout)
        presets = MODELS_DATA['platforms']['codex']['presets']
        for tier in ('economic', 'balanced', 'quality'):
            self.assertIn(tier, proc.stdout, tier)
            model = next(iter(presets[tier].values()))
            self.assertIn(model, proc.stdout, tier)
        self.assertIn('spawn_agent', proc.stdout)
        self.assertIn('逃生门', proc.stdout)

    def test_show_missing_models_file_degrades(self):
        """show：budget-models.json 缺失 → 警告行降级不崩溃（rc 0）。"""
        models = self.home / '.budgetbuddy' / 'budget-models.json'
        models.unlink()
        proc = run_bash('bash "%s" show' % self.setup_sh, self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未找到 budget-models.json', proc.stdout)


class DiffQueryFunctionsTests(SandboxTestCase):
    """do_diff 查询函数契约（budget_get_current_models / budget_preset_table）。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp)
        self.lib = self.cb / 'lib'

    def _call(self, func, args=''):
        script = (
            'export BUDGET_PYTHON=python3; '
            'export BUDGET_LIB_DIR="%s"; '
            'export BUDGET_MODELS_FILE="%s"; '
            'source "%s"; source "%s"; source "%s"; %s %s'
            % (self.lib, self.cb / 'budget-models.json', self.lib / 'colors.sh',
               self.lib / 'platform.sh', self.lib / 'preset.sh', func, args)
        )
        return run_bash(script, self.work, self.home)

    def test_get_current_models_outputs_agent_model_lines(self):
        proc = self._call('budget_get_current_models')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = dict(line.split('=', 1) for line in proc.stdout.strip().splitlines())
        self.assertEqual(sorted(lines), sorted(LOCKED_AGENTS))
        for agent in LOCKED_AGENTS:
            self.assertEqual(lines[agent], 'glm-5.2')

    def test_get_current_models_after_inherit_empty_values(self):
        run_bash('bash "%s" agent inherit' % (self.cb / 'setup.sh'), self.work, self.home)
        proc = self._call('budget_get_current_models')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = dict(line.split('=', 1) for line in proc.stdout.strip().splitlines())
        self.assertEqual(sorted(lines), sorted(LOCKED_AGENTS))
        for agent in LOCKED_AGENTS:
            self.assertEqual(lines[agent], '')

    def test_preset_table_matches_catalog(self):
        proc = self._call('budget_preset_table', 'economic')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = dict(line.split('=', 1) for line in proc.stdout.strip().splitlines())
        self.assertEqual(lines, expected_preset('codebuddy', 'economic'))

    def test_preset_table_default_balanced(self):
        proc = self._call('budget_preset_table')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = dict(line.split('=', 1) for line in proc.stdout.strip().splitlines())
        self.assertEqual(lines, expected_preset('codebuddy', 'balanced'))

    def test_preset_table_unknown_preset_fails(self):
        proc = self._call('budget_preset_table', 'ultra')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('预设 "ultra" 不存在', proc.stderr)


class DiffQueryNoPlatformTests(SandboxTestCase):
    """无安装形态时查询函数显式报错（不静默猜默认）。"""

    def test_get_current_models_no_platform_fails(self):
        script = (
            'export BUDGET_PYTHON=python3; '
            'export BUDGET_LIB_DIR="%s"; '
            'export BUDGET_MODELS_FILE="%s"; '
            'source "%s"; source "%s"; source "%s"; budget_get_current_models'
            % (CORE_LIB, CORE_MODELS, CORE_LIB / 'colors.sh',
               CORE_LIB / 'platform.sh', CORE_LIB / 'preset.sh')
        )
        proc = run_bash(script, self.work, self.home)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未检测到平台形态', proc.stderr)


class ModelsCommandTests(SandboxTestCase):
    """budget setup models：lib/models.sh 就位时 do_models 接管内置概要。"""

    def setUp(self):
        super().setUp()
        self.cb = make_codebuddy_install(self.tmp)

    def test_models_full_table_via_lib_module(self):
        proc = run_bash('bash "%s" models' % (self.cb / 'setup.sh'), self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # do_models 独有列头（内置概要实现无「模型ID/适用角色」列）
        for text in ('付费模型', '免费模型', '模型ID', '厂商', '倍率', '档位',
                     '适用角色', '别名', '预设'):
            self.assertIn(text, proc.stdout)
        self.assertIn('glm-5.2', proc.stdout)
        self.assertIn('hy3', proc.stdout)
        self.assertIn('x0.65', proc.stdout)
        self.assertIn('coder_lite', proc.stdout)


class SyntaxSmokeTests(unittest.TestCase):
    """bash -n 语法冒烟与 resolver 语法编译检查。"""

    def test_bash_n_new_scripts(self):
        for script in (CORE_LIB / 'models.sh', CORE_LIB / 'preset.sh', CORE_SETUP):
            proc = subprocess.run(
                ['bash', '-n', str(script)], capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, '%s: %s' % (script, proc.stderr))

    def test_resolver_syntax_valid(self):
        source = RESOLVER.read_text(encoding='utf-8')
        compile(source, str(RESOLVER), 'exec')


if __name__ == '__main__':
    unittest.main()
