#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""autorun.py 单测（agent-autorun design.md D4/D5/D7、specs/agent-autorun/spec.md）。

复刻 tests/test_preset.py RewriteUnitTests(SandboxTestCase) 沙盒模式（L103-106
子进程直调先例 + L195-209 公共沙箱）：tmp 目录伪造 agents 目录 + 隔离 HOME +
子进程直调 core/lib/autorun.py，把原沙盒手动验证项转为自动化用例——

① 补丁插入/改值/删除与锚点（name/description/mode 最后出现行之后）；
② CRLF 行尾保留；
③ 幂等（重复 on/off 字节稳定）；
④ 种子化仅值 true 进基线（enabledAutoRun: false 行不被翻转）；
⑤ apply 全量对齐（清单内 on/清单外 off）；
⑥ 损坏 JSON 非零退出且状态文件字节不变；
⑦ unknown 形态 on/off 非零退出、list exit 0；
⑧ opencode/claudecode 降级 exit 0 零文件修改（mtime/内容双核验）；
⑨ list 双栏输出解析；
⑩ list 遇损坏状态文件只读展示（状态栏明示损坏 + 修复路径、退出码 0、字节不变）；
⑪ on 输出 bash 模式取自 .bash-patterns.json（存在时列目标 agent 模式；
   缺失时降级通用提示且开启照常完成）。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTORUN = REPO_ROOT / 'core' / 'lib' / 'autorun.py'

# codebuddy 形态 agent 产物 frontmatter 模板（结构对齐 dist 构建产物）。
AGENT_TMPL = '''---
name: {name}
description: MUST BE USED — {name} 测试 agent。
model: glm-5.2
tools: [Read, Write, Edit, Bash, Grep, Glob]
permissionMode: acceptEdits
max_turns: 35
---

{name} 的正文内容（补丁不得触碰）。
'''

# list 实况栏双栏行格式（autorun.py cmd_list：f'  {{name:<16}} {{mark}}'）。
ACTUAL_COLUMN_NAME_END = 18


class SandboxTestCase(unittest.TestCase):
    """公共沙箱：每个用例独立临时目录（伪造 agents 目录 + 隔离 HOME）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-autorun-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.agents = self.tmp / 'agents'
        self.home.mkdir()
        self.agents.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, args, kind='codebuddy', scope='project'):
        """子进程直调 autorun.py（隔离 HOME、剥离 BUDGET_*、按需注入形态变量）。

        kind 为空字符串时不注入任何形态变量——走兜底五级探测（unknown 场景）。
        """
        env = dict(os.environ)
        env['HOME'] = str(self.home)
        for key in list(env):
            if key.startswith('BUDGET_'):
                del env[key]
        if kind:
            env['BUDGET_PLATFORM_KIND'] = kind
            env['BUDGET_PLATFORM_SCOPE'] = scope
            env['BUDGET_PLATFORM_ROOT'] = str(self.tmp)
            env['BUDGET_AGENTS_DIR'] = str(self.agents)
        return subprocess.run(
            [sys.executable, str(AUTORUN)] + args,
            cwd=str(self.tmp), env=env, capture_output=True, text=True, timeout=60,
        )

    def _write_agent(self, name, content):
        """写 agent 文件（字节级精确，避开 universal newlines 翻译）。"""
        path = self.agents / (name + '.md')
        path.write_bytes(content.encode('utf-8'))
        return path

    def _make_agent(self, name):
        """以标准模板构造 agent（frontmatter 无 enabledAutoRun 行）。"""
        return self._write_agent(name, AGENT_TMPL.format(name=name))

    def _state_path(self):
        """全局状态文件路径（隔离 HOME 下 ~/.budgetbuddy/auto-run.json）。"""
        return self.home / '.budgetbuddy' / 'auto-run.json'

    def _write_state(self, agents):
        """写合法状态文件（与 autorun.write_state_file 同序列化口径）。"""
        content = json.dumps({'agents': sorted(set(agents))}, indent=2, sort_keys=True) + '\n'
        self._state_path().parent.mkdir(parents=True, exist_ok=True)
        self._state_path().write_bytes(content.encode('utf-8'))

    def _write_state_raw(self, raw):
        """写原始字节状态文件（损坏场景构造用）。"""
        self._state_path().parent.mkdir(parents=True, exist_ok=True)
        self._state_path().write_bytes(raw.encode('utf-8'))

    def _read_state(self):
        """解析状态文件 agents 清单。"""
        return json.loads(self._state_path().read_text(encoding='utf-8'))['agents']

    def _snapshot_agents(self):
        """agents 目录快照：{文件名: (内容字节, mtime_ns)}（零修改双核验用）。"""
        return {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.agents.iterdir()
        }

    def _assert_agents_unchanged(self, snapshot):
        """断言 agents 目录内容与 mtime 均未变化。"""
        self.assertEqual(
            sorted(p.name for p in self.agents.iterdir()), sorted(snapshot),
            'agents 目录文件集发生变化')
        for path in self.agents.iterdir():
            content, mtime_ns = snapshot[path.name]
            self.assertEqual(path.read_bytes(), content, '%s 内容被修改' % path.name)
            self.assertEqual(path.stat().st_mtime_ns, mtime_ns, '%s mtime 被修改' % path.name)

    def _parse_actual_marks(self, stdout, names):
        """解析 list 实况栏双栏：行格式 '  {name:<16} {mark}' → {name: mark}。

        状态栏行（'  {name}'，mark 列为空）天然被非空 mark 条件滤除。
        """
        marks = {}
        for line in stdout.splitlines():
            if not line.startswith('  '):
                continue
            name = line[2:ACTUAL_COLUMN_NAME_END].strip()
            mark = line[ACTUAL_COLUMN_NAME_END:].strip()
            if name in names and mark:
                marks[name] = mark
        return marks


class PatchOnOffTests(SandboxTestCase):
    """① 补丁插入/改值/删除与锚点（name/description/mode 最后出现行之后）。"""

    def test_on_inserts_after_last_anchor_line(self):
        """无 enabledAutoRun 行时 on 插入锚点行之后，其余字段与正文逐字节保留。"""
        content = (
            '---\n'
            'name: coder-lite\n'
            'description: 测试 agent。\n'
            'mode: subagent\n'
            'model: glm-5.2\n'
            'tools: [Read]\n'
            '---\n'
            '正文。\n'
        )
        path = self._write_agent('coder-lite', content)
        proc = self._run(['on', 'coder-lite'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('inserted', proc.stdout)
        # 锚点 = name/description/mode 最后出现行（mode）之后，非文件尾
        expected = (
            '---\n'
            'name: coder-lite\n'
            'description: 测试 agent。\n'
            'mode: subagent\n'
            'enabledAutoRun: true\n'
            'model: glm-5.2\n'
            'tools: [Read]\n'
            '---\n'
            '正文。\n'
        )
        self.assertEqual(path.read_bytes(), expected.encode('utf-8'))
        self.assertEqual(self._read_state(), ['coder-lite'])

    def test_on_replaces_existing_false_value(self):
        """已有 enabledAutoRun: false 行时 on 仅改值 true，不新增行、不动其他字段。"""
        content = (
            '---\n'
            'name: coder-lite\n'
            'description: 测试 agent。\n'
            'enabledAutoRun: false\n'
            'model: glm-5.2\n'
            '---\n'
            '正文。\n'
        )
        path = self._write_agent('coder-lite', content)
        proc = self._run(['on', 'coder-lite'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('replaced', proc.stdout)
        expected = (
            '---\n'
            'name: coder-lite\n'
            'description: 测试 agent。\n'
            'enabledAutoRun: true\n'
            'model: glm-5.2\n'
            '---\n'
            '正文。\n'
        )
        self.assertEqual(path.read_bytes(), expected.encode('utf-8'))

    def test_off_removes_line_and_keeps_others(self):
        """off 删除 enabledAutoRun 行，frontmatter 其余字段与正文逐字节保留。"""
        content = (
            '---\n'
            'name: coder-lite\n'
            'description: 测试 agent。\n'
            'enabledAutoRun: true\n'
            'model: glm-5.2\n'
            '---\n'
            '正文。\n'
        )
        path = self._write_agent('coder-lite', content)
        proc = self._run(['off', 'coder-lite'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('removed', proc.stdout)
        self.assertIn('恢复逐条确认', proc.stdout)
        expected = (
            '---\n'
            'name: coder-lite\n'
            'description: 测试 agent。\n'
            'model: glm-5.2\n'
            '---\n'
            '正文。\n'
        )
        self.assertEqual(path.read_bytes(), expected.encode('utf-8'))
        self.assertEqual(self._read_state(), [])
        self.assertIn('清单已空', proc.stdout)

    def test_off_without_line_unchanged(self):
        """无 enabledAutoRun 行时 off 为 unchanged，文件字节不变。"""
        content = '---\nname: coder-lite\ndescription: 测试。\n---\n正文。\n'
        path = self._write_agent('coder-lite', content)
        proc = self._run(['off', 'coder-lite'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('unchanged', proc.stdout)
        self.assertEqual(path.read_bytes(), content.encode('utf-8'))

    def test_unknown_agent_name_exit_2(self):
        """未知名非零退出（exit 2）并列可用名，不写状态文件、不补丁任何文件。"""
        self._make_agent('coder-lite')
        before = self._snapshot_agents()
        proc = self._run(['on', 'not-exist'])
        self.assertEqual(proc.returncode, 2)
        self.assertIn('未知 agent 名: not-exist', proc.stderr)
        self.assertIn('coder-lite', proc.stderr)
        self.assertFalse(self._state_path().exists())
        self._assert_agents_unchanged(before)


class CrlfPreserveTests(SandboxTestCase):
    """② CRLF 行尾保留（插入/改值/删除三路径均不被静默转为 LF）。"""

    def test_on_insert_keeps_crlf(self):
        content = (
            '---\r\n'
            'name: coder-lite\r\n'
            'description: 测试。\r\n'
            'model: glm-5.2\r\n'
            '---\r\n'
            '正文。\r\n'
        )
        path = self._write_agent('coder-lite', content)
        proc = self._run(['on', 'coder-lite'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = (
            '---\r\n'
            'name: coder-lite\r\n'
            'description: 测试。\r\n'
            'enabledAutoRun: true\r\n'
            'model: glm-5.2\r\n'
            '---\r\n'
            '正文。\r\n'
        )
        self.assertEqual(path.read_bytes(), expected.encode('utf-8'))

    def test_on_replace_keeps_crlf(self):
        content = (
            '---\r\n'
            'name: coder-lite\r\n'
            'description: 测试。\r\n'
            'enabledAutoRun: false\r\n'
            'model: glm-5.2\r\n'
            '---\r\n'
            '正文。\r\n'
        )
        path = self._write_agent('coder-lite', content)
        proc = self._run(['on', 'coder-lite'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = (
            '---\r\n'
            'name: coder-lite\r\n'
            'description: 测试。\r\n'
            'enabledAutoRun: true\r\n'
            'model: glm-5.2\r\n'
            '---\r\n'
            '正文。\r\n'
        )
        self.assertEqual(path.read_bytes(), expected.encode('utf-8'))

    def test_off_remove_keeps_crlf(self):
        content = (
            '---\r\n'
            'name: coder-lite\r\n'
            'description: 测试。\r\n'
            'enabledAutoRun: true\r\n'
            'model: glm-5.2\r\n'
            '---\r\n'
            '正文。\r\n'
        )
        path = self._write_agent('coder-lite', content)
        proc = self._run(['off', 'coder-lite'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = (
            '---\r\n'
            'name: coder-lite\r\n'
            'description: 测试。\r\n'
            'model: glm-5.2\r\n'
            '---\r\n'
            '正文。\r\n'
        )
        self.assertEqual(path.read_bytes(), expected.encode('utf-8'))

    def test_seed_reads_crlf_true_value(self):
        """CRLF 文件的 enabledAutoRun: true 同样被种子化识别（读取关停 newlines 翻译）。"""
        content = (
            '---\r\n'
            'name: architect\r\n'
            'description: 测试。\r\n'
            'enabledAutoRun: true\r\n'
            '---\r\n'
            '正文。\r\n'
        )
        self._write_agent('architect', content)
        self._make_agent('reviewer')
        proc = self._run(['on', 'reviewer'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._read_state(), ['architect', 'reviewer'])


class IdempotentTests(SandboxTestCase):
    """③ 幂等：重复 on/off 字节级稳定（不累积重复行）。"""

    def test_repeated_on_byte_stable(self):
        content = '---\nname: coder-lite\ndescription: 测试。\n---\n正文。\n'
        path = self._write_agent('coder-lite', content)
        self._run(['on', 'coder-lite'])
        first = path.read_bytes()
        state_first = self._state_path().read_bytes()
        proc = self._run(['on', 'coder-lite'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(path.read_bytes(), first)
        self.assertEqual(self._state_path().read_bytes(), state_first)
        self.assertEqual(path.read_text(encoding='utf-8').count('enabledAutoRun'), 1)

    def test_repeated_off_byte_stable(self):
        content = (
            '---\n'
            'name: coder-lite\n'
            'description: 测试。\n'
            'enabledAutoRun: true\n'
            '---\n'
            '正文。\n'
        )
        path = self._write_agent('coder-lite', content)
        self._run(['off', 'coder-lite'])
        first = path.read_bytes()
        proc = self._run(['off', 'coder-lite'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(path.read_bytes(), first)
        self.assertNotIn('enabledAutoRun', path.read_text(encoding='utf-8'))


class SeedBaselineTests(SandboxTestCase):
    """④ 种子化仅值 true 进基线（enabledAutoRun: false 行不被翻转）。"""

    def test_seed_only_true_enters_baseline(self):
        """状态缺失时 on：true 行进基线、false 行视为显式关闭不进基线且不被翻转。"""
        self._write_agent(
            'architect',
            '---\nname: architect\ndescription: 测试。\nenabledAutoRun: true\n---\n正文。\n')
        self._write_agent(
            'coder-lite',
            '---\nname: coder-lite\ndescription: 测试。\nenabledAutoRun: false\n---\n正文。\n')
        self._make_agent('reviewer')
        proc = self._run(['on', 'reviewer'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已按安装态种子化基线', proc.stdout)
        self.assertIn('architect', proc.stdout)
        self.assertNotIn('coder-lite 进基线', proc.stdout)
        # 基线 = 仅值 true 的 architect + 本次开启目标 reviewer
        self.assertEqual(self._read_state(), ['architect', 'reviewer'])
        # false 行原样保留（不被翻转为 true，也不被删除）
        coder_lite_text = (self.agents / 'coder-lite.md').read_text(encoding='utf-8')
        self.assertIn('enabledAutoRun: false', coder_lite_text)
        self.assertEqual(
            coder_lite_text.count('enabledAutoRun'), 1, 'false 行被累积或翻转')


class ApplyAlignTests(SandboxTestCase):
    """⑤ apply 全量对齐（清单内 on/清单外 off）。"""

    def test_apply_aligns_all_agents(self):
        """清单内 agent 开启、清单外 agent 关闭；状态文件字节不被改写。"""
        self._write_agent(
            'architect',
            '---\nname: architect\ndescription: 测试。\nenabledAutoRun: true\n---\n正文。\n')
        self._write_agent(
            'coder-lite',
            '---\nname: coder-lite\ndescription: 测试。\nenabledAutoRun: false\n---\n正文。\n')
        self._make_agent('reviewer')
        self._write_state(['coder-lite', 'reviewer'])
        state_before = self._state_path().read_bytes()
        proc = self._run(['apply'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('3 个 agent 文件变更', proc.stdout)
        self.assertIn('清单内 2 个开启', proc.stdout)
        # 清单外 architect：true 行被删除
        architect_text = (self.agents / 'architect.md').read_text(encoding='utf-8')
        self.assertNotIn('enabledAutoRun', architect_text)
        self.assertIn('name: architect', architect_text)
        # 清单内 coder-lite：false 改值 true；清单内 reviewer：无行插 true
        self.assertIn(
            'enabledAutoRun: true',
            (self.agents / 'coder-lite.md').read_text(encoding='utf-8'))
        self.assertIn(
            'enabledAutoRun: true',
            (self.agents / 'reviewer.md').read_text(encoding='utf-8'))
        # apply 只读状态文件
        self.assertEqual(self._state_path().read_bytes(), state_before)

    def test_apply_without_state_file_noop(self):
        """无状态文件时 apply 无需重放（dist 默认值成立），不创建状态文件。"""
        self._make_agent('coder-lite')
        before = self._snapshot_agents()
        proc = self._run(['apply'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('无需重放', proc.stdout)
        self.assertFalse(self._state_path().exists())
        self._assert_agents_unchanged(before)

    def test_apply_skips_uninstalled_state_agents(self):
        """状态清单含未安装 agent 时告警跳过，其余照常对齐，退出码 0。"""
        self._make_agent('coder-lite')
        self._write_state(['coder-lite', 'ghost-agent'])
        proc = self._run(['apply'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('状态清单中的 agent 未安装（跳过）: ghost-agent', proc.stderr)
        self.assertIn(
            'enabledAutoRun: true',
            (self.agents / 'coder-lite.md').read_text(encoding='utf-8'))


class CorruptStateTests(SandboxTestCase):
    """⑥ 损坏 JSON 非零退出且状态文件字节不变（on/off/apply 一致，绝不覆盖写）。"""

    def test_on_off_apply_reject_corrupt_state(self):
        raw = '{ 这不是合法 JSON'
        self._write_state_raw(raw)
        self._make_agent('coder-lite')
        agents_before = self._snapshot_agents()
        for args in (['on', 'coder-lite'], ['off', 'coder-lite'], ['apply']):
            proc = self._run(args)
            self.assertEqual(proc.returncode, 1, '%s: %s' % (args, proc.stdout))
            combined = proc.stdout + proc.stderr
            self.assertIn('状态文件损坏', combined, args)
            # 修复路径明示：编辑或删除状态文件后重试（spec「损坏状态文件拒绝执行」）
            self.assertIn('编辑或删除', combined, args)
            # 状态文件字节不被改写；agent 文件不被补丁
            self.assertEqual(self._state_path().read_bytes(), raw.encode('utf-8'), args)
            self._assert_agents_unchanged(agents_before)


class UnknownFormTests(SandboxTestCase):
    """⑦ unknown 形态（五级探测未命中）：on/off/apply 非零退出、list exit 0。"""

    def test_on_off_apply_nonzero_exit(self):
        for args in (['on', 'coder-lite'], ['off', 'coder-lite'], ['apply']):
            proc = self._run(args, kind='')
            self.assertEqual(proc.returncode, 1, '%s: %s' % (args, proc.stdout))
            combined = proc.stdout + proc.stderr
            self.assertIn('未检测到', combined, args)
            self.assertIn('BUDGET_PLATFORM=codebuddy|claudecode|opencode', combined, args)
            # 不写状态文件
            self.assertFalse(self._state_path().exists(), args)

    def test_list_exit_zero_with_hint(self):
        """同形态下 list 仍退出码 0，输出全局清单并提示未检测到安装形态。"""
        proc = self._run(['list'], kind='')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('═══ 全局状态清单', proc.stdout)
        self.assertIn('未检测到安装形态', proc.stdout)
        self.assertFalse(self._state_path().exists())


class NonCodebuddyDegradeTests(SandboxTestCase):
    """⑧ opencode/claudecode 降级 exit 0 零文件修改（mtime/内容双核验）。"""

    def test_opencode_degrade_zero_modification(self):
        self._make_agent('coder-lite')
        before = self._snapshot_agents()
        proc = self._run(['on', 'coder-lite'], kind='opencode')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('无 AutoRun 机制', proc.stdout)
        self.assertIn('permission map', proc.stdout)
        self._assert_agents_unchanged(before)
        self.assertFalse(self._state_path().exists())

    def test_claudecode_degrade_zero_modification(self):
        self._make_agent('coder-lite')
        before = self._snapshot_agents()
        proc = self._run(['off', 'coder-lite'], kind='claudecode')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('无 AutoRun 机制', proc.stdout)
        self.assertIn('settings.json', proc.stdout)
        self._assert_agents_unchanged(before)
        self.assertFalse(self._state_path().exists())


class ListDualColumnTests(SandboxTestCase):
    """⑨ list 双栏输出解析（全局状态清单 + 当前安装态实况）。"""

    def test_list_consistent_dual_columns(self):
        """一致态：双栏齐全、逐 agent 实况标记可解析、明示一致。"""
        self._write_agent(
            'coder-lite',
            '---\nname: coder-lite\ndescription: 测试。\nenabledAutoRun: true\n---\n正文。\n')
        self._make_agent('reviewer')
        self._write_state(['coder-lite'])
        proc = self._run(['list'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('═══ 全局状态清单', proc.stdout)
        self.assertIn('═══ 当前安装态实况', proc.stdout)
        marks = self._parse_actual_marks(proc.stdout, {'coder-lite', 'reviewer'})
        self.assertEqual(marks.get('coder-lite'), 'enabledAutoRun: true（免审批）')
        self.assertEqual(marks.get('reviewer'), '未设置（逐条确认）')
        self.assertIn('状态清单与安装态一致。', proc.stdout)

    def test_list_reports_state_and_actual_diffs(self):
        """差异态：状态清单多出与安装态多出均如实展示（双栏比对语义）。"""
        self._write_agent(
            'coder-lite',
            '---\nname: coder-lite\ndescription: 测试。\nenabledAutoRun: true\n---\n正文。\n')
        self._write_agent(
            'tester',
            '---\nname: tester\ndescription: 测试。\nenabledAutoRun: true\n---\n正文。\n')
        self._make_agent('reviewer')
        self._write_state(['coder-lite', 'reviewer'])
        proc = self._run(['list'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('差异: 状态清单含 reviewer，但安装态未开启', proc.stdout)
        self.assertIn('差异: 安装态已开启 tester，但不在状态清单', proc.stdout)
        marks = self._parse_actual_marks(proc.stdout, {'coder-lite', 'tester', 'reviewer'})
        self.assertEqual(marks.get('tester'), 'enabledAutoRun: true（免审批）')


class ListCorruptReadonlyTests(SandboxTestCase):
    """⑩ list 遇损坏状态文件只读展示（状态栏明示损坏 + 修复路径、exit 0、字节不变）。"""

    def test_list_corrupt_state_readonly(self):
        raw = '{"agents": [损坏'
        self._write_state_raw(raw)
        self._make_agent('coder-lite')
        proc = self._run(['list'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('损坏（JSON 解析失败', proc.stdout)
        self.assertIn('修复：编辑或删除', proc.stdout)
        self.assertIn('状态文件字节不被改写', proc.stdout)
        # 实况栏照常展示当前安装态（只读不中断）
        self.assertIn('═══ 当前安装态实况', proc.stdout)
        marks = self._parse_actual_marks(proc.stdout, {'coder-lite'})
        self.assertEqual(marks.get('coder-lite'), '未设置（逐条确认）')
        # list 只读：状态文件字节不变
        self.assertEqual(self._state_path().read_bytes(), raw.encode('utf-8'))


class BashPatternNoticeTests(SandboxTestCase):
    """⑪ on 输出 bash 模式取自 .bash-patterns.json（D7：存在时列模式、缺失时降级）。"""

    def _write_patterns(self, data):
        (self.agents / '.bash-patterns.json').write_bytes(
            (json.dumps(data, indent=2, sort_keys=True) + '\n').encode('utf-8'))

    def test_on_lists_bash_patterns_when_present(self):
        """数据文件存在时：列目标 agent 的 bash 模式，* 与 git 类给醒目提示。"""
        self._make_agent('architect')
        self._make_agent('coder-lite')
        self._write_patterns({'agents': {
            'architect': {'bash_allow': ['git *', 'openspec *']},
            'coder-lite': {'bash_allow': ['*']},
        }})
        proc = self._run(['on', 'architect', 'coder-lite'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('[安全知情]', proc.stdout)
        self.assertIn('git *', proc.stdout)
        self.assertIn('openspec *', proc.stdout)
        self.assertIn('git 类命令免审批', proc.stdout)
        self.assertIn('任意 shell 命令免审批', proc.stdout)
        # 开启照常完成
        self.assertEqual(self._read_state(), ['architect', 'coder-lite'])
        for name in ('architect', 'coder-lite'):
            self.assertIn(
                'enabledAutoRun: true',
                (self.agents / (name + '.md')).read_text(encoding='utf-8'))

    def test_on_degrades_when_patterns_missing(self):
        """数据文件缺失（旧安装）时降级通用提示，且不阻断开启。"""
        self._make_agent('reviewer')
        proc = self._run(['on', 'reviewer'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('[安全知情]', proc.stdout)
        self.assertIn('未找到 .bash-patterns.json', proc.stdout)
        self.assertIn('暂无法列出具体 bash 模式', proc.stdout)
        self.assertIn('开启照常完成', proc.stdout)
        # 开启照常完成：补丁落位 + 状态文件写入
        self.assertIn(
            'enabledAutoRun: true',
            (self.agents / 'reviewer.md').read_text(encoding='utf-8'))
        self.assertEqual(self._read_state(), ['reviewer'])

    def test_on_empty_bash_allow_notice(self):
        """bash_allow 为 [] 时明示无 bash 权限，不影响开启。"""
        self._make_agent('director')
        self._write_patterns({'agents': {'director': {'bash_allow': []}}})
        proc = self._run(['on', 'director'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未配置任何 bash 权限', proc.stdout)
        self.assertEqual(self._read_state(), ['director'])


class SyntaxSmokeTests(unittest.TestCase):
    """autorun.py 语法编译冒烟（与 test_preset resolver 先例一致）。"""

    def test_autorun_syntax_valid(self):
        source = AUTORUN.read_text(encoding='utf-8')
        compile(source, str(AUTORUN), 'exec')


if __name__ == '__main__':
    unittest.main()
