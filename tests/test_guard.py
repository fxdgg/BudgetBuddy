#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""guard.sh Coder Guard 降级判定单测（tasks.md 3.5 / design.md §8.2/§12-A14）。

驱动方式与 test_state.py 一致：bash source colors.sh + guard.sh 后调函数
（临时目录项目区 + 隔离 HOME + 剥离 BUDGET_* 与会话注入环境变量）。

用例覆盖（A14 核心语义）:
  1. guard_query 空历史 → 无降级建议（样本不足）
  2. 4 次窗口 1 失败 → 不触发降级（失败 1 < 2）
  3. 5 次窗口恰 2 失败（阈值边界）→ 触发降级（lite→standard /
     standard→senior 各一例）
  4. 连续 3 次失败 → 建议升级 Director（3 轮全败语义）
  5. guard_append 追加后 summary 计数同步
  6. guard_reset 清空历史
  7. 不同 coder 级别记录隔离（lite/standard/senior 的 history 正确标记
     escalated_to，判定窗口互不串扰）
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_SCRIPT = REPO_ROOT / 'core' / 'lib' / 'guard.sh'
RTK_SCRIPT = REPO_ROOT / 'core' / 'lib' / 'rtk.sh'
COLORS_SCRIPT = REPO_ROOT / 'core' / 'lib' / 'colors.sh'


def run_bash(script, cwd, home):
    """在指定 cwd/HOME 下运行 bash（剥离 BUDGET_* 与会话注入变量实现隔离）。"""
    env = dict(os.environ)
    env['HOME'] = str(home)
    for key in list(env):
        if key.startswith('BUDGET_') or key in ('BASH_ENV', 'CODEBUDDY_SESSION_ID'):
            del env[key]
    return subprocess.run(
        ['bash', '-c', script], cwd=str(cwd), env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )


class SandboxTestCase(unittest.TestCase):
    """公共沙箱：每个用例独立临时目录（项目区 + 隔离 HOME）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-guard-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    # ── guard 辅助 ─────────────────────────────────────────────────────

    def run_guard(self, script, cwd=None):
        """source colors.sh + guard.sh 后执行片段（budget_print_* 依赖就位）。"""
        full = 'source "%s"; source "%s"; %s' % (COLORS_SCRIPT, GUARD_SCRIPT, script)
        return run_bash(full, cwd or self.work, self.home)

    def guard_file(self):
        """预期记录文件路径（无 git 时 project-name = cwd 目录名）。"""
        return (self.home / '.budgetbuddy' / 'projects' / self.work.name
                / 'memory' / 'coder-guard.json')

    def read_json(self, path):
        return json.loads(path.read_text(encoding='utf-8'))

    def append_records(self, coder, tag, results):
        """按序追加记录（时间顺序即列表顺序，越靠后越新）。"""
        for result in results:
            proc = self.run_guard(
                'guard_append --coder %s --tags %s --result %s' % (coder, tag, result))
            self.assertEqual(proc.returncode, 0, proc.stderr)


class GuardQueryEmptyTests(SandboxTestCase):
    """用例 1：空历史 → 无降级建议。"""

    def test_query_no_file_no_degradation(self):
        """记录文件不存在 → 提示无记录，无任何降级建议。"""
        proc = self.run_guard('guard_query coder-lite')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未找到 Coder Guard 记录', proc.stdout)
        self.assertNotIn('触发降级保护', proc.stdout)
        self.assertNotIn('Director', proc.stdout)

    def test_query_empty_history_insufficient_samples(self):
        """空历史（reset 后空文件）→ 样本不足，无降级建议。"""
        proc = self.run_guard('guard_reset')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('样本不足', proc.stdout)
        self.assertNotIn('触发降级保护', proc.stdout)
        self.assertNotIn('Director', proc.stdout)


class GuardQueryWindowTests(SandboxTestCase):
    """用例 2/3：窗口失败计数与降级阈值（失败 >= 2 触发）。"""

    def test_four_records_one_failure_no_degradation(self):
        """4 次窗口 1 失败 → 不触发降级（失败 1 < 2）。"""
        self.append_records('coder-lite', 'api_endpoint',
                            ['failure', 'success', 'success', 'success'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('无降级风险', proc.stdout)
        self.assertIn('失败 1', proc.stdout)
        self.assertNotIn('触发降级保护', proc.stdout)

    def test_five_records_two_failures_degrades_lite_to_standard(self):
        """5 次窗口恰 2 失败（阈值边界）→ lite 降级改派 standard。"""
        self.append_records('coder-lite', 'api_endpoint',
                            ['failure', 'failure', 'success', 'success', 'success'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('触发降级保护', proc.stdout)
        self.assertIn('coder-standard', proc.stdout)

    def test_five_records_two_failures_degrades_standard_to_senior(self):
        """5 次窗口恰 2 失败 → standard 降级改派 senior。"""
        self.append_records('coder-standard', 'api_endpoint',
                            ['failure', 'failure', 'success', 'success', 'success'])
        proc = self.run_guard('guard_query coder-standard api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('触发降级保护', proc.stdout)
        self.assertIn('coder-senior', proc.stdout)


class GuardQueryStreakTests(SandboxTestCase):
    """用例 4：连续失败判定（连续 3 次 → Director，3 轮全败语义）。"""

    def test_consecutive_three_failures_suggests_director(self):
        self.append_records('coder-lite', 'api_endpoint',
                            ['success', 'success', 'failure', 'failure', 'failure'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('连续失败 3 次', proc.stdout)
        self.assertIn('Director', proc.stdout)

    def test_two_consecutive_failures_not_director(self):
        """连续 2 次失败走降级分支而非 Director（streak 达 3 才升级）。"""
        self.append_records('coder-lite', 'api_endpoint',
                            ['success', 'success', 'success', 'failure', 'failure'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('触发降级保护', proc.stdout)
        self.assertNotIn('连续失败 3 次', proc.stdout)


class GuardAppendSummaryTests(SandboxTestCase):
    """用例 5：guard_append 追加后 summary 计数同步。"""

    def test_append_syncs_history_and_summary_counts(self):
        self.append_records('coder-lite', 'api_endpoint',
                            ['failure', 'failure', 'success'])
        guard_file = self.guard_file()
        self.assertTrue(guard_file.is_file())
        data = self.read_json(guard_file)
        self.assertEqual(len(data['history']), 3)
        self.assertEqual(
            data['summary']['coder-lite']['api_endpoint'],
            {'failure': 2, 'success': 1, 'total': 3})

    def test_summary_output_reflects_appended_records(self):
        self.append_records('coder-lite', 'api_endpoint',
                            ['failure', 'failure', 'success'])
        proc = self.run_guard('guard_summary')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('coder-lite', proc.stdout)
        self.assertIn('total=3', proc.stdout)
        self.assertIn('failure=2', proc.stdout)
        self.assertIn('历史记录: 3 条', proc.stdout)


class GuardResetTests(SandboxTestCase):
    """用例 6：guard_reset 清空历史。"""

    def test_reset_clears_history_and_summary(self):
        self.append_records('coder-lite', 'api_endpoint', ['failure', 'failure'])
        proc = self.run_guard('guard_reset')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已重置', proc.stdout)
        data = self.read_json(self.guard_file())
        self.assertEqual(data, {'history': [], 'summary': {}})
        # 清空后查询回到无降级建议
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('样本不足', proc.stdout)
        self.assertNotIn('触发降级保护', proc.stdout)


class GuardCoderIsolationTests(SandboxTestCase):
    """用例 7：不同 coder 级别记录隔离（history 正确标记 escalated_to）。"""

    def test_history_marks_escalated_to_per_coder(self):
        """lite/standard/senior 各自追加的记录按 coder 正确标记 escalated_to。"""
        proc = self.run_guard(
            'guard_append --coder coder-lite --tags api_endpoint --result failure '
            '--escalated-to coder-standard')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.run_guard(
            'guard_append --coder coder-standard --tags api_endpoint --result failure '
            '--escalated-to coder-senior')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.run_guard(
            'guard_append --coder coder-senior --tags api_endpoint --result failure')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_json(self.guard_file())
        self.assertEqual(len(data['history']), 3)
        by_coder = {entry['coder']: entry for entry in data['history']}
        self.assertEqual(by_coder['coder-lite']['escalated_to'], 'coder-standard')
        self.assertEqual(by_coder['coder-standard']['escalated_to'], 'coder-senior')
        self.assertIsNone(by_coder['coder-senior']['escalated_to'])

    def test_query_windows_isolated_per_coder(self):
        """lite 的失败窗口不串扰 standard / senior 的判定（按 coder 过滤）。"""
        self.append_records('coder-lite', 'api_endpoint', ['failure', 'failure'])
        self.append_records('coder-standard', 'api_endpoint',
                            ['success', 'success', 'success'])
        self.append_records('coder-senior', 'api_endpoint', ['success'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('触发降级保护', proc.stdout)
        proc = self.run_guard('guard_query coder-standard api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('无降级风险', proc.stdout)
        proc = self.run_guard('guard_query coder-senior api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('样本不足', proc.stdout)


class LibScriptSyntaxTests(unittest.TestCase):
    """bash -n 语法检查（guard.sh + rtk.sh，lib 平移入产物前的静态门禁）。"""

    def test_bash_n_guard_script(self):
        proc = subprocess.run(
            ['bash', '-n', str(GUARD_SCRIPT)],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_bash_n_rtk_script(self):
        proc = subprocess.run(
            ['bash', '-n', str(RTK_SCRIPT)],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == '__main__':
    unittest.main()
