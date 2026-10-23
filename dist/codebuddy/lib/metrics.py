#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy 质量指标采集与趋势告警 — metrics（agent-quality-trend design D2-D4）。

从 change 目录递归提取 budget-verdict 结构化标记，聚合 phase2 评分/轮数、
终审评分、reviewer-b 结论，快照 guard.json 全量失败/降级计数，写入
metrics.json；并提供趋势与告警查询面（display.py / run_summary.py 延迟导入）。

标记约定（design D1）:
    reviewer    ``<!-- budget-verdict: {"rating":"A","conclusion":"pass","round":1} -->``
    reviewer-b  ``<!-- budget-verdict: {"conclusion":"fail","round":2} -->``（无 rating 键）
    终审        reviewer 标记 round==0（Phase 4，无轮次语义）
    提取用整行匹配：行首 ``<!-- budget-verdict:`` 且行尾 ``-->``；嵌段落/反引号
    code span 内的示例行（非行首）不匹配；坏 JSON 行跳过并 stderr 提示。

聚合规则（design D2）:
    phase2_rating / phase2_rounds = round 最大且非 0 的 reviewer 标记（同 round
        多文件取文件路径字典序最大者）；final_rating = round==0 标记的 rating
        （缺失记 null）；reviewer_b_conclusion = round 最大的 reviewer-b 标记
        （无 rating 键）；显式 CLI 参数优先于扫描结果。

guard 快照（design D3，全 history 口径，不用 summary）:
    guard_failures = history 中 result=='failure' 条目数；guard_history_total =
        history 总条数（R3 分母）；guard_downgrades = history 中 escalated_to
        非空条目数。

存储（design D3）:
    ``~/.budgetbuddy/projects/<project-name>/memory/metrics.json``，结构
    ``{"history": [{change_id, date, phase2_rating, phase2_rounds,
    reviewer_b_conclusion, final_rating, guard_failures, guard_history_total,
    guard_downgrades}], "recorded_count": N}``；history 追加 + 同 change_id
    幂等覆盖（去重更新非追加）；原子写 mkstemp(0600) + os.replace；文件缺失
    / 坏 JSON 按新建处理。

趋势与告警（design D4）:
    R1 最近 ≥3 条 final_rating 严格连续下降且无 null 中断（A→B→C 告警；
    A→null→B→C 不告警；B→B→C 不告警）；R2 一次通过率（rounds==1 占比，分母
    = 有 phase2_rounds 的条数，分母 0 不计算不告警）< 50%；R3 失败率（最新
    一条快照 guard_failures / guard_history_total，样本 ≥5）> 40%。告警仅
    查询面呈现（不推送通知、不影响任何判定）。

环境变量:
    BUDGET_METRICS_FILE（metrics.json 路径，CLI 形态显式覆盖）
    BUDGET_GUARD_FILE（guard.json 路径，快照读取，对齐 guard_metrics/display 先例）

退出码: 0 成功（含文件缺失 / 空 history / 坏 JSON 降级等空态场景）；1 错误
（缺少必需参数 / metrics.json 写入失败）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

# ─── 常量 ─────────────────────────────────────────────────────────────────────

# 标记整行匹配的固定前缀/后缀（design D1）
VERDICT_PREFIX = '<!-- budget-verdict:'
VERDICT_SUFFIX = '-->'

# 评分档位顺序（A 最高质量，D 最低；R1 用秩比较严格下降）
RATING_ORDER = ('A', 'B', 'C', 'D')

# trend 默认窗口（design D4）
DEFAULT_TREND_LIMIT = 5

# R2 / R3 告警阈值（design D4）
R2_PASS_RATE_THRESHOLD = 0.5
R3_FAILURE_RATE_THRESHOLD = 0.4
R3_MIN_SAMPLE = 5

# 写入端 timestamp 格式（对齐 budget-state.py / guard_metrics.py）
TS_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def now_iso() -> str:
    """当前 UTC 时间（ISO8601，秒精度，对齐 budget-state.py）。"""
    return datetime.now(timezone.utc).strftime(TS_FORMAT)


# ─── 路径解析（对齐 display.py / guard_metrics.py）────────────────────────────


def project_name() -> str:
    """project-name: git 根目录名优先，无 git 退 basename(cwd)（对齐 guard.sh）。"""
    try:
        proc = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=10,
        )
        root = proc.stdout.strip()
        if proc.returncode == 0 and root:
            return os.path.basename(root)
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.basename(os.path.abspath(os.getcwd()))


def guard_file_path() -> str:
    """Coder Guard 记录路径（BUDGET_GUARD_FILE 显式覆盖 > 固定全局路径）。"""
    override = os.environ.get('BUDGET_GUARD_FILE', '')
    if override:
        return override
    home = os.path.expanduser('~')
    return os.path.join(
        home, '.budgetbuddy', 'projects', project_name(), 'memory', 'coder-guard.json')


def metrics_file_path() -> str:
    """metrics.json 路径（BUDGET_METRICS_FILE 显式覆盖 > 固定全局路径）。"""
    override = os.environ.get('BUDGET_METRICS_FILE', '')
    if override:
        return override
    home = os.path.expanduser('~')
    return os.path.join(
        home, '.budgetbuddy', 'projects', project_name(), 'memory', 'metrics.json')


# ─── 标记扫描与聚合 ───────────────────────────────────────────────────────────


def _parse_verdict_line(path: str, line: str) -> tuple[str, dict | None, str | None]:
    """解析单行标记；返回 (status, data, error)。

    status: 'none'（非标记行，含嵌段落/反引号示例行）/ 'bad'（标记前缀但坏 JSON
        或非对象）/ 'ok'（合法标记）。整行匹配：行首前缀且行尾后缀。
    """
    stripped = line.rstrip()
    if not stripped.startswith(VERDICT_PREFIX):
        return 'none', None, None
    if not stripped.endswith(VERDICT_SUFFIX):
        return 'none', None, None
    inner = stripped[len(VERDICT_PREFIX):-len(VERDICT_SUFFIX)].strip()
    try:
        data = json.loads(inner)
    except ValueError as exc:
        return 'bad', None, str(exc)
    if not isinstance(data, dict):
        return 'bad', None, '标记内容不是 JSON 对象'
    return 'ok', data, None


def scan_verdicts(change_dir: str) -> tuple[list[tuple[str, dict]], list[str]]:
    """递归扫描 change 目录 .md 提取全部 budget-verdict 标记。

    os.walk 默认 followlinks=False 防符号链接环；返回 (verdicts, warnings)：
    verdicts 为 [(file_path, data), ...]（扫描顺序）；warnings 为坏 JSON 行提示。
    """
    verdicts: list[tuple[str, dict]] = []
    warnings: list[str] = []
    if not os.path.isdir(change_dir):
        return verdicts, warnings
    for root, _dirs, files in os.walk(change_dir, followlinks=False):
        for name in files:
            if not name.endswith('.md'):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, encoding='utf-8') as handle:
                    lines = handle.readlines()
            except (OSError, UnicodeDecodeError):
                continue
            for line in lines:
                status, data, error = _parse_verdict_line(path, line)
                if status == 'ok':
                    verdicts.append((path, data))
                elif status == 'bad':
                    warnings.append('%s: 坏 JSON 标记行已跳过（%s）' % (path, error))
    return verdicts, warnings


def _round_of(data: dict) -> int | None:
    """提取 round 字段（非 int / bool → None）。"""
    value = data.get('round')
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _pick_max_round(candidates: list[tuple[str, dict]]) -> dict | None:
    """从 (path, data) 列表选 round 最大者；同 round 取文件路径字典序最大。"""
    if not candidates:
        return None
    max_round = max(_round_of(data) for _, data in candidates)
    ties = [(path, data) for path, data in candidates if _round_of(data) == max_round]
    ties.sort(key=lambda item: item[0])
    return ties[-1][1]


def aggregate(verdicts: list[tuple[str, dict]]) -> tuple:
    """聚合标记 → (phase2_rating, phase2_rounds, reviewer_b_conclusion, final_rating)。

    reviewer 标记 = 含 rating 键；reviewer-b 标记 = 无 rating 键。phase2 取 round
    最大且非 0 的 reviewer 标记（同 round 取路径字典序最大）；终审取 round==0 标记
    的 rating（缺失 None）；reviewer-b 取 round 最大标记的 conclusion。
    """
    reviewer = [(path, data) for path, data in verdicts if 'rating' in data]
    reviewer_b = [(path, data) for path, data in verdicts if 'rating' not in data]

    phase2_rating: object = None
    phase2_rounds: object = None
    phase2_candidates = [
        (path, data) for path, data in reviewer
        if _round_of(data) not in (None, 0)
    ]
    if phase2_candidates:
        picked = _pick_max_round(phase2_candidates)
        if picked is not None:
            phase2_rating = picked.get('rating')
            phase2_rounds = _round_of(picked)

    final_rating: object = None
    final_candidates = [(path, data) for path, data in reviewer if _round_of(data) == 0]
    if final_candidates:
        picked = _pick_max_round(final_candidates)
        if picked is not None:
            final_rating = picked.get('rating')

    reviewer_b_conclusion: object = None
    reviewer_b_valid = [
        (path, data) for path, data in reviewer_b if _round_of(data) is not None
    ]
    if reviewer_b_valid:
        picked = _pick_max_round(reviewer_b_valid)
        if picked is not None:
            reviewer_b_conclusion = picked.get('conclusion')

    return phase2_rating, phase2_rounds, reviewer_b_conclusion, final_rating


# ─── guard 快照与文件读写 ─────────────────────────────────────────────────────


def _read_guard_history(guard_file: str) -> list[dict]:
    """读取 guard.json history 列表；缺失/坏 JSON/非对象返回 []（快照不阻断）。"""
    if not os.path.isfile(guard_file):
        return []
    try:
        with open(guard_file, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    history = data.get('history')
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def _guard_snapshot(guard_file: str | None) -> dict:
    """guard 全 history 快照（failures / history_total / downgrades，design D3）。"""
    path = guard_file or guard_file_path()
    history = _read_guard_history(path)
    return {
        'guard_failures': sum(1 for e in history if e.get('result') == 'failure'),
        'guard_history_total': len(history),
        'guard_downgrades': sum(1 for e in history if e.get('escalated_to')),
    }


def _read_history(metrics_file: str) -> list[dict]:
    """读取 metrics.json history 列表；缺失/坏 JSON/非对象返回 []（按新建处理）。"""
    if not os.path.isfile(metrics_file):
        return []
    try:
        with open(metrics_file, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    history = data.get('history')
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def _write_metrics(path: str, data: dict) -> None:
    """原子写 metrics.json（mkstemp + chmod 0600 + os.replace，design D3）。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, sort_keys=True) + '\n'
    fd, tmp_path = tempfile.mkstemp(prefix='.metrics-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except OSError:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _write_record(path: str, change_id: str, phase2_rating: object,
                  phase2_rounds: object, reviewer_b_conclusion: object,
                  final_rating: object, guard: dict) -> dict:
    """追加/幂等覆盖一条记录，返回写入结果 dict（design D2/D3）。"""
    history = _read_history(path)
    entry = {
        'change_id': change_id,
        'date': now_iso(),
        'phase2_rating': phase2_rating,
        'phase2_rounds': phase2_rounds,
        'reviewer_b_conclusion': reviewer_b_conclusion,
        'final_rating': final_rating,
        'guard_failures': guard['guard_failures'],
        'guard_history_total': guard['guard_history_total'],
        'guard_downgrades': guard['guard_downgrades'],
    }
    replaced = False
    for index, existing in enumerate(history):
        if existing.get('change_id') == change_id:
            history[index] = entry
            replaced = True
            break
    if not replaced:
        history.append(entry)
    _write_metrics(path, {'history': history, 'recorded_count': len(history)})
    return {
        'change_id': change_id,
        'path': path,
        'recorded_count': len(history),
        'status': 'recorded',
    }


# ─── 趋势与告警 ───────────────────────────────────────────────────────────────


def _r1_triggered(ratings: list[object]) -> bool:
    """R1 判定：最近 3 条评分严格连续下降且无 null 中断（design D4）。"""
    if len(ratings) < 3:
        return False
    tail = ratings[-3:]
    ranks = []
    for rating in tail:
        if rating not in RATING_ORDER:
            return False  # null 或未知评分 → 中断
        ranks.append(RATING_ORDER.index(rating))
    return ranks[0] < ranks[1] < ranks[2]


def load_trend(metrics_file: str | None = None, limit: int = DEFAULT_TREND_LIMIT) -> dict:
    """读取 metrics.json 计算趋势与告警（design D4）。

    metrics_file 缺省用 metrics_file_path()；limit 为最近 N 条窗口。返回
    {available, path, ratings, pass_first_rate, guard_failure_rate, alerts}；
    文件缺失 / 空 history / 坏 JSON → available False 空态（不崩溃）。
    """
    path = metrics_file or metrics_file_path()
    empty = {
        'available': False,
        'path': path,
        'ratings': [],
        'pass_first_rate': None,
        'guard_failure_rate': None,
        'alerts': [],
    }
    history = _read_history(path)
    if not history:
        return empty

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_TREND_LIMIT
    if limit < 1:
        limit = DEFAULT_TREND_LIMIT
    window = history[-limit:]

    ratings: list[object] = [entry.get('final_rating') for entry in window]

    denominator = 0
    numerator = 0
    for entry in window:
        rounds = entry.get('phase2_rounds')
        if rounds is not None:
            denominator += 1
            if rounds == 1:
                numerator += 1
    pass_first_rate = numerator / denominator if denominator > 0 else None

    latest = history[-1]
    guard_failures = latest.get('guard_failures')
    guard_history_total = latest.get('guard_history_total')
    guard_failure_rate = None
    sample: int | None = None
    if (
        isinstance(guard_failures, (int, float))
        and not isinstance(guard_failures, bool)
        and isinstance(guard_history_total, (int, float))
        and not isinstance(guard_history_total, bool)
        and guard_history_total > 0
    ):
        guard_failure_rate = guard_failures / guard_history_total
        sample = int(guard_history_total)

    alerts: list[dict] = []
    if _r1_triggered(ratings):
        alerts.append({'rule': 'rating_decline', 'message': '退化趋势: 评分连续下降'})
    if pass_first_rate is not None and pass_first_rate < R2_PASS_RATE_THRESHOLD:
        alerts.append({
            'rule': 'pass_first_rate_low',
            'message': '一次通过率低: %.0f%%' % (pass_first_rate * 100),
        })
    if (
        sample is not None
        and sample >= R3_MIN_SAMPLE
        and guard_failure_rate is not None
        and guard_failure_rate > R3_FAILURE_RATE_THRESHOLD
    ):
        alerts.append({
            'rule': 'failure_rate_high',
            'message': '失败率高: %.0f%%' % (guard_failure_rate * 100),
        })

    return {
        'available': True,
        'path': path,
        'ratings': ratings,
        'pass_first_rate': pass_first_rate,
        'guard_failure_rate': guard_failure_rate,
        'alerts': alerts,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────


class MetricsArgumentParser(argparse.ArgumentParser):
    """参数错误统一退出码 1（对齐 budget-state.py，避免 argparse 默认 2）。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(json.dumps({'error': '参数错误: %s' % message},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        sys.exit(1)


def build_parser() -> MetricsArgumentParser:
    """构造子命令解析器（record / trend）。"""
    parser = MetricsArgumentParser(
        prog='metrics',
        description='BudgetBuddy 质量指标采集与趋势告警（agent-quality-trend design D2-D4）',
    )
    sub = parser.add_subparsers(
        dest='command', required=True, parser_class=MetricsArgumentParser)

    p_record = sub.add_parser('record', help='采集 change 目录标记写入 metrics.json')
    p_record.add_argument('--change-id', help='变更标识（openspec change id）')
    p_record.add_argument('--change-dir', help='change 目录路径（递归扫描 .md）')
    p_record.add_argument('--phase2-rating', help='显式 Phase 2 评分（优先于扫描）')
    p_record.add_argument('--phase2-rounds', type=int, help='显式 Phase 2 轮数（优先于扫描）')
    p_record.add_argument('--final-rating', help='显式终审评分（优先于扫描）')
    p_record.add_argument(
        '--reviewer-b', choices=['pass', 'fail'], help='显式 reviewer-b 结论（优先于扫描）')
    p_record.add_argument('--metrics-file', help='metrics.json 路径（覆盖默认，供测试）')
    p_record.add_argument('--guard-file', help='guard.json 路径（覆盖默认，供测试）')
    p_record.set_defaults(func=cmd_record)

    p_trend = sub.add_parser('trend', help='趋势与告警查询')
    p_trend.add_argument('--json', action='store_true', help='JSON 输出（键排序）')
    p_trend.add_argument('--limit', type=int, default=DEFAULT_TREND_LIMIT,
                         help='最近 N 条窗口（默认 %d）' % DEFAULT_TREND_LIMIT)
    p_trend.add_argument('--metrics-file', help='metrics.json 路径（覆盖默认，供测试）')
    p_trend.set_defaults(func=cmd_trend)

    return parser


def cmd_record(args: argparse.Namespace) -> int:
    """record：扫描 → 聚合 → 快照 → 写入 → JSON 输出（显式参数优先于扫描）。"""
    if not args.change_id:
        print('error: 缺少 --change-id', file=sys.stderr)
        return 1
    if not args.change_dir:
        print('error: 缺少 --change-dir', file=sys.stderr)
        return 1

    verdicts, warnings = scan_verdicts(args.change_dir)
    for warning in warnings:
        print(warning, file=sys.stderr)

    phase2_rating, phase2_rounds, reviewer_b_conclusion, final_rating = aggregate(verdicts)
    if args.phase2_rating is not None:
        phase2_rating = args.phase2_rating
    if args.phase2_rounds is not None:
        phase2_rounds = args.phase2_rounds
    if args.final_rating is not None:
        final_rating = args.final_rating
    if args.reviewer_b is not None:
        reviewer_b_conclusion = args.reviewer_b

    guard = _guard_snapshot(args.guard_file)
    path = args.metrics_file or metrics_file_path()
    try:
        result = _write_record(
            path, args.change_id, phase2_rating, phase2_rounds,
            reviewer_b_conclusion, final_rating, guard)
    except OSError as exc:
        print('error: metrics.json 写入失败: %s' % exc, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _render_trend_text(trend: dict) -> None:
    """非 --json 的人类可读输出（评分序列 / 一次通过率 / 失败率 / 告警行）。"""
    if not trend['available']:
        print('暂无指标（metrics.json 缺失或为空）')
        return
    ratings_text = ' → '.join(
        str(r) if r is not None else '-' for r in trend['ratings'])
    print('评分序列:   %s' % ratings_text)
    if trend['pass_first_rate'] is not None:
        print('一次通过率: %.0f%%' % (trend['pass_first_rate'] * 100))
    else:
        print('一次通过率: -')
    if trend['guard_failure_rate'] is not None:
        print('Guard 失败率: %.0f%%' % (trend['guard_failure_rate'] * 100))
    else:
        print('Guard 失败率: -')
    for alert in trend['alerts']:
        print('⚠ %s' % alert['message'])


def cmd_trend(args: argparse.Namespace) -> int:
    """trend：读取 metrics.json → 趋势告警 → JSON/文本输出。"""
    trend = load_trend(metrics_file=args.metrics_file, limit=args.limit)
    if args.json:
        print(json.dumps(trend, ensure_ascii=False, sort_keys=True))
    else:
        _render_trend_text(trend)
    return 0


def main(argv: list[str] | None = None) -> int:
    """入口：解析子命令并分发（record / trend）。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
