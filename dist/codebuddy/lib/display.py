#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy 工作流统计展示（budget setup stats，design.md §8.2「persona 与校验」组）。

三类数据源（--json 输出机器可读 JSON，键排序）:
  1. Coder Guard 汇总: ~/.budgetbuddy/projects/<project-name>/memory/
     coder-guard.json（总记录 / 失败 / 降级次数 / 最近 5 条；project-name
     = git 根目录名，无 git 退 basename(cwd)，与 guard.sh 一致）
  2. 工作流状态机: ./openspec/changes/*/{start,goal}-state.json（活跃变更
     / 当前步骤 / agent 调用计数；活跃判定与 budget-state.py find 一致:
     goal in_progress 优先，start current_step 非空非 archived 兜底）
  3. 项目形态概览: 平台（BUDGET_PLATFORM_* 环境变量，setup.sh stats 分发
     前探测注入）/ 安装根（BUDGET_SETUP_DIR）/ agent 数（BUDGET_AGENTS_DIR
     扫描 .md）/ 角色主题（persona-active.json）

环境变量（BUDGET_* 前缀；setup.sh 注入或独立执行时自主兜底）:
  BUDGET_PLATFORM_KIND / BUDGET_PLATFORM_SCOPE / BUDGET_AGENTS_DIR /
  BUDGET_SETUP_DIR / BUDGET_GUARD_FILE / BUDGET_PERSONA_ACTIVE / BUDGET_DIR

persona-active.json 定位: BUDGET_PERSONA_ACTIVE 显式 > BUDGET_DIR >
  .budget/ 向上查找（10 层，对齐 utils.sh budget_project_data_dir）>
  ~/.budgetbuddy/

用法: python3 display.py [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

RECENT_LIMIT = 5
STATE_DIR_DEPTH = 10

# 置信档中文标签（数据层 guard_metrics.py 输出英文机器值 low/medium/high）
CONF_LABEL = {'low': '低', 'medium': '中', 'high': '高'}


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


def load_json_quiet(path: str) -> dict | None:
    """容错加载 JSON 文件（缺失/格式错误/非对象 → None，不终止）。"""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ─── 数据源 1: Coder Guard 汇总 ──────────────────────────────────────────


def guard_section() -> dict:
    """Coder Guard 汇总（总记录 / 失败 / 降级 / 最近 5 条 + 保鲜与置信）。"""
    path = guard_file_path()
    data = load_json_quiet(path)
    if data is None:
        return {'available': False, 'path': path}
    history = data.get('history')
    entries = [e for e in history if isinstance(e, dict)] if isinstance(history, list) else []
    result = {
        'available': True,
        'escalations': sum(1 for e in entries if e.get('escalated_to')),
        'failures': sum(1 for e in entries if e.get('result') == 'failure'),
        'path': path,
        'recent': [
            {
                'coder': str(e.get('coder', '-')),
                'escalated_to': e.get('escalated_to'),
                'result': str(e.get('result', '-')),
                'tags': [str(t) for t in e.get('tags') or []],
                'timestamp': str(e.get('timestamp', '-')),
            }
            for e in entries[-RECENT_LIMIT:]
        ],
        'total': len(entries),
    }
    freshness = _guard_freshness(path)
    if freshness is not None:
        result['freshness'] = freshness
    return result


def _guard_freshness(path: str) -> list[dict] | None:
    """保鲜与置信摘要（延迟导入 guard_metrics；导入/取数失败 → None 不展示）。"""
    try:
        import guard_metrics
    except ImportError:
        return None
    try:
        metrics = guard_metrics.load_metrics(path, coder=None)
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


# ─── 数据源 2: 工作流状态机 ──────────────────────────────────────────────


def scan_changes() -> list[dict]:
    """扫描 openspec/changes/ 下全部状态文件（goal 优先于 start）。"""
    changes_dir = os.path.join(os.getcwd(), 'openspec', 'changes')
    result: list[dict] = []
    if not os.path.isdir(changes_dir):
        return result
    for name in sorted(os.listdir(changes_dir)):
        for filename, mode in (('goal-state.json', 'goal'), ('start-state.json', 'start')):
            state_path = os.path.join(changes_dir, name, filename)
            if not os.path.isfile(state_path):
                continue
            data = load_json_quiet(state_path)
            if data is None:
                continue
            result.append({
                'agent_calls_used': data.get('agent_calls_used', 0),
                'change_id': str(data.get('change_id') or name),
                'completed_steps': len(data.get('completed_steps') or []),
                'current_step': data.get('current_step', ''),
                'max_agent_calls': data.get('max_agent_calls'),
                'mode': mode,
                'path': state_path,
                'status': data.get('status', ''),
            })
            break
    return result


def active_change(changes: list[dict]) -> dict | None:
    """活跃变更: goal in_progress 优先 > 任意 goal > start 非归档（对齐 find）。"""
    goals = [c for c in changes if c['mode'] == 'goal']
    for change in goals:
        if change.get('status') == 'in_progress':
            return change
    if goals:
        return goals[0]
    for change in changes:
        if change['mode'] == 'start' and change.get('current_step') not in (None, '', 'archived'):
            return change
    return None


# ─── 数据源 3: 项目形态概览 ──────────────────────────────────────────────


def persona_active_path() -> str:
    """persona-active.json 定位（显式 > BUDGET_DIR > .budget/ 向上 > 全局）。"""
    override = os.environ.get('BUDGET_PERSONA_ACTIVE', '')
    if override:
        return override
    budget_dir = os.environ.get('BUDGET_DIR', '')
    if budget_dir:
        return os.path.join(budget_dir, 'persona-active.json')
    current = os.getcwd()
    for _ in range(STATE_DIR_DEPTH):
        candidate = os.path.join(current, '.budget', 'persona-active.json')
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.path.join(os.path.expanduser('~'), '.budgetbuddy', 'persona-active.json')


def persona_section() -> dict:
    """角色主题（theme + greeting；无 active 文件时 default）。"""
    path = persona_active_path()
    data = load_json_quiet(path) if os.path.isfile(path) else None
    if data is None:
        return {'greeting': '', 'theme': 'default'}
    return {
        'greeting': str(data.get('greeting', '')),
        'theme': str(data.get('theme', 'default')),
    }


def platform_section() -> dict:
    """项目形态概览（平台 / 安装根 / agent 数 / 主题）。"""
    kind = os.environ.get('BUDGET_PLATFORM_KIND', 'unknown')
    scope = os.environ.get('BUDGET_PLATFORM_SCOPE', '')
    agents_dir = os.environ.get('BUDGET_AGENTS_DIR', '')
    agent_count = 0
    if agents_dir and os.path.isdir(agents_dir):
        agent_count = sum(
            1 for name in os.listdir(agents_dir)
            if name.endswith('.md') and os.path.isfile(os.path.join(agents_dir, name)))
    persona = persona_section()
    return {
        'agents': agent_count,
        'greeting': persona['greeting'],
        'platform': f'{kind}:{scope}' if scope else kind,
        'setup_dir': os.environ.get('BUDGET_SETUP_DIR', ''),
        'theme': persona['theme'],
    }


# ─── 汇总与渲染 ──────────────────────────────────────────────────────────


def collect() -> dict:
    """汇总三类数据源（guard / state / project）。"""
    changes = scan_changes()
    return {
        'guard': guard_section(),
        'project': platform_section(),
        'state': {
            'active': active_change(changes),
            'changes': changes,
        },
    }


def _change_line(change: dict) -> str:
    """变更行摘要（change_id · 模式 · 步骤 · 调用 used/max）。"""
    used = change.get('agent_calls_used', 0)
    maximum = change.get('max_agent_calls')
    calls = f'{used}/{maximum}' if maximum is not None else str(used)
    return f"{change['change_id']}（{change['mode']} · {change.get('current_step') or '-'} · 调用 {calls}）"


def render_text(data: dict) -> None:
    """文本表格输出（guard / state / project 三段）。"""
    project = data['project']
    print('BudgetBuddy 工作流统计')
    print()
    print('── 项目形态 ──')
    print('平台:        %s' % project['platform'])
    if project['setup_dir']:
        print('安装根:      %s' % project['setup_dir'])
    print('Agent 数:    %d' % project['agents'])
    theme_line = '角色主题:    %s' % project['theme']
    if project['greeting']:
        theme_line += '（%s）' % project['greeting']
    print(theme_line)
    print()

    guard = data['guard']
    print('── Coder Guard 护栏 ──')
    print('记录文件:    %s' % guard['path'])
    if not guard['available']:
        print('暂无记录（工作流执行后自动生成）')
    else:
        print('总记录:      %d 次（失败 %d / 降级 %d）' % (
            guard['total'], guard['failures'], guard['escalations']))
        if guard['recent']:
            print('最近 %d 条:' % len(guard['recent']))
            for entry in guard['recent']:
                escalated = ' → %s' % entry['escalated_to'] if entry['escalated_to'] else ''
                print('  %s  %-14s %-8s%s' % (
                    entry['timestamp'], entry['coder'], entry['result'], escalated))
        freshness = guard.get('freshness')
        if freshness:
            print('保鲜与置信:')
            for item in freshness:
                confidence = CONF_LABEL.get(item['confidence'], item['confidence'])
                stale = '是' if item['stale'] else '否'
                print('  %s: n_eff=%.2f / 置信: %s / 陈旧: %s' % (
                    item['coder'], item['n_eff'], confidence, stale))
    print()

    state = data['state']
    print('── 工作流状态机 ──')
    if state['active'] is None:
        print('无活跃工作流状态（未启动或已归档）')
    else:
        print('活跃变更:    %s' % _change_line(state['active']))
    print('变更总数:    %d 个' % len(state['changes']))
    for change in state['changes']:
        print('  - %s' % _change_line(change))


def render_json(data: dict) -> None:
    """JSON 输出（键排序，机器可读）。"""
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))


def main() -> int:
    """入口: --json 机器可读 / 默认文本表格。"""
    parser = argparse.ArgumentParser(
        prog='display',
        description='BudgetBuddy 工作流统计（design.md §8.2）',
    )
    parser.add_argument('--json', action='store_true', help='JSON 输出（键排序）')
    args = parser.parse_args()
    data = collect()
    if args.json:
        render_json(data)
    else:
        render_text(data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
