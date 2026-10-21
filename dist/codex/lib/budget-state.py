#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy 工作流状态机（全仓单份，design.md §8.2/§12-A4）。

封装 budget workflow 全部固定状态操作，减少 Leader token 消耗。skill 文档
（SKILL.md / phases.md / goal.md）以 ``$HOME/.budgetbuddy/lib/budget-state.py``
固定路径引用本脚本（运行时）；构建期平移至 ``dist/<platform>/lib/``。

状态文件（openspec/changes/ 下按 change 目录隔离）：
    start 模式  ``<change-id>/start-state.json``（SKILL.md 规则 5.4 / start.md，
                7 字段：current_step / change_id / created_at / completed_steps /
                agent_calls_used / max_agent_calls / updated_at）
    goal 模式   ``goal-<slug>/goal-state.json``（goal.md Step 0.3 字段参考，
                含状态锁 / 计数器 / 时间戳全量字段）

子命令（调用签名与工作流文档一致）：
    init        初始化状态文件（start: ``init <change-id>``；goal: ``init --goal <目标>``）
    step        更新 current_step（写锚点，SKILL.md 规则 5）
    get         读取单个字段（JSON 输出）
    set         设置单个字段（智能类型解析）
    post-call   Agent 调用后置位（递增计数 + 状态锁 + completed_steps + 日志）
    dispatch    仅追加 agent_dispatch.log（SKILL.md 规则 6）
    check       安全边界一致性校验（goal.md 安全边界 6 项）
    reset       重置单轮状态锁（递增迭代号，goal.md 精简 Pipeline）
    achieve     标记目标达成
    find        查找活跃状态文件（SKILL.md 规则 5 读锚点）

通用选项：``--state-file`` 显式路径 / ``--mode auto|goal|start`` 查找模式。

输出约定：查询与操作类均输出 JSON（键排序，机器可解析）；错误输出 stderr
JSON。退出码：0 成功（check 全通过）；1 错误；2 check 存在需暂停项。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import NoReturn

GOAL_STATE_FILENAME = 'goal-state.json'
START_STATE_FILENAME = 'start-state.json'
DEFAULT_GOAL_DIR = 'goal-pending'

# start 模式默认值（SKILL.md 规则 5.4 / start.md）
START_DEFAULT_STEP = 'pipeline-running'
START_DEFAULT_MAX_AGENT_CALLS = 60

# goal 模式默认值（goal.md Step 0.1.1 标准 Profile）
GOAL_DEFAULT_STEP = '0.1-clarification'
GOAL_DEFAULT_STEP_FORCE = '0.5-pipeline'
GOAL_DEFAULT_MAX_ITERATIONS = 8
GOAL_DEFAULT_MAX_AGENT_CALLS = 80
GOAL_DEFAULT_NO_PROGRESS_LIMIT = 3
GOAL_DEFAULT_HUMAN_REJECT_LIMIT = 3

# reset 重置的单轮状态锁（goal.md「精简 Pipeline」：9 个字段）。
# director_target_review_done（全局一次性操作）与 human_reject_count（跨迭代
# 持久化）不重置。
RESET_LOCK_FIELDS = {
    'director_dispute_review_done': False,
    'director_dispute_verdict': None,
    'director_final_review_done': False,
    'evaluator_done': False,
    'evaluator_confidence': None,
    'evaluator_reason': None,
    'evaluator_verdict': None,
    'human_director_done': False,
    'human_director_verdict': None,
}

# reset 保留字段（输出报告用）
RESET_KEPT_FIELDS = ['director_target_review_done', 'human_reject_count']


def now_iso() -> str:
    """当前 UTC 时间（ISO8601，秒精度）。"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def emit(payload: dict) -> None:
    """stdout 输出 JSON（键排序，ensure_ascii=False）。"""
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def fail(message: str, hint: str | None = None) -> NoReturn:
    """stderr 输出错误 JSON 并以退出码 1 终止。"""
    payload = {'error': message}
    if hint:
        payload['hint'] = hint
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    sys.exit(1)


def load_json_quiet(path: str) -> dict | None:
    """加载 JSON 文件；失败（不存在/格式错误/IO/非对象）返回 None，不终止。"""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_state_file(mode: str = 'auto') -> tuple[str | None, str | None]:
    """查找活跃状态文件。

    goal 优先（status=in_progress 的 goal-state.json；否则任意 goal-state.json
    兜底），start 兜底（current_step 非空且非 archived 的 start-state.json，
    SKILL.md 规则 5.2 读锚点）。返回 (path, type) 或 (None, None)。
    """
    openspec_dir = os.path.join(os.getcwd(), 'openspec', 'changes')
    if not os.path.isdir(openspec_dir):
        return None, None

    if mode in ('auto', 'goal'):
        fallback: tuple[str, str] | None = None
        for name in sorted(os.listdir(openspec_dir)):
            state_path = os.path.join(openspec_dir, name, GOAL_STATE_FILENAME)
            if not os.path.isfile(state_path):
                continue
            data = load_json_quiet(state_path)
            if data is None:
                continue
            if data.get('status') == 'in_progress':
                return state_path, 'goal'
            if fallback is None:
                fallback = (state_path, 'goal')
        if fallback is not None:
            return fallback

    if mode in ('auto', 'start'):
        for name in sorted(os.listdir(openspec_dir)):
            state_path = os.path.join(openspec_dir, name, START_STATE_FILENAME)
            if not os.path.isfile(state_path):
                continue
            data = load_json_quiet(state_path)
            if data is None:
                continue
            if data.get('current_step') not in (None, '', 'archived'):
                return state_path, 'start'

    return None, None


def get_state_path(explicit_path: str | None = None, mode: str = 'auto') -> tuple[str, str]:
    """定位状态文件（显式路径优先，否则按 mode 查找；未找到终止）。"""
    if explicit_path:
        stype = 'goal' if GOAL_STATE_FILENAME in explicit_path else 'start'
        return explicit_path, stype
    path, stype = find_state_file(mode)
    if path is None:
        fail(
            '未找到活跃的状态文件',
            '请确认在项目根目录执行，且 openspec/changes/ 下存在状态文件',
        )
    return path, stype


def load_state(path: str) -> dict:
    """加载状态文件；失败以退出码 1 终止。"""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError:
        fail(f'状态文件不存在: {path}')
    except (json.JSONDecodeError, OSError) as exc:
        fail(f'状态文件 JSON 格式错误: {exc}')
    if not isinstance(data, dict):
        fail(f'状态文件顶层必须是 JSON 对象: {path}')
    return data


def save_state(path: str, data: dict) -> None:
    """写回状态文件（刷新 updated_at；键排序幂等；临时文件原子替换）。"""
    data['updated_at'] = now_iso()
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write('\n')
    os.replace(tmp_path, path)


def append_dispatch_log(state_path: str, step: str, agent: str, task: str) -> str:
    """向 change 目录追加 agent_dispatch.log（JSON 行，SKILL.md 规则 6）。"""
    log_path = os.path.join(os.path.dirname(state_path), 'agent_dispatch.log')
    entry = {
        'agent_type': agent,
        'step': step,
        'task': task,
        'ts': now_iso(),
    }
    with open(log_path, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + '\n')
    return log_path


# ─── 子命令实现 ──────────────────────────────────────────────────────────


def cmd_init(args: argparse.Namespace) -> None:
    """init：初始化状态文件（start / goal 双模式）。"""
    if args.goal is not None and args.change_id is not None:
        fail('参数冲突: <change-id> 与 --goal 互斥（start 与 goal 两种模式）')
    if args.goal is not None:
        init_goal_state(args)
        return
    if args.change_id is not None:
        init_start_state(args)
        return
    fail(
        '缺少初始化目标',
        "start 模式: init <change-id>；goal 模式: init --goal '<目标描述>'",
    )


def init_goal_state(args: argparse.Namespace) -> None:
    """goal 模式：创建 goal-state.json（goal.md Step 0.1 / Step 0.3）。"""
    target_dir = args.target_dir or os.path.join(
        os.getcwd(), 'openspec', 'changes', DEFAULT_GOAL_DIR)
    os.makedirs(target_dir, exist_ok=True)
    state_path = os.path.join(target_dir, GOAL_STATE_FILENAME)

    if os.path.exists(state_path) and not args.force:
        emit({'hint': '使用 --force 覆盖', 'path': state_path, 'status': 'exists'})
        return

    # --force 覆盖为正式配置时默认进入 pipeline（goal.md Step 0.3）
    default_step = GOAL_DEFAULT_STEP_FORCE if args.force else GOAL_DEFAULT_STEP
    now = now_iso()
    data = {
        'agent_calls_used': 0,
        'completed_steps': [],
        'created_at': now,
        'current_iteration': 0,
        'current_step': args.step or default_step,
        'design_revisions_used': 0,
        'director_dispute_review_done': False,
        'director_dispute_verdict': None,
        'director_final_review': bool(args.director_final_review),
        'director_final_review_done': False,
        'director_target_review_done': False,
        'evaluator_confidence': None,
        'evaluator_done': False,
        'evaluator_reason': None,
        'evaluator_verdict': None,
        'goal': args.goal or '',
        'human_director_done': False,
        'human_director_verdict': None,
        'human_reject_count': 0,
        'human_reject_limit': args.human_reject_limit or GOAL_DEFAULT_HUMAN_REJECT_LIMIT,
        'max_agent_calls': args.max_agent_calls or GOAL_DEFAULT_MAX_AGENT_CALLS,
        'max_iterations': args.max_iterations or GOAL_DEFAULT_MAX_ITERATIONS,
        'no_progress_limit': args.no_progress_limit or GOAL_DEFAULT_NO_PROGRESS_LIMIT,
        'no_progress_streak': 0,
        'status': 'in_progress',
        'stop_after_minutes': args.stop_after_minutes,
        'stop_after_turns': args.stop_after_turns,
        'updated_at': now,
        'verification_results': [],
    }
    save_state(state_path, data)
    emit({'path': state_path, 'status': 'created'})


def init_start_state(args: argparse.Namespace) -> None:
    """start 模式：创建 start-state.json（SKILL.md 规则 5.4 / start.md）。"""
    target_dir = os.path.join(os.getcwd(), 'openspec', 'changes', args.change_id)
    os.makedirs(target_dir, exist_ok=True)
    state_path = os.path.join(target_dir, START_STATE_FILENAME)

    if os.path.exists(state_path) and not args.force:
        emit({'hint': '使用 --force 覆盖', 'path': state_path, 'status': 'exists'})
        return

    now = now_iso()
    data = {
        'agent_calls_used': 0,
        'change_id': args.change_id,
        'completed_steps': [],
        'created_at': now,
        'current_step': args.step or START_DEFAULT_STEP,
        'max_agent_calls': args.max_agent_calls or START_DEFAULT_MAX_AGENT_CALLS,
        'updated_at': now,
    }
    save_state(state_path, data)
    emit({'change_id': args.change_id, 'path': state_path, 'status': 'created'})


def cmd_step(args: argparse.Namespace) -> None:
    """step：更新 current_step（写锚点，SKILL.md 规则 5）。"""
    path, _ = get_state_path(args.state_file, args.mode)
    data = load_state(path)
    data['current_step'] = args.step
    save_state(path, data)
    emit({'current_step': args.step, 'path': path, 'status': 'ok'})


def cmd_get(args: argparse.Namespace) -> None:
    """get：读取单个字段（JSON 输出）。"""
    path, _ = get_state_path(args.state_file, args.mode)
    data = load_state(path)
    emit({'field': args.field, 'value': data.get(args.field)})


def parse_value(raw: str) -> object:
    """解析字段值（bool / null / int / float / JSON 数组对象 / 字符串）。"""
    text = raw.strip()
    lowered = text.lower()
    if lowered == 'true':
        return True
    if lowered == 'false':
        return False
    if lowered == 'null':
        return None
    if text.startswith('[') or text.startswith('{'):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            fail(f'JSON 解析失败: {exc}')
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return raw


def cmd_set(args: argparse.Namespace) -> None:
    """set：设置单个字段（智能类型解析）。"""
    path, _ = get_state_path(args.state_file, args.mode)
    data = load_state(path)
    value = parse_value(args.value)
    data[args.field] = value
    save_state(path, data)
    emit({'field': args.field, 'path': path, 'status': 'ok', 'value': value})


def cmd_post_call(args: argparse.Namespace) -> None:
    """post-call：Agent 调用后置位（计数 + 锁 + extra + completed_steps + 日志）。"""
    path, _ = get_state_path(args.state_file, args.mode)
    data = load_state(path)

    # 递增 agent_calls_used（安全边界检查依赖此计数）
    data['agent_calls_used'] = data.get('agent_calls_used', 0) + 1

    # 设置状态锁字段（如 director_target_review_done）
    locks_set: list[str] = []
    if args.lock:
        data[args.lock] = True
        locks_set.append(args.lock)

    # 写入额外字段（JSON 对象，如 evaluator 判定三字段）
    extras_set: list[str] = []
    if args.extra:
        try:
            extras = json.loads(args.extra)
        except json.JSONDecodeError as exc:
            fail(f'--extra JSON 解析失败: {exc}')
        if not isinstance(extras, dict):
            fail("--extra 必须是 JSON 对象（如 '{\"evaluator_verdict\":\"achieved\"}'）")
        for key, value in extras.items():
            data[key] = value
            extras_set.append(key)

    # 追加 completed_steps（去重；重入跳过依赖此数组，phases.md 防重复调用）
    step_id_added: str | None = None
    if args.step_id:
        completed = data.setdefault('completed_steps', [])
        if args.step_id not in completed:
            completed.append(args.step_id)
            step_id_added = args.step_id

    # 追加 agent_dispatch.log（委派门禁检查依据，SKILL.md 规则 6）
    log_path = append_dispatch_log(path, args.step or '', args.agent or '', args.task or '')

    save_state(path, data)
    emit({
        'agent_calls_used': data['agent_calls_used'],
        'dispatch_log': log_path,
        'extras_set': extras_set,
        'locks_set': locks_set,
        'step_id_added': step_id_added,
        'status': 'ok',
    })


def cmd_dispatch(args: argparse.Namespace) -> None:
    """dispatch：仅追加 agent_dispatch.log（不递增计数，SKILL.md 规则 6）。"""
    path, _ = get_state_path(args.state_file, args.mode)
    load_state(path)
    log_path = append_dispatch_log(path, args.step or '', args.agent or '', args.task or '')
    emit({'dispatch_log': log_path, 'status': 'ok'})


def check_result(check: str, passed: bool, detail: str, action: str | None = None) -> dict:
    """构造单条检查结果（action 仅失败项携带）。"""
    result = {'check': check, 'detail': detail, 'passed': passed}
    if action:
        result['action'] = action
    return result


def cmd_check(args: argparse.Namespace) -> None:
    """check：安全边界一致性校验（goal.md 安全边界 6 项；退出码 2=需暂停）。"""
    path, _ = get_state_path(args.state_file, args.mode)
    data = load_state(path)

    results: list[dict] = []
    should_pause = False
    current_iteration = data.get('current_iteration', 0)
    calls_used = data.get('agent_calls_used', 0)

    # 1. max_iterations（N9）
    max_iterations = data.get('max_iterations', GOAL_DEFAULT_MAX_ITERATIONS)
    if current_iteration >= max_iterations:
        results.append(check_result(
            'max_iterations', False, f'{current_iteration} >= {max_iterations}',
            '暂停，向用户报告进展和剩余差距'))
        should_pause = True
    else:
        results.append(check_result(
            'max_iterations', True, f'{current_iteration}/{max_iterations}'))

    # 2. max_agent_calls（N9）
    max_calls = data.get('max_agent_calls', GOAL_DEFAULT_MAX_AGENT_CALLS)
    if calls_used >= max_calls:
        results.append(check_result(
            'max_agent_calls', False, f'{calls_used} >= {max_calls}',
            '暂停，向用户报告预算消耗'))
        should_pause = True
    else:
        results.append(check_result(
            'max_agent_calls', True, f'{calls_used}/{max_calls}'))

    # 3. no_progress_streak（N4）
    no_progress_limit = data.get('no_progress_limit', GOAL_DEFAULT_NO_PROGRESS_LIMIT)
    no_progress = data.get('no_progress_streak', 0)
    if no_progress >= no_progress_limit:
        results.append(check_result(
            'no_progress_streak', False, f'{no_progress} >= {no_progress_limit}',
            '暂停，向用户报告阻塞点'))
        should_pause = True
    else:
        results.append(check_result(
            'no_progress_streak', True, f'{no_progress}/{no_progress_limit}'))

    # 4. stop_after_turns（N9；用户内嵌限制优先）
    stop_turns = data.get('stop_after_turns')
    if stop_turns is not None and current_iteration >= stop_turns:
        results.append(check_result(
            'stop_after_turns', False, f'{current_iteration} >= {stop_turns}',
            '暂停，向用户报告已达到用户指定的轮次上限'))
        should_pause = True
    elif stop_turns is not None:
        results.append(check_result(
            'stop_after_turns', True, f'{current_iteration}/{stop_turns}'))

    # 5. stop_after_minutes（N9；已运行时间 = now - created_at）
    stop_minutes = data.get('stop_after_minutes')
    if stop_minutes is not None:
        created_at = data.get('created_at')
        if isinstance(created_at, str) and created_at:
            try:
                created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except ValueError:
                results.append(check_result(
                    'stop_after_minutes', True, 'created_at 解析失败，跳过'))
            else:
                elapsed = (datetime.now(timezone.utc) - created).total_seconds() / 60
                if elapsed >= stop_minutes:
                    results.append(check_result(
                        'stop_after_minutes', False, f'{elapsed:.0f}min >= {stop_minutes}min',
                        '暂停，向用户报告已达到用户指定的时间上限'))
                    should_pause = True
                else:
                    results.append(check_result(
                        'stop_after_minutes', True, f'{elapsed:.0f}/{stop_minutes}min'))

    # 6. human_reject_count（Director 介入，不暂停）
    reject_count = data.get('human_reject_count', 0)
    reject_limit = data.get('human_reject_limit', GOAL_DEFAULT_HUMAN_REJECT_LIMIT)
    if reject_count >= reject_limit:
        results.append(check_result(
            'human_reject_count', False, f'{reject_count} >= {reject_limit}',
            '强制触发 Director 介入（不暂停）'))
    else:
        results.append(check_result(
            'human_reject_count', True, f'{reject_count}/{reject_limit}'))

    emit({'results': results, 'should_pause': should_pause})
    if should_pause:
        sys.exit(2)


def cmd_reset(args: argparse.Namespace) -> None:
    """reset：重置单轮状态锁（递增迭代号，goal.md 精简 Pipeline）。"""
    path, _ = get_state_path(args.state_file, args.mode)
    data = load_state(path)

    data['current_iteration'] = data.get('current_iteration', 0) + 1
    for field, value in RESET_LOCK_FIELDS.items():
        data[field] = value
    data['completed_steps'] = []

    save_state(path, data)
    emit({
        'current_iteration': data['current_iteration'],
        'kept_fields': RESET_KEPT_FIELDS,
        'reset_fields': sorted(RESET_LOCK_FIELDS),
        'status': 'ok',
    })


def cmd_achieve(args: argparse.Namespace) -> None:
    """achieve：标记目标达成（goal.md 归档完成）。"""
    path, _ = get_state_path(args.state_file, args.mode)
    data = load_state(path)
    data['status'] = 'achieved'
    data['current_step'] = 'achieved'
    save_state(path, data)
    emit({'path': path, 'status': 'achieved'})


def cmd_find(args: argparse.Namespace) -> None:
    """find：查找活跃状态文件（SKILL.md 规则 5 读锚点）。"""
    path, stype = find_state_file(args.mode)
    if path:
        emit({'found': True, 'path': path, 'type': stype})
    else:
        emit({'found': False})


# ─── 参数解析 ────────────────────────────────────────────────────────────


class StateArgumentParser(argparse.ArgumentParser):
    """参数错误统一退出码 1（argparse 默认 2，与 check 业务码 2 冲突）。"""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(
            json.dumps({'error': f'参数错误: {message}'}, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        sys.exit(1)


def add_state_locator(sub: argparse.ArgumentParser) -> None:
    """为子命令追加 --state-file / --mode 通用定位选项。"""
    sub.add_argument('--state-file', help='显式指定状态文件路径')
    sub.add_argument(
        '--mode', choices=['auto', 'goal', 'start'], default='auto',
        help='查找模式（默认 auto：goal 优先，start 兜底）')


def build_parser() -> StateArgumentParser:
    """构造完整子命令解析器（签名与工作流文档调用段落一致）。"""
    parser = StateArgumentParser(
        prog='budget-state',
        description='BudgetBuddy 工作流状态机（单份，design.md §12-A4）',
    )
    sub = parser.add_subparsers(
        dest='command', required=True, parser_class=StateArgumentParser)

    p_init = sub.add_parser(
        'init', help='初始化状态文件（start: <change-id>；goal: --goal）')
    p_init.add_argument(
        'change_id', nargs='?',
        help='start 模式 change 标识（openspec/changes/<change-id>/）')
    p_init.add_argument(
        '--goal', help='goal 模式目标描述（创建 goal-pending/goal-state.json）')
    p_init.add_argument(
        '--target-dir', help='goal 模式目标目录（默认 openspec/changes/goal-pending）')
    p_init.add_argument(
        '--max-iterations', type=int, help='最大迭代数（goal，默认 8）')
    p_init.add_argument(
        '--max-agent-calls', type=int,
        help='最大 Agent 调用数（start 默认 60 / goal 默认 80）')
    p_init.add_argument(
        '--no-progress-limit', type=int, help='连续无进展上限（goal，默认 3）')
    p_init.add_argument(
        '--human-reject-limit', type=int, help='人工驳回上限（goal，默认 3）')
    p_init.add_argument(
        '--director-final-review', action='store_true', help='启用 Director 终审（goal）')
    p_init.add_argument(
        '--stop-after-turns', type=int, help='用户指定轮次上限（goal）')
    p_init.add_argument(
        '--stop-after-minutes', type=int, help='用户指定时间上限（分钟，goal）')
    p_init.add_argument(
        '--step',
        help='初始 current_step（start 默认 pipeline-running；goal 默认'
             ' 0.1-clarification，--force 时 0.5-pipeline）')
    p_init.add_argument('--force', action='store_true', help='覆盖已有状态文件')
    p_init.set_defaults(func=cmd_init)

    p_step = sub.add_parser('step', help='更新 current_step')
    p_step.add_argument('step', help='步骤值（如 0.1-clarification, iterating）')
    add_state_locator(p_step)
    p_step.set_defaults(func=cmd_step)

    p_get = sub.add_parser('get', help='读取单个字段')
    p_get.add_argument('field', help='字段名')
    add_state_locator(p_get)
    p_get.set_defaults(func=cmd_get)

    p_set = sub.add_parser('set', help='设置单个字段')
    p_set.add_argument('field', help='字段名')
    p_set.add_argument('value', help='字段值（支持 true/false/null/int/JSON）')
    add_state_locator(p_set)
    p_set.set_defaults(func=cmd_set)

    p_post = sub.add_parser('post-call', help='Agent 调用后置位')
    p_post.add_argument('--step', help='步骤号（如 0.4, 6.5.1）')
    p_post.add_argument('--agent', help='Agent 类型（如 director, goal-evaluator）')
    p_post.add_argument('--task', help='任务简述')
    p_post.add_argument('--lock', help='状态锁字段名（设为 true）')
    p_post.add_argument(
        '--extra',
        help="额外字段 JSON 对象（如 '{\"evaluator_verdict\":\"achieved\"}'）")
    p_post.add_argument('--step-id', help='completed_steps 步骤标识')
    add_state_locator(p_post)
    p_post.set_defaults(func=cmd_post_call)

    p_dispatch = sub.add_parser('dispatch', help='仅追加 agent_dispatch.log')
    p_dispatch.add_argument('--step', help='步骤号')
    p_dispatch.add_argument('--agent', help='Agent 类型')
    p_dispatch.add_argument('--task', help='任务简述')
    add_state_locator(p_dispatch)
    p_dispatch.set_defaults(func=cmd_dispatch)

    p_check = sub.add_parser('check', help='安全边界一致性校验')
    add_state_locator(p_check)
    p_check.set_defaults(func=cmd_check)

    p_reset = sub.add_parser('reset', help='重置单轮状态锁')
    add_state_locator(p_reset)
    p_reset.set_defaults(func=cmd_reset)

    p_achieve = sub.add_parser('achieve', help='标记目标达成')
    add_state_locator(p_achieve)
    p_achieve.set_defaults(func=cmd_achieve)

    p_find = sub.add_parser('find', help='查找活跃状态文件')
    p_find.add_argument(
        '--mode', choices=['auto', 'goal', 'start'], default='auto',
        help='查找模式（默认 auto：goal 优先，start 兜底）')
    p_find.set_defaults(func=cmd_find)

    return parser


def main() -> int:
    """入口：解析子命令并分发（错误 exit 1；check 需暂停 exit 2）。"""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
