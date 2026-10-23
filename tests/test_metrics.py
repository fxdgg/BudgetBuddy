#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""metrics.py 质量指标采集与趋势告警单测（openspec agent-quality-trend task 3.1）。

被测对象（design D1-D4）:
  - core/lib/metrics.py：scan_verdicts / aggregate / load_trend / record CLI
  - core/lib/display.py / core/lib/run_summary.py：延迟导入 metrics 的「质量趋势」段
  - core/skills/budget-workflow/phases.md 与 reviewer/reviewer-b 定义：采集流程静态断言

驱动方式: Python 侧 import 直调 + sys.executable CLI 端到端（参照
tests/test_guard_metrics.py）；每个用例在临时目录内构造 change 目录 / guard.json
/ metrics.json，并隔离 HOME 与 BUDGET_* 环境变量，绝不触碰真实 ~/.budgetbuddy。

用例分组（对应 tasks.md 3.1）:
  ① 标记提取   ② 显式参数优先  ③ 幂等覆盖  ④ guard 快照  ⑤ R1 退化告警
  ⑥ R2 一次通过率  ⑦ R3 失败率  ⑧ 空态降级  ⑨ 原子写  ⑩ display/run_summary
  ⑪ recorder 流程静态断言  ⑫ sandbox 隔离
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
LIB_DIR = REPO_ROOT / 'core' / 'lib'
METRICS_SCRIPT = LIB_DIR / 'metrics.py'
DISPLAY_SCRIPT = LIB_DIR / 'display.py'
RUN_SUMMARY_SCRIPT = LIB_DIR / 'run_summary.py'
PHASES_MD = REPO_ROOT / 'core' / 'skills' / 'budget-workflow' / 'phases.md'
REVIEWER_MD = REPO_ROOT / 'core' / 'agents' / 'reviewer.md'
REVIEWER_B_MD = REPO_ROOT / 'core' / 'agents' / 'reviewer-b.md'

sys.path.insert(0, str(LIB_DIR))
import metrics  # noqa: E402  pylint: disable=wrong-import-position

sys.path.remove(str(LIB_DIR))


# ─── 公共辅助 ────────────────────────────────────────────────────────────────


def marker(data: dict) -> str:
    """构造 budget-verdict 标记行（单行 JSON，与 agent 定义约定一致）。"""
    return '<!-- budget-verdict: %s -->' % json.dumps(data, ensure_ascii=False)


def reviewer_marker(rating: str, conclusion: str, round_no: int) -> str:
    """reviewer 标记（含 rating 键，Phase 2 轮次或 Phase 4 round 0）。"""
    return marker({'rating': rating, 'conclusion': conclusion, 'round': round_no})


def reviewer_b_marker(conclusion: str, round_no: int) -> str:
    """reviewer-b 标记（无 rating 键）。"""
    return marker({'conclusion': conclusion, 'round': round_no})


def trend_entry(change_id: str, final_rating=None, phase2_rounds=None,
                guard_failures=0, guard_history_total=0) -> dict:
    """构造 metrics.json history 条目（只填充趋势计算相关字段）。"""
    return {
        'change_id': change_id,
        'date': '2026-10-23T00:00:00Z',
        'phase2_rating': None,
        'phase2_rounds': phase2_rounds,
        'reviewer_b_conclusion': None,
        'final_rating': final_rating,
        'guard_failures': guard_failures,
        'guard_history_total': guard_history_total,
        'guard_downgrades': 0,
    }


def load_lib_module(path: Path, name: str):
    """按文件路径加载 core/lib 模块（display / run_summary，避免 sys.path 污染）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MetricsSandboxTestCase(unittest.TestCase):
    """公共沙箱：临时目录 change 区 + 隔离 HOME + 临时 metrics/guard 路径。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-metrics-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.change_dir = self.tmp / 'change'
        for path in (self.home, self.work, self.change_dir):
            path.mkdir()
        self.memory = self.tmp / 'memory'
        self.metrics_file = self.memory / 'metrics.json'
        self.guard_file = self.memory / 'coder-guard.json'

    def tearDown(self):
        self._tmp.cleanup()

    # ── 产物构造 ───────────────────────────────────────────────────────

    def write_change(self, name: str, lines: list[str]) -> Path:
        """在 change 目录写入 .md 文件（支持 reviews/ 等子目录）。"""
        path = self.change_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return path

    def write_metrics(self, entries: list[dict]) -> Path:
        """写入 metrics.json（history + recorded_count）。"""
        payload = {'history': entries, 'recorded_count': len(entries)}
        return self.write_raw_metrics(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + '\n')

    def write_raw_metrics(self, text: str) -> Path:
        """写入任意 metrics.json 内容（坏 JSON 场景）。"""
        self.memory.mkdir(parents=True, exist_ok=True)
        self.metrics_file.write_text(text, encoding='utf-8')
        return self.metrics_file

    def write_guard(self, entries: list[dict], summary=None) -> Path:
        """写入 coder-guard.json（summary 可故意与 history 口径冲突）。"""
        self.memory.mkdir(parents=True, exist_ok=True)
        payload = {'history': entries, 'summary': summary or {}}
        self.guard_file.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + '\n',
            encoding='utf-8')
        return self.guard_file

    def read_metrics(self) -> dict:
        return json.loads(self.metrics_file.read_text(encoding='utf-8'))

    def last_entry(self) -> dict:
        return self.read_metrics()['history'][-1]

    # ── 进程调用 ───────────────────────────────────────────────────────

    def cli(self, *args, env=None, cwd=None) -> subprocess.CompletedProcess:
        """执行 metrics.py CLI（剥离 BUDGET_* + 隔离 HOME，临时 cwd）。"""
        base = {key: value for key, value in os.environ.items()
                if not key.startswith('BUDGET_')}
        base['HOME'] = str(self.home)
        base.update(env or {})
        return subprocess.run(
            [sys.executable, str(METRICS_SCRIPT), *args],
            cwd=str(cwd or self.work), env=base,
            capture_output=True, text=True, encoding='utf-8', timeout=60,
        )

    def record(self, *extra, change_id='c1', env=None) -> subprocess.CompletedProcess:
        """record 子命令（默认指向沙箱 metrics/guard 路径与 change 目录）。"""
        return self.cli(
            'record', '--change-id', change_id,
            '--change-dir', str(self.change_dir),
            '--metrics-file', str(self.metrics_file),
            '--guard-file', str(self.guard_file),
            *extra, env=env)


# ─── ① 标记提取与聚合 ────────────────────────────────────────────────────────


class VerdictExtractionTests(MetricsSandboxTestCase):
    """用例 ①：单文件 / 子目录多文件 / reviewer-b / 坏 JSON / 整行匹配 / tie-breaker。"""

    def test_single_gate_review_file(self):
        """单文件 gate-review.md 的 reviewer 标记 → phase2 字段。"""
        path = self.write_change('gate-review.md', [reviewer_marker('B', 'revise', 2)])
        verdicts, warnings = metrics.scan_verdicts(str(self.change_dir))
        self.assertEqual(warnings, [])
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0][0], str(path))
        self.assertEqual(verdicts[0][1]['rating'], 'B')
        self.assertEqual(metrics.aggregate(verdicts), ('B', 2, None, None))

    def test_reviews_subdir_multiple_files(self):
        """reviews/ 子目录多文件：phase2 取非 0 轮次，终审取 round 0，reviewer-b 独立。"""
        self.write_change('reviews/reviewer-a.md', [reviewer_marker('C', 'revise', 1)])
        self.write_change('reviews/reviewer-b.md', [reviewer_b_marker('fail', 2)])
        self.write_change('final-review.md', [reviewer_marker('A', 'pass', 0)])
        verdicts, warnings = metrics.scan_verdicts(str(self.change_dir))
        self.assertEqual(warnings, [])
        self.assertEqual(len(verdicts), 3)
        self.assertEqual(metrics.aggregate(verdicts), ('C', 1, 'fail', 'A'))

    def test_reviewer_b_marker_without_rating_recorded(self):
        """reviewer-b 标记（无 rating 键）→ reviewer_b_conclusion 落盘。"""
        self.write_change('reviews/reviewer-b.md', [reviewer_b_marker('fail', 2)])
        verdicts, _ = metrics.scan_verdicts(str(self.change_dir))
        self.assertEqual(metrics.aggregate(verdicts), (None, None, 'fail', None))

        proc = self.record()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.last_entry()
        self.assertEqual(entry['reviewer_b_conclusion'], 'fail')
        self.assertIsNone(entry['phase2_rating'])
        self.assertIsNone(entry['phase2_rounds'])
        self.assertIsNone(entry['final_rating'])

    def test_bad_json_skipped_with_stderr_hint(self):
        """坏 JSON 标记行跳过 + stderr 提示，合法标记仍正常聚合且退出码 0。"""
        self.write_change('notes.md', [
            '<!-- budget-verdict: {"rating": "B", "round": -->',
            reviewer_marker('A', 'pass', 3),
        ])
        verdicts, warnings = metrics.scan_verdicts(str(self.change_dir))
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn('坏 JSON', warnings[0])

        proc = self.record()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('坏 JSON', proc.stderr)
        self.assertEqual(self.last_entry()['phase2_rating'], 'A')

    def test_embedded_markers_in_paragraph_and_code_span_ignored(self):
        """整行匹配：段落内嵌 / 反引号 code span / 缩进示例行均不提取。"""
        example = reviewer_marker('D', 'escalate', 1)
        self.write_change('design.md', [
            '示例：段落内嵌 %s 不提取。' % example,
            '`%s`' % example,
            '    %s' % example,
            reviewer_marker('A', 'pass', 2),
        ])
        verdicts, warnings = metrics.scan_verdicts(str(self.change_dir))
        self.assertEqual(warnings, [])
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(metrics.aggregate(verdicts), ('A', 2, None, None))

    def test_marker_prefix_without_suffix_ignored(self):
        """行首前缀但缺行尾 --> 的段落行不匹配（整行匹配双端约束）。"""
        self.write_change('design.md', [
            '<!-- budget-verdict: {"rating":"D","conclusion":"revise","round":1}',
        ])
        verdicts, warnings = metrics.scan_verdicts(str(self.change_dir))
        self.assertEqual(verdicts, [])
        self.assertEqual(warnings, [])

    def test_same_round_tie_breaker_lexicographic(self):
        """同 round 多文件取文件路径字典序最大者（与写入顺序无关）。"""
        self.write_change('reviews/round2-verdict.md', [reviewer_marker('C', 'revise', 2)])
        self.write_change('reviews/reviewer-a.md', [reviewer_marker('B', 'revise', 2)])
        self.write_change('reviews/aaa-round2.md', [reviewer_marker('D', 'escalate', 2)])
        for _ in range(2):
            verdicts, _ = metrics.scan_verdicts(str(self.change_dir))
            self.assertEqual(metrics.aggregate(verdicts), ('C', 2, None, None))

    def test_round_aggregation_includes_final_round_zero(self):
        """phase2 取最大非 0 轮次，终审评分单独取 round==0，互不污染。"""
        self.write_change('gate-review.md', [reviewer_marker('C', 'revise', 1)])
        self.write_change('reviews/round2.md', [reviewer_marker('B', 'revise', 2)])
        self.write_change('final-review.md', [reviewer_marker('A', 'pass', 0)])
        verdicts, _ = metrics.scan_verdicts(str(self.change_dir))
        self.assertEqual(metrics.aggregate(verdicts), ('B', 2, None, 'A'))

        proc = self.record()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.last_entry()
        self.assertEqual(entry['phase2_rating'], 'B')
        self.assertEqual(entry['phase2_rounds'], 2)
        self.assertEqual(entry['final_rating'], 'A')

    def test_phase3_directory_without_markers(self):
        """Phase 3 无标记场景：目录仅含普通 .md → 聚合全 null 且不阻断归档。"""
        self.write_change('design.md', ['## 方案设计', '无标记正文。'])
        self.write_change('tasks.md', ['- [x] 1.1 已完成'])
        verdicts, warnings = metrics.scan_verdicts(str(self.change_dir))
        self.assertEqual(verdicts, [])
        self.assertEqual(warnings, [])
        self.assertEqual(metrics.aggregate(verdicts), (None, None, None, None))

        proc = self.record()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.last_entry()
        for key in ('phase2_rating', 'phase2_rounds', 'reviewer_b_conclusion',
                    'final_rating'):
            self.assertIsNone(entry[key])


# ─── ② 显式参数优先 ─────────────────────────────────────────────────────────


class ExplicitOverrideTests(MetricsSandboxTestCase):
    """用例 ②：--phase2-rating 等显式参数覆盖扫描结果（标记缺失人工兜底）。"""

    def test_explicit_args_override_scan(self):
        self.write_change('gate-review.md', [reviewer_marker('B', 'revise', 2)])
        self.write_change('final-review.md', [reviewer_marker('C', 'revise', 0)])
        self.write_change('reviews/reviewer-b.md', [reviewer_b_marker('fail', 2)])

        proc = self.record(
            '--phase2-rating', 'A', '--phase2-rounds', '1',
            '--final-rating', 'D', '--reviewer-b', 'pass')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.last_entry()
        self.assertEqual(entry['phase2_rating'], 'A')
        self.assertEqual(entry['phase2_rounds'], 1)
        self.assertEqual(entry['final_rating'], 'D')
        self.assertEqual(entry['reviewer_b_conclusion'], 'pass')

    def test_explicit_args_fill_missing_markers(self):
        """标记全缺失时显式参数补齐，未兜底字段保持 null。"""
        self.write_change('design.md', ['无标记正文。'])
        proc = self.record('--final-rating', 'B')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.last_entry()
        self.assertEqual(entry['final_rating'], 'B')
        self.assertIsNone(entry['phase2_rating'])


# ─── ③ 幂等覆盖 ─────────────────────────────────────────────────────────────


class IdempotentRecordTests(MetricsSandboxTestCase):
    """用例 ③：同 change_id 重录覆盖非追加，recorded_count 不虚增。"""

    def test_same_change_id_updates_in_place(self):
        self.write_change('gate-review.md', [reviewer_marker('B', 'revise', 2)])
        first = self.record()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)['recorded_count'], 1)

        self.write_change('gate-review.md', [reviewer_marker('A', 'pass', 3)])
        second = self.record()
        self.assertEqual(second.returncode, 0, second.stderr)
        payload = self.read_metrics()
        self.assertEqual(payload['recorded_count'], 1)
        self.assertEqual(len(payload['history']), 1)
        self.assertEqual(payload['history'][0]['phase2_rating'], 'A')
        self.assertEqual(payload['history'][0]['phase2_rounds'], 3)

    def test_distinct_change_ids_append(self):
        self.write_change('gate-review.md', [reviewer_marker('B', 'revise', 1)])
        self.assertEqual(self.record(change_id='c1').returncode, 0)
        self.assertEqual(self.record(change_id='c2').returncode, 0)
        payload = self.read_metrics()
        self.assertEqual(payload['recorded_count'], 2)
        self.assertEqual([entry['change_id'] for entry in payload['history']],
                         ['c1', 'c2'])


# ─── ④ guard 快照（history 全量口径）────────────────────────────────────────


class GuardSnapshotTests(MetricsSandboxTestCase):
    """用例 ④：failures / history_total / downgrades 三口径取自 history，不用 summary。"""

    def test_guard_snapshot_uses_history_not_summary(self):
        entries = [
            {'coder': 'coder-lite', 'result': 'failure', 'tags': ['api_endpoint'],
             'escalated_to': None, 'timestamp': '2026-10-20T00:00:00Z'},
            {'coder': 'coder-lite', 'result': 'failure', 'tags': [],
             'escalated_to': 'coder-standard', 'timestamp': '2026-10-20T01:00:00Z'},
            {'coder': 'coder-standard', 'result': 'success',
             'tags': ['config_edit', 'docs_only'],
             'escalated_to': 'coder-senior', 'timestamp': '2026-10-21T00:00:00Z'},
            # 无 tags 键条目（历史遗留写入）
            {'coder': 'coder-lite', 'result': 'success', 'escalated_to': None,
             'timestamp': '2026-10-22T00:00:00Z'},
            # escalated_to 空串不计入降级
            {'coder': 'coder-senior', 'result': 'success', 'tags': ['test_only'],
             'escalated_to': '', 'timestamp': '2026-10-23T00:00:00Z'},
        ]
        self.write_guard(entries, summary={'failures': 99, 'total': 999,
                                           'downgrades': 88})
        proc = self.record()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.last_entry()
        self.assertEqual(entry['guard_failures'], 2)
        self.assertEqual(entry['guard_history_total'], 5)
        self.assertEqual(entry['guard_downgrades'], 2)

    def test_missing_guard_file_snapshots_zero(self):
        """guard.json 缺失 → 三口径均 0（快照不阻断采集）。"""
        proc = self.record()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = self.last_entry()
        self.assertEqual(entry['guard_failures'], 0)
        self.assertEqual(entry['guard_history_total'], 0)
        self.assertEqual(entry['guard_downgrades'], 0)


# ─── ⑤ R1 评分连续下降 ─────────────────────────────────────────────────────


class RatingDeclineAlertTests(MetricsSandboxTestCase):
    """用例 ⑤：R1 最近 ≥3 条严格连续下降，null 中断不告警。"""

    def _rules(self, entries, limit=5) -> list[str]:
        self.write_metrics(entries)
        return [alert['rule'] for alert in
                metrics.load_trend(str(self.metrics_file), limit=limit)['alerts']]

    def test_three_consecutive_decline_alerts(self):
        rules = self._rules([trend_entry('c1', 'A'), trend_entry('c2', 'B'),
                             trend_entry('c3', 'C')])
        self.assertIn('rating_decline', rules)

    def test_null_interrupts_decline(self):
        rules = self._rules([trend_entry('c1', 'A'), trend_entry('c2', None),
                             trend_entry('c3', 'B'), trend_entry('c4', 'C')])
        self.assertNotIn('rating_decline', rules)

    def test_flat_ratings_do_not_alert(self):
        rules = self._rules([trend_entry('c1', 'B'), trend_entry('c2', 'B'),
                             trend_entry('c3', 'C')])
        self.assertNotIn('rating_decline', rules)

    def test_two_records_are_not_enough(self):
        rules = self._rules([trend_entry('c1', 'A'), trend_entry('c2', 'B')])
        self.assertNotIn('rating_decline', rules)

    def test_decline_window_uses_latest_three(self):
        """窗口只看最近 3 条：更早的高分不参与（A,B,C,D 最近三条 B→C→D 仍告警）。"""
        rules = self._rules([trend_entry('c1', 'A'), trend_entry('c2', 'B'),
                             trend_entry('c3', 'C'), trend_entry('c4', 'D')])
        self.assertIn('rating_decline', rules)


# ─── ⑥ R2 一次通过率 ───────────────────────────────────────────────────────


class PassFirstRateAlertTests(MetricsSandboxTestCase):
    """用例 ⑥：R2 一次通过率 <50% 告警（恰 50% 不告警，分母 0 不计算）。"""

    def _trend(self, entries, limit=200) -> dict:
        self.write_metrics(entries)
        return metrics.load_trend(str(self.metrics_file), limit=limit)

    def test_exact_half_does_not_alert(self):
        trend = self._trend([trend_entry('c1', phase2_rounds=1),
                             trend_entry('c2', phase2_rounds=2)])
        self.assertEqual(trend['pass_first_rate'], 0.5)
        rules = [alert['rule'] for alert in trend['alerts']]
        self.assertNotIn('pass_first_rate_low', rules)

    def test_below_half_alerts(self):
        entries = [trend_entry('c%d' % index, phase2_rounds=1) for index in range(49)]
        entries += [trend_entry('c%d' % index, phase2_rounds=2) for index in range(49, 100)]
        trend = self._trend(entries)
        self.assertAlmostEqual(trend['pass_first_rate'], 0.49, places=6)
        rules = [alert['rule'] for alert in trend['alerts']]
        self.assertIn('pass_first_rate_low', rules)
        message = [alert['message'] for alert in trend['alerts']
                   if alert['rule'] == 'pass_first_rate_low'][0]
        self.assertIn('49%', message)

    def test_all_null_rounds_denominator_zero(self):
        trend = self._trend([trend_entry('c1'), trend_entry('c2')])
        self.assertIsNone(trend['pass_first_rate'])
        rules = [alert['rule'] for alert in trend['alerts']]
        self.assertNotIn('pass_first_rate_low', rules)


# ─── ⑦ R3 guard 失败率 ─────────────────────────────────────────────────────


class FailureRateAlertTests(MetricsSandboxTestCase):
    """用例 ⑦：R3 最新快照失败率 >40% 且样本 ≥5 才告警。"""

    def _trend(self, failures: int, total: int) -> dict:
        self.write_metrics([
            trend_entry('c1', 'A'),
            trend_entry('c2', 'A', guard_failures=failures,
                        guard_history_total=total),
        ])
        return metrics.load_trend(str(self.metrics_file))

    def test_forty_percent_boundary_does_not_alert(self):
        trend = self._trend(4, 10)
        self.assertAlmostEqual(trend['guard_failure_rate'], 0.4, places=6)
        rules = [alert['rule'] for alert in trend['alerts']]
        self.assertNotIn('failure_rate_high', rules)

    def test_sixty_percent_alerts(self):
        trend = self._trend(6, 10)
        self.assertAlmostEqual(trend['guard_failure_rate'], 0.6, places=6)
        rules = [alert['rule'] for alert in trend['alerts']]
        self.assertIn('failure_rate_high', rules)

    def test_small_sample_does_not_alert(self):
        """样本 4 < 5：即使失败率 75% 也不告警（但比率照常计算）。"""
        trend = self._trend(3, 4)
        self.assertAlmostEqual(trend['guard_failure_rate'], 0.75, places=6)
        rules = [alert['rule'] for alert in trend['alerts']]
        self.assertNotIn('failure_rate_high', rules)

    def test_latest_snapshot_wins(self):
        """取最新一条快照口径：旧记录的高失败率不参与判定。"""
        self.write_metrics([
            trend_entry('c1', 'A', guard_failures=9, guard_history_total=10),
            trend_entry('c2', 'A', guard_failures=1, guard_history_total=10),
        ])
        trend = metrics.load_trend(str(self.metrics_file))
        self.assertAlmostEqual(trend['guard_failure_rate'], 0.1, places=6)
        rules = [alert['rule'] for alert in trend['alerts']]
        self.assertNotIn('failure_rate_high', rules)


# ─── ⑧ 空态与坏 JSON 降级 ───────────────────────────────────────────────────


class EmptyStateTests(MetricsSandboxTestCase):
    """用例 ⑧：metrics.json 缺失 / 空 history / 坏 JSON → available false 不崩。"""

    def test_missing_file_load_trend_unavailable(self):
        trend = metrics.load_trend(str(self.metrics_file))
        self.assertFalse(trend['available'])
        self.assertEqual(trend['ratings'], [])
        self.assertIsNone(trend['pass_first_rate'])
        self.assertIsNone(trend['guard_failure_rate'])
        self.assertEqual(trend['alerts'], [])

    def test_missing_file_cli_trend_exit_zero(self):
        proc = self.cli('trend', '--metrics-file', str(self.metrics_file))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('暂无指标', proc.stdout)

        proc_json = self.cli('trend', '--metrics-file', str(self.metrics_file),
                             '--json')
        self.assertEqual(proc_json.returncode, 0, proc_json.stderr)
        payload = json.loads(proc_json.stdout)
        self.assertFalse(payload['available'])
        self.assertEqual(payload['alerts'], [])

    def test_empty_history_unavailable(self):
        self.write_metrics([])
        self.assertFalse(metrics.load_trend(str(self.metrics_file))['available'])
        proc = self.cli('trend', '--metrics-file', str(self.metrics_file), '--json')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(json.loads(proc.stdout)['available'])

    def test_bad_json_degrades(self):
        self.write_raw_metrics('{"history": [')
        self.assertFalse(metrics.load_trend(str(self.metrics_file))['available'])
        proc = self.cli('trend', '--metrics-file', str(self.metrics_file))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('暂无指标', proc.stdout)
        # 坏 JSON 之后 record 按新建处理，不崩溃
        self.write_change('gate-review.md', [reviewer_marker('A', 'pass', 1)])
        self.assertEqual(self.record().returncode, 0)
        self.assertEqual(self.read_metrics()['recorded_count'], 1)

    def test_available_trend_cli_json(self):
        self.write_metrics([trend_entry('c1', 'A'), trend_entry('c2', 'B'),
                            trend_entry('c3', 'C')])
        proc = self.cli('trend', '--metrics-file', str(self.metrics_file), '--json')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload['available'])
        self.assertEqual(payload['ratings'], ['A', 'B', 'C'])
        self.assertEqual([alert['rule'] for alert in payload['alerts']],
                         ['rating_decline'])


# ─── ⑨ 原子写 ───────────────────────────────────────────────────────────────


class AtomicWriteTests(MetricsSandboxTestCase):
    """用例 ⑨：mkstemp + os.replace 写入，落盘文件权限 600。"""

    def test_recorded_file_mode_is_600(self):
        self.write_change('gate-review.md', [reviewer_marker('A', 'pass', 1)])
        proc = self.record()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        mode = stat.S_IMODE(os.stat(self.metrics_file).st_mode)
        self.assertEqual(mode, 0o600)

    def test_existing_wider_mode_is_tightened(self):
        self.write_metrics([trend_entry('old', 'B')])
        os.chmod(self.metrics_file, 0o644)
        self.write_change('gate-review.md', [reviewer_marker('A', 'pass', 1)])
        proc = self.record()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(stat.S_IMODE(os.stat(self.metrics_file).st_mode), 0o600)
        # 原子写不残留临时文件
        leftovers = list(self.memory.glob('.metrics-*'))
        self.assertEqual(leftovers, [])


# ─── ⑩ display / run_summary 集成 ───────────────────────────────────────────


class DisplayRunSummaryIntegrationTests(MetricsSandboxTestCase):
    """用例 ⑩：有指标 → 质量趋势段（含告警）；import 失败/无数据 → 省略不崩。"""

    def setUp(self):
        super().setUp()
        self.display = load_lib_module(DISPLAY_SCRIPT, 'display_trend_test')
        self.summary = load_lib_module(RUN_SUMMARY_SCRIPT, 'run_summary_trend_test')
        self.write_metrics([trend_entry('c1', 'A'), trend_entry('c2', 'B'),
                            trend_entry('c3', 'C')])
        self.state = self.tmp / 'state' / 'start-state.json'
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text(json.dumps({
            'agent_calls_used': 2,
            'change_id': 'c3',
            'completed_steps': [],
            'current_step': '3.1',
            'max_agent_calls': 10,
            'status': 'in_progress',
        }), encoding='utf-8')

    def _env(self, **overrides):
        values = {
            'BUDGET_METRICS_FILE': str(self.metrics_file),
            'BUDGET_GUARD_FILE': str(self.guard_file),
        }
        values.update(overrides)
        return mock.patch.dict(os.environ, values)

    def _summary_argv(self) -> list[str]:
        return ['run_summary', '--state-file', str(self.state),
                '--guard-file', str(self.guard_file)]

    def test_display_text_shows_trend_with_alert(self):
        with self._env():
            data = self.display.collect()
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.display.render_text(data)
        self.assertEqual(data['trend']['ratings'], ['A', 'B', 'C'])
        output = buffer.getvalue()
        self.assertIn('── 质量趋势 ──', output)
        self.assertIn('评分序列:    A → B → C', output)
        self.assertIn('⚠ 退化趋势', output)

    def test_display_main_exit_zero_with_trend(self):
        buffer = io.StringIO()
        with self._env(), mock.patch.object(sys, 'argv', ['display', '--json']), \
                contextlib.redirect_stdout(buffer):
            code = self.display.main()
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual([alert['rule'] for alert in payload['trend']['alerts']],
                         ['rating_decline'])

    def test_run_summary_markdown_shows_trend(self):
        with self._env():
            trend = self.summary._metrics_trend()
        text = self.summary.render_markdown(
            'c3', 'start',
            {'agent_calls_used': 2, 'completed_steps': [], 'current_step': '3.1',
             'max_agent_calls': 10, 'status': 'in_progress'},
            str(self.state), {'total': 0, 'by_agent': {}},
            {'available': False, 'path': str(self.guard_file)}, trend)
        self.assertIn('## 质量趋势', text)
        self.assertIn('评分序列: A → B → C', text)
        self.assertIn('⚠ 退化趋势', text)

    def test_run_summary_main_exit_zero_with_trend(self):
        buffer = io.StringIO()
        with self._env(), mock.patch.object(sys, 'argv', self._summary_argv()), \
                contextlib.redirect_stdout(buffer):
            code = self.summary.main()
        self.assertEqual(code, 0)
        self.assertIn('## 质量趋势', buffer.getvalue())

    def test_import_failure_degrades_without_trend(self):
        with mock.patch.dict(sys.modules, {'metrics': None}), self._env():
            data = self.display.collect()
            self.assertNotIn('trend', data)
            display_buffer = io.StringIO()
            with contextlib.redirect_stdout(display_buffer):
                self.display.render_text(data)
            self.assertIsNone(self.summary._metrics_trend())
            summary_buffer = io.StringIO()
            with mock.patch.object(sys, 'argv', ['display', '--json']), \
                    contextlib.redirect_stdout(io.StringIO()):
                display_code = self.display.main()
            with mock.patch.object(sys, 'argv', self._summary_argv()), \
                    contextlib.redirect_stdout(summary_buffer):
                summary_code = self.summary.main()
        self.assertNotIn('质量趋势', display_buffer.getvalue())
        self.assertNotIn('## 质量趋势', summary_buffer.getvalue())
        self.assertIn('## 概览', summary_buffer.getvalue())
        self.assertEqual(display_code, 0)
        self.assertEqual(summary_code, 0)

    def test_missing_metrics_omits_trend_section(self):
        missing = self.tmp / 'nope' / 'metrics.json'
        with self._env(**{'BUDGET_METRICS_FILE': str(missing)}):
            data = self.display.collect()
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.display.render_text(data)
        self.assertNotIn('trend', data)
        self.assertNotIn('质量趋势', buffer.getvalue())


# ─── ⑪ recorder 流程静态断言 ───────────────────────────────────────────────


class RecorderFlowStaticTests(unittest.TestCase):
    """用例 ⑪：phases.md Step 5/6 与 reviewer 定义的标记约定静态核对。"""

    @classmethod
    def setUpClass(cls):
        cls.phases = PHASES_MD.read_text(encoding='utf-8')

    def test_step5_requires_rating_and_verdict_marker(self):
        step5 = self.phases.split('### Step 5', 1)[1].split('### Step 6', 1)[0]
        self.assertIn('评分', step5)
        self.assertIn('budget-verdict', step5)
        self.assertIn('round: 0', step5)

    def test_step6_requires_metrics_record(self):
        step6 = self.phases.split('### Step 6', 1)[1]
        self.assertIn('metrics.py record', step6)
        self.assertIn('--phase2-rating', step6)
        self.assertIn('--reviewer-b', step6)

    def test_reviewer_definitions_have_marker_section(self):
        for path in (REVIEWER_MD, REVIEWER_B_MD):
            with self.subTest(path=path.name):
                text = path.read_text(encoding='utf-8')
                self.assertIn('### 结构化标记', text)
                self.assertIn('budget-verdict', text)


# ─── ⑫ sandbox 隔离 ─────────────────────────────────────────────────────────


class SandboxIsolationTests(MetricsSandboxTestCase):
    """用例 ⑫：默认路径全部落在隔离 HOME 内，不触碰真实 ~/.budgetbuddy。"""

    def test_default_paths_stay_inside_sandbox_home(self):
        real_home = Path(os.path.expanduser('~'))
        real_memory = real_home / '.budgetbuddy' / 'projects' / self.work.name / 'memory'
        preexisting = real_memory.exists()
        self.write_change('gate-review.md', [reviewer_marker('A', 'pass', 1)])

        proc = self.cli('record', '--change-id', 'iso-1',
                        '--change-dir', str(self.change_dir), cwd=self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sandbox_metrics = (self.home / '.budgetbuddy' / 'projects' / self.work.name
                           / 'memory' / 'metrics.json')
        self.assertTrue(sandbox_metrics.is_file())
        if not preexisting:
            self.assertFalse(real_memory.exists(),
                             '真实 ~/.budgetbuddy 被写入: %s' % real_memory)


if __name__ == '__main__':
    unittest.main()
