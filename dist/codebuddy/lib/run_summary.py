#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy 变更完成摘要生成（design.md §8.2「交互与汇总」组）。

读工作流状态机（指定 change-id 或 find 活跃）与 Coder Guard 记录，生成
markdown 摘要输出到 stdout（供 recorder 归档复用）。摘要内容: 变更 ID /
模式与状态 / 时间线 / Agent 调用统计（状态计数 + 委派日志分布）/ 完成步骤 /
失败与降级史。

状态文件定位（与 budget-state.py find 语义一致）:
  --state-file 显式路径 > openspec/changes/<change-id>/{start,goal}-state.json
  > find 活跃（goal in_progress 优先，start current_step 非空非 archived 兜底）

Coder Guard 记录: --guard-file 显式覆盖 >
  ~/.budgetbuddy/projects/<project-name>/memory/coder-guard.json
  （project-name = git 根目录名，无 git 退 basename(cwd)，与 guard.sh 一致）

用法:
  python3 run_summary.py [change-id] [--state-file PATH] [--guard-file PATH]

退出码: 0 成功（摘要输出 stdout）；1 未找到状态文件 / 状态文件损坏。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import NoReturn

GOAL_STATE_FILENAME = 'goal-state.json'
START_STATE_FILENAME = 'start-state.json'
RECENT_LIMIT = 5

# 置信档中文标签（数据层 guard_metrics.py 输出英文机器值 low/medium/high）
CONF_LABEL = {'low': '低', 'medium': '中', 'high': '高'}


def fail(message: str, hint: str | None = None) -> NoReturn:
    """stderr 输出错误 JSON（键排序）并以退出码 1 终止。"""
    payload = {'error': message}
    if hint:
        payload['hint'] = hint
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    sys.exit(1)


def load_json_quiet(path: str) -> dict | None:
    """容错加载 JSON 文件（缺失/格式错误/非对象 → None，不终止）。"""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_json_strict(path: str, label: str) -> dict:
    """严格加载 JSON 文件（缺失/格式错误/非对象 → fail 终止）。"""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError:
        fail(f'{label} 不存在: {path}')
    except (OSError, ValueError) as exc:
        fail(f'{label} 读取失败: {path}（{exc}）')
    if not isinstance(data, dict):
        fail(f'{label} 顶层必须是 JSON 对象: {path}')
    return data


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
    """Coder Guard 记录路径（固定全局路径，design.md §8.4 跨会话汇总）。"""
    home = os.path.expanduser('~')
    return os.path.join(
        home, '.budgetbuddy', 'projects', project_name(), 'memory', 'coder-guard.json')


# ─── 状态文件定位 ────────────────────────────────────────────────────────


def find_active_state(changes_dir: str) -> tuple[str | None, str]:
    """查找活跃状态文件（goal in_progress 优先 > 任意 goal > start 非归档）。"""
    if not os.path.isdir(changes_dir):
        return None, ''
    fallback: str | None = None
    for name in sorted(os.listdir(changes_dir)):
        path = os.path.join(changes_dir, name, GOAL_STATE_FILENAME)
        if not os.path.isfile(path):
            continue
        data = load_json_quiet(path)
        if data is None:
            continue
        if data.get('status') == 'in_progress':
            return path, 'goal'
        if fallback is None:
            fallback = path
    if fallback is not None:
        return fallback, 'goal'
    for name in sorted(os.listdir(changes_dir)):
        path = os.path.join(changes_dir, name, START_STATE_FILENAME)
        if not os.path.isfile(path):
            continue
        data = load_json_quiet(path)
        if data is None:
            continue
        if data.get('current_step') not in (None, '', 'archived'):
            return path, 'start'
    return None, ''


def locate_state(change_id: str, state_file: str) -> tuple[str, str, dict]:
    """定位并加载状态文件（显式路径 > change-id > find 活跃）。"""
    if state_file:
        mode = 'goal' if GOAL_STATE_FILENAME in os.path.basename(state_file) else 'start'
        return state_file, mode, load_json_strict(state_file, '状态文件')
    changes_dir = os.path.join(os.getcwd(), 'openspec', 'changes')
    if change_id:
        for filename, mode in ((GOAL_STATE_FILENAME, 'goal'), (START_STATE_FILENAME, 'start')):
            path = os.path.join(changes_dir, change_id, filename)
            if os.path.isfile(path):
                return path, mode, load_json_strict(path, '状态文件')
        fail(
            f"变更 '{change_id}' 未找到状态文件",
            f'请确认 openspec/changes/{change_id}/ 下存在 start-state.json 或 goal-state.json',
        )
    path, mode = find_active_state(changes_dir)
    if path is None:
        fail(
            '未找到活跃的状态文件',
            '请指定 change-id，或确认 openspec/changes/ 下存在状态文件',
        )
    return path, mode, load_json_strict(path, '状态文件')


# ─── 数据汇总 ────────────────────────────────────────────────────────────


def dispatch_stats(state_path: str) -> dict:
    """agent_dispatch.log 统计（按 agent_type 计数；文件缺失返回空）。"""
    log_path = os.path.join(os.path.dirname(state_path), 'agent_dispatch.log')
    counts: dict[str, int] = {}
    if os.path.isfile(log_path):
        try:
            with open(log_path, encoding='utf-8') as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(entry, dict):
                        agent = str(entry.get('agent_type', '-'))
                        counts[agent] = counts.get(agent, 0) + 1
        except OSError:
            pass
    return {'by_agent': counts, 'log_path': log_path, 'total': sum(counts.values())}


def guard_section(guard_file: str) -> dict:
    """Coder Guard 失败与降级史（总记录 / 失败 / 降级 / 最近失败条目 + 保鲜）。"""
    data = load_json_quiet(guard_file)
    if data is None:
        return {'available': False, 'path': guard_file}
    history = data.get('history')
    entries = [e for e in history if isinstance(e, dict)] if isinstance(history, list) else []
    failures = [e for e in entries if e.get('result') == 'failure']
    result = {
        'available': True,
        'escalations': sum(1 for e in entries if e.get('escalated_to')),
        'failures': len(failures),
        'path': guard_file,
        'recent_failures': failures[-RECENT_LIMIT:],
        'total': len(entries),
    }
    freshness = _guard_freshness(guard_file)
    if freshness is not None:
        result['freshness'] = freshness
    return result


def _guard_freshness(guard_file: str) -> list[dict] | None:
    """保鲜与置信摘要（延迟导入 guard_metrics；导入/取数失败 → None 不展示）。"""
    try:
        import guard_metrics
    except ImportError:
        return None
    try:
        metrics = guard_metrics.load_metrics(guard_file, coder=None)
    except Exception:
        return None
    if not metrics.get('available'):
        return None
    return [
        {
            'coder': str(item.get('coder', '-')),
            'n_eff': item.get('n_eff', 0.0),
            'confidence': str(item.get('confidence', 'low')),
            'stale': bool(item.get('stale', False)),
        }
        for item in metrics.get('per_coder', [])
    ]


def _metrics_trend() -> dict | None:
    """质量趋势摘要（延迟导入 metrics；导入/取数失败或空态 → None 不展示）。"""
    try:
        import metrics
    except ImportError:
        return None
    try:
        trend = metrics.load_trend()
    except Exception:
        return None
    if not trend.get('available'):
        return None
    return trend


# ─── markdown 渲染 ───────────────────────────────────────────────────────


def render_markdown(change_id: str, mode: str, data: dict, state_path: str,
                    dispatch: dict, guard: dict, trend: dict | None = None) -> str:
    """生成 markdown 摘要文本（概览 / 调用统计 / 完成步骤 / 失败降级史 / 质量趋势）。"""
    lines: list[str] = []
    lines.append(f'# 变更完成摘要: {change_id}')
    lines.append('')
    lines.append('## 概览')
    lines.append('')
    lines.append(f'- 变更 ID: {change_id}')
    lines.append(f'- 模式: {mode}')
    status = data.get('status')
    if status:
        lines.append(f'- 状态: {status}')
    lines.append(f'- 当前步骤: {data.get("current_step") or "-"}')
    lines.append(f'- 时间线: {data.get("created_at") or "-"} → {data.get("updated_at") or "-"}')
    lines.append('')

    lines.append('## Agent 调用统计')
    lines.append('')
    used = data.get('agent_calls_used', 0)
    maximum = data.get('max_agent_calls')
    if maximum is not None:
        lines.append(f'- 调用计数: {used} / {maximum}（agent_calls_used / max_agent_calls）')
    else:
        lines.append(f'- 调用计数: {used}')
    lines.append(f'- 委派日志: {dispatch["total"]} 条（agent_dispatch.log）')
    if dispatch['by_agent']:
        lines.append('')
        lines.append('| Agent | 委派次数 |')
        lines.append('|-------|---------|')
        for agent in sorted(dispatch['by_agent']):
            lines.append(f'| {agent} | {dispatch["by_agent"][agent]} |')
    lines.append('')

    completed = data.get('completed_steps') or []
    lines.append(f'## 完成步骤（{len(completed)}）')
    lines.append('')
    if completed:
        lines.extend(f'- {step}' for step in completed)
    else:
        lines.append('（无）')
    lines.append('')

    lines.append('## Coder Guard 失败与降级史')
    lines.append('')
    if not guard['available']:
        lines.append(f'（无记录: {guard["path"]}）')
    else:
        lines.append(
            f'- 总记录: {guard["total"]}（失败 {guard["failures"]} / 降级 {guard["escalations"]}）')
        if guard['recent_failures']:
            lines.append('- 最近失败记录:')
            for entry in guard['recent_failures']:
                escalated = entry.get('escalated_to')
                suffix = f' → {escalated}' if escalated else ''
                tags = ', '.join(str(t) for t in entry.get('tags') or [])
                tag_suffix = f'（tags: {tags}）' if tags else ''
                lines.append(
                    f'  - {entry.get("timestamp", "-")} {entry.get("coder", "-")}'
                    f'{suffix}{tag_suffix}')
        else:
            lines.append('- 无失败记录')
        freshness = guard.get('freshness')
        if freshness:
            lines.append('- 保鲜与置信:')
            for item in freshness:
                confidence = CONF_LABEL.get(item['confidence'], item['confidence'])
                stale = '是' if item['stale'] else '否'
                lines.append(
                    f"  - {item['coder']}: n_eff={item['n_eff']:.2f} / 置信: {confidence} / 陈旧: {stale}")

    if trend is not None:
        lines.append('')
        lines.append('## 质量趋势')
        lines.append('')
        ratings_text = ' → '.join(
            str(r) if r is not None else '-' for r in trend['ratings'])
        lines.append(f'- 评分序列: {ratings_text}')
        if trend['pass_first_rate'] is not None:
            lines.append(f'- 一次通过率: {trend["pass_first_rate"] * 100:.0f}%')
        else:
            lines.append('- 一次通过率: -')
        if trend['guard_failure_rate'] is not None:
            lines.append(f'- Guard 失败率: {trend["guard_failure_rate"] * 100:.0f}%')
        else:
            lines.append('- Guard 失败率: -')
        for alert in trend['alerts']:
            lines.append(f'- ⚠ {alert["message"]}')

    return '\n'.join(lines) + '\n'


# ─── 参数解析与入口 ──────────────────────────────────────────────────────


class RunSummaryArgumentParser(argparse.ArgumentParser):
    """参数错误统一退出码 1（与业务错误一致）。"""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(
            json.dumps({'error': f'参数错误: {message}'}, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        sys.exit(1)


def build_parser() -> RunSummaryArgumentParser:
    """构造参数解析器（change-id 位置参数 + 显式路径覆盖选项）。"""
    parser = RunSummaryArgumentParser(
        prog='run_summary',
        description='BudgetBuddy 变更完成摘要生成（design.md §8.2）',
    )
    parser.add_argument(
        'change_id', nargs='?',
        help='变更标识（openspec/changes/<change-id>/；缺省查找活跃状态文件）')
    parser.add_argument('--state-file', help='显式状态文件路径')
    parser.add_argument('--guard-file', help='显式 Coder Guard 记录路径')
    return parser


def main() -> int:
    """入口: 定位状态文件 → 汇总数据 → markdown 摘要输出 stdout。"""
    parser = build_parser()
    args = parser.parse_args()
    state_path, mode, data = locate_state(args.change_id, args.state_file)
    change_id = str(data.get('change_id') or os.path.basename(os.path.dirname(state_path)))
    guard_file = args.guard_file or guard_file_path()
    dispatch = dispatch_stats(state_path)
    guard = guard_section(guard_file)
    trend = _metrics_trend()
    print(render_markdown(change_id, mode, data, state_path, dispatch, guard, trend),
          end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
