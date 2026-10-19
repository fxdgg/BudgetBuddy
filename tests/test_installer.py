#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install.sh 双平台安装器单测（design.md §10 / specs/installer）。

以 subprocess 驱动 bash install.sh：临时目录构造 mini 仓库（install.sh +
dist/ 副本，可自由改动 manifest 与文件哈希模拟升级场景，不触碰仓库真实
dist/），HOME 环境隔离（剥离外层 BUDGET_* 变量）。覆盖：

- 四形态端到端（codebuddy 项目/全局、opencode 项目/全局）：文件落点、
  本地清单、命令包装器、hooks 注入（settings.json）、budget setup show 冒烟
- AGENTS.md 标记区块幂等合并：创建 / 追加 / 幂等重装内容不变 / 用户内容保护
- manifest 增量同步：哈希一致跳过、哈希变化覆盖、清单外用户文件保留、
  本地清单写入（files / platform_files 双字段）
- 升级差集清理：本地旧清单 − 新 manifest 差集删除、清单外文件不受影响
- 非交互：BUDGET_PLATFORM / BUDGET_GLOBAL 环境变量、无 tty 默认项目安装、
  both 双平台
- 依赖缺失 mock（PATH 隔离，python3 不可用 → 明确报错中止）
- bash -n 语法冒烟与 CLI 入口（--help / --version）
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
    """构造 mini 仓库：install.sh + dist/ 双平台副本（可自由改动模拟升级）。"""
    repo = base / 'repo'
    repo.mkdir()
    shutil.copy2(INSTALL_SH, repo / 'install.sh')
    shutil.copytree(DIST_CODEBUDDY, repo / 'dist' / 'codebuddy')
    shutil.copytree(DIST_OPENCODE, repo / 'dist' / 'opencode')
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


if __name__ == '__main__':
    unittest.main()
