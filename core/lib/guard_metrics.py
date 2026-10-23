#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy Coder Guard 保鲜与置信统计 — guard_metrics（design.md D4）。

对 coder-guard.json 做读取时的时间加权统计，供四个读取面复用（单一实现源）：
guard.sh guard_query / guard_summary（子进程 CLI 形态）、display.py、run_summary.py
（同目录 import 形态）。

统计口径（design D4）:
  ① 指数半衰期权重 w = 0.5 ** (age_days / half_life)，默认 half_life = 30 天，
     BUDGET_GUARD_HALF_LIFE_DAYS 环境变量覆盖（非法值回退默认并 stderr 提示）。
  ② n_eff（有效样本数）= 匹配条目权重之和；加权失败数 / 加权成功率（成功率
     = 加权成功 / n_eff，n_eff = 0 时 0.0）。
  ③ 置信档 = f(n_eff)：n_eff < 2 → low / < 4 → medium / ≥ 4 → high。
  ④ 陈旧标注：该组合最新可解析记录年龄 > 90 天（BUDGET_GUARD_STALE_DAYS 覆盖，
     与半衰期两参数独立不联动）。
  ⑤ timestamp 按写入端格式 %Y-%m-%dT%H:%M:%SZ 解析；缺失/无法解析的条目权重
     按 0 且不参与 newest_age_days（陈旧判定只用可解析条目）。

返回形态（design D4）:
  - coder 指定 → 单组合 dict
  - coder=None → {'available': bool, 'per_coder': [<单组合 dict>, ...]}（coder
    名字典序；available 对齐 display.py 既有不可用语义）

输出 JSON 键（两形态一致）: {coder, tags, n_eff, weighted_failures,
weighted_success_rate, confidence, stale, newest_age_days, half_life_days,
matched}。置信档取 low/medium/high 英文机器值，中文标签由各读取端渲染。

环境变量:
  BUDGET_GUARD_HALF_LIFE_DAYS（半衰期天数，默认 30，非法回退 + stderr 提示）
  BUDGET_GUARD_STALE_DAYS（陈旧阈值天数，默认 90，非法回退 + stderr 提示）
  BUDGET_GUARD_FILE（guard.json 路径，CLI 形态兼容 guard.sh 先例）

退出码: 0 成功（含文件缺失 / 空 history / 环境变量非法回退等降级场景）；
1 错误（guard.json 解析失败 / 缺少文件路径参数）。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

# ─── 常量 ─────────────────────────────────────────────────────────────────────

# 半衰期默认天数（design D1）
DEFAULT_HALF_LIFE = 30

# 陈旧阈值默认天数（design D2，与半衰期两参数独立）
DEFAULT_STALE_DAYS = 90

# 写入端 timestamp 格式（guard.sh guard_append 段）
TS_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

# 每天秒数（age_days 换算）
SECONDS_PER_DAY = 86400.0

# 置信档英文机器值（中文标签由读取端渲染，design D4）
CONFIDENCE_LOW = 'low'
CONFIDENCE_MEDIUM = 'medium'
CONFIDENCE_HIGH = 'high'


class GuardParseError(Exception):
    """guard.json 解析失败（文件存在但 JSON 非法或顶层非对象）。"""


# ─── 环境变量与时间解析 ───────────────────────────────────────────────────────


def _env_positive_float(name: str, default: float) -> float:
    """读取正数环境变量；缺失回退默认，非法（非数/非有限/非正）回退默认并 stderr 提示。"""
    raw = os.environ.get(name, '')
    if raw == '':
        return default
    try:
        value = float(raw)
    except ValueError:
        print('警告: %s 非法值 %r，回退默认 %s' % (name, raw, default), file=sys.stderr)
        return default
    if not math.isfinite(value) or value <= 0:
        print('警告: %s 需为正数，收到 %r，回退默认 %s' % (name, raw, default), file=sys.stderr)
        return default
    return value


def _as_utc(dt: datetime) -> datetime:
    """把 datetime 归一为 UTC 时区（naive 视为 UTC，对齐写入端无后缀时间戳）。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    """解析写入端 timestamp；缺失/非字符串/格式非法 → None（权重按 0，不参与陈旧判定）。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _normalize_tags(tags: object) -> list[str] | None:
    """归一化 tags（None/空 → None；str 按逗号拆分；可迭代去重保序）。"""
    if tags is None:
        return None
    if isinstance(tags, str):
        items = [item.strip() for item in tags.split(',') if item.strip()]
    else:
        items = [str(item).strip() for item in tags if str(item).strip()]
    return items or None


# ─── 文件读取 ────────────────────────────────────────────────────────────────


def _read_history(guard_file: str) -> list[dict]:
    """读取 history 列表；文件缺失返回 []；JSON 非法/顶层非对象抛 GuardParseError。"""
    if not os.path.isfile(guard_file):
        return []
    try:
        with open(guard_file, encoding='utf-8') as handle:
            data = json.load(handle)
    except OSError as exc:
        raise GuardParseError('guard 记录读取失败: %s（%s）' % (guard_file, exc))
    except ValueError as exc:
        raise GuardParseError('guard 记录解析失败: %s（%s）' % (guard_file, exc))
    if not isinstance(data, dict):
        raise GuardParseError('guard 记录顶层必须是 JSON 对象: %s' % guard_file)
    history = data.get('history')
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


# ─── 置信档 ───────────────────────────────────────────────────────────────────


def _confidence(n_eff: float) -> str:
    """置信档：n_eff < 2 low / < 4 medium / ≥ 4 high（design D2）。"""
    if n_eff < 2:
        return CONFIDENCE_LOW
    if n_eff < 4:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_HIGH


# ─── 单组合统计 ───────────────────────────────────────────────────────────────


def _compute_one(history: list[dict], coder: str, tags: list[str] | None,
                 half_life: float, stale_days: float, now: datetime) -> dict:
    """计算单个 coder（×可选 tags 交集）的加权统计（design D4 输出键）。"""
    matched = [entry for entry in history if entry.get('coder') == coder]
    if tags:
        wanted = set(tags)
        matched = [entry for entry in matched if set(entry.get('tags') or []) & wanted]

    n_eff = 0.0
    weighted_failures = 0.0
    weighted_successes = 0.0
    newest_age_days: float | None = None

    for entry in matched:
        parsed = _parse_timestamp(entry.get('timestamp'))
        if parsed is None:
            continue
        age_days = max(0.0, (now - parsed).total_seconds() / SECONDS_PER_DAY)
        weight = 0.5 ** (age_days / half_life)
        n_eff += weight
        if entry.get('result') == 'failure':
            weighted_failures += weight
        elif entry.get('result') == 'success':
            weighted_successes += weight
        if newest_age_days is None or age_days < newest_age_days:
            newest_age_days = age_days

    stale = newest_age_days is not None and newest_age_days > stale_days
    weighted_success_rate = weighted_successes / n_eff if n_eff > 0 else 0.0

    return {
        'coder': coder,
        'tags': tags,
        'n_eff': round(n_eff, 4),
        'weighted_failures': round(weighted_failures, 4),
        'weighted_success_rate': round(weighted_success_rate, 4),
        'confidence': _confidence(n_eff),
        'stale': stale,
        'newest_age_days': round(newest_age_days, 4) if newest_age_days is not None else None,
        'half_life_days': half_life,
        'matched': len(matched),
    }


# ─── 对外主入口 ───────────────────────────────────────────────────────────────


def load_metrics(guard_file: str, coder: str | None = None, tags: object = None,
                 now: datetime | None = None) -> dict:
    """计算 coder-guard 保鲜与置信统计（design D4）。

    coder 指定 → 单组合 dict；coder=None → {'available': bool, 'per_coder': [...]}
    （按 coder 名字典序）。now 可注入供单测固定时间基准。
    """
    half_life = _env_positive_float('BUDGET_GUARD_HALF_LIFE_DAYS', DEFAULT_HALF_LIFE)
    stale_days = _env_positive_float('BUDGET_GUARD_STALE_DAYS', DEFAULT_STALE_DAYS)
    now = _as_utc(now if now is not None else datetime.now(timezone.utc))
    tags_list = _normalize_tags(tags)

    if coder is None:
        if not os.path.isfile(guard_file):
            return {'available': False, 'per_coder': []}
        history = _read_history(guard_file)
        coders = sorted({str(entry.get('coder')) for entry in history if entry.get('coder')})
        return {
            'available': True,
            'per_coder': [
                _compute_one(history, name, None, half_life, stale_days, now)
                for name in coders
            ],
        }

    history = _read_history(guard_file)
    return _compute_one(history, coder, tags_list, half_life, stale_days, now)


# ─── CLI ──────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器（--file/--coder/--tags/--json）。"""
    parser = argparse.ArgumentParser(
        prog='guard_metrics',
        description='Coder Guard 保鲜与置信统计（design.md D4）',
    )
    parser.add_argument('--file', help='guard.json 路径（缺省用 BUDGET_GUARD_FILE）')
    parser.add_argument('--coder', help='coder 名（缺省返回 per-coder 列表）')
    parser.add_argument('--tags', help='逗号分隔 tag 列表（仅 coder 指定时参与交集过滤）')
    parser.add_argument('--json', action='store_true', help='JSON 输出（键排序）')
    return parser


def _render_text(result: dict, coder: str | None) -> None:
    """非 --json 的人类可读输出（单组合三行 / per-coder 列表每行）。"""
    conf_label = {CONFIDENCE_LOW: '低', CONFIDENCE_MEDIUM: '中', CONFIDENCE_HIGH: '高'}
    if coder is not None:
        half_life = result.get('half_life_days', DEFAULT_HALF_LIFE)
        confidence = conf_label.get(result.get('confidence'), str(result.get('confidence')))
        stale = '是' if result.get('stale') else '否'
        print('保鲜: n_eff=%.2f（半衰期 %gd）' % (result.get('n_eff', 0.0), half_life))
        print('置信: %s' % confidence)
        print('陈旧: %s' % stale)
        return
    for item in result.get('per_coder', []):
        confidence = conf_label.get(item.get('confidence'), str(item.get('confidence')))
        stale = '是' if item.get('stale') else '否'
        print('  %s: n_eff=%.2f / 置信: %s / 陈旧: %s' % (
            item.get('coder', '-'), item.get('n_eff', 0.0), confidence, stale))


def main(argv: list[str] | None = None) -> int:
    """入口：加载 guard.json → 计算统计 → JSON/文本输出；解析失败非零退出。"""
    args = build_parser().parse_args(argv)

    guard_file = args.file or os.environ.get('BUDGET_GUARD_FILE', '')
    if not guard_file:
        print('error: 缺少 guard 文件路径（--file 或 BUDGET_GUARD_FILE）', file=sys.stderr)
        return 1

    tags = _normalize_tags(args.tags) if args.tags else None
    coder = args.coder or None

    try:
        result = load_metrics(guard_file, coder=coder, tags=tags)
    except GuardParseError as exc:
        print('error: %s' % exc, file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        _render_text(result, coder)
    return 0


if __name__ == '__main__':
    sys.exit(main())
