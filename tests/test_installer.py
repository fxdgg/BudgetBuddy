#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install.sh 三平台安装器单测（design.md §10 / specs/installer）。

以 subprocess 驱动 bash install.sh：临时目录构造 mini 仓库（install.sh +
dist/ 副本，可自由改动 manifest 与文件哈希模拟升级场景，不触碰仓库真实
dist/），HOME 环境隔离（剥离外层 BUDGET_* 变量）。覆盖：

- 四形态端到端（codebuddy 项目/全局、opencode 项目/全局）：文件落点、
  本地清单、命令包装器、hooks 注入（settings.json）、budget setup show 冒烟
- claudecode 项目级端到端（.claude/ 结构 + CLAUDE.md 标记区块 + 管理面
  ~/.budgetbuddy/ + 本地清单 claudecode: 前缀段）
- AGENTS.md / CLAUDE.md 标记区块幂等合并：创建 / 追加 / 幂等重装内容不变 /
  用户内容保护
- manifest 增量同步：哈希一致跳过、哈希变化覆盖、清单外用户文件保留、
  本地清单写入（files / platform_files 双字段）
- 复审 C1 三组断言：write_local_manifest 合并写（opencode 无前缀段 /
  claudecode: 前缀段 / files 磁盘存在性过滤，多平台共装两段并存）、
  upgrade_diff_cleanup 命名空间解析（platform_files:claudecode 去前缀仅取
  本平台段、无后缀 platform_files 仅取无冒号键，对既有安装升级模拟）、
  local_manifest_other_platform 共装判定（opencode 视角带前缀键=他平台 /
  claudecode 视角无冒号键=他平台 / 清单缺失=0）
- 复审 F1/F2/F3：codebuddy→claudecode 共装与 all 模式下两平台
  settings.json 三事件互不串写（claudecode 注入不依赖探测）；注入失败
  降级警告不阻断安装、SUMMARY 如实呈现
- 升级差集清理：本地旧清单 − 新 manifest 差集删除、清单外文件不受影响
- 非交互：BUDGET_PLATFORM / BUDGET_GLOBAL 环境变量、无 tty 默认项目安装、
  both 双平台
- 依赖缺失 mock（PATH 隔离，python3 不可用 → 明确报错中止）
- bash -n 语法冒烟与 CLI 入口（--help / --version）
- agent-autorun install.sh 集成面（design.md D4/D5、installer spec 2.5 重放
  钩子）：钩子落点（upgrade_diff_cleanup 后、write_local_manifest 前；状态
  文件存在时 apply 被调用且 reviewer 的 enabledAutoRun 恢复）、无状态文件
  不重放（dist 默认 4 个在位）、损坏状态文件 apply 失败仅告警不阻断且安装
  完成与状态文件字节不变、二次安装 apply 幂等（无状态/默认一致时同步全
  跳过；非默认状态下同步先以 dist 重覆盖偏差 agent 再由 apply 重放，终态
  一致、字节稳定）
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / 'install.sh'
DIST_CODEBUDDY = REPO_ROOT / 'dist' / 'codebuddy'
DIST_OPENCODE = REPO_ROOT / 'dist' / 'opencode'
DIST_CLAUDECODE = REPO_ROOT / 'dist' / 'claudecode'
DIST_CODEX = REPO_ROOT / 'dist' / 'codex'

SUITE_AGENTS = (
    'architect', 'coder-lite', 'coder-standard', 'coder-senior', 'reviewer',
    'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
)

AGENTS_BEGIN = '<!-- BudgetBuddy:begin -->'
AGENTS_END = '<!-- BudgetBuddy:end -->'


def sha256_of(path):
    """计算文件 SHA256（与 manifest 哈希同口径）。"""
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def count_files(root):
    """统计目录树内普通文件数（含隐藏文件）。"""
    total = 0
    for _, _, files in os.walk(root):
        total += len(files)
    return total


def make_mini_repo(base):
    """构造 mini 仓库：install.sh + dist/ 四平台副本（可自由改动模拟升级）。"""
    repo = base / 'repo'
    repo.mkdir()
    shutil.copy2(INSTALL_SH, repo / 'install.sh')
    shutil.copytree(DIST_CODEBUDDY, repo / 'dist' / 'codebuddy')
    shutil.copytree(DIST_OPENCODE, repo / 'dist' / 'opencode')
    shutil.copytree(DIST_CLAUDECODE, repo / 'dist' / 'claudecode')
    shutil.copytree(DIST_CODEX, repo / 'dist' / 'codex')
    return repo


class InstallerSandbox(unittest.TestCase):
    """公共沙箱：每用例独立临时目录（mini 仓库 + 隔离 HOME + 项目目录）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-installer-')
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir()
        self.work.mkdir()
        self.repo = make_mini_repo(self.tmp)

    def run_install(self, env_extra=None, stdin_text='', cwd=None,
                    new_session=False):
        """运行 mini 仓库 install.sh（HOME 隔离 + 剥离外层 BUDGET_*）。"""
        env = dict(os.environ)
        env['HOME'] = str(self.home)
        for key in list(env):
            if key.startswith('BUDGET_'):
                del env[key]
        # 剥离 IDE safe-delete 注入（BASH_ENV 函数 + PATH shim + 会话 ID）：
        # 包装版 rm 投递回收站失败时返回非零，install.sh 差集清理的
        # `if rm -f` 会静默跳过（时序性断言失败）。测试需验证原生删除
        # 语义（与 tests/test_update.py run_setup 同族防护）。
        for key in ('BASH_ENV', 'CODEBUDDY_SESSION_ID', 'CLAUDE_SESSION_ID',
                    'CODEBUDDY_SAFE_DELETE_ENABLED',
                    'CODEBUDDY_SAFE_DELETE_BIN_DIR',
                    'CODEBUDDY_SAFE_DELETE_SHIM_DIR',
                    'CODEBUDDY_SAFE_DELETE_REPORT_PATH',
                    'CODEBUDDY_SAFE_DELETE_HOST_HEARTBEAT',
                    'CODEBUDDY_SAFE_DELETE_BULK_GUARD',
                    'CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR',
                    'CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD'):
            env.pop(key, None)
        env['PATH'] = ':'.join(
            p for p in env.get('PATH', '').split(':')
            if p and '/shim/safe-bin' not in p)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ['bash', str(self.repo / 'install.sh')],
            cwd=str(cwd if cwd is not None else self.work),
            env=env, capture_output=True, text=True, encoding='utf-8',
            timeout=180, input=stdin_text,
            start_new_session=new_session,
        )

    def run_setup(self, subcommand, cwd, extra_args=None):
        """在指定 cwd 下运行安装形态的 setup.sh 子命令（HOME 隔离）。"""
        env = dict(os.environ)
        env['HOME'] = str(self.home)
        for key in list(env):
            if key.startswith('BUDGET_'):
                del env[key]
        for key in ('BASH_ENV', 'CODEBUDDY_SESSION_ID', 'CLAUDE_SESSION_ID',
                    'CODEBUDDY_SAFE_DELETE_ENABLED',
                    'CODEBUDDY_SAFE_DELETE_BIN_DIR',
                    'CODEBUDDY_SAFE_DELETE_SHIM_DIR',
                    'CODEBUDDY_SAFE_DELETE_REPORT_PATH',
                    'CODEBUDDY_SAFE_DELETE_HOST_HEARTBEAT',
                    'CODEBUDDY_SAFE_DELETE_BULK_GUARD',
                    'CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR',
                    'CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD'):
            env.pop(key, None)
        env['PATH'] = ':'.join(
            p for p in env.get('PATH', '').split(':')
            if p and '/shim/safe-bin' not in p)
        setup = Path(cwd) / '.codebuddy' / 'setup.sh'
        return subprocess.run(
            ['bash', str(setup), subcommand] + list(extra_args or []),
            cwd=str(cwd), env=env, capture_output=True, text=True,
            encoding='utf-8', timeout=60,
        )

    def assert_install_ok(self, result):
        self.assertEqual(
            result.returncode, 0,
            'install.sh 失败:\nstdout:\n%s\nstderr:\n%s' % (
                result.stdout, result.stderr))


class CliEntryTests(unittest.TestCase):
    """bash -n 语法冒烟与 CLI 入口（--help / --version）。"""

    def test_bash_n_syntax(self):
        result = subprocess.run(
            ['bash', '-n', str(INSTALL_SH)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_help(self):
        result = subprocess.run(
            ['bash', str(INSTALL_SH), '--help'],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertIn('用法', result.stdout)
        self.assertIn('BUDGET_PLATFORM', result.stdout)
        self.assertIn('--global', result.stdout)

    def test_version(self):
        result = subprocess.run(
            ['bash', str(INSTALL_SH), '--version'],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertIn('BudgetBuddy installer', result.stdout)


class DependencyCheckTests(InstallerSandbox):
    """依赖缺失 mock：PATH 隔离使 python3 不可用 → 明确报错中止。"""

    def test_missing_python_aborts(self):
        fake_bin = self.tmp / 'fakebin'
        fake_bin.mkdir()
        # bash/sh 走系统 symlink（subprocess 经 PATH 解析 bash 本体）
        for name in ('bash', 'sh'):
            os.symlink('/bin/bash', fake_bin / name)
        # curl / tar / sha256 stub（command -v 命中即可，不会真正执行）
        for name in ('curl', 'tar', 'shasum', 'sha256sum'):
            stub = fake_bin / name
            stub.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
            stub.chmod(0o755)
        env = {
            'PATH': str(fake_bin),
            'HOME': str(self.home),
            'BUDGET_PLATFORM': 'codebuddy',
            'BUDGET_GLOBAL': '0',
        }
        result = subprocess.run(
            ['bash', str(self.repo / 'install.sh')],
            cwd=str(self.work), env=env, capture_output=True, text=True,
            encoding='utf-8', timeout=60, input='')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('python3', result.stderr)
        self.assertIn('缺少必要的依赖', result.stderr)
        # 中止于依赖检查：未复制任何文件到安装目录
        self.assertFalse((self.work / '.codebuddy').exists())


class NonInteractiveTests(InstallerSandbox):
    """非交互模式：环境变量纯非交互、无 tty 默认、both 双平台。"""

    def test_env_platform_and_global(self):
        # specs/installer Scenario「环境变量非交互」：
        # BUDGET_PLATFORM=opencode BUDGET_GLOBAL=1 → 无任何交互提示完成安装
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'opencode', 'BUDGET_GLOBAL': '1'})
        self.assert_install_ok(result)
        self.assertIn('OpenCode 全局安装', result.stdout)
        self.assertTrue(
            (self.home / '.config' / 'opencode' / 'agent').is_dir())
        self.assertTrue((self.home / '.budgetbuddy' / 'setup.sh').is_file())

    def test_env_explicit_project_scope(self):
        # BUDGET_GLOBAL=0 显式设置 → 跳过作用域交互（纯非交互）
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codebuddy', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        self.assertTrue((self.work / '.codebuddy' / 'setup.sh').is_file())

    def test_no_tty_defaults_to_project(self):
        # 纯非交互环境（无控制终端）：默认 codebuddy + 项目安装
        result = self.run_install(new_session=True)
        self.assert_install_ok(result)
        self.assertIn('默认安装 CodeBuddy 平台', result.stdout)
        self.assertTrue((self.work / '.codebuddy' / 'setup.sh').is_file())
        self.assertFalse((self.home / '.codebuddy').exists())

    def test_both_mode_installs_two_platforms(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'both', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        # codebuddy 项目级 + opencode 项目级 + 管理面 + AGENTS.md 全部就位
        self.assertTrue((self.work / '.codebuddy' / 'setup.sh').is_file())
        self.assertTrue((self.work / '.opencode' / 'agent').is_dir())
        self.assertTrue((self.home / '.budgetbuddy' / 'setup.sh').is_file())
        agents_md = self.work / 'AGENTS.md'
        self.assertTrue(agents_md.is_file())
        self.assertIn(AGENTS_BEGIN, agents_md.read_text(encoding='utf-8'))


class CodebuddyProjectTests(InstallerSandbox):
    """codebuddy 项目级安装端到端（specs/installer Scenario「codebuddy 项目级安装」）。"""

    def install(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codebuddy', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def test_full_layout(self):
        self.install()
        cb = self.work / '.codebuddy'
        # agents ×10
        for name in SUITE_AGENTS:
            self.assertTrue((cb / 'agents' / ('%s.md' % name)).is_file(),
                            '缺失 agent: %s' % name)
        # commands（budget×3 + opsx×4）
        for rel in ('budget/start.md', 'budget/status.md', 'budget/goal.md',
                    'opsx/apply.md', 'opsx/archive.md', 'opsx/explore.md',
                    'opsx/propose.md'):
            self.assertTrue((cb / 'commands' / rel).is_file(), '缺失命令: %s' % rel)
        # skills ×6 目录 / rules ×12 / hooks / lib / setup.sh / docs / 数据
        self.assertTrue((cb / 'skills' / 'budget-workflow' / 'SKILL.md').is_file())
        self.assertTrue((cb / 'skills' / 'openspec-propose' / 'SKILL.md').is_file())
        self.assertTrue((cb / 'rules' / 'budget-leader-no-code.mdc').is_file())
        self.assertTrue((cb / 'hooks' / 'budget-notify-hook.py').is_file())
        self.assertTrue((cb / 'lib' / 'utils.sh').is_file())
        self.assertTrue((cb / 'setup.sh').is_file())
        self.assertTrue((cb / 'budget-models.json').is_file())
        self.assertTrue((cb / 'personas.json').is_file())
        self.assertTrue((cb / 'docs' / 'MODEL_SELECTION.md').is_file())
        # 命令包装器
        self.assertTrue((self.home / '.local' / 'bin' / 'budget').is_file())
        # hooks 注入 settings.json（三事件 + superpowers 插件）
        settings = cb / 'settings.json'
        self.assertTrue(settings.is_file(), 'settings.json 未生成')
        text = settings.read_text(encoding='utf-8')
        self.assertIn('budget-notify-hook.py', text)
        self.assertIn('superpowers', text)

    def test_local_manifest_written(self):
        self.install()
        local = load_json(self.work / '.codebuddy' / '.budget-manifest.json')
        dist = load_json(self.repo / 'dist' / 'codebuddy' / '.manifest.json')
        self.assertEqual(local['files'], dist['files'])
        # 清单文件自身不列入清单
        self.assertNotIn('.budget-manifest.json', local['files'])

    def test_setup_show_smoke(self):
        # specs/installer Scenario：安装后 budget setup show 可执行
        self.install()
        result = self.run_setup('show', self.work)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('运行平台', result.stdout)

    def test_reinstall_all_skipped(self):
        self.install()
        dist = load_json(self.repo / 'dist' / 'codebuddy' / '.manifest.json')
        total = len(dist['files'])
        result = self.install()
        # 幂等重装：全部文件哈希一致跳过，无新增无更新
        self.assertIn('新增 0 / 更新 0 / 跳过 %d' % total, result.stdout)

    def test_out_of_manifest_user_file_preserved(self):
        # specs/installer Scenario「用户自建 agent 保留」
        self.install()
        custom = self.work / '.codebuddy' / 'agents' / 'my-agent.md'
        custom.write_text('---\nname: my-agent\n---\n用户自定义\n', encoding='utf-8')
        before = count_files(self.work / '.codebuddy')
        self.install()
        self.assertTrue(custom.is_file())
        self.assertEqual(
            custom.read_text(encoding='utf-8'),
            '---\nname: my-agent\n---\n用户自定义\n')
        # dist 文件不重复（总数不变：清单内哈希跳过 + 清单外保留）
        self.assertEqual(before, count_files(self.work / '.codebuddy'))


class CodebuddyGlobalTests(InstallerSandbox):
    """codebuddy 全局安装端到端。"""

    def test_global_layout_and_manifest(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codebuddy', 'BUDGET_GLOBAL': '1'})
        self.assert_install_ok(result)
        cb = self.home / '.codebuddy'
        self.assertTrue((cb / 'agents' / 'architect.md').is_file())
        self.assertTrue((cb / 'lib' / 'hooks.sh').is_file())
        self.assertTrue((cb / '.budget-manifest.json').is_file())
        # 全局 hooks 注入到 ~/.codebuddy/settings.json
        settings = cb / 'settings.json'
        self.assertTrue(settings.is_file())
        self.assertIn('budget-notify-hook.py', settings.read_text(encoding='utf-8'))
        # 项目目录不受影响
        self.assertFalse((self.work / '.codebuddy').exists())


class OpencodeProjectTests(InstallerSandbox):
    """opencode 项目级安装端到端（specs/installer Scenario「opencode 全局安装」的项目级对偶）。"""

    def install(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'opencode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def test_full_layout(self):
        self.install()
        oc = self.work / '.opencode'
        # 平台结构：agent×10 / command×7 / skill
        for name in SUITE_AGENTS:
            self.assertTrue((oc / 'agent' / ('%s.md' % name)).is_file(),
                            '缺失 agent: %s' % name)
        for rel in ('command/budget-start.md', 'command/budget-status.md',
                    'command/budget-goal.md', 'command/opsx-apply.md',
                    'command/opsx-archive.md', 'command/opsx-explore.md',
                    'command/opsx-propose.md'):
            self.assertTrue((oc / rel).is_file(), '缺失命令: %s' % rel)
        self.assertTrue((oc / 'skill' / 'budget-workflow' / 'SKILL.md').is_file())
        # AGENTS.fragment.md 不复制为文件（合并进 AGENTS.md）
        self.assertFalse((oc / 'AGENTS.fragment.md').exists())
        # 管理面统一 ~/.budgetbuddy/（A3）
        mgmt = self.home / '.budgetbuddy'
        self.assertTrue((mgmt / 'setup.sh').is_file())
        self.assertTrue((mgmt / 'lib' / 'utils.sh').is_file())
        self.assertTrue((mgmt / 'budget-models.json').is_file())
        self.assertTrue((mgmt / 'personas.json').is_file())
        self.assertTrue((mgmt / 'docs' / 'MODEL_SELECTION.md').is_file())
        self.assertTrue((mgmt / 'docs' / 'PERSONAS.md').is_file())
        # AGENTS.md 标记区块（项目根）
        agents_md = self.work / 'AGENTS.md'
        text = agents_md.read_text(encoding='utf-8')
        self.assertIn(AGENTS_BEGIN, text)
        self.assertIn(AGENTS_END, text)
        self.assertIn('budget-leader-no-code:begin', text)
        # 命令包装器
        self.assertTrue((self.home / '.local' / 'bin' / 'budget').is_file())

    def test_local_manifest_split_fields(self):
        self.install()
        local = load_json(self.home / '.budgetbuddy' / '.budget-manifest.json')
        dist = load_json(self.repo / 'dist' / 'opencode' / '.manifest.json')
        struct = set(
            rel for rel in dist['files']
            if rel.startswith(('agent/', 'command/', 'skill/')))
        mgmt = set(
            rel for rel in dist['files']
            if not rel.startswith(('agent/', 'command/', 'skill/'))
            and rel != 'AGENTS.fragment.md')
        # files 字段与 lib/uninstall.sh 读取约定一致（管理面，相对 ~/.budgetbuddy/）
        self.assertEqual(set(local['files']), mgmt)
        self.assertEqual(local['files'], {
            rel: dist['files'][rel] for rel in sorted(mgmt)})
        # platform_files 记录平台结构条目（安装器升级差集清理依据）
        self.assertEqual(set(local['platform_files']), struct)
        # AGENTS.fragment.md 不进任何清单字段（合并产物非复制文件）
        self.assertNotIn('AGENTS.fragment.md', local['files'])
        self.assertNotIn('AGENTS.fragment.md', local['platform_files'])

    def test_agents_md_idempotent(self):
        # specs/installer Scenario「幂等重装」：区块内容不变、无重复追加
        self.install()
        first = (self.work / 'AGENTS.md').read_text(encoding='utf-8')
        self.install()
        second = (self.work / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertEqual(first, second)
        self.assertEqual(1, first.count(AGENTS_BEGIN))
        self.assertEqual(1, first.count(AGENTS_END))

    def test_agents_md_user_content_preserved(self):
        # specs/installer Scenario「用户内容保护」：区块外用户内容原样保留
        user_text = '# My project\n\nCustom instructions for my team.\n'
        (self.work / 'AGENTS.md').write_text(user_text, encoding='utf-8')
        self.install()
        text = (self.work / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertTrue(text.startswith(user_text))
        self.assertIn(AGENTS_BEGIN, text)
        # 重装后用户内容仍在区块外且不变
        self.install()
        text2 = (self.work / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertTrue(text2.startswith(user_text))
        self.assertEqual(text, text2)

    def test_agents_md_created_when_missing(self):
        # 目标文件不存在时创建
        self.assertFalse((self.work / 'AGENTS.md').exists())
        self.install()
        text = (self.work / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertIn(AGENTS_BEGIN, text)
        self.assertIn(AGENTS_END, text)

    def test_user_struct_file_preserved(self):
        # 清单外用户自建 agent 保留（specs/installer Scenario「用户自建 agent 保留」）
        self.install()
        custom = self.work / '.opencode' / 'agent' / 'my-agent.md'
        custom.write_text('---\ndescription: custom\n---\n用户自定义\n', encoding='utf-8')
        before = count_files(self.work / '.opencode')
        self.install()
        self.assertTrue(custom.is_file())
        self.assertEqual(
            custom.read_text(encoding='utf-8'),
            '---\ndescription: custom\n---\n用户自定义\n')
        # dist 文件不重复（总数不变：清单内哈希跳过 + 清单外保留）
        self.assertEqual(before, count_files(self.work / '.opencode'))


class OpencodeGlobalTests(InstallerSandbox):
    """opencode 全局安装端到端（specs/installer Scenario「opencode 全局安装」）。"""

    def test_global_layout(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'opencode', 'BUDGET_GLOBAL': '1'})
        self.assert_install_ok(result)
        oc = self.home / '.config' / 'opencode'
        self.assertTrue((oc / 'agent' / 'architect.md').is_file())
        self.assertTrue((oc / 'command' / 'budget-start.md').is_file())
        self.assertTrue((oc / 'skill' / 'budget-workflow' / 'SKILL.md').is_file())
        # 管理面 ~/.budgetbuddy/（含 docs/）
        mgmt = self.home / '.budgetbuddy'
        self.assertTrue((mgmt / 'setup.sh').is_file())
        self.assertTrue((mgmt / 'docs' / 'MODEL_SELECTION.md').is_file())
        self.assertTrue((mgmt / '.budget-manifest.json').is_file())
        # AGENTS.md 标记区块（~/.config/opencode/AGENTS.md）
        agents_md = oc / 'AGENTS.md'
        text = agents_md.read_text(encoding='utf-8')
        self.assertIn(AGENTS_BEGIN, text)
        self.assertIn(AGENTS_END, text)
        # 项目目录不受影响
        self.assertFalse((self.work / '.opencode').exists())
        self.assertFalse((self.work / 'AGENTS.md').exists())


def split_manifest_entries(files, prefixes):
    """按平台结构目录前缀拆分 manifest files 键集。

    返回 (struct, mgmt)：struct = 平台结构条目；mgmt = 管理面条目（不含
    *.fragment.md——fragment 走合并不复制，不进本地清单任何字段）。
    """
    struct = {rel for rel in files if rel.startswith(tuple(p + '/' for p in prefixes))}
    rest = set(files) - struct
    mgmt = {rel for rel in rest if not rel.endswith('.fragment.md')}
    return struct, mgmt


class ClaudecodeProjectTests(InstallerSandbox):
    """claudecode 项目级安装端到端（specs/installer Scenario「claudecode 项目级安装」）。"""

    def install(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'claudecode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def test_full_layout(self):
        self.install()
        cc = self.work / '.claude'
        # 平台结构：agents×10 / commands（budget×3 + opsx×4）/ skills×6
        for name in SUITE_AGENTS:
            self.assertTrue((cc / 'agents' / ('%s.md' % name)).is_file(),
                            '缺失 agent: %s' % name)
        for rel in ('budget/start.md', 'budget/status.md', 'budget/goal.md',
                    'opsx/apply.md', 'opsx/archive.md', 'opsx/explore.md',
                    'opsx/propose.md'):
            self.assertTrue((cc / 'commands' / rel).is_file(), '缺失命令: %s' % rel)
        self.assertTrue((cc / 'skills' / 'budget-workflow' / 'SKILL.md').is_file())
        # CLAUDE.fragment.md 不复制为文件（合并进 CLAUDE.md）
        self.assertFalse((cc / 'CLAUDE.fragment.md').exists())
        # hooks 分发 + settings.json 三事件注入（v0.2.1 起，无 superpowers）
        self.assertTrue((cc / 'hooks' / 'budget-notify-hook.py').is_file())
        settings = cc / 'settings.json'
        self.assertTrue(settings.is_file(), 'settings.json 未生成')
        settings_data = load_json(settings)
        hooks = settings_data.get('hooks', {})
        for event in ('Notification', 'PermissionRequest', 'SubagentStop'):
            self.assertIn(event, hooks, '缺失注入事件: %s' % event)
        self.assertIn('budget-notify-hook.py', settings.read_text(encoding='utf-8'))
        self.assertNotIn('enabledPlugins', settings_data)
        # 管理面统一 ~/.budgetbuddy/（与 opencode 共享）
        mgmt = self.home / '.budgetbuddy'
        self.assertTrue((mgmt / 'setup.sh').is_file())
        self.assertTrue((mgmt / 'lib' / 'utils.sh').is_file())
        self.assertTrue((mgmt / 'budget-models.json').is_file())
        self.assertTrue((mgmt / 'personas.json').is_file())
        self.assertTrue((mgmt / 'docs' / 'MODEL_SELECTION.md').is_file())
        # CLAUDE.md 标记区块（项目根）
        claude_md = self.work / 'CLAUDE.md'
        text = claude_md.read_text(encoding='utf-8')
        self.assertIn(AGENTS_BEGIN, text)
        self.assertIn(AGENTS_END, text)
        self.assertIn('budget-leader-no-code:begin', text)
        # 命令包装器
        self.assertTrue((self.home / '.local' / 'bin' / 'budget').is_file())

    def test_local_manifest_prefixed_segment(self):
        """本地清单：platform_files 条目带 claudecode: 前缀（单装命名空间格式）。"""
        self.install()
        local = load_json(self.home / '.budgetbuddy' / '.budget-manifest.json')
        dist = load_json(self.repo / 'dist' / 'claudecode' / '.manifest.json')
        struct, mgmt = split_manifest_entries(
            dist['files'], ('agents', 'commands', 'skills', 'hooks'))
        # files 字段 = 管理面条目（相对 ~/.budgetbuddy/，哈希与 dist 一致）
        self.assertEqual(local['files'],
                         {rel: dist['files'][rel] for rel in sorted(mgmt)})
        # platform_files = claudecode: 前缀平台结构条目
        self.assertEqual(set(local['platform_files']),
                         {'claudecode:' + rel for rel in struct})
        for key, sha in local['platform_files'].items():
            self.assertEqual(sha, dist['files'][key[len('claudecode:'):]], key)
        # fragment 不入任何清单字段（合并产物非复制文件）
        self.assertNotIn('CLAUDE.fragment.md', local['files'])
        self.assertNotIn('CLAUDE.fragment.md', local['platform_files'])

    def test_claude_md_idempotent(self):
        # specs/installer Scenario「幂等重装」：区块内容不变、无重复追加
        self.install()
        first = (self.work / 'CLAUDE.md').read_text(encoding='utf-8')
        self.install()
        second = (self.work / 'CLAUDE.md').read_text(encoding='utf-8')
        self.assertEqual(first, second)
        self.assertEqual(1, first.count(AGENTS_BEGIN))
        self.assertEqual(1, first.count(AGENTS_END))

    def test_claude_md_user_content_preserved(self):
        # specs/installer Scenario「用户内容保护」：区块外用户内容原样保留
        user_text = '# My project\n\nCustom instructions for my team.\n'
        (self.work / 'CLAUDE.md').write_text(user_text, encoding='utf-8')
        self.install()
        text = (self.work / 'CLAUDE.md').read_text(encoding='utf-8')
        self.assertTrue(text.startswith(user_text))
        self.assertIn(AGENTS_BEGIN, text)

    def test_reinstall_all_skipped(self):
        self.install()
        dist = load_json(self.repo / 'dist' / 'claudecode' / '.manifest.json')
        # fragment 走合并不复制，不计入同步统计
        total = len([rel for rel in dist['files']
                     if not rel.endswith('.fragment.md')])
        result = self.install()
        # 幂等重装：全部文件哈希一致跳过（结构 + 管理面两段合计）
        self.assertIn('新增 0 / 更新 0', result.stdout)
        self.assertIn('跳过 %d' % total, result.stdout)


class CoInstallHooksTests(InstallerSandbox):
    """复审 F1/F2/F3：codebuddy/claudecode 共装 hooks 注入互不串写。

    F1 复现场景：codebuddy 先装（.codebuddy/setup.sh 就位，all 模式必现）
    后再装 claudecode——修复前 inject_hooks_claudecode 子进程内
    detect_platform 探测命中 codebuddy，注入错写到 .codebuddy/settings.json
    且 .claude/settings.json 不生成（安装器仍报「hooks 注入完成」假成功）。
    """

    CC_EVENTS = ('Notification', 'PermissionRequest', 'SubagentStop')
    CB_EVENTS = ('Notification', 'PreToolUse', 'SubagentStop')

    def _assert_claudecode_settings(self):
        """claudecode settings：本平台三事件，无 codebuddy 事件/插件键。"""
        path = self.work / '.claude' / 'settings.json'
        self.assertTrue(path.is_file(), 'claudecode settings.json 未生成')
        settings = load_json(path)
        hooks = settings.get('hooks', {})
        for event in self.CC_EVENTS:
            self.assertIn(event, hooks, 'claudecode 缺失注入事件: %s' % event)
        # 互不串写：不含 codebuddy 独有事件与 superpowers 插件键
        self.assertNotIn('PreToolUse', hooks)
        self.assertNotIn('enabledPlugins', settings)
        self.assertIn('budget-notify-hook.py', path.read_text(encoding='utf-8'))

    def _assert_codebuddy_settings(self):
        """codebuddy settings：本平台三事件 + superpowers，无 claudecode 事件。"""
        path = self.work / '.codebuddy' / 'settings.json'
        self.assertTrue(path.is_file(), 'codebuddy settings.json 未生成')
        settings = load_json(path)
        hooks = settings.get('hooks', {})
        for event in self.CB_EVENTS:
            self.assertIn(event, hooks, 'codebuddy 缺失注入事件: %s' % event)
        # 互不串写：不含 claudecode 独有事件
        self.assertNotIn('PermissionRequest', hooks)
        self.assertIn('superpowers@codebuddy-plugins-official',
                      settings.get('enabledPlugins', {}))

    def test_codebuddy_then_claudecode_no_crosswrite(self):
        """F1：codebuddy → claudecode 顺序两装，两 settings 各含本平台
        三事件、互不串写；安装摘要如实指向 .claude/settings.json。"""
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codebuddy', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'claudecode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        self._assert_claudecode_settings()
        self._assert_codebuddy_settings()
        # SUMMARY 真实：hooks 行指向 .claude/settings.json 且报注入完成
        self.assertIn('.claude/settings.json', result.stdout)
        self.assertIn('hooks 注入完成', result.stdout)

    def test_all_mode_settings_per_platform(self):
        """all 模式（cb/oc/cc 顺序三装）：两 settings 各含本平台三事件
        （互不串写），opencode 无 settings 注入（无 hooks 机制）。"""
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'all', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        self._assert_claudecode_settings()
        self._assert_codebuddy_settings()
        self.assertFalse((self.work / '.opencode' / 'settings.json').exists())
        self.assertIn('hooks 注入完成', result.stdout)

    def test_inject_failure_degrades_to_warning(self):
        """F2：注入失败（settings.json 路径被占位目录阻断原子写）→
        安装不阻断（rc 0）、降级警告文案、SUMMARY 如实呈现注入失败。"""
        # 占位目录：引擎对 settings.json 的原子写（os.replace 到目录）必然
        # 失败 → 子进程回传 INJECT_RESULT=failed（修复前 exit 0 假成功）
        (self.work / '.claude').mkdir()
        (self.work / '.claude' / 'settings.json').mkdir()
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'claudecode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        self.assertIn('hooks 注入失败', result.stdout)
        self.assertNotIn('hooks 注入完成', result.stdout)
        # SUMMARY 如实呈现失败（不再输出落点行假成功）
        self.assertIn('注入失败（可运行 budget setup init 补全）', result.stdout)
        self.assertNotIn(
            '%s/settings.json（Notification' % (self.work / '.claude'),
            result.stdout)


class CoInstallManifestTests(InstallerSandbox):
    """复审 C1-①：write_local_manifest 合并写（多平台共装两段并存）。"""

    def install_opencode(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'opencode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def install_claudecode(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'claudecode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def test_dual_platform_segments_coexist(self):
        """共装两段并存：opencode 无前缀段 + claudecode: 前缀段，值与各自
        dist manifest 一致；files 段合并写保留他平台管理面条目。"""
        self.install_opencode()
        self.install_claudecode()
        local = load_json(self.home / '.budgetbuddy' / '.budget-manifest.json')
        oc_dist = load_json(self.repo / 'dist' / 'opencode' / '.manifest.json')
        cc_dist = load_json(self.repo / 'dist' / 'claudecode' / '.manifest.json')
        oc_struct, oc_mgmt = split_manifest_entries(
            oc_dist['files'], ('agent', 'command', 'skill'))
        cc_struct, cc_mgmt = split_manifest_entries(
            cc_dist['files'], ('agents', 'commands', 'skills', 'hooks'))
        # opencode 段：无前缀键（历史格式，后装不覆盖先装）
        self.assertEqual(
            {k for k in local['platform_files'] if ':' not in k}, oc_struct)
        for rel in oc_struct:
            self.assertEqual(local['platform_files'][rel], oc_dist['files'][rel], rel)
        # claudecode 段：claudecode: 前缀键
        self.assertEqual(
            {k for k in local['platform_files'] if k.startswith('claudecode:')},
            {'claudecode:' + rel for rel in cc_struct})
        for rel in cc_struct:
            self.assertEqual(
                local['platform_files']['claudecode:' + rel], cc_dist['files'][rel], rel)
        # files 合并写：claudecode 管理面 + opencode 独有管理面（磁盘仍存在者，
        # 如 docs/setup-notes.md）
        self.assertEqual(set(local['files']), cc_mgmt | oc_mgmt)
        self.assertIn('docs/setup-notes.md', local['files'])
        # 两平台结构文件并存落盘
        self.assertTrue((self.work / '.opencode' / 'agent' / 'architect.md').is_file())
        self.assertTrue((self.work / '.claude' / 'agents' / 'architect.md').is_file())

    def test_files_disk_existence_filter(self):
        """files 磁盘存在性过滤：他平台管理面条目对应文件已从磁盘删除 →
        claudecode 合并写不延续该条目。"""
        self.install_opencode()
        stale = self.home / '.budgetbuddy' / 'docs' / 'setup-notes.md'
        self.assertTrue(stale.is_file())
        stale.unlink()
        self.install_claudecode()
        local = load_json(self.home / '.budgetbuddy' / '.budget-manifest.json')
        self.assertNotIn('docs/setup-notes.md', local['files'])


class UpgradeNamespaceTests(InstallerSandbox):
    """复审 C1-②：upgrade_diff_cleanup 命名空间解析（对既有安装升级模拟）。"""

    def install_opencode(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'opencode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def install_claudecode(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'claudecode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def _drop_from_dist(self, platform, rel):
        """从 mini 仓库 dist 清单与磁盘移除一个产物文件（模拟新版下线）。"""
        manifest_path = self.repo / 'dist' / platform / '.manifest.json'
        manifest = load_json(manifest_path)
        del manifest['files'][rel]
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
        (self.repo / 'dist' / platform / rel).unlink()

    def test_claudecode_upgrade_cleans_only_own_segment(self):
        """platform_files:claudecode 去前缀仅取本平台段：升级清理删除
        .claude/ 陈旧文件，opencode 段与其落盘文件不受影响。"""
        self.install_opencode()
        self.install_claudecode()
        self._drop_from_dist('claudecode', 'agents/goal-evaluator.md')
        result = self.install_claudecode()
        self.assertIn('差集清理', result.stdout)
        self.assertFalse((self.work / '.claude' / 'agents' / 'goal-evaluator.md').exists())
        self.assertTrue((self.work / '.opencode' / 'agent' / 'goal-evaluator.md').is_file())
        local = load_json(self.home / '.budgetbuddy' / '.budget-manifest.json')
        self.assertNotIn('claudecode:agents/goal-evaluator.md', local['platform_files'])
        self.assertIn('agent/goal-evaluator.md', local['platform_files'])

    def test_opencode_upgrade_cleans_only_own_segment(self):
        """无后缀 platform_files 仅取无冒号键：opencode 升级清理删除
        .opencode/ 陈旧文件，claudecode: 前缀段与其落盘文件不受影响。"""
        self.install_opencode()
        self.install_claudecode()
        self._drop_from_dist('opencode', 'agent/goal-evaluator.md')
        result = self.install_opencode()
        self.assertIn('差集清理', result.stdout)
        self.assertFalse((self.work / '.opencode' / 'agent' / 'goal-evaluator.md').exists())
        self.assertTrue((self.work / '.claude' / 'agents' / 'goal-evaluator.md').is_file())
        local = load_json(self.home / '.budgetbuddy' / '.budget-manifest.json')
        self.assertNotIn('agent/goal-evaluator.md', local['platform_files'])
        self.assertIn('claudecode:agents/goal-evaluator.md', local['platform_files'])

    def test_mgmt_cleanup_skipped_when_co_installed(self):
        """共装 guard：claudecode 升级跳过管理面差集清理，opencode 独有
        管理面文件（docs/setup-notes.md）不被误删。"""
        self.install_opencode()
        result = self.install_claudecode()
        self.assertIn('检测到其他平台共装', result.stdout)
        self.assertIn('跳过管理面差集清理', result.stdout)
        self.assertTrue(
            (self.home / '.budgetbuddy' / 'docs' / 'setup-notes.md').is_file())


class OtherPlatformDetectionTests(InstallerSandbox):
    """复审 C1-③：local_manifest_other_platform 共装判定三视角。"""

    def test_claudecode_view_unprefixed_keys_are_other(self):
        # claudecode 视角：无冒号键（opencode 历史格式）= 他平台 → 1
        # → claudecode 安装跳过管理面差集清理
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'opencode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'claudecode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        self.assertIn('检测到其他平台共装', result.stdout)

    def test_opencode_view_prefixed_keys_are_other(self):
        # opencode 视角：带前缀键（claudecode:）= 他平台 → 1
        # → opencode 重装跳过管理面差集清理
        for platform in ('opencode', 'claudecode'):
            result = self.run_install(
                env_extra={'BUDGET_PLATFORM': platform, 'BUDGET_GLOBAL': '0'})
            self.assert_install_ok(result)
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'opencode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        self.assertIn('检测到其他平台共装', result.stdout)

    def test_missing_manifest_means_no_other(self):
        # 清单缺失 = 0：单装无共装提示，管理面差集清理正常执行
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'claudecode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        self.assertNotIn('检测到其他平台共装', result.stdout)
        self.assertNotIn('跳过管理面差集清理', result.stdout)


class UpgradeTests(InstallerSandbox):
    """升级语义：哈希变化覆盖、差集清理、本地清单刷新。"""

    def install_opencode(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'opencode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def test_hash_change_overwritten(self):
        # specs/installer Scenario「变更文件覆盖」：清单内文件哈希变化 → 覆盖
        self.install_opencode()
        target = self.repo / 'dist' / 'opencode' / 'agent' / 'architect.md'
        target.write_text(
            '---\ndescription: upgraded architect\n---\nnew body\n', encoding='utf-8')
        manifest_path = self.repo / 'dist' / 'opencode' / '.manifest.json'
        manifest = load_json(manifest_path)
        manifest['files']['agent/architect.md'] = sha256_of(target)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
        result = self.install_opencode()
        self.assertIn('更新 1', result.stdout)
        installed = self.work / '.opencode' / 'agent' / 'architect.md'
        self.assertIn('upgraded architect', installed.read_text(encoding='utf-8'))
        # 本地清单同步刷新为新哈希
        local = load_json(self.home / '.budgetbuddy' / '.budget-manifest.json')
        self.assertEqual(
            local['platform_files']['agent/architect.md'], sha256_of(target))

    def test_diff_cleanup_removes_stale_file(self):
        # specs/installer Scenario「升级差集清理」：新版 manifest 不含本地
        # 旧清单中的某文件 → 升级时清理；清单外用户自建文件不受影响
        self.install_opencode()
        stale_rel = 'skill/openspec-explore/SKILL.md'
        manifest_path = self.repo / 'dist' / 'opencode' / '.manifest.json'
        manifest = load_json(manifest_path)
        del manifest['files'][stale_rel]
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
        (self.repo / 'dist' / 'opencode' / stale_rel).unlink()
        # 用户自建文件（清单外）
        custom = self.work / '.opencode' / 'agent' / 'my-agent.md'
        custom.write_text('user custom\n', encoding='utf-8')
        result = self.install_opencode()
        self.assertIn('差集清理', result.stdout)
        self.assertFalse((self.work / '.opencode' / stale_rel).exists())
        self.assertTrue(custom.is_file())
        # 本地清单不再含旧条目
        local = load_json(self.home / '.budgetbuddy' / '.budget-manifest.json')
        self.assertNotIn(stale_rel, local['platform_files'])

    def test_diff_cleanup_codebuddy_mgmt_root(self):
        # codebuddy 形态差集清理（管理面与结构同根，files 单字段）
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codebuddy', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        stale_rel = 'rules/budget-rtk.mdc'
        manifest_path = self.repo / 'dist' / 'codebuddy' / '.manifest.json'
        manifest = load_json(manifest_path)
        del manifest['files'][stale_rel]
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
        (self.repo / 'dist' / 'codebuddy' / stale_rel).unlink()
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codebuddy', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        self.assertFalse((self.work / '.codebuddy' / stale_rel).exists())

    def test_interrupted_install_recovers(self):
        # specs/installer Scenario「安装中断恢复」：删除部分已装文件（模拟
        # 中断）后重跑 → 按哈希跳过已完成部分、补齐缺失部分，恢复完成
        self.install_opencode()
        # 模拟中断：删掉若干已装文件（清单仍在）
        (self.work / '.opencode' / 'agent' / 'architect.md').unlink()
        (self.home / '.budgetbuddy' / 'lib' / 'utils.sh').unlink()
        result = self.install_opencode()
        self.assert_install_ok(result)
        self.assertTrue((self.work / '.opencode' / 'agent' / 'architect.md').is_file())
        self.assertTrue((self.home / '.budgetbuddy' / 'lib' / 'utils.sh').is_file())
        # AGENTS.md 合并幂等（无重复区块）
        text = (self.work / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertEqual(1, text.count(AGENTS_BEGIN))


class AutoRunReplayTests(InstallerSandbox):
    """agent-autorun install.sh 集成面（design.md D4/D5、installer spec 2.5 钩子）。

    复用既有 harness（mini 仓库 + dist 副本 + HOME 隔离沙盒）subprocess 驱动
    install.sh 端到端，覆盖 installer spec 的 4 个 MUST 场景：

    ① 钩子落点：upgrade_diff_cleanup 之后、write_local_manifest 之前
       （stdout 消息顺序佐证；codebuddy 模式 write_local_manifest 照抄 dist
       清单哈希，落点只能以消息顺序 + apply 实效双重佐证）；状态文件存在时
       apply 被调用且 reviewer 的 enabledAutoRun 恢复；
    ② 无状态文件不重放（dist 默认 4 个在位）；
    ③ 损坏状态文件 apply 失败仅告警不阻断、安装完成与状态文件字节不变；
    ④ 二次安装 apply 幂等（无状态/默认一致时同步全跳过；非默认状态下同步
       先以 dist 重覆盖偏差 agent 再由 apply 重放，终态一致、字节稳定）。
    """

    # dist 构建产物默认开启 AutoRun 的 4 个执行类 agent（Task 1.1）
    DEFAULT_ON = ('coder-lite', 'coder-senior', 'coder-standard', 'tester')
    # 清单外（默认关闭）agent
    DEFAULT_OFF = ('architect', 'director', 'goal-evaluator', 'recorder',
                   'reviewer-b')

    def install_codebuddy(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codebuddy', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def _state_path(self):
        return self.home / '.budgetbuddy' / 'auto-run.json'

    def _write_state(self, agents):
        """写状态文件（与 autorun.write_state_file 同序列化口径）。"""
        content = json.dumps(
            {'agents': sorted(set(agents))}, indent=2, sort_keys=True) + '\n'
        self._state_path().parent.mkdir(parents=True, exist_ok=True)
        self._state_path().write_bytes(content.encode('utf-8'))

    def _agents_dir(self):
        return self.work / '.codebuddy' / 'agents'

    def _dist_agents_dir(self):
        return self.repo / 'dist' / 'codebuddy' / 'agents'

    def _agent_path(self, name):
        return self._agents_dir() / (name + '.md')

    def _agent_bytes(self, name):
        return self._agent_path(name).read_bytes()

    def _agent_has_autorun(self, name):
        return 'enabledAutoRun: true' in self._agent_path(name).read_text(
            encoding='utf-8')

    def _assert_agents_match_dist(self):
        """断言 agents 目录 10 个 .md 与 mini 仓库 dist 逐字节一致（无补丁漂移）。"""
        for name in SUITE_AGENTS:
            self.assertEqual(
                self._agent_bytes(name),
                (self._dist_agents_dir() / (name + '.md')).read_bytes(), name)

    def _drop_from_dist(self, rel):
        """从 mini 仓库 dist 清单与磁盘移除一个产物文件（模拟新版下线）。"""
        manifest_path = self.repo / 'dist' / 'codebuddy' / '.manifest.json'
        manifest = load_json(manifest_path)
        del manifest['files'][rel]
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
        (self.repo / 'dist' / 'codebuddy' / rel).unlink()

    def _assert_replay_outcome(self):
        """apply 重放终态：清单内开启（默认 4 + reviewer）、清单外无行。

        按实际安装集断言（升级路径下被 dist 下线的 agent 已不在场）。
        """
        installed = {path.stem for path in self._agents_dir().glob('*.md')}
        for name in self.DEFAULT_ON + ('reviewer',):
            if name in installed:
                self.assertTrue(self._agent_has_autorun(name), '%s 未开启' % name)
        for name in self.DEFAULT_OFF:
            if name in installed:
                self.assertFalse(self._agent_has_autorun(name), '%s 误开启' % name)

    # ── ① 钩子落点 ─────────────────────────────────────────────────────────

    def test_replay_hook_restores_reviewer(self):
        """状态文件存在（用户曾 on reviewer）→ apply 被调用、reviewer 恢复；
        钩子落点于 sync 之后、write_local_manifest 之前（stdout 消息顺序）。"""
        self._write_state(self.DEFAULT_ON + ('reviewer',))
        result = self.install_codebuddy()
        self.assertIn('AutoRun 状态重放完成', result.stdout)
        # reviewer 的 enabledAutoRun 恢复（dist 默认无该行，唯 apply 可写回）
        self._assert_replay_outcome()
        # 落点佐证：文件同步完成 < 状态重放完成 < 本地清单写入
        stdout = result.stdout
        self.assertIn('文件同步完成', stdout)
        self.assertIn('本地安装清单已写入', stdout)
        self.assertLess(
            stdout.index('文件同步完成'),
            stdout.index('AutoRun 状态重放完成'))
        self.assertLess(
            stdout.index('AutoRun 状态重放完成'),
            stdout.index('本地安装清单已写入'))

    def test_replay_hook_after_cleanup_before_manifest(self):
        """落点佐证（升级路径）：差集清理先于重放——dist 下线的 agent 已删，
        apply 视角其未安装（告警跳过）；消息顺序 同步 < 清理 < 重放 < 清单。"""
        # 先装一版（10 agent 全集），再从 dist 下线 reviewer-b 触发差集清理
        self.install_codebuddy()
        self._drop_from_dist('agents/reviewer-b.md')
        # 状态清单含已下线的 reviewer-b（apply 应告警跳过而非失败）
        self._write_state(self.DEFAULT_ON + ('reviewer', 'reviewer-b'))
        result = self.install_codebuddy()
        self.assert_install_ok(result)
        # 清理先于重放：stale 文件已删 + apply 未见该 agent
        self.assertFalse(self._agent_path('reviewer-b').exists())
        self.assertIn('未安装（跳过）: reviewer-b', result.stderr)
        # 消息顺序：同步 < 差集清理 < 状态重放 < 清单写入
        stdout = result.stdout
        self.assertIn('差集清理', stdout)
        self.assertLess(stdout.index('文件同步完成'), stdout.index('差集清理'))
        self.assertLess(
            stdout.index('差集清理'), stdout.index('AutoRun 状态重放完成'))
        self.assertLess(
            stdout.index('AutoRun 状态重放完成'),
            stdout.index('本地安装清单已写入'))
        # 重放对在场 agent 照常完成
        self._assert_replay_outcome()

    # ── ② 无状态文件不重放 ─────────────────────────────────────────────────

    def test_no_state_file_skips_replay(self):
        """无状态文件 → 不重放：无重放消息、dist 默认 4 个在位、不创建状态
        文件、安装态与 dist 逐字节一致（无 apply 补丁漂移）。"""
        result = self.install_codebuddy()
        self.assertNotIn('AutoRun 状态重放', result.stdout)
        for name in self.DEFAULT_ON:
            self.assertTrue(self._agent_has_autorun(name), name)
        for name in self.DEFAULT_OFF + ('reviewer',):
            self.assertFalse(self._agent_has_autorun(name), name)
        self.assertFalse(self._state_path().exists())
        self._assert_agents_match_dist()

    # ── ③ 损坏状态文件仅告警不阻断 ─────────────────────────────────────────

    def test_corrupt_state_warns_without_blocking(self):
        """状态文件损坏 → apply 失败仅告警不阻断：安装完成（rc 0 + 清单写入）、
        告警文案、状态文件字节不变；apply 中止于损坏校验，agent 保持 dist 默认态。"""
        raw = '{ 这不是合法 JSON'
        self._state_path().parent.mkdir(parents=True, exist_ok=True)
        self._state_path().write_bytes(raw.encode('utf-8'))
        result = self.install_codebuddy()
        self.assertEqual(result.returncode, 0)
        self.assertIn('AutoRun 状态重放失败', result.stdout)
        self.assertNotIn('AutoRun 状态重放完成', result.stdout)
        self.assertIn('本地安装清单已写入', result.stdout)
        # 状态文件字节不变（绝不覆盖写）
        self.assertEqual(self._state_path().read_bytes(), raw.encode('utf-8'))
        # agent 文件保持 dist 默认态（apply 未触碰任何文件）
        self._assert_agents_match_dist()

    # ── ④ 二次安装 apply 幂等 ──────────────────────────────────────────────

    def test_reinstall_without_state_all_skipped(self):
        """无状态/默认一致：二次安装同步全跳过、不重放、字节稳定。"""
        self.install_codebuddy()
        dist = load_json(self.repo / 'dist' / 'codebuddy' / '.manifest.json')
        total = len(dist['files'])
        first_bytes = {name: self._agent_bytes(name) for name in SUITE_AGENTS}
        result = self.install_codebuddy()
        self.assertIn('新增 0 / 更新 0 / 跳过 %d' % total, result.stdout)
        self.assertNotIn('AutoRun 状态重放', result.stdout)
        self.assertFalse(self._state_path().exists())
        for name in SUITE_AGENTS:
            self.assertEqual(self._agent_bytes(name), first_bytes[name], name)

    def test_reinstall_with_state_replay_idempotent(self):
        """非默认状态（默认 4 + reviewer）：首次安装 apply 补放后，模拟用户/IDE
        偏差改写 reviewer.md，二次安装同步先以 dist 重覆盖偏差 agent（更新 1）、
        再由 apply 重放，终态与首次补放后逐字节一致；三次安装字节稳定。"""
        self._write_state(self.DEFAULT_ON + ('reviewer',))
        self.install_codebuddy()
        first_bytes = {name: self._agent_bytes(name) for name in SUITE_AGENTS}
        self._assert_replay_outcome()
        # 模拟偏差：reviewer.md 被追加用户内容（脱离 dist 与补丁态）
        reviewer_path = self._agent_path('reviewer')
        reviewer_path.write_bytes(
            reviewer_path.read_bytes() + b'\n<!-- user edit -->\n')
        # 二次安装：同步重覆盖偏差 agent → apply 重放
        result = self.install_codebuddy()
        self.assertIn('更新 1', result.stdout)
        self.assertIn('AutoRun 状态重放完成', result.stdout)
        self._assert_replay_outcome()
        # 终态一致：与首次安装补放后逐字节相同（偏差被抹平）
        for name in SUITE_AGENTS:
            self.assertEqual(self._agent_bytes(name), first_bytes[name], name)
        # 三次安装：同步重覆盖 → apply 重放循环，字节稳定
        result = self.install_codebuddy()
        self.assertIn('AutoRun 状态重放完成', result.stdout)
        for name in SUITE_AGENTS:
            self.assertEqual(self._agent_bytes(name), first_bytes[name], name)


# ---------------------------------------------------------------------------
# codex 平台安装（add-codex-platform D4，任务 4.1）
# ---------------------------------------------------------------------------

CODEX_SKILLS = (
    'budget-workflow', 'budget-notify', 'openspec-apply-change',
    'openspec-archive-change', 'openspec-explore', 'openspec-propose',
)
CODEX_COMMANDS = (
    'budget-start.md', 'budget-status.md', 'budget-goal.md',
    'opsx-apply.md', 'opsx-archive.md', 'opsx-explore.md', 'opsx-propose.md',
)
CODEX_RULES_COUNT = 12


class CodexProjectTests(InstallerSandbox):
    """codex 项目级安装端到端（specs/installer codex Scenario）。

    结构前缀仅 skills/（skill 形态产物）；AGENTS.fragment.md 轻量区块合并进
    项目根 AGENTS.md（不落盘副本）；config.toml [features] multi_agent 幂等
    注入；管理面 ~/.budgetbuddy/（与 opencode/claudecode 共享）；本地清单
    codex: 前缀段。
    """

    def install(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codex', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def test_full_layout(self):
        result = self.install()
        cx = self.work / '.codex'
        # skill 落点：6 个 skill 全集 + budget-workflow 内部结构。
        for skill in CODEX_SKILLS:
            self.assertTrue((cx / 'skills' / skill / 'SKILL.md').is_file(),
                            '缺失 skill: %s' % skill)
        bw = cx / 'skills' / 'budget-workflow'
        for name in SUITE_AGENTS:
            self.assertTrue((bw / 'agents' / ('%s.md' % name)).is_file(),
                            '缺失 agent 素材: %s' % name)
        for rel in CODEX_COMMANDS:
            self.assertTrue((bw / 'commands' / rel).is_file(), '缺失命令: %s' % rel)
        rules = sorted(p.name for p in (bw / 'rules').glob('*.md'))
        self.assertEqual(len(rules), CODEX_RULES_COUNT, rules)
        self.assertTrue((bw / 'codex-runtime.md').is_file())
        # AGENTS.fragment.md 不复制为文件（合并进 AGENTS.md）。
        self.assertFalse((cx / 'AGENTS.fragment.md').exists())
        # config.toml 注入。
        config = (cx / 'config.toml').read_text(encoding='utf-8')
        self.assertIn('[features]', config)
        self.assertTrue(any(
            line.strip().replace(' ', '') == 'multi_agent=true'
            for line in config.splitlines()), config)
        # AGENTS.md 轻量区块（项目根）。
        agents_md = self.work / 'AGENTS.md'
        text = agents_md.read_text(encoding='utf-8')
        self.assertIn(AGENTS_BEGIN, text)
        self.assertIn(AGENTS_END, text)
        self.assertIn('# BudgetBuddy 规则索引', text)
        self.assertNotIn('budget-leader-no-code:begin', text)  # 轻量索引非全文合并
        # 管理面 ~/.budgetbuddy/。
        mgmt = self.home / '.budgetbuddy'
        self.assertTrue((mgmt / 'setup.sh').is_file())
        self.assertTrue((mgmt / 'lib' / 'utils.sh').is_file())
        self.assertTrue((mgmt / 'budget-models.json').is_file())
        self.assertTrue((mgmt / 'personas.json').is_file())
        self.assertTrue((mgmt / 'docs' / 'MODEL_SELECTION.md').is_file())
        # 命令包装器。
        self.assertTrue((self.home / '.local' / 'bin' / 'budget').is_file())
        # 摘要如实呈现 codex 形态。
        self.assertIn('Codex（项目级）', result.stdout)
        self.assertIn('config.toml（[features] multi_agent = true）', result.stdout)
        self.assertIn('自然语言触发 budget-workflow skill', result.stdout)

    def test_local_manifest_codex_prefix_segment(self):
        """本地清单：platform_files 条目带 codex: 前缀（结构前缀仅 skills/）。"""
        self.install()
        local = load_json(self.home / '.budgetbuddy' / '.budget-manifest.json')
        dist = load_json(self.repo / 'dist' / 'codex' / '.manifest.json')
        struct, mgmt = split_manifest_entries(dist['files'], ('skills',))
        # files 字段 = 管理面条目（相对 ~/.budgetbuddy/，哈希与 dist 一致）。
        self.assertEqual(local['files'],
                         {rel: dist['files'][rel] for rel in sorted(mgmt)})
        # platform_files = codex: 前缀平台结构条目。
        self.assertEqual(set(local['platform_files']),
                         {'codex:' + rel for rel in struct})
        for key, sha in local['platform_files'].items():
            self.assertEqual(sha, dist['files'][key[len('codex:'):]], key)
        # fragment 不入任何清单字段（合并产物非复制文件）。
        self.assertNotIn('AGENTS.fragment.md', local['files'])
        self.assertNotIn('AGENTS.fragment.md', local['platform_files'])

    def test_agents_md_idempotent(self):
        """幂等重装：AGENTS.md 区块内容不变、config 单键。"""
        self.install()
        first = (self.work / 'AGENTS.md').read_text(encoding='utf-8')
        first_config = (self.work / '.codex' / 'config.toml').read_text(encoding='utf-8')
        result = self.install()
        second = (self.work / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertEqual(first, second)
        self.assertEqual(1, first.count(AGENTS_BEGIN))
        self.assertEqual(1, first.count(AGENTS_END))
        self.assertEqual(
            first_config,
            (self.work / '.codex' / 'config.toml').read_text(encoding='utf-8'))
        self.assertEqual(1, first_config.count('multi_agent'))
        self.assertIn('跳过注入', result.stdout)

    def test_agents_md_user_content_preserved(self):
        """用户内容保护：区块外用户内容原样保留。"""
        user_text = '# My project\n\nCustom instructions for my agents.\n'
        (self.work / 'AGENTS.md').write_text(user_text, encoding='utf-8')
        self.install()
        text = (self.work / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertTrue(text.startswith(user_text))
        self.assertIn(AGENTS_BEGIN, text)

    def test_reinstall_all_skipped(self):
        self.install()
        dist = load_json(self.repo / 'dist' / 'codex' / '.manifest.json')
        total = len([rel for rel in dist['files']
                     if not rel.endswith('.fragment.md')])
        result = self.install()
        self.assertIn('新增 0 / 更新 0', result.stdout)
        self.assertIn('跳过 %d' % total, result.stdout)


class CodexGlobalTests(InstallerSandbox):
    """codex 全局安装端到端：~/.codex/ 落点 + ~/.codex/AGENTS.md。"""

    def test_global_layout(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codex', 'BUDGET_GLOBAL': '1'})
        self.assert_install_ok(result)
        cx = self.home / '.codex'
        self.assertTrue((cx / 'skills' / 'budget-workflow' / 'SKILL.md').is_file())
        self.assertTrue((cx / 'skills' / 'budget-workflow' / 'agents'
                         / 'architect.md').is_file())
        self.assertTrue((cx / 'skills' / 'budget-workflow' / 'rules').is_dir())
        self.assertTrue((cx / 'config.toml').is_file())
        config = (cx / 'config.toml').read_text(encoding='utf-8')
        self.assertTrue(any(
            line.strip().replace(' ', '') == 'multi_agent=true'
            for line in config.splitlines()), config)
        agents_md = (cx / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertIn(AGENTS_BEGIN, agents_md)
        self.assertIn('# BudgetBuddy 规则索引', agents_md)
        # 管理面 ~/.budgetbuddy/。
        self.assertTrue((self.home / '.budgetbuddy' / 'setup.sh').is_file())
        # 项目目录不受影响。
        self.assertFalse((self.work / '.codex').exists())
        self.assertFalse((self.work / 'AGENTS.md').exists())


class CodexConfigInjectTests(InstallerSandbox):
    """inject_codex_config 四态（文本级幂等注入，design D4）。

    经完整安装驱动（BUDGET_PLATFORM=codex），预置 .codex/config.toml 各形态
    内容，断言注入结果、备份、其他配置零触碰。
    """

    def _seed_config(self, text):
        target = self.work / '.codex' / 'config.toml'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        return target

    def _install(self):
        return self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codex', 'BUDGET_GLOBAL': '0'})

    @staticmethod
    def _has_key_true(text):
        return any(line.strip().replace(' ', '') == 'multi_agent=true'
                   for line in text.splitlines())

    def test_state1_existing_true_skips_with_spacing_tolerance(self):
        """① 含键跳过：容忍 = 两侧空格差异（true / 无空格 / 多空格）。"""
        for content in ('[features]\nmulti_agent = true\n',
                        '[features]\nmulti_agent=true\n',
                        '[features]\nmulti_agent  =  true\n'):
            target = self._seed_config(content)
            result = self._install()
            self.assert_install_ok(result)
            self.assertEqual(target.read_text(encoding='utf-8'), content)
            self.assertIn('已含 multi_agent = true，跳过注入', result.stdout)
            self.assertFalse((target.parent / 'config.toml.bak-budget').exists())
            # 段内其他键零触碰。
            self._seed_config('[features]\nfoo = "bar"\nmulti_agent = true\n')
            result = self._install()
            self.assert_install_ok(result)
            self.assertIn('foo = "bar"', target.read_text(encoding='utf-8'))

    def test_state2_explicit_false_respected_with_warning(self):
        """② 显式 false：尊重用户配置零写入，告警 spawn 工具不可用，摘要如实。"""
        content = '[features]\nmulti_agent = false\n'
        target = self._seed_config(content)
        result = self._install()
        self.assert_install_ok(result)
        self.assertEqual(target.read_text(encoding='utf-8'), content)
        self.assertIn('尊重用户配置不注入', result.stdout)
        self.assertIn('spawn 工具', result.stdout)
        self.assertIn('multi_agent 被用户显式关闭（spawn 工具不可用）',
                      result.stdout)
        self.assertFalse((target.parent / 'config.toml.bak-budget').exists())

    def test_state3_section_missing_key_injected_into_section(self):
        """③ 段缺键：段内追加（下一个段头前），其他段零触碰，备份原始内容。"""
        content = '[features]\nfoo = "bar"\n\n[other]\nx = 1\n'
        target = self._seed_config(content)
        result = self._install()
        self.assert_install_ok(result)
        text = target.read_text(encoding='utf-8')
        self.assertIn('已在 config.toml [features] 段内注入', result.stdout)
        self.assertTrue(self._has_key_true(text))
        # 注入位于 [features] 段内（[other] 之前）。
        self.assertLess(text.index('multi_agent'), text.index('[other]'))
        self.assertIn('foo = "bar"', text)
        self.assertIn('x = 1', text)
        backup = target.parent / 'config.toml.bak-budget'
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_text(encoding='utf-8'), content)

    def test_state4_no_section_appended_at_end(self):
        """④ 无段：文末追加 [features] 段，原有内容保留，备份创建。"""
        content = 'model = "gpt-5"\n'
        target = self._seed_config(content)
        result = self._install()
        self.assert_install_ok(result)
        text = target.read_text(encoding='utf-8')
        self.assertIn('已在 config.toml 文末追加', result.stdout)
        self.assertIn('model = "gpt-5"', text)
        self.assertTrue(self._has_key_true(text))
        self.assertGreater(text.index('[features]'), text.index('model ='))
        self.assertEqual(
            (target.parent / 'config.toml.bak-budget').read_text(encoding='utf-8'),
            content)

    def test_section_header_line_start_precision(self):
        """段头行首精确匹配：缩进 [features] 与 [features.xxx] 子段均不误判。"""
        content = '  [features]\nfoo = 1\n'
        target = self._seed_config(content)
        result = self._install()
        self.assert_install_ok(result)
        text = target.read_text(encoding='utf-8')
        self.assertIn('已在 config.toml 文末追加', result.stdout)
        self.assertTrue(self._has_key_true(text))
        # 追加段在文末（缩进伪段头之后），伪段头未被注入键。
        self.assertGreater(text.index('\n[features]'),
                           text.index('  [features]'))
        self.assertIn('foo = 1', text)

    def test_features_subsection_decoy_not_matched(self):
        """[features.xxx] 子段含 multi_agent = false 不误判为段：
        仍文末追加真正的 [features] 段，子段内容零触碰。"""
        content = '[features.xxx]\nmulti_agent = false\nfoo = 1\n'
        target = self._seed_config(content)
        result = self._install()
        self.assert_install_ok(result)
        text = target.read_text(encoding='utf-8')
        self.assertIn('已在 config.toml 文末追加', result.stdout)
        # 子段保持原样（其 multi_agent = false 未被视作 [features] 段内键）。
        self.assertIn('[features.xxx]\nmulti_agent = false\n', text)
        # 新段独立存在于文末且含注入键。
        self.assertIn('\n[features]\nmulti_agent = true\n', text)

    def test_backup_not_overwritten_on_reinstall(self):
        """备份不覆盖原始恢复点：二次安装（exists 态）不触碰备份。"""
        content = '[features]\nfoo = "bar"\n'
        target = self._seed_config(content)
        self._install()
        backup = target.parent / 'config.toml.bak-budget'
        self.assertEqual(backup.read_text(encoding='utf-8'), content)
        self._install()
        self.assertEqual(backup.read_text(encoding='utf-8'), content)

    def test_injection_failure_degrades_to_warning(self):
        """注入失败（config.toml 为目录阻断原子写）→ 告警不阻断，摘要如实。"""
        (self.work / '.codex').mkdir(parents=True)
        (self.work / '.codex' / 'config.toml').mkdir()
        result = self._install()
        self.assert_install_ok(result)
        self.assertIn('注入失败（可手动添加 [features] multi_agent = true）',
                      result.stdout)
        self.assertIn('config:    注入失败', result.stdout)


class CodexBlockShapeWarningTests(InstallerSandbox):
    """codex AGENTS.md 既有区块异形态检测（D4：opencode 全文形态告警）。"""

    def _seed_agents_md(self, inner_lines):
        block = ['<!-- BudgetBuddy:begin -->']
        block += ['全文规则行 %d' % i for i in range(1, inner_lines + 1)]
        block.append('<!-- BudgetBuddy:end -->')
        (self.work / 'AGENTS.md').write_text('\n'.join(block) + '\n',
                                             encoding='utf-8')

    def _install(self):
        return self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codex', 'BUDGET_GLOBAL': '0'})

    def test_opencode_fulltext_block_warns(self):
        """既有区块 >100 行（opencode 全文形态特征）→ 告警混装风险，合并照常。"""
        self._seed_agents_md(120)
        result = self._install()
        self.assert_install_ok(result)
        self.assertIn('检测到 OpenCode 全文区块', result.stdout)
        self.assertIn('120', result.stdout)
        self.assertIn('混装', result.stdout)
        # 合并未阻断：区块仍唯一且已替换为轻量索引形态。
        text = (self.work / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertEqual(1, text.count(AGENTS_BEGIN))
        self.assertIn('# BudgetBuddy 规则索引', text)

    def test_light_block_no_warning(self):
        """既有区块 ≤100 行（轻量形态）→ 无异形态告警。"""
        self._seed_agents_md(5)
        result = self._install()
        self.assert_install_ok(result)
        self.assertNotIn('检测到 OpenCode 全文区块', result.stdout)


class CodexCoInstallManifestTests(InstallerSandbox):
    """codex 与 opencode 双装：清单 codex: 前缀段与 opencode 无前缀段并存。"""

    def install_opencode(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'opencode', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def install_codex(self):
        result = self.run_install(
            env_extra={'BUDGET_PLATFORM': 'codex', 'BUDGET_GLOBAL': '0'})
        self.assert_install_ok(result)
        return result

    def test_dual_platform_segments_coexist(self):
        self.install_opencode()
        self.install_codex()
        local = load_json(self.home / '.budgetbuddy' / '.budget-manifest.json')
        oc_dist = load_json(self.repo / 'dist' / 'opencode' / '.manifest.json')
        cx_dist = load_json(self.repo / 'dist' / 'codex' / '.manifest.json')
        oc_struct, oc_mgmt = split_manifest_entries(
            oc_dist['files'], ('agent', 'command', 'skill'))
        cx_struct, cx_mgmt = split_manifest_entries(cx_dist['files'], ('skills',))
        # opencode 段：无前缀键；codex 段：codex: 前缀键。
        self.assertEqual(
            {k for k in local['platform_files'] if ':' not in k}, oc_struct)
        self.assertEqual(
            {k for k in local['platform_files'] if k.startswith('codex:')},
            {'codex:' + rel for rel in cx_struct})
        # 两平台结构文件并存落盘。
        self.assertTrue((self.work / '.opencode' / 'agent' / 'architect.md').is_file())
        self.assertTrue((self.work / '.codex' / 'skills' / 'budget-workflow' / (
            'SKILL.md')).is_file())
        # 卸载其一互不破坏的对称性由 uninstall.sh 用例覆盖（2.2 闭环）；
        # 此处断言后装 codex 的 AGENTS.md 合并不破坏 opencode 无 AGENTS.md 形态。
        self.assertIn(AGENTS_BEGIN, (self.work / 'AGENTS.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
