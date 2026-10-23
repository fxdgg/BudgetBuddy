#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""guard_metrics 保鲜与置信单测（openspec guard-freshness-confidence task 2.1）。

被测对象（单一实现源 + 四个读取面）:
  - core/lib/guard_metrics.py：load_metrics / _env_positive_float / CLI
  - core/lib/guard.sh：guard_query 判定模式保鲜段、guard_summary 概览段
  - core/lib/display.py / core/lib/run_summary.py：延迟 import 容错与 freshness 键

驱动方式: Python 侧 import 直调与 sys.executable CLI 端到端（参照
tests/test_validate.py:344/424-479）；bash 侧参照 tests/test_guard.py
（source colors.sh + guard.sh，临时目录项目区 + 隔离 HOME + 剥离 BUDGET_*）。
全程不触碰真实 ~/.budgetbuddy。

用例编号对应 tasks.md 2.1 的 ①-⑬（⑬ 为既有 tests/test_guard.py 的全量回归，
由 `unittest discover -s tests` 覆盖，本文件不重复实现）。
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
LIB_DIR = REPO_ROOT / 'core' / 'lib'
GUARD_SCRIPT = LIB_DIR / 'guard.sh'
COLORS_SCRIPT = LIB_DIR / 'colors.sh'
METRICS_SCRIPT = LIB_DIR / 'guard_metrics.py'
DISPLAY_SCRIPT = LIB_DIR / 'display.py'
RUN_SUMMARY_SCRIPT = LIB_DIR / 'run_summary.py'

# 写入端 timestamp 格式（guard.sh guard_append 段）
TS_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
SECONDS_PER_DAY = 86400.0

# 固定时间基准（now 注入用；脱离真实时钟，结果可复现）
FIXED_NOW = datetime(2026, 10, 23, 0, 0, 0, tzinfo=timezone.utc)

# 置信档中文标签（数据层输出 low/medium/high，读取端渲染中文）
CONF_LABEL = {'low': '低', 'medium': '中', 'high': '高'}

# 单组合 JSON 键（design D4；两形态一致）
SINGLE_KEYS = {
    'coder', 'tags', 'n_eff', 'weighted_failures', 'weighted_success_rate',
    'confidence', 'stale', 'newest_age_days', 'half_life_days', 'matched',
}

# 固定渲染格式正则（guard.sh _guard_render_metrics / display / run_summary）
RE_N_EFF_LINE = re.compile(r'保鲜: n_eff=([\d.]+)（半衰期 [\d.]+d）')
RE_CONF_LINE = re.compile(r'^置信: (低|中|高)$', re.MULTILINE)
RE_STALE_LINE = re.compile(r'^陈旧: (是|否)$', re.MULTILINE)
RE_PER_CODER_LINE = re.compile(
    r'^\s+(\S+): n_eff=([\d.]+) / 置信: (低|中|高) / 陈旧: (是|否)$', re.MULTILINE)

sys.path.insert(0, str(LIB_DIR))
import guard_metrics  # noqa: E402  pylint: disable=wrong-import-position

sys.path.remove(str(LIB_DIR))

HALF_LIFE = guard_metrics.DEFAULT_HALF_LIFE


# ─── 公共辅助 ────────────────────────────────────────────────────────────────


def iso(dt: datetime) -> str:
    """按写入端格式输出 timestamp（UTC）。"""
    return dt.strftime(TS_FORMAT)


def real_now() -> datetime:
    """真实当前时间（秒级对齐；bash 读取面无法注入 now，需真实时钟）。"""
    return datetime.now(timezone.utc).replace(microsecond=0)


def age_for_weight(weight: float) -> float:
    """反解权重对应年龄：w = 0.5 ** (age / half_life)。"""
    return -HALF_LIFE * math.log2(weight)


def make_entry(coder: str, result: str, age_days: float = 0.0, tags=None,
               now: datetime = FIXED_NOW) -> dict:
    """构造 history 条目（age_days 相对 now，秒级精度对齐写入端格式）。"""
    timestamp = now - timedelta(seconds=round(age_days * SECONDS_PER_DAY))
    return {
        'coder': coder,
        'escalated_to': None,
        'result': result,
        'tags': list(tags or []),
        'timestamp': iso(timestamp),
    }


@contextlib.contextmanager
def clean_guard_env(**overrides):
    """临时清空 BUDGET_GUARD_* 环境变量并可注入覆盖值（用例间隔离）。"""
    saved = {key: os.environ[key] for key in list(os.environ)
             if key.startswith('BUDGET_GUARD_')}
    for key in saved:
        del os.environ[key]
    os.environ.update({key: str(value) for key, value in overrides.items()})
    try:
        yield
    finally:
        for key in [key for key in os.environ if key.startswith('BUDGET_GUARD_')]:
            del os.environ[key]
        os.environ.update(saved)


def cli_env(**overrides) -> dict:
    """构造 CLI 子进程环境（剥离 BUDGET_* 后注入覆盖值）。"""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('BUDGET_')}
    env.update({key: str(value) for key, value in overrides.items()})
    return env


def run_cli(args, extra_env=None):
    """执行 guard_metrics.py CLI（sys.executable 端到端）。"""
    return subprocess.run(
        [sys.executable, str(METRICS_SCRIPT), *args],
        env=cli_env(**(extra_env or {})),
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )


def run_bash(script, cwd, home, extra_env=None):
    """在指定 cwd/HOME 下运行 bash（剥离 BUDGET_* 与会话注入变量实现隔离）。"""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('BUDGET_') and key not in ('BASH_ENV', 'CODEBUDDY_SESSION_ID')}
    env['HOME'] = str(home)
    env.update(extra_env or {})
    return subprocess.run(
        ['bash', '-c', script], cwd=str(cwd), env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )


def load_lib_module(path: Path, name: str):
    """按文件路径加载 core/lib 模块（display / run_summary，避免 sys.path 污染）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cli_tuple(payload: dict) -> dict:
    """CLI JSON → 渲染层显示口径（两位小数 + 中文置信/陈旧）。"""
    return {
        'n_eff': '%.2f' % payload.get('n_eff', 0.0),
        'confidence': CONF_LABEL.get(payload.get('confidence'), str(payload.get('confidence'))),
        'stale': '是' if payload.get('stale') else '否',
    }


def parse_single_freshness(output: str) -> dict:
    """从 guard_query 判定模式输出提取保鲜段（固定渲染格式正则）。"""
    n_eff_match = RE_N_EFF_LINE.search(output)
    conf_match = RE_CONF_LINE.search(output)
    stale_match = RE_STALE_LINE.search(output)
    if not (n_eff_match and conf_match and stale_match):
        raise AssertionError('保鲜段缺失/格式不符: %r' % output)
    return {
        'n_eff': n_eff_match.group(1),
        'confidence': conf_match.group(1),
        'stale': stale_match.group(1),
    }


def parse_per_coder_freshness(output: str) -> dict:
    """从概览/summary 输出提取 per-coder 保鲜行（固定渲染格式正则）。"""
    return {
        match.group(1): {
            'n_eff': match.group(2),
            'confidence': match.group(3),
            'stale': match.group(4),
        }
        for match in RE_PER_CODER_LINE.finditer(output)
    }


class SandboxTestCase(unittest.TestCase):
    """公共沙箱：临时目录项目区 + 隔离 HOME（不触碰真实 ~/.budgetbuddy）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-guard-metrics-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    # ── 记录文件与调用辅助 ─────────────────────────────────────────────

    def guard_path(self) -> Path:
        """guard.sh guard_file_path 预期路径（无 git 时 project-name = cwd 目录名）。"""
        return (self.home / '.budgetbuddy' / 'projects' / self.work.name
                / 'memory' / 'coder-guard.json')

    def write_guard(self, entries, summary=None, path=None) -> Path:
        """写入 coder-guard.json（缺失目录自动创建）。"""
        target = Path(path) if path else self.guard_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {'history': entries, 'summary': summary or {}}
        target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True),
                          encoding='utf-8')
        return target

    def run_guard(self, script):
        """source colors.sh + guard.sh 后执行片段（budget_print_* 依赖就位）。"""
        full = 'source "%s"; source "%s"; %s' % (COLORS_SCRIPT, GUARD_SCRIPT, script)
        return run_bash(full, self.work, self.home)

    def metrics(self, entries, coder=None, tags=None, now=FIXED_NOW, env=None):
        """落盘 history 后调用 load_metrics（now 注入 + 环境变量隔离）。"""
        target = self.write_guard(entries)
        with clean_guard_env(**(env or {})):
            return guard_metrics.load_metrics(
                str(target), coder=coder, tags=tags, now=now)

    def cli_payload(self, coder, path=None, extra_env=None) -> dict:
        """CLI --coder X --json 基准值。"""
        target = Path(path) if path else self.guard_path()
        proc = run_cli(['--file', str(target), '--coder', coder, '--json'], extra_env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip())

    def cli_per_coder(self, path=None, extra_env=None) -> dict:
        """CLI 无 coder 的 per-coder 列表形态。"""
        target = Path(path) if path else self.guard_path()
        proc = run_cli(['--file', str(target), '--json'], extra_env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip())


# ─── ① 半衰期数学 ────────────────────────────────────────────────────────────


class HalfLifeMathTests(SandboxTestCase):
    """用例 ①：权重 0/30/90 天 → 1.0/0.5/0.125，n_eff 聚合正确。"""

    def test_half_life_weights_at_0_30_90_days(self):
        """单条记录 age=0/30/90 天 → 权重 1.0/0.5/0.125（容差 1e-9）。"""
        for age_days, expected in ((0, 1.0), (30, 0.5), (90, 0.125)):
            with self.subTest(age_days=age_days):
                result = self.metrics([make_entry('coder-x', 'success', age_days)],
                                      coder='coder-x')
                self.assertAlmostEqual(result['n_eff'], expected, delta=1e-9)
                self.assertEqual(result['half_life_days'], 30)
                self.assertEqual(result['matched'], 1)

    def test_n_eff_aggregates_weighted_entries(self):
        """2 条当天 + 1 条 30 天前失败 → n_eff=2.5、加权失败=0.5、成功率=0.8。"""
        entries = [
            make_entry('coder-x', 'success', 0),
            make_entry('coder-x', 'success', 0),
            make_entry('coder-x', 'failure', 30),
        ]
        result = self.metrics(entries, coder='coder-x')
        self.assertAlmostEqual(result['n_eff'], 2.5, delta=1e-9)
        self.assertAlmostEqual(result['weighted_failures'], 0.5, delta=1e-9)
        self.assertAlmostEqual(result['weighted_success_rate'], 0.8, delta=1e-9)
        self.assertEqual(result['newest_age_days'], 0.0)
        self.assertEqual(result['matched'], 3)


# ─── ② 置信档边界 ────────────────────────────────────────────────────────────


class ConfidenceBoundaryTests(SandboxTestCase):
    """用例 ②：n_eff 1.9/2.0/3.9/4.0 → low/medium/medium/high。"""

    def _entries_with_weight(self, weight: float, base_count: int) -> list[dict]:
        """base_count 条当天（权重 1.0）+ 1 条反解权重 weight 的记录。"""
        entries = [make_entry('coder-x', 'success', 0) for _ in range(base_count)]
        entries.append(make_entry('coder-x', 'success', age_for_weight(weight)))
        return entries

    def test_n_eff_1_9_low(self):
        """n_eff≈1.9（< 2）→ 低置信。"""
        result = self.metrics(self._entries_with_weight(0.9, 1), coder='coder-x')
        self.assertAlmostEqual(result['n_eff'], 1.9, delta=1e-3)
        self.assertEqual(result['confidence'], 'low')

    def test_n_eff_2_0_medium(self):
        """n_eff=2.0（阈值下界含）→ 中置信。"""
        result = self.metrics([make_entry('coder-x', 'success', 0) for _ in range(2)],
                              coder='coder-x')
        self.assertAlmostEqual(result['n_eff'], 2.0, delta=1e-9)
        self.assertEqual(result['confidence'], 'medium')

    def test_n_eff_3_9_medium(self):
        """n_eff≈3.9（< 4）→ 中置信。"""
        result = self.metrics(self._entries_with_weight(0.9, 3), coder='coder-x')
        self.assertAlmostEqual(result['n_eff'], 3.9, delta=1e-3)
        self.assertEqual(result['confidence'], 'medium')

    def test_n_eff_4_0_high(self):
        """n_eff=4.0（阈值下界含）→ 高置信。"""
        result = self.metrics([make_entry('coder-x', 'success', 0) for _ in range(4)],
                              coder='coder-x')
        self.assertAlmostEqual(result['n_eff'], 4.0, delta=1e-9)
        self.assertEqual(result['confidence'], 'high')


# ─── ③ 陈旧标注边界 ──────────────────────────────────────────────────────────


class StaleBoundaryTests(SandboxTestCase):
    """用例 ③：最新记录 91 天 → stale；90 天 → 不 stale（阈值边界）。"""

    def test_91_days_marks_stale(self):
        result = self.metrics([make_entry('coder-x', 'success', 91)], coder='coder-x')
        self.assertTrue(result['stale'])
        self.assertAlmostEqual(result['newest_age_days'], 91.0, delta=1e-3)

    def test_90_days_not_stale(self):
        """90 天恰在阈值上（>90 才陈旧）。"""
        result = self.metrics([make_entry('coder-x', 'success', 90)], coder='coder-x')
        self.assertFalse(result['stale'])
        self.assertAlmostEqual(result['newest_age_days'], 90.0, delta=1e-3)

    def test_stale_uses_newest_entry_only(self):
        """陈旧判定取最新可解析条目（旧条目多也不 stale）。"""
        result = self.metrics([
            make_entry('coder-x', 'success', 200),
            make_entry('coder-x', 'success', 10),
        ], coder='coder-x')
        self.assertFalse(result['stale'])
        self.assertAlmostEqual(result['newest_age_days'], 10.0, delta=1e-3)


# ─── ④ 样本不足独立触发（bash 集成）────────────────────────────────────────


class SampleShortageWarningTests(SandboxTestCase):
    """用例 ④：单条 1 天前记录（n_eff≈1<2、stale=false）→ 仍出「仅供参考」。"""

    def test_single_recent_record_marks_reference_only(self):
        now = real_now()
        self.write_guard([make_entry('coder-lite', 'success', 1, ['api_endpoint'], now=now)])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('样本不足', proc.stdout)
        self.assertIn('陈旧: 否', proc.stdout)
        self.assertIn('仅供参考', proc.stdout)
        freshness = parse_single_freshness(proc.stdout)
        self.assertEqual(freshness['confidence'], '低')
        self.assertEqual(freshness['stale'], '否')
        self.assertLess(float(freshness['n_eff']), 2.0)
        # 保鲜段在判定行之后
        self.assertLess(proc.stdout.index('判定:'), proc.stdout.index('保鲜:'))


# ─── ⑤ timestamp 容错 ────────────────────────────────────────────────────────


class TimestampToleranceTests(SandboxTestCase):
    """用例 ⑤：缺失/坏格式 timestamp 权重 0，不影响 newest_age_days。"""

    def test_bad_timestamps_zero_weight(self):
        good = make_entry('coder-x', 'success', 2)
        bad_entries = [
            {'coder': 'coder-x', 'escalated_to': None, 'result': 'failure', 'tags': []},
            {'coder': 'coder-x', 'result': 'success', 'tags': [],
             'timestamp': '2026/10/23 00:00:00'},
            {'coder': 'coder-x', 'result': 'success', 'tags': [], 'timestamp': ''},
            {'coder': 'coder-x', 'result': 'success', 'tags': [], 'timestamp': 1730000000},
        ]
        result = self.metrics([good] + bad_entries, coder='coder-x')
        # 仅好条目贡献权重（0.5 ** (2/30)），坏条目权重 0
        self.assertAlmostEqual(result['n_eff'], 0.5 ** (2 / HALF_LIFE), delta=1e-4)
        self.assertEqual(result['weighted_failures'], 0.0)
        # matched 仍统计全部匹配条目（口径为过滤后条数）
        self.assertEqual(result['matched'], 5)
        # newest_age_days 由好条目决定
        self.assertAlmostEqual(result['newest_age_days'], 2.0, delta=1e-3)
        self.assertFalse(result['stale'])

    def test_only_bad_timestamps_yield_zero_sample(self):
        """全部坏 timestamp → n_eff=0、低置信、无 newest_age_days。"""
        result = self.metrics([
            {'coder': 'coder-x', 'result': 'success', 'tags': [], 'timestamp': 'bad'},
        ], coder='coder-x')
        self.assertEqual(result['n_eff'], 0.0)
        self.assertEqual(result['confidence'], 'low')
        self.assertIsNone(result['newest_age_days'])
        self.assertFalse(result['stale'])
        self.assertEqual(result['matched'], 1)


# ─── ⑥ coder×tag 交集、隔离与空数据 ────────────────────────────────────────


class CoderTagFilterTests(SandboxTestCase):
    """用例 ⑥：coder×tag 交集过滤、各 coder 独立统计、空 history/缺文件、now 注入。"""

    def _history(self) -> list[dict]:
        return [
            make_entry('coder-a', 'failure', 0, ['api_endpoint']),
            make_entry('coder-a', 'success', 0, ['api_endpoint', 'docs_only']),
            make_entry('coder-a', 'success', 0, ['docs_only']),
            make_entry('coder-b', 'failure', 0, ['api_endpoint']),
        ]

    def test_tag_intersection_filters_entries(self):
        """coder-a × api_endpoint → 2 条（含多 tag 条目），加权失败 1.0。"""
        result = self.metrics(self._history(), coder='coder-a', tags=['api_endpoint'])
        self.assertEqual(result['matched'], 2)
        self.assertAlmostEqual(result['n_eff'], 2.0, delta=1e-9)
        self.assertAlmostEqual(result['weighted_failures'], 1.0, delta=1e-9)
        self.assertEqual(result['tags'], ['api_endpoint'])

    def test_tags_accept_comma_string(self):
        """tags 支持逗号字符串形态（CLI/环境变量口径一致）。"""
        result = self.metrics(self._history(), coder='coder-a', tags='api_endpoint,docs_only')
        self.assertEqual(result['matched'], 3)
        self.assertAlmostEqual(result['n_eff'], 3.0, delta=1e-9)

    def test_coders_are_isolated(self):
        """无 tag 全量口径按 coder 隔离统计。"""
        history = self._history()
        result_a = self.metrics(history, coder='coder-a')
        result_b = self.metrics(history, coder='coder-b', tags=['api_endpoint'])
        self.assertEqual(result_a['matched'], 3)
        self.assertAlmostEqual(result_a['n_eff'], 3.0, delta=1e-9)
        self.assertEqual(result_b['matched'], 1)
        self.assertAlmostEqual(result_b['n_eff'], 1.0, delta=1e-9)
        self.assertEqual(result_b['confidence'], 'low')

    def test_empty_history_zeros(self):
        """空 history → n_eff=0/low/matched=0；per-coder 形态 available 且空列表。"""
        self.write_guard([])
        with clean_guard_env():
            single = guard_metrics.load_metrics(str(self.guard_path()), coder='coder-a',
                                                now=FIXED_NOW)
            everything = guard_metrics.load_metrics(str(self.guard_path()), coder=None,
                                                    now=FIXED_NOW)
        self.assertEqual(single['n_eff'], 0.0)
        self.assertEqual(single['confidence'], 'low')
        self.assertEqual(single['matched'], 0)
        self.assertIsNone(single['newest_age_days'])
        self.assertFalse(single['stale'])
        self.assertEqual(everything, {'available': True, 'per_coder': []})

    def test_missing_file_zeros(self):
        """缺文件 → 单组合零值；per-coder 形态 available=False。"""
        missing = str(self.tmp / 'no-such-guard.json')
        with clean_guard_env():
            single = guard_metrics.load_metrics(missing, coder='coder-a', now=FIXED_NOW)
            everything = guard_metrics.load_metrics(missing, coder=None, now=FIXED_NOW)
        self.assertEqual(single['n_eff'], 0.0)
        self.assertEqual(single['confidence'], 'low')
        self.assertEqual(single['matched'], 0)
        self.assertEqual(everything, {'available': False, 'per_coder': []})

    def test_per_coder_sorted_by_name(self):
        """per-coder 列表按 coder 名字典序（与 summary 输出一致）。"""
        result = self.metrics([
            make_entry('coder-senior', 'success', 0),
            make_entry('coder-lite', 'success', 0),
            make_entry('coder-lite', 'success', 0),
        ], coder=None)
        self.assertTrue(result['available'])
        self.assertEqual([item['coder'] for item in result['per_coder']],
                         ['coder-lite', 'coder-senior'])
        self.assertAlmostEqual(result['per_coder'][0]['n_eff'], 2.0, delta=1e-9)
        self.assertAlmostEqual(result['per_coder'][1]['n_eff'], 1.0, delta=1e-9)


# ─── ⑦ 环境变量非法回退 ────────────────────────────────────────────────────


class EnvFallbackTests(SandboxTestCase):
    """用例 ⑦：半衰期/陈旧天数非法值（含超大数）回退默认，CLI 退出码 0。"""

    INVALID_VALUES = ('abc', '0', '-5', '1e309')

    def test_invalid_half_life_values_fallback(self):
        self.write_guard([make_entry('coder-x', 'success', 0, now=real_now())])
        for value in self.INVALID_VALUES:
            with self.subTest(value=value):
                proc = run_cli(
                    ['--file', str(self.guard_path()), '--coder', 'coder-x', '--json'],
                    {'BUDGET_GUARD_HALF_LIFE_DAYS': value})
                self.assertEqual(proc.returncode, 0, proc.stderr)
                payload = json.loads(proc.stdout.strip())
                self.assertEqual(payload['half_life_days'], 30)
                # 当天记录权重 1.0（秒级容差；CLI 以真实时钟计算年龄）
                self.assertAlmostEqual(payload['n_eff'], 1.0, delta=1e-3)
                self.assertIn('回退默认', proc.stderr)

    def test_invalid_stale_days_values_fallback(self):
        self.write_guard([make_entry('coder-x', 'success', 100, now=real_now())])
        for value in self.INVALID_VALUES:
            with self.subTest(value=value):
                proc = run_cli(
                    ['--file', str(self.guard_path()), '--coder', 'coder-x', '--json'],
                    {'BUDGET_GUARD_STALE_DAYS': value})
                self.assertEqual(proc.returncode, 0, proc.stderr)
                payload = json.loads(proc.stdout.strip())
                # 回退默认 90 → 100 天记录仍判陈旧
                self.assertTrue(payload['stale'])
                self.assertEqual(payload['half_life_days'], 30)
                self.assertIn('回退默认', proc.stderr)

    def test_valid_env_override_applied(self):
        """合法覆盖生效（半衰期 60 → 30 天前权重 0.5**0.5）。"""
        self.write_guard([make_entry('coder-x', 'success', 30, now=real_now())])
        proc = run_cli(['--file', str(self.guard_path()), '--coder', 'coder-x', '--json'],
                       {'BUDGET_GUARD_HALF_LIFE_DAYS': '60'})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout.strip())
        self.assertEqual(payload['half_life_days'], 60)
        self.assertAlmostEqual(payload['n_eff'], 0.5 ** 0.5, delta=1e-3)


# ─── ⑧ CLI --json 输出键完整性 ──────────────────────────────────────────────


class CliJsonShapeTests(SandboxTestCase):
    """用例 ⑧：单组合全键 / per_coder 列表形态键完整性。"""

    def setUp(self):
        super().setUp()
        self.write_guard([
            make_entry('coder-lite', 'failure', 1, ['api_endpoint']),
            make_entry('coder-standard', 'success', 2, ['docs_only']),
        ])

    def test_single_coder_payload_has_all_keys(self):
        payload = self.cli_payload('coder-lite')
        self.assertEqual(set(payload), SINGLE_KEYS)
        self.assertEqual(payload['coder'], 'coder-lite')
        self.assertIn(payload['confidence'], CONF_LABEL)
        self.assertIsInstance(payload['stale'], bool)
        self.assertEqual(payload['matched'], 1)

    def test_per_coder_payload_shape(self):
        payload = self.cli_per_coder()
        self.assertEqual(set(payload), {'available', 'per_coder'})
        self.assertTrue(payload['available'])
        self.assertEqual([item['coder'] for item in payload['per_coder']],
                         ['coder-lite', 'coder-standard'])
        for item in payload['per_coder']:
            self.assertEqual(set(item), SINGLE_KEYS)


# ─── ⑨ import 容错 ──────────────────────────────────────────────────────────


class ImportToleranceTests(SandboxTestCase):
    """用例 ⑨：guard_metrics 不可用时 display/run_summary 不崩、结构回退。"""

    def setUp(self):
        super().setUp()
        self.target = self.write_guard([
            make_entry('coder-lite', 'failure', 1, ['api_endpoint'], now=real_now()),
            make_entry('coder-standard', 'success', 2, ['api_endpoint'], now=real_now()),
        ])
        self.display = load_lib_module(DISPLAY_SCRIPT, 'display_under_test')
        self.run_summary = load_lib_module(RUN_SUMMARY_SCRIPT, 'run_summary_under_test')

    def _display_section(self) -> dict:
        with mock.patch.dict(os.environ, {'BUDGET_GUARD_FILE': str(self.target)}):
            return self.display.guard_section()

    def test_display_and_run_summary_baseline_have_freshness(self):
        """集成生效时：display/run_summary 均带 freshness（每 coder 一行数据）。"""
        section = self._display_section()
        self.assertTrue(section['available'])
        self.assertEqual([item['coder'] for item in section['freshness']],
                         ['coder-lite', 'coder-standard'])
        summary = self.run_summary.guard_section(str(self.target))
        self.assertEqual([item['coder'] for item in summary['freshness']],
                         ['coder-lite', 'coder-standard'])

    def test_display_section_survives_missing_module(self):
        """模拟 guard_metrics 不可用（sys.modules 置 None）→ 无 freshness 键、其余不变。"""
        baseline = self._display_section()
        with mock.patch.dict(sys.modules, {'guard_metrics': None}):
            section = self._display_section()
        self.assertNotIn('freshness', section)
        self.assertEqual(section['available'], True)
        self.assertEqual(section['total'], baseline['total'])
        self.assertEqual(section['failures'], baseline['failures'])
        self.assertEqual(section['escalations'], baseline['escalations'])
        self.assertEqual(section['recent'], baseline['recent'])

    def test_run_summary_section_survives_missing_module(self):
        with mock.patch.dict(sys.modules, {'guard_metrics': None}):
            section = self.run_summary.guard_section(str(self.target))
        self.assertNotIn('freshness', section)
        self.assertEqual(section['available'], True)
        self.assertEqual(section['total'], 2)
        self.assertEqual(section['failures'], 1)

    def test_sections_survive_metrics_failure(self):
        """guard_metrics.load_metrics 抛异常（非 ImportError）同样降级不展示。"""
        broken = types.ModuleType('guard_metrics')

        def boom(*args, **kwargs):
            raise RuntimeError('boom')

        broken.load_metrics = boom
        with mock.patch.dict(sys.modules, {'guard_metrics': broken}):
            display_section = self._display_section()
            summary_section = self.run_summary.guard_section(str(self.target))
        self.assertNotIn('freshness', display_section)
        self.assertNotIn('freshness', summary_section)
        self.assertTrue(display_section['available'])
        self.assertTrue(summary_section['available'])


# ─── ⑩ 跨读取面一致性（无 tag 全量口径）────────────────────────────────────


class CrossSurfaceConsistencyTests(SandboxTestCase):
    """用例 ⑩：CLI 基准 == guard_query == guard_summary == display == run_summary。"""

    def setUp(self):
        super().setUp()
        now = real_now()
        self.target = self.write_guard([
            make_entry('coder-lite', 'failure', 2, ['api_endpoint'], now=now),
            make_entry('coder-lite', 'success', 2, ['api_endpoint'], now=now),
            make_entry('coder-lite', 'success', 20, ['docs_only'], now=now),
            make_entry('coder-lite', 'success', 45, ['api_endpoint'], now=now),
            make_entry('coder-standard', 'success', 120, ['api_endpoint'], now=now),
        ])
        self.display = load_lib_module(DISPLAY_SCRIPT, 'display_under_test')
        self.run_summary = load_lib_module(RUN_SUMMARY_SCRIPT, 'run_summary_under_test')

    def _display_freshness(self) -> dict:
        with mock.patch.dict(os.environ, {'BUDGET_GUARD_FILE': str(self.target)}):
            section = self.display.guard_section()
        return {
            item['coder']: {
                'n_eff': '%.2f' % item['n_eff'],
                'confidence': CONF_LABEL.get(item['confidence'], item['confidence']),
                'stale': '是' if item['stale'] else '否',
            }
            for item in section['freshness']
        }

    def _run_summary_freshness(self) -> dict:
        section = self.run_summary.guard_section(str(self.target))
        return {
            item['coder']: {
                'n_eff': '%.2f' % item['n_eff'],
                'confidence': CONF_LABEL.get(item['confidence'], item['confidence']),
                'stale': '是' if item['stale'] else '否',
            }
            for item in section['freshness']
        }

    def test_four_surfaces_agree_per_coder(self):
        cli_lite = self.cli_payload('coder-lite', self.target)
        cli_standard = self.cli_payload('coder-standard', self.target)
        baseline = {'coder-lite': cli_tuple(cli_lite), 'coder-standard': cli_tuple(cli_standard)}

        # guard_query 判定模式（不带 tag = coder 全量口径）
        for coder in ('coder-lite', 'coder-standard'):
            proc = self.run_guard('guard_query %s' % coder)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(parse_single_freshness(proc.stdout), baseline[coder],
                             'guard_query 与 CLI 不一致: %s' % coder)

        # guard_summary 概览段
        proc = self.run_guard('guard_summary')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        summary_freshness = parse_per_coder_freshness(proc.stdout)
        self.assertEqual(summary_freshness, baseline)
        self.assertIn('历史记录: 5 条', proc.stdout)

        # guard_query 概览模式（无 coder）per-coder 列表
        proc = self.run_guard('guard_query')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(parse_per_coder_freshness(proc.stdout), baseline)

        # display.py / run_summary.py 的 freshness 键
        self.assertEqual(self._display_freshness(), baseline)
        self.assertEqual(self._run_summary_freshness(), baseline)

    def test_per_coder_cli_matches_single_coder_cli(self):
        """CLI 两形态同源：per_coder 列表值 == 单组合查询值。"""
        per_coder = {item['coder']: item for item in self.cli_per_coder(self.target)['per_coder']}
        for coder in ('coder-lite', 'coder-standard'):
            single = self.cli_payload(coder, self.target)
            self.assertEqual(per_coder[coder]['n_eff'], single['n_eff'])
            self.assertEqual(per_coder[coder]['confidence'], single['confidence'])
            self.assertEqual(per_coder[coder]['stale'], single['stale'])

    def test_stale_and_low_confidence_propagate(self):
        """120 天记录在四端一致呈现「低置信 + 陈旧」。"""
        self.assertEqual(cli_tuple(self.cli_payload('coder-standard', self.target)),
                         {'n_eff': '0.06', 'confidence': '低', 'stale': '是'})
        proc = self.run_guard('guard_query coder-standard')
        self.assertEqual(parse_single_freshness(proc.stdout),
                         {'n_eff': '0.06', 'confidence': '低', 'stale': '是'})
        self.assertEqual(self._display_freshness()['coder-standard'],
                         {'n_eff': '0.06', 'confidence': '低', 'stale': '是'})


# ─── ⑪ guard_query 集成（硬规则文案不变）────────────────────────────────────


class GuardQueryIntegrationTests(SandboxTestCase):
    """用例 ⑪：硬规则判定文案逐字不变，保鲜段出现在判定行之后。"""

    def test_hard_rule_text_unchanged_with_freshness(self):
        now = real_now()
        entries = [
            make_entry('coder-lite', 'failure', 4, ['api_endpoint'], now=now),
            make_entry('coder-lite', 'failure', 3, ['api_endpoint'], now=now),
            make_entry('coder-lite', 'success', 2, ['api_endpoint'], now=now),
            make_entry('coder-lite', 'success', 1, ['api_endpoint'], now=now),
            make_entry('coder-lite', 'success', 0, ['api_endpoint'], now=now),
        ]
        self.write_guard(entries)
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('触发降级保护，建议改派 coder-standard', proc.stdout)
        self.assertIn('置信: 高', proc.stdout)
        self.assertIn('陈旧: 否', proc.stdout)
        # 保鲜段在判定行之后，且新鲜高置信不附加参考提示
        self.assertLess(proc.stdout.index('判定:'), proc.stdout.index('保鲜:'))
        self.assertNotIn('仅供参考', proc.stdout)

    def test_stale_records_still_degrade_with_reference_hint(self):
        """陈旧记录（n_eff<2 且 stale）仍触发硬规则降级，仅追加参考提示。"""
        now = real_now()
        entries = [
            make_entry('coder-lite', 'failure', 200, ['api_endpoint'], now=now),
            make_entry('coder-lite', 'failure', 201, ['api_endpoint'], now=now),
            make_entry('coder-lite', 'success', 202, ['api_endpoint'], now=now),
            make_entry('coder-lite', 'success', 203, ['api_endpoint'], now=now),
            make_entry('coder-lite', 'success', 204, ['api_endpoint'], now=now),
        ]
        self.write_guard(entries)
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('触发降级保护，建议改派 coder-standard', proc.stdout)
        self.assertIn('⚠ 记录陈旧/样本不足，降级建议仅供参考', proc.stdout)
        freshness = parse_single_freshness(proc.stdout)
        self.assertEqual(freshness['confidence'], '低')
        self.assertEqual(freshness['stale'], '是')


# ─── ⑫ lib 模块计数回归 ────────────────────────────────────────────────────


class LibModuleCountTests(unittest.TestCase):
    """用例 ⑫：core/lib/ 的 .sh + .py 共 27 个模块，六组枚举文件齐全。"""

    def _actual_modules(self) -> set[str]:
        return {path.name for pattern in ('*.sh', '*.py') for path in LIB_DIR.glob(pattern)}

    def test_module_count_is_27(self):
        modules = self._actual_modules()
        self.assertEqual(len(modules), 27)
        self.assertEqual(len(list(LIB_DIR.glob('*.sh'))), 16)
        self.assertEqual(len(list(LIB_DIR.glob('*.py'))), 11)
        self.assertTrue(METRICS_SCRIPT.is_file())

    def test_six_group_enumeration_complete(self):
        """六组归组（design D5）：4+3+7+5+5+3 = 27。"""
        groups = {
            '基础层': {'colors.sh', 'utils.sh', 'platform.sh', 'shell.sh'},
            '生命周期': {'init.sh', 'update.sh', 'uninstall.sh'},
            '模型与护栏': {'models.sh', 'preset.sh', 'model_resolver.py', 'guard.sh',
                          'guard_metrics.py', 'rtk.sh', 'ocr-setup.py'},
            'persona 与校验': {'persona.sh', 'persona_expand.py', 'validate.sh',
                           'budget-state.py', 'display.py'},
            '交互与汇总': {'interactive.sh', 'quickstart.py', 'run_summary.py',
                         'banner.py', 'autorun.py'},
            '通知与 hooks': {'notify.sh', 'hooks.sh', 'hooks_inject.py'},
        }
        enumerated = set().union(*groups.values())
        self.assertEqual(sum(len(files) for files in groups.values()), 27)
        self.assertEqual(enumerated, self._actual_modules())


if __name__ == '__main__':
    unittest.main()
