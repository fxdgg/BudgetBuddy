#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""budget-state.py 状态机与 guard.sh Coder Guard 单测（design.md §8.2/§12-A4/A14）。

状态机：subprocess 直调脚本（cwd=临时项目根），覆盖 init（start/goal 双模
式）/step/get/set/post-call/dispatch/check/reset/achieve/find 全子命令、
JSON 键排序幂等与错误退出码（1 错误 / 2 check 需暂停）。
guard：bash source colors.sh + guard.sh 后调函数（HOME 隔离、剥离 BUDGET_*
变量），覆盖追加记录与 summary 计数同步、5 次窗口降级判定（失败 >=2 改派
更高级 / 连续 3 次 Director）、标签交集过滤、汇总、重置、project-name 解析
（git 根优先 / 无 git 退 basename）与 setup.sh guard 分发对接。
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
STATE_SCRIPT = REPO_ROOT / 'core' / 'lib' / 'budget-state.py'
GUARD_SCRIPT = REPO_ROOT / 'core' / 'lib' / 'guard.sh'
COLORS_SCRIPT = REPO_ROOT / 'core' / 'lib' / 'colors.sh'
CORE_SETUP = REPO_ROOT / 'core' / 'setup.sh'

# 基础层 4 文件（setup.sh 硬依赖；guard 分发对接测试用）
BASE_LIB_FILES = ('colors.sh', 'utils.sh', 'platform.sh', 'shell.sh')

# start-state.json 7 字段（SKILL.md 规则 5.4 / start.md）
START_STATE_FIELDS = [
    'agent_calls_used', 'change_id', 'completed_steps', 'created_at',
    'current_step', 'max_agent_calls', 'updated_at',
]


def run_state(args, cwd):
    """直调状态机脚本（cwd=项目根，UTF-8 编码显式声明）。"""
    return subprocess.run(
        [sys.executable, str(STATE_SCRIPT)] + args,
        cwd=str(cwd), capture_output=True, text=True,
        encoding='utf-8', timeout=60,
    )


def run_bash(script, cwd, home, env_extra=None):
    """在指定 cwd/HOME 下运行 bash（剥离 BUDGET_* 环境变量实现隔离）。"""
    env = dict(os.environ)
    env['HOME'] = str(home)
    for key in list(env):
        if key.startswith('BUDGET_'):
            del env[key]
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ['bash', '-c', script], cwd=str(cwd), env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )


class SandboxTestCase(unittest.TestCase):
    """公共沙箱：每个用例独立临时目录（项目区 + 隔离 HOME）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-state-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    # ── 状态机辅助 ─────────────────────────────────────────────────────

    def state_init_start(self, change_id='demo-change'):
        proc = run_state(['init', change_id], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return self.work / 'openspec' / 'changes' / change_id / 'start-state.json'

    def state_init_goal(self, goal='让测试全通过'):
        proc = run_state(['init', '--goal', goal], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return self.work / 'openspec' / 'changes' / 'goal-pending' / 'goal-state.json'

    def read_json(self, path):
        return json.loads(path.read_text(encoding='utf-8'))

    # ── guard 辅助 ─────────────────────────────────────────────────────

    def run_guard(self, script, cwd=None, env_extra=None):
        """source colors.sh + guard.sh 后执行片段（budget_print_* 依赖就位）。"""
        full = 'source "%s"; source "%s"; %s' % (COLORS_SCRIPT, GUARD_SCRIPT, script)
        return run_bash(full, cwd or self.work, self.home, env_extra)

    def guard_file(self, project_name=None):
        """预期记录文件路径（无 git 时 project-name = cwd 目录名）。"""
        name = project_name or self.work.name
        return self.home / '.budgetbuddy' / 'projects' / name / 'memory' / 'coder-guard.json'

    def append_records(self, coder, tag, results):
        """按序追加记录（时间顺序即列表顺序，越靠后越新）。"""
        for result in results:
            proc = self.run_guard(
                'guard_append --coder %s --tags %s --result %s' % (coder, tag, result))
            self.assertEqual(proc.returncode, 0, proc.stderr)


class StateInitStartTests(SandboxTestCase):
    """init start 模式：<change-id> 位置参数创建 start-state.json。"""

    def test_creates_seven_field_state(self):
        proc = run_state(['init', 'demo-change'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload['status'], 'created')
        state_path = self.work / 'openspec' / 'changes' / 'demo-change' / 'start-state.json'
        self.assertTrue(state_path.is_file())
        data = self.read_json(state_path)
        self.assertEqual(sorted(data), START_STATE_FIELDS)
        self.assertEqual(data['change_id'], 'demo-change')
        self.assertEqual(data['current_step'], 'pipeline-running')
        self.assertEqual(data['max_agent_calls'], 60)
        self.assertEqual(data['agent_calls_used'], 0)
        self.assertEqual(data['completed_steps'], [])
        self.assertTrue(data['created_at'])
        self.assertTrue(data['updated_at'])

    def test_max_agent_calls_override(self):
        proc = run_state(['init', 'demo', '--max-agent-calls', '30'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state_path = self.work / 'openspec' / 'changes' / 'demo' / 'start-state.json'
        data = self.read_json(state_path)
        self.assertEqual(data['max_agent_calls'], 30)

    def test_step_override(self):
        run_state(['init', 'demo', '--step', 'custom-step'], self.work)
        state_path = self.work / 'openspec' / 'changes' / 'demo' / 'start-state.json'
        self.assertEqual(self.read_json(state_path)['current_step'], 'custom-step')

    def test_existing_without_force_keeps_file(self):
        state_path = self.state_init_start('demo')
        data = self.read_json(state_path)
        data['agent_calls_used'] = 5
        state_path.write_text(json.dumps(data), encoding='utf-8')
        proc = run_state(['init', 'demo'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['status'], 'exists')
        self.assertEqual(self.read_json(state_path)['agent_calls_used'], 5)

    def test_force_overwrites_file(self):
        state_path = self.state_init_start('demo')
        proc = run_state(['init', 'demo', '--force'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['status'], 'created')
        self.assertEqual(self.read_json(state_path)['agent_calls_used'], 0)


class StateInitGoalTests(SandboxTestCase):
    """init goal 模式：--goal 创建 goal-state.json（goal.md Step 0.1/0.3）。"""

    def test_creates_full_state_defaults(self):
        proc = run_state(['init', '--goal', '让测试全通过'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state_path = self.work / 'openspec' / 'changes' / 'goal-pending' / 'goal-state.json'
        self.assertTrue(state_path.is_file())
        data = self.read_json(state_path)
        self.assertEqual(data['goal'], '让测试全通过')
        self.assertEqual(data['status'], 'in_progress')
        self.assertEqual(data['current_step'], '0.1-clarification')
        self.assertEqual(data['current_iteration'], 0)
        self.assertEqual(data['max_iterations'], 8)
        self.assertEqual(data['max_agent_calls'], 80)
        self.assertEqual(data['agent_calls_used'], 0)
        self.assertEqual(data['no_progress_streak'], 0)
        self.assertEqual(data['no_progress_limit'], 3)
        self.assertEqual(data['human_reject_count'], 0)
        self.assertEqual(data['human_reject_limit'], 3)
        self.assertEqual(data['design_revisions_used'], 0)
        self.assertFalse(data['director_final_review'])
        self.assertIsNone(data['stop_after_turns'])
        self.assertIsNone(data['stop_after_minutes'])
        self.assertEqual(data['completed_steps'], [])
        self.assertEqual(data['verification_results'], [])
        # 状态锁全量字段（goal.md 字段参考）
        for field in ('director_target_review_done', 'director_dispute_review_done',
                      'director_final_review_done', 'human_director_done',
                      'evaluator_done'):
            self.assertIn(field, data)
            self.assertFalse(data[field])

    def test_force_sets_pipeline_step_and_options(self):
        """goal.md Step 0.3：--force 覆盖为正式配置，current_step=0.5-pipeline。"""
        self.state_init_goal('首轮')
        proc = run_state([
            'init', '--goal', '正式目标', '--max-iterations', '12',
            '--max-agent-calls', '120', '--human-reject-limit', '4',
            '--no-progress-limit', '2', '--director-final-review',
            '--stop-after-turns', '5', '--stop-after-minutes', '50',
            '--force'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state_path = self.work / 'openspec' / 'changes' / 'goal-pending' / 'goal-state.json'
        data = self.read_json(state_path)
        self.assertEqual(data['current_step'], '0.5-pipeline')
        self.assertEqual(data['goal'], '正式目标')
        self.assertEqual(data['max_iterations'], 12)
        self.assertEqual(data['max_agent_calls'], 120)
        self.assertEqual(data['human_reject_limit'], 4)
        self.assertEqual(data['no_progress_limit'], 2)
        self.assertTrue(data['director_final_review'])
        self.assertEqual(data['stop_after_turns'], 5)
        self.assertEqual(data['stop_after_minutes'], 50)

    def test_target_dir_override(self):
        proc = run_state(
            ['init', '--goal', 'x', '--target-dir',
             str(self.work / 'openspec' / 'changes' / 'goal-custom')], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state_path = self.work / 'openspec' / 'changes' / 'goal-custom' / 'goal-state.json'
        self.assertTrue(state_path.is_file())

    def test_goal_and_change_id_conflict(self):
        proc = run_state(['init', '--goal', 'x', 'some-change'], self.work)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('互斥', proc.stderr)

    def test_without_target_errors(self):
        proc = run_state(['init'], self.work)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('缺少初始化目标', proc.stderr)


class StateStepGetSetTests(SandboxTestCase):
    """step / get / set：写读锚点与字段设置（SKILL.md 规则 5 / goal.md）。"""

    def test_step_updates_current_step(self):
        self.state_init_start()
        proc = run_state(['step', 'iterating'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['current_step'], 'iterating')

    def test_get_outputs_json(self):
        self.state_init_start()
        proc = run_state(['get', 'current_step'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload['field'], 'current_step')
        self.assertEqual(payload['value'], 'pipeline-running')

    def test_get_missing_field_null(self):
        self.state_init_start()
        proc = run_state(['get', 'no_such_field'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNone(json.loads(proc.stdout)['value'])

    def test_set_string_value(self):
        self.state_init_start()
        proc = run_state(['set', 'current_step', '6-verification'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['value'], '6-verification')
        proc = run_state(['get', 'current_step'], self.work)
        self.assertEqual(json.loads(proc.stdout)['value'], '6-verification')

    def test_set_int_and_bool(self):
        self.state_init_goal()
        run_state(['set', 'agent_calls_used', '7'], self.work)
        run_state(['set', 'director_final_review', 'true'], self.work)
        run_state(['set', 'evaluator_verdict', 'null'], self.work)
        data = self.read_json(self.work / 'openspec' / 'changes' / 'goal-pending' / 'goal-state.json')
        self.assertEqual(data['agent_calls_used'], 7)
        self.assertTrue(data['director_final_review'])
        self.assertIsNone(data['evaluator_verdict'])

    def test_set_json_array(self):
        """goal.md：set verification_results '<JSON数组>'。"""
        self.state_init_goal()
        proc = run_state(
            ['set', 'verification_results', '[{"iteration":1,"verdict":"gap"}]'],
            self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state_path = self.work / 'openspec' / 'changes' / 'goal-pending' / 'goal-state.json'
        data = self.read_json(state_path)
        self.assertEqual(data['verification_results'], [{'iteration': 1, 'verdict': 'gap'}])

    def test_set_invalid_json_errors(self):
        self.state_init_goal()
        proc = run_state(['set', 'verification_results', '[broken'], self.work)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('JSON 解析失败', proc.stderr)


class StatePostCallTests(SandboxTestCase):
    """post-call / dispatch：调用后置位与委派日志（phases.md / SKILL.md 规则 6）。"""

    def test_post_call_increments_and_appends(self):
        """phases.md 签名：post-call --step --agent --step-id --task。"""
        self.state_init_start('demo')
        proc = run_state([
            'post-call', '--step', '2', '--agent', 'architect',
            '--step-id', '2-architect', '--task', '方案设计'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['agent_calls_used'], 1)
        self.assertEqual(payload['step_id_added'], '2-architect')
        state_path = self.work / 'openspec' / 'changes' / 'demo' / 'start-state.json'
        data = self.read_json(state_path)
        self.assertEqual(data['agent_calls_used'], 1)
        self.assertEqual(data['completed_steps'], ['2-architect'])
        log_path = self.work / 'openspec' / 'changes' / 'demo' / 'agent_dispatch.log'
        lines = log_path.read_text(encoding='utf-8').strip().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry['agent_type'], 'architect')
        self.assertEqual(entry['step'], '2')
        self.assertEqual(entry['task'], '方案设计')
        self.assertIn('ts', entry)

    def test_post_call_lock_and_extra(self):
        """goal.md 签名：post-call --lock + --extra（evaluator 判定三字段）。"""
        self.state_init_goal()
        proc = run_state([
            'post-call', '--step', '6.5.1', '--agent', 'goal-evaluator',
            '--lock', 'evaluator_done',
            '--extra', '{"evaluator_verdict":"achieved","evaluator_confidence":"high","evaluator_reason":"全部通过"}',
            '--task', '独立判定'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload['locks_set'], ['evaluator_done'])
        self.assertEqual(
            sorted(payload['extras_set']),
            ['evaluator_confidence', 'evaluator_reason', 'evaluator_verdict'])
        state_path = self.work / 'openspec' / 'changes' / 'goal-pending' / 'goal-state.json'
        data = self.read_json(state_path)
        self.assertTrue(data['evaluator_done'])
        self.assertEqual(data['evaluator_verdict'], 'achieved')
        self.assertEqual(data['evaluator_confidence'], 'high')
        self.assertEqual(data['evaluator_reason'], '全部通过')
        self.assertEqual(data['agent_calls_used'], 1)

    def test_post_call_step_id_deduplicated(self):
        self.state_init_start('demo')
        run_state(['post-call', '--step', '4.1', '--agent', 'coder-lite',
                   '--step-id', '4.1-coder-lite-task1', '--task', '实现'], self.work)
        proc = run_state(['post-call', '--step', '4.1', '--agent', 'coder-lite',
                          '--step-id', '4.1-coder-lite-task1', '--task', '自修复'], self.work)
        payload = json.loads(proc.stdout)
        self.assertIsNone(payload['step_id_added'])  # 重复标识不追加
        state_path = self.work / 'openspec' / 'changes' / 'demo' / 'start-state.json'
        data = self.read_json(state_path)
        self.assertEqual(data['completed_steps'], ['4.1-coder-lite-task1'])
        self.assertEqual(data['agent_calls_used'], 2)  # 计数仍递增
        log_lines = (self.work / 'openspec' / 'changes' / 'demo' / 'agent_dispatch.log'
                     ).read_text(encoding='utf-8').strip().splitlines()
        self.assertEqual(len(log_lines), 2)

    def test_post_call_extra_invalid_json(self):
        self.state_init_goal()
        proc = run_state(['post-call', '--extra', '{broken'], self.work)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('--extra', proc.stderr)

    def test_post_call_extra_non_object_rejected(self):
        self.state_init_goal()
        proc = run_state(['post-call', '--extra', '[1,2]'], self.work)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('JSON 对象', proc.stderr)

    def test_dispatch_only_appends_log(self):
        """dispatch 仅追加日志，不递增计数（SKILL.md 规则 6）。"""
        self.state_init_start('demo')
        proc = run_state(
            ['dispatch', '--step', '4.x', '--agent', 'tester', '--task', '验证'],
            self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['status'], 'ok')
        state_path = self.work / 'openspec' / 'changes' / 'demo' / 'start-state.json'
        data = self.read_json(state_path)
        self.assertEqual(data['agent_calls_used'], 0)
        log_lines = (self.work / 'openspec' / 'changes' / 'demo' / 'agent_dispatch.log'
                     ).read_text(encoding='utf-8').strip().splitlines()
        self.assertEqual(len(log_lines), 1)
        self.assertEqual(json.loads(log_lines[0])['agent_type'], 'tester')


class StateCheckTests(SandboxTestCase):
    """check：安全边界一致性校验（goal.md 安全边界 6 项；退出码 0/2）。"""

    def check_once(self):
        return run_state(['check'], self.work)

    def test_all_pass_exit_zero(self):
        self.state_init_goal()
        proc = self.check_once()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload['should_pause'])
        checks = {item['check'] for item in payload['results']}
        self.assertEqual(
            checks, {'max_iterations', 'max_agent_calls', 'no_progress_streak',
                     'human_reject_count'})

    def test_max_iterations_pause(self):
        self.state_init_goal()
        run_state(['set', 'current_iteration', '8'], self.work)
        proc = self.check_once()
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload['should_pause'])
        item = next(i for i in payload['results'] if i['check'] == 'max_iterations')
        self.assertFalse(item['passed'])
        self.assertIn('action', item)

    def test_max_agent_calls_pause(self):
        self.state_init_goal()
        run_state(['set', 'agent_calls_used', '80'], self.work)
        proc = self.check_once()
        self.assertEqual(proc.returncode, 2)
        item = next(i for i in json.loads(proc.stdout)['results']
                    if i['check'] == 'max_agent_calls')
        self.assertFalse(item['passed'])

    def test_no_progress_pause(self):
        self.state_init_goal()
        run_state(['set', 'no_progress_streak', '3'], self.work)
        proc = self.check_once()
        self.assertEqual(proc.returncode, 2)
        item = next(i for i in json.loads(proc.stdout)['results']
                    if i['check'] == 'no_progress_streak')
        self.assertFalse(item['passed'])

    def test_stop_after_turns_pause(self):
        run_state(['init', '--goal', 'x', '--stop-after-turns', '2'], self.work)
        run_state(['set', 'current_iteration', '2'], self.work)
        proc = self.check_once()
        self.assertEqual(proc.returncode, 2)
        item = next(i for i in json.loads(proc.stdout)['results']
                    if i['check'] == 'stop_after_turns')
        self.assertFalse(item['passed'])

    def test_stop_after_minutes_elapsed_pause(self):
        """已运行时间 >= stop_after_minutes（0 分钟恒触发）。"""
        run_state(['init', '--goal', 'x', '--stop-after-minutes', '0'], self.work)
        proc = self.check_once()
        self.assertEqual(proc.returncode, 2)
        item = next(i for i in json.loads(proc.stdout)['results']
                    if i['check'] == 'stop_after_minutes')
        self.assertFalse(item['passed'])

    def test_human_reject_director_without_pause(self):
        """human_reject 达限 → Director 介入建议但不暂停（goal.md 第 6 项）。"""
        self.state_init_goal()
        run_state(['set', 'human_reject_count', '3'], self.work)
        proc = self.check_once()
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload['should_pause'])
        item = next(i for i in payload['results']
                    if i['check'] == 'human_reject_count')
        self.assertFalse(item['passed'])
        self.assertIn('Director', item['action'])

    def test_start_mode_budget_check(self):
        """start 模式：max_agent_calls 边界生效（其余项字段缺失走默认通过）。"""
        self.state_init_start('demo')
        proc = self.check_once()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        run_state(['set', 'agent_calls_used', '60'], self.work)
        proc = self.check_once()
        self.assertEqual(proc.returncode, 2)


class StateResetAchieveTests(SandboxTestCase):
    """reset / achieve：单轮状态锁重置与达标标记（goal.md）。"""

    def test_reset_increments_iteration_and_clears_locks(self):
        self.state_init_goal()
        run_state(['post-call', '--step', '6.5.1', '--agent', 'goal-evaluator',
                   '--lock', 'evaluator_done', '--task', '判定'], self.work)
        run_state(['set', 'human_reject_count', '2'], self.work)
        proc = run_state(['reset'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload['current_iteration'], 1)
        self.assertEqual(payload['kept_fields'],
                         ['director_target_review_done', 'human_reject_count'])
        self.assertEqual(len(payload['reset_fields']), 9)
        state_path = self.work / 'openspec' / 'changes' / 'goal-pending' / 'goal-state.json'
        data = self.read_json(state_path)
        self.assertFalse(data['evaluator_done'])
        self.assertEqual(data['completed_steps'], [])
        self.assertEqual(data['human_reject_count'], 2)  # 跨迭代持久化
        # 再 reset：迭代号继续递增
        proc = run_state(['reset'], self.work)
        self.assertEqual(json.loads(proc.stdout)['current_iteration'], 2)

    def test_reset_keeps_director_target_review(self):
        """director_target_review_done 全局一次性操作，reset 不重置。"""
        self.state_init_goal()
        run_state(['post-call', '--step', '0.4', '--agent', 'director',
                   '--lock', 'director_target_review_done', '--task', '审定'], self.work)
        run_state(['reset'], self.work)
        state_path = self.work / 'openspec' / 'changes' / 'goal-pending' / 'goal-state.json'
        data = self.read_json(state_path)
        self.assertTrue(data['director_target_review_done'])

    def test_achieve_marks_status(self):
        self.state_init_goal()
        proc = run_state(['achieve'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['status'], 'achieved')
        state_path = self.work / 'openspec' / 'changes' / 'goal-pending' / 'goal-state.json'
        data = self.read_json(state_path)
        self.assertEqual(data['status'], 'achieved')
        self.assertEqual(data['current_step'], 'achieved')


class StateFindTests(SandboxTestCase):
    """find：查找活跃状态文件（SKILL.md 规则 5 读锚点：goal 优先 / start 兜底）。"""

    def test_find_none_when_no_state(self):
        proc = run_state(['find'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(json.loads(proc.stdout)['found'])

    def test_find_goal_preferred_over_start(self):
        self.state_init_goal()
        self.state_init_start('demo')
        proc = run_state(['find'], self.work)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload['found'])
        self.assertEqual(payload['type'], 'goal')
        self.assertIn('goal-pending', payload['path'])

    def test_find_start_fallback(self):
        self.state_init_start('demo')
        proc = run_state(['find'], self.work)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload['found'])
        self.assertEqual(payload['type'], 'start')
        self.assertIn('demo', payload['path'])

    def test_find_mode_goal_filters_start(self):
        self.state_init_start('demo')
        proc = run_state(['find', '--mode', 'goal'], self.work)
        self.assertFalse(json.loads(proc.stdout)['found'])
        proc = run_state(['find', '--mode', 'start'], self.work)
        self.assertTrue(json.loads(proc.stdout)['found'])

    def test_find_start_archived_skipped(self):
        self.state_init_start('demo')
        run_state(['set', 'current_step', 'archived'], self.work)
        proc = run_state(['find'], self.work)
        self.assertFalse(json.loads(proc.stdout)['found'])

    def test_find_goal_in_progress_preferred(self):
        """多个 goal-state：in_progress 优先于 achieved。"""
        run_state(['init', '--goal', 'a', '--target-dir',
                   str(self.work / 'openspec' / 'changes' / 'goal-a')], self.work)
        run_state(['init', '--goal', 'b', '--target-dir',
                   str(self.work / 'openspec' / 'changes' / 'goal-b')], self.work)
        # goal-a 置为 achieved，goal-b 保持 in_progress
        path_a = self.work / 'openspec' / 'changes' / 'goal-a' / 'goal-state.json'
        data_a = self.read_json(path_a)
        data_a['status'] = 'achieved'
        path_a.write_text(json.dumps(data_a), encoding='utf-8')
        proc = run_state(['find'], self.work)
        payload = json.loads(proc.stdout)
        self.assertIn('goal-b', payload['path'])


class StateErrorTests(SandboxTestCase):
    """错误处理：状态文件缺失 / 损坏 / 参数错误统一 exit 1。"""

    def test_missing_state_file_errors(self):
        proc = run_state(['get', 'current_step'], self.work)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未找到活跃的状态文件', proc.stderr)

    def test_corrupted_state_file_errors(self):
        state_path = self.state_init_start('demo')
        state_path.write_text('{broken json', encoding='utf-8')
        proc = run_state(
            ['get', 'current_step', '--state-file', str(state_path)], self.work)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('JSON 格式错误', proc.stderr)

    def test_find_skips_corrupted_file(self):
        """find 静默跳过损坏的状态文件（不崩溃，报未找到）。"""
        state_path = self.state_init_start('demo')
        state_path.write_text('{broken json', encoding='utf-8')
        proc = run_state(['find'], self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(json.loads(proc.stdout)['found'])

    def test_state_file_keys_sorted(self):
        """json 按键排序（幂等）：文件键序 == sorted(keys)。"""
        self.state_init_goal()
        run_state(['post-call', '--step', '0.4', '--agent', 'director',
                   '--lock', 'director_target_review_done', '--task', '审定'], self.work)
        state_path = self.work / 'openspec' / 'changes' / 'goal-pending' / 'goal-state.json'
        data = self.read_json(state_path)
        self.assertEqual(list(data.keys()), sorted(data.keys()))

    def test_dispatch_log_keys_sorted(self):
        self.state_init_start('demo')
        run_state(['dispatch', '--step', '1', '--agent', 'tester', '--task', 't'], self.work)
        log_path = self.work / 'openspec' / 'changes' / 'demo' / 'agent_dispatch.log'
        entry = json.loads(log_path.read_text(encoding='utf-8').strip())
        self.assertEqual(list(entry.keys()), sorted(entry.keys()))


class GuardAppendTests(SandboxTestCase):
    """guard_append：追加记录与 summary 计数同步。"""

    def test_append_creates_file_and_counts(self):
        proc = self.run_guard(
            'guard_append --coder coder-lite --tags api_endpoint --result failure')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(payload['status'], 'ok')
        guard_file = self.guard_file()
        self.assertTrue(guard_file.is_file())
        data = self.read_json(guard_file)
        self.assertEqual(len(data['history']), 1)
        entry = data['history'][0]
        self.assertEqual(entry['coder'], 'coder-lite')
        self.assertEqual(entry['tags'], ['api_endpoint'])
        self.assertEqual(entry['result'], 'failure')
        self.assertIsNone(entry['escalated_to'])
        self.assertTrue(entry['timestamp'])
        self.assertEqual(
            data['summary']['coder-lite']['api_endpoint'],
            {'failure': 1, 'success': 0, 'total': 1})

    def test_append_multiple_tags_and_success(self):
        proc = self.run_guard(
            'guard_append --coder coder-standard --tags api_endpoint,security_related --result success')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_json(self.guard_file())
        expected = {'failure': 0, 'success': 1, 'total': 1}
        self.assertEqual(data['summary']['coder-standard']['api_endpoint'], expected)
        self.assertEqual(data['summary']['coder-standard']['security_related'], expected)

    def test_append_escalated_to(self):
        proc = self.run_guard(
            'guard_append --coder coder-lite --tags api_endpoint --result failure '
            '--escalated-to coder-standard')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_json(self.guard_file())
        self.assertEqual(data['history'][0]['escalated_to'], 'coder-standard')

    def test_append_without_tags_not_summarized(self):
        """无标签记录仅入 history，summary 不归桶。"""
        proc = self.run_guard('guard_append --coder coder-lite --result failure')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_json(self.guard_file())
        self.assertEqual(len(data['history']), 1)
        self.assertEqual(data['history'][0]['tags'], [])
        self.assertEqual(data['summary'], {})

    def test_append_rejects_bad_result(self):
        proc = self.run_guard('guard_append --coder coder-lite --result broken')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('success/failure', proc.stdout)

    def test_append_requires_coder_and_result(self):
        proc = self.run_guard('guard_append --result failure')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('用法', proc.stdout)

    def test_append_unknown_option(self):
        proc = self.run_guard(
            'guard_append --coder coder-lite --result failure --bad-option x')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未知参数', proc.stdout)

    def test_append_missing_value_no_infinite_loop(self):
        """缺值参数报错退出（防 shift 越界死循环）。"""
        proc = self.run_guard('guard_append --coder')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('缺少值', proc.stdout)

    def test_append_survives_corrupted_file(self):
        """记录文件损坏时归一为空结构继续追加，不阻断。"""
        guard_file = self.guard_file()
        guard_file.parent.mkdir(parents=True)
        guard_file.write_text('{broken', encoding='utf-8')
        proc = self.run_guard(
            'guard_append --coder coder-lite --tags api_endpoint --result failure')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_json(guard_file)
        self.assertEqual(len(data['history']), 1)


class GuardQueryTests(SandboxTestCase):
    """guard_query：5 次窗口降级判定（失败 >=2 改派 / 连续 3 次 Director）。"""

    def test_query_no_file(self):
        proc = self.run_guard('guard_query')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未找到 Coder Guard 记录', proc.stdout)

    def test_query_no_risk_below_threshold(self):
        self.append_records('coder-lite', 'api_endpoint',
                            ['failure', 'success', 'success', 'success', 'success'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('无降级风险', proc.stdout)
        self.assertIn('失败 1', proc.stdout)

    def test_query_degrades_lite_to_standard(self):
        self.append_records('coder-lite', 'api_endpoint',
                            ['failure', 'failure', 'success', 'success', 'success'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('触发降级保护', proc.stdout)
        self.assertIn('coder-standard', proc.stdout)

    def test_query_degrades_standard_to_senior(self):
        self.append_records('coder-standard', 'api_endpoint',
                            ['failure', 'failure', 'success', 'success', 'success'])
        proc = self.run_guard('guard_query coder-standard api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('触发降级保护', proc.stdout)
        self.assertIn('coder-senior', proc.stdout)

    def test_query_senior_suggests_director(self):
        self.append_records('coder-senior', 'api_endpoint',
                            ['failure', 'failure', 'success', 'success', 'success'])
        proc = self.run_guard('guard_query coder-senior api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('触发降级保护', proc.stdout)
        self.assertIn('已是最高级', proc.stdout)
        self.assertIn('Director', proc.stdout)

    def test_query_consecutive_three_director(self):
        """连续失败 3 次 → 建议 Director 介入（3 轮全败语义）。"""
        self.append_records('coder-lite', 'api_endpoint',
                            ['success', 'success', 'failure', 'failure', 'failure'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('连续失败 3 次', proc.stdout)
        self.assertIn('Director', proc.stdout)

    def test_query_window_excludes_old_records(self):
        """窗口只取最近 5 条：早期失败滑出窗口后不再计入。"""
        self.append_records('coder-lite', 'api_endpoint',
                            ['failure', 'failure', 'success', 'success', 'success',
                             'success', 'success'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('无降级风险', proc.stdout)

    def test_query_insufficient_samples(self):
        self.append_records('coder-lite', 'api_endpoint', ['failure'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('样本不足', proc.stdout)

    def test_query_tag_filtering(self):
        """标签交集过滤：其他标签的失败不计入本标签判定。"""
        self.append_records('coder-lite', 'api_endpoint',
                            ['failure', 'failure'])
        self.append_records('coder-lite', 'config_edit',
                            ['success', 'success', 'success'])
        proc = self.run_guard('guard_query coder-lite api_endpoint')
        self.assertIn('触发降级保护', proc.stdout)
        proc = self.run_guard('guard_query coder-lite config_edit')
        self.assertIn('无降级风险', proc.stdout)

    def test_query_no_matching_records(self):
        self.append_records('coder-lite', 'api_endpoint', ['success'])
        proc = self.run_guard('guard_query coder-senior api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('样本不足', proc.stdout)

    def test_query_overview_without_coder(self):
        """无 coder 概览模式：最近记录 + summary 概览 + 提示。"""
        self.append_records('coder-lite', 'api_endpoint', ['failure', 'success'])
        proc = self.run_guard('guard_query')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('历史记录: 2 条', proc.stdout)
        self.assertIn('coder-lite', proc.stdout)
        self.assertIn('降级建议', proc.stdout)


class GuardSummaryResetTests(SandboxTestCase):
    """guard_summary / guard_reset：汇总统计与记录重置。"""

    def test_summary_outputs_stats(self):
        self.append_records('coder-lite', 'api_endpoint', ['failure', 'success'])
        proc = self.run_guard('guard_summary')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('coder-lite', proc.stdout)
        self.assertIn('api_endpoint', proc.stdout)
        self.assertIn('total=2', proc.stdout)
        self.assertIn('failure=1', proc.stdout)
        self.assertIn('历史记录: 2 条', proc.stdout)

    def test_summary_no_file(self):
        proc = self.run_guard('guard_summary')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未找到 Coder Guard 记录', proc.stdout)

    def test_reset_clears_records(self):
        self.append_records('coder-lite', 'api_endpoint', ['failure', 'failure'])
        proc = self.run_guard('guard_reset')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('已重置', proc.stdout)
        guard_file = self.guard_file()
        self.assertTrue(guard_file.is_file())
        data = self.read_json(guard_file)
        self.assertEqual(data, {'history': [], 'summary': {}})
        proc = self.run_guard('guard_query')
        self.assertIn('历史记录: 0 条', proc.stdout)


class GuardPathTests(SandboxTestCase):
    """project-name 解析：git 根目录名优先，无 git 退 basename $PWD。"""

    def test_project_name_no_git_uses_basename(self):
        proc = self.run_guard('guard_project_name')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), self.work.name)

    def test_project_name_git_root_preferred(self):
        if shutil.which('git') is None:
            self.skipTest('git 不可用')
        subprocess.run(
            ['git', 'init', '-q', str(self.tmp)],
            capture_output=True, text=True, timeout=60, check=True)
        # work 是 tmp 子目录：git 根 = tmp（basename 不同于 work）
        proc = self.run_guard('guard_project_name', cwd=self.work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), self.tmp.name)

    def test_guard_file_path_layout(self):
        proc = self.run_guard('guard_file_path')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = '%s/.budgetbuddy/projects/%s/memory/coder-guard.json' % (
            self.home, self.work.name)
        self.assertEqual(proc.stdout.strip(), expected)

    def test_records_isolated_per_project(self):
        """不同 project-name 的记录互不串扰（按项目名隔离）。"""
        self.append_records('coder-lite', 'api_endpoint', ['failure'])
        other = self.tmp / 'other-work'
        other.mkdir()
        proc = self.run_guard('guard_query', cwd=other)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未找到 Coder Guard 记录', proc.stdout)


class GuardDispatchTests(SandboxTestCase):
    """setup_guard 分发入口与 setup.sh guard 子命令对接。"""

    def test_bash_n_guard_script(self):
        proc = subprocess.run(
            ['bash', '-n', str(GUARD_SCRIPT)],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_setup_guard_default_query(self):
        proc = self.run_guard('setup_guard')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未找到 Coder Guard 记录', proc.stdout)

    def test_setup_guard_query_action(self):
        self.append_records('coder-lite', 'api_endpoint', ['failure', 'failure'])
        proc = self.run_guard('setup_guard query coder-lite api_endpoint')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('触发降级保护', proc.stdout)

    def test_setup_guard_append_action(self):
        proc = self.run_guard(
            'setup_guard append --coder coder-lite --tags api_endpoint --result failure')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.read_json(self.guard_file())
        self.assertEqual(len(data['history']), 1)

    def test_setup_guard_summary_and_reset(self):
        self.append_records('coder-lite', 'api_endpoint', ['failure'])
        proc = self.run_guard('setup_guard summary')
        self.assertIn('total=1', proc.stdout)
        proc = self.run_guard('setup_guard reset')
        self.assertIn('已重置', proc.stdout)
        proc = self.run_guard('setup_guard summary')
        self.assertIn('历史记录: 0 条', proc.stdout)

    def test_setup_guard_unknown_action(self):
        proc = self.run_guard('setup_guard badaction')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('未知操作', proc.stdout)

    def test_setup_sh_guard_dispatch(self):
        """setup.sh 分发表对接：guard.sh 就位后 `budget setup guard` 可用。"""
        cb = self.tmp / '.codebuddy'
        (cb / 'lib').mkdir(parents=True)
        shutil.copy2(CORE_SETUP, cb / 'setup.sh')
        for name in BASE_LIB_FILES:
            shutil.copy2(REPO_ROOT / 'core' / 'lib' / name, cb / 'lib' / name)
        shutil.copy2(GUARD_SCRIPT, cb / 'lib' / 'guard.sh')
        proc = run_bash('bash "%s" guard' % (cb / 'setup.sh'), self.work, self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('未找到 Coder Guard 记录', proc.stdout)


if __name__ == '__main__':
    unittest.main()
