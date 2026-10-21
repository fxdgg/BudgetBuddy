#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ocr-rule.json 结构校验 + ocr-setup.py 单测（integrate-ocr-pre-review tasks 5.1）。

三块被测对象：
    A. core/lib/ocr-rule.json 真实文件结构（design D7）：7 条语言 source 与
       core/rules/budget-*-style.md 主名双向一一对应（动态 glob 枚举后排除
       budget-trpc-style）、merge_system_rule 全 true、path/rule/source 字段
       齐备、rule 文案以「按 budget-xx-style 检查」起头、trpc 未纳入。
    B. scripts/build.py validate_ocr_rule(core_dir) 负向行为：临时 core 沙盒
       构造规则文件与语言规范文件，逐条触发 BuildError（参照 tests/test_build.py
       的 sys.path 注入 build 模块方式）。
    C/D. core/lib/ocr-setup.py 行为：tempfile 隔离目录 + 注入 template_path /
       target_path / confirm / is_tty / shutil.which，绝不触碰真实
       ~/.opencodereview/；覆盖全新安装、幂等 no-op、备份不静默覆盖
       （confirm True/False）、.bak 时间戳后缀、非交互默认跳过、CLI 缺失降级、
       模型配置未检出不阻断、模板缺失非零退出、目录自动创建、原子写无残留；
       D 组专测「差异展示 + 覆盖语义」（差异逐行输出、备份先于覆盖、原文件
       逐字节可恢复）。

交互分支一律走注入参数（confirm / is_tty），禁止真实 input()，用例不挂起。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = REPO_ROOT / 'core'
SCRIPTS_DIR = REPO_ROOT / 'scripts'
RULES_DIR = CORE_DIR / 'rules'
OCR_RULE_JSON = CORE_DIR / 'lib' / 'ocr-rule.json'
OCR_SETUP = CORE_DIR / 'lib' / 'ocr-setup.py'

# 排除项（trpc 规范不入 OCR 规则集，但规范文件本身必须存在）
EXCLUDED_SOURCE = 'budget-trpc-style'
TRPC_RULE_FILE = RULES_DIR / 'budget-trpc-style.md'

# 七元组冻结（防止后续新增语言规范文件时校验侧与规则侧静默失配）
EXPECTED_SOURCES = {
    'budget-go-style',
    'budget-python-style',
    'budget-typescript-style',
    'budget-java-style',
    'budget-cpp-style',
    'budget-css-style',
    'budget-sql-style',
}

sys.path.insert(0, str(SCRIPTS_DIR))
import build  # noqa: E402  pylint: disable=wrong-import-position


def load_ocr_setup():
    """按文件路径加载 ocr-setup.py（文件名含连字符，无法常规 import）。"""
    spec = importlib.util.spec_from_file_location('ocr_setup_under_test', OCR_SETUP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ocr_setup = load_ocr_setup()


def read_rule_doc():
    """读取真实 core/lib/ocr-rule.json。"""
    return json.loads(OCR_RULE_JSON.read_text(encoding='utf-8'))


def capture(func, *args, **kwargs):
    """执行 func，返回 (返回值, stdout, stderr)——测试输出不污染 -v 结果。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = func(*args, **kwargs)
    return code, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def isolated_env(home, extra=None):
    """隔离 HOME 并清除 OCR_LLM_* 与 BUDGET_* 变量（退出后完整还原）。"""
    saved = {key: os.environ[key] for key in list(os.environ)
             if key == 'HOME' or key.startswith(('OCR_LLM_', 'BUDGET_'))}
    for key in list(os.environ):
        if key == 'HOME' or key.startswith(('OCR_LLM_', 'BUDGET_')):
            del os.environ[key]
    os.environ['HOME'] = str(home)
    os.environ.update(extra or {})
    try:
        yield
    finally:
        for key in list(os.environ):
            if key == 'HOME' or key.startswith(('OCR_LLM_', 'BUDGET_')):
                del os.environ[key]
        os.environ.update(saved)


# ─── A. ocr-rule.json 真实文件结构 ────────────────────────────────────────────


class OcrRuleTemplateStructureTests(unittest.TestCase):
    """A 组：规则模板结构（真实文件断言，不构造沙盒）。"""

    def setUp(self):
        self.doc = read_rule_doc()
        self.rules = self.doc['rules']
        self.sources = [entry['source'] for entry in self.rules]

    def test_rules_count_is_seven(self):
        """rules 恰为 7 条（新增语言规范须同步扩展预期集合）。"""
        self.assertEqual(len(self.rules), 7)

    def test_source_set_matches_language_style_files_bidirectionally(self):
        """source 集合 == core/rules/budget-*-style.md 主名集合 − trpc（双向无缺失无多余）。"""
        expected = {path.stem for path in RULES_DIR.glob('budget-*-style.md')}
        expected.discard(EXCLUDED_SOURCE)
        self.assertEqual({*self.sources} - expected, set(), msg='规则侧存在多余 source')
        self.assertEqual(expected - {*self.sources}, set(), msg='规则侧缺失 source')

    def test_expected_source_set_frozen_to_seven(self):
        """枚举结果恰为冻结七元组（防 glob 结果漂移）。"""
        self.assertEqual({*self.sources}, EXPECTED_SOURCES)

    def test_source_names_are_style_suffix(self):
        """source 命名形态统一：budget-*-style。"""
        for source in self.sources:
            self.assertRegex(source, r'^budget-[a-z0-9]+-style$')

    def test_trpc_excluded_but_rule_file_exists(self):
        """trpc 规范文件存在，但未纳入规则集（防误删文件 / 防漏排除）。"""
        self.assertTrue(TRPC_RULE_FILE.is_file(), msg='trpc 语言规范文件不应被删除')
        self.assertNotIn(EXCLUDED_SOURCE, self.sources)

    def test_merge_system_rule_all_true(self):
        """全部条目 merge_system_rule is True（bool 严格 true，非 "true"）。"""
        for index, entry in enumerate(self.rules):
            self.assertIs(entry.get('merge_system_rule'), True, msg=f'rules[{index}]')

    def test_path_rule_source_fields_non_empty(self):
        """每条 path/rule/source 均为非空字符串，rule 以规则名前缀起头。"""
        for index, entry in enumerate(self.rules):
            label = f'rules[{index}]'
            for field in ('path', 'rule', 'source'):
                self.assertIsInstance(entry.get(field), str, msg=f'{label}.{field}')
                self.assertTrue(entry[field].strip(), msg=f'{label}.{field} 为空')
            self.assertTrue(entry['rule'].startswith(f"按 {entry['source']} 检查："),
                            msg=f'{label}.rule 缺少「按 {entry["source"]} 检查」前缀')

    def test_source_unique(self):
        """source 无重复（重复会让 merge_system_rule 覆盖语义失真）。"""
        self.assertEqual(len(self.sources), len(set(self.sources)))


# ─── B. build.validate_ocr_rule 负向行为 ────────────────────────────────────


class ValidateOcrRuleTests(unittest.TestCase):
    """B 组：validate_ocr_rule 沙盒负向用例（BuildError 阻断构建）。"""

    STYLE_FILES = ('budget-go-style.md', 'budget-python-style.md',
                   'budget-css-style.md', 'budget-trpc-style.md')

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-ocr-rule-')
        self.core = Path(self._tmp.name)
        (self.core / 'lib').mkdir()
        (self.core / 'rules').mkdir()
        for name in self.STYLE_FILES:
            (self.core / 'rules' / name).write_text('# 规范\n', encoding='utf-8')

    def tearDown(self):
        self._tmp.cleanup()

    # -- 工具 ---------------------------------------------------------------

    @staticmethod
    def make_rule(source, merge=True):
        entry = {'path': f'**/*.{source.split("-")[1]}',
                 'rule': f'按 {source} 检查：示例规则。',
                 'source': source}
        if merge is not None:
            entry['merge_system_rule'] = merge
        return entry

    def valid_rules(self):
        return [self.make_rule('budget-go-style'),
                self.make_rule('budget-python-style'),
                self.make_rule('budget-css-style')]

    def write_rules(self, rules):
        (self.core / 'lib' / 'ocr-rule.json').write_text(
            json.dumps({'rules': rules}, ensure_ascii=False), encoding='utf-8')

    def assert_build_error(self, *needles):
        with self.assertRaises(build.BuildError) as ctx:
            build.validate_ocr_rule(self.core)
        message = str(ctx.exception)
        for needle in needles:
            self.assertIn(needle, message)
        return message

    # -- 用例 --------------------------------------------------------------

    def test_valid_structure_passes(self):
        self.write_rules(self.valid_rules())
        build.validate_ocr_rule(self.core)  # 不抛异常即通过

    def test_merge_system_rule_false_rejected(self):
        rules = self.valid_rules()
        rules[1]['merge_system_rule'] = False
        self.write_rules(rules)
        self.assert_build_error('merge_system_rule', 'rules[1]')

    def test_merge_system_rule_missing_rejected(self):
        rules = self.valid_rules()
        rules[0].pop('merge_system_rule')
        self.write_rules(rules)
        self.assert_build_error('merge_system_rule')

    def test_missing_source_rejected(self):
        """少一条 source（语言规范文件存在但规则缺失）→ 缺失清单点名。"""
        self.write_rules(self.valid_rules()[:2])
        self.assert_build_error('缺失', 'budget-css-style')

    def test_extra_source_rejected(self):
        """多余 source（无对应语言规范文件）→ 多余清单点名。"""
        rules = self.valid_rules() + [self.make_rule('budget-rust-style')]
        self.write_rules(rules)
        self.assert_build_error('多余', 'budget-rust-style')

    def test_duplicate_source_rejected(self):
        """重复 source 直接拒绝（先于集合比对）。"""
        rules = self.valid_rules() + [self.make_rule('budget-go-style')]
        self.write_rules(rules)
        self.assert_build_error('重复', 'budget-go-style')

    def test_trpc_source_rejected_as_extra(self):
        """把 trpc 塞进规则集 → 判为多余（排除语义硬约束）。"""
        rules = self.valid_rules() + [self.make_rule(EXCLUDED_SOURCE)]
        self.write_rules(rules)
        self.assert_build_error('多余', EXCLUDED_SOURCE)

    def test_missing_rule_file_rejected(self):
        """core/lib/ocr-rule.json 缺失 → BuildError。"""
        self.assert_build_error('缺失', 'ocr-rule.json')

    def test_invalid_json_rejected(self):
        (self.core / 'lib' / 'ocr-rule.json').write_text('{invalid', encoding='utf-8')
        self.assert_build_error('不是合法 JSON')

    def test_empty_rule_field_rejected(self):
        rules = self.valid_rules()
        rules[0]['path'] = ''
        self.write_rules(rules)
        self.assert_build_error('path')

    def test_empty_rules_rejected(self):
        self.write_rules([])
        self.assert_build_error('不能为空')

    def test_no_language_style_files_rejected(self):
        """无任何 budget-*-style.md → 无法建立期望集合，阻断构建。"""
        for name in self.STYLE_FILES:
            (self.core / 'rules' / name).unlink()
        self.write_rules(self.valid_rules())
        self.assert_build_error('无法建立 source 期望集合')


# ─── C. ocr-setup.py 行为（隔离目录 + 注入参数）──────────────────────────────


class OcrSetupSandboxTestCase(unittest.TestCase):
    """公共沙盒：独立临时目录 + 隔离 HOME，绝不触碰真实 ~/.opencodereview/。"""

    TEMPLATE_BODY = '{"rules": [{"source": "budget-go-style", "path": "**/*.go"}]}\n'
    EXISTING_BODY = '{"rules": [{"source": "legacy", "path": "**/*.x"}]}\n'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='budget-ocr-setup-')
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.home.mkdir()
        self.target = self.home / '.opencodereview' / 'rule.json'
        self.backup = self.target.parent / ocr_setup.BACKUP_NAME
        self.template = self.tmp / 'template' / ocr_setup.RULE_TEMPLATE_NAME
        self.template.parent.mkdir()
        self.template.write_text(self.TEMPLATE_BODY, encoding='utf-8')
        self._env = isolated_env(self.home)
        self._env.__enter__()

    def tearDown(self):
        self._env.__exit__(None, None, None)
        self._tmp.cleanup()

    # -- 工具 ---------------------------------------------------------------

    def seed_target(self, content=None):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text(content or self.EXISTING_BODY, encoding='utf-8')

    def install(self, **kwargs):
        """直接调用 install_rules（模板/目标显式注入），返回 (rc, out, err)。"""
        template = kwargs.pop('template_path', str(self.template))
        target = kwargs.pop('target_path', str(self.target))
        return capture(ocr_setup.install_rules, template, target, **kwargs)

    def run_main(self, cli='__missing__', **kwargs):
        """调用 main；cli 默认模拟 ocr 缺失（patch shutil.which）。"""
        kwargs.setdefault('template_path', str(self.template))
        kwargs.setdefault('target_path', str(self.target))
        which = None if cli == '__missing__' else cli
        with mock.patch.object(ocr_setup.shutil, 'which', return_value=which):
            return capture(ocr_setup.main, [], **kwargs)


class ResolvePathTests(OcrSetupSandboxTestCase):
    """C 组：路径解析（模板优先级 / 目标默认值）。"""

    def test_target_default_under_home(self):
        self.assertEqual(
            ocr_setup.resolve_target_path(),
            os.path.join(str(self.home), '.opencodereview', 'rule.json'))

    def test_template_explicit_missing_does_not_fallback(self):
        """显式 template_path 不存在 → None，不回退真实模板（供「模板缺失」用例）。"""
        self.assertIsNone(ocr_setup.resolve_template_path(str(self.tmp / 'nope.json')))

    def test_template_budget_lib_dir_preferred(self):
        with mock.patch.dict(os.environ, {'BUDGET_LIB_DIR': str(self.template.parent)}):
            self.assertEqual(ocr_setup.resolve_template_path(), str(self.template))


class InstallRulesTests(OcrSetupSandboxTestCase):
    """C 组：规则安装主流程（安装 / 幂等 / 跳过 / 降级 / 原子写）。"""

    def test_fresh_install_writes_template(self):
        """目标不存在（父目录不存在）→ 自动创建目录并写入，rc 0。"""
        self.assertFalse(self.target.parent.exists())
        rc, out, _ = self.install()
        self.assertEqual(rc, 0)
        self.assertTrue(self.target.is_file())
        self.assertEqual(self.target.read_text(encoding='utf-8'), self.TEMPLATE_BODY)
        self.assertIn('规则已安装', out)

    def test_idempotent_same_content_not_rewritten(self):
        """内容相同 → no-op：不调用 _atomic_write、mtime 不变、rc 0。"""
        self.seed_target(self.TEMPLATE_BODY)
        before = self.target.stat().st_mtime_ns
        with mock.patch.object(ocr_setup, '_atomic_write') as writer:
            rc, out, _ = self.install()
        self.assertEqual(rc, 0)
        writer.assert_not_called()
        self.assertEqual(self.target.stat().st_mtime_ns, before)
        self.assertFalse(self.backup.exists(), msg='幂等路径不得产生备份')
        self.assertIn('幂等', out)

    def test_non_interactive_skips_overwrite(self):
        """is_tty=False + 内容不同 → 不覆盖、原文不变、无备份、rc 0。"""
        self.seed_target()
        rc, out, _ = self.install(is_tty=False)
        self.assertEqual(rc, 0)
        self.assertEqual(self.target.read_text(encoding='utf-8'), self.EXISTING_BODY)
        self.assertFalse(self.backup.exists())
        self.assertIn('非交互环境', out)
        self.assertIn('默认跳过覆盖', out)

    def test_confirm_false_keeps_target_bytes(self):
        """用户取消（confirm → False）→ 原文件逐字节不变、无备份、rc 0。"""
        self.seed_target()
        before = self.target.read_bytes()
        rc, out, _ = self.install(confirm=lambda _prompt: False)
        self.assertEqual(rc, 0)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertFalse(self.backup.exists())
        self.assertIn('已取消', out)

    def test_confirm_true_backs_up_then_overwrites(self):
        """确认覆盖 → 生成 .bak（旧内容）+ 目标更新为模板。"""
        self.seed_target()
        rc, out, _ = self.install(confirm=lambda _prompt: True)
        self.assertEqual(rc, 0)
        self.assertEqual(self.target.read_text(encoding='utf-8'), self.TEMPLATE_BODY)
        self.assertEqual(self.backup.read_text(encoding='utf-8'), self.EXISTING_BODY)
        self.assertIn(str(self.backup), out)

    def test_backup_timestamp_suffix_when_bak_exists(self):
        """.bak 已存在 → 时间戳后缀 .bak.<YYYYMMDDHHMMSS>，既有 .bak 不被覆盖。"""
        self.seed_target()
        self.backup.write_text('older backup\n', encoding='utf-8')
        backup_path = ocr_setup.compute_backup_path(str(self.target))
        self.assertNotEqual(backup_path, str(self.backup))
        self.assertRegex(os.path.basename(backup_path),
                         r'^rule\.json\.bak\.\d{14}$')

        rc, _, _ = self.install(confirm=lambda _prompt: True)
        self.assertEqual(rc, 0)
        self.assertEqual(self.backup.read_text(encoding='utf-8'), 'older backup\n')
        self.assertEqual(Path(backup_path).read_text(encoding='utf-8'), self.EXISTING_BODY)
        self.assertEqual(self.target.read_text(encoding='utf-8'), self.TEMPLATE_BODY)

    def test_compute_backup_path_default_when_absent(self):
        self.assertEqual(ocr_setup.compute_backup_path(str(self.target)), str(self.backup))

    def test_atomic_write_leaves_no_temp_residue(self):
        """原子写：目录内仅目标文件，无 .ocr-* 临时残留；新文件权限 0o600。"""
        rc, _, _ = self.install()
        self.assertEqual(rc, 0)
        leftovers = [name for name in os.listdir(self.target.parent)
                     if name.startswith('.ocr-')]
        self.assertEqual(leftovers, [])
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)

    def test_atomic_write_uses_replace(self):
        """写入形态：同目录临时文件 + os.replace（mock 断言调用路径）。"""
        real_replace = os.replace
        with mock.patch.object(ocr_setup.os, 'replace', side_effect=real_replace) as repl:
            rc, _, _ = self.install()
        self.assertEqual(rc, 0)
        self.assertEqual(repl.call_count, 1)
        src, dst = repl.call_args[0]
        self.assertEqual(os.path.dirname(src), str(self.target.parent))
        self.assertTrue(os.path.basename(src).startswith('.ocr-'))
        self.assertEqual(dst, str(self.target))

    def test_write_failure_returns_nonzero(self):
        """写入抛 OSError → rc 1 且 stderr 有 error 提示。"""
        with mock.patch.object(ocr_setup, '_atomic_write', side_effect=OSError('disk full')):
            rc, _, err = self.install()
        self.assertEqual(rc, 1)
        self.assertIn('error', err)

    def test_missing_template_returns_nonzero(self):
        """模板不可读 → rc 1，目标文件不被触碰。"""
        self.template.unlink()
        rc, _, err = self.install()
        self.assertEqual(rc, 1)
        self.assertIn('无法读取规则模板', err)
        self.assertFalse(self.target.exists())


class MainFlowTests(OcrSetupSandboxTestCase):
    """C 组：main 全流程（CLI 缺失 / 模型配置 / 模板缺失 / 降级语义）。"""

    def test_cli_missing_prints_guidance_and_installs(self):
        """CLI 探测不到 → 输出指引、规则安装照常完成、rc 0。"""
        rc, out, _ = self.run_main(cli='__missing__')
        self.assertEqual(rc, 0)
        self.assertIn('未检测到 OCR CLI', out)
        self.assertIn(ocr_setup.INSTALL_GUIDANCE, out)
        self.assertEqual(self.target.read_text(encoding='utf-8'), self.TEMPLATE_BODY)
        self.assertIn('降级语义', out)

    def test_model_config_absent_does_not_block(self):
        """无 OCR_LLM_* 且无 ~/.opencodereview 配置 → 仅提示、rc 0、规则照装。"""
        self.assertFalse(ocr_setup.check_model_config())
        rc, out, _ = self.run_main(cli='/usr/local/bin/ocr')
        self.assertEqual(rc, 0)
        self.assertIn('检测到 OCR CLI', out)
        self.assertIn('未检测到模型配置', out)
        self.assertIn('delegate', out)
        self.assertEqual(self.target.read_text(encoding='utf-8'), self.TEMPLATE_BODY)

    def test_model_config_env_detected(self):
        """OCR_LLM_* 任一存在 → 视为已配置（不阻断、不回显值）。"""
        with mock.patch.dict(os.environ, {'OCR_LLM_URL': 'https://example.invalid/v1'}):
            rc, out, _ = self.run_main(cli='/usr/local/bin/ocr')
        self.assertEqual(rc, 0)
        self.assertIn('检测到模型配置', out)
        self.assertNotIn('example.invalid', out, msg='凭据纪律：配置值不得回显')

    def test_check_model_config_excludes_self_installed_rules(self):
        """~/.opencodereview/ 仅含 rule.json(.bak) 时不算模型配置。"""
        self.seed_target()
        self.backup.write_text('x', encoding='utf-8')
        self.assertFalse(ocr_setup.check_model_config(str(self.home)))
        (self.target.parent / 'config.yaml').write_text('model: x\n', encoding='utf-8')
        self.assertTrue(ocr_setup.check_model_config(str(self.home)))

    def test_template_missing_exits_nonzero_target_untouched(self):
        """模板缺失（显式路径不存在 + BUDGET_LIB_DIR 空目录）→ 非零退出。"""
        empty_lib = self.tmp / 'empty-lib'
        empty_lib.mkdir()
        with mock.patch.dict(os.environ, {'BUDGET_LIB_DIR': str(empty_lib)}):
            rc, _, err = self.run_main(cli='__missing__',
                                       template_path=str(self.tmp / 'nope.json'))
        self.assertEqual(rc, 1)
        self.assertIn('未找到规则模板', err)
        self.assertIn('budget setup update', err)
        self.assertFalse(self.target.exists())

    def test_non_interactive_skip_still_exit_zero(self):
        """main 非交互 + 内容不同 → 不覆盖、rc 0（降级不阻断）。"""
        self.seed_target()
        rc, out, _ = self.run_main(cli='__missing__', is_tty=False)
        self.assertEqual(rc, 0)
        self.assertEqual(self.target.read_text(encoding='utf-8'), self.EXISTING_BODY)
        self.assertIn('非交互环境', out)


# ─── D. 差异展示 + 覆盖语义（tasks 5.1 明确不得跳过）────────────────────────


class OverwriteSemanticsTests(OcrSetupSandboxTestCase):
    """D 组：差异逐行展示、备份先于覆盖、取消路径可完整恢复。"""

    def test_diff_displayed_before_overwrite(self):
        """覆盖前逐行展示 unified diff（-旧 / +新 与文件名标头）。"""
        self.seed_target()
        rc, out, _ = self.install(confirm=lambda _prompt: True)
        self.assertEqual(rc, 0)
        self.assertIn('--- 当前 rule.json', out)
        self.assertIn('+++ 新模板', out)
        self.assertIn('-{"rules": [{"source": "legacy"', out)
        self.assertIn('+{"rules": [{"source": "budget-go-style"', out)
        # 差异展示先于覆盖结果输出
        self.assertLess(out.index('+++ 新模板'), out.index('规则已更新'))

    def test_backup_written_before_target_overwrite(self):
        """备份内容为覆盖前字节（可完整恢复原文件）。"""
        self.seed_target()
        original = self.target.read_bytes()
        rc, _, _ = self.install(confirm=lambda _prompt: True)
        self.assertEqual(rc, 0)
        self.assertEqual(self.backup.read_bytes(), original)

    def test_confirm_prompt_asked_once(self):
        """差异路径只询问一次，且传入 [y/N] 提示语。"""
        self.seed_target()
        prompts = []

        def confirm(prompt):
            prompts.append(prompt)
            return True

        rc, _, _ = self.install(confirm=confirm)
        self.assertEqual(rc, 0)
        self.assertEqual(len(prompts), 1)
        self.assertIn('[y/N]', prompts[0])

    def test_confirmed_overwrite_is_idempotent_on_rerun(self):
        """确认覆盖后再次运行 → 幂等 no-op，无二次备份。"""
        self.seed_target()
        rc, _, _ = self.install(confirm=lambda _prompt: True)
        self.assertEqual(rc, 0)
        backup_mtime = self.backup.stat().st_mtime_ns
        rc, out, _ = self.install(is_tty=False)
        self.assertEqual(rc, 0)
        self.assertIn('幂等', out)
        self.assertEqual(self.backup.stat().st_mtime_ns, backup_mtime)

    def test_cancel_after_diff_keeps_original_restorable(self):
        """取消路径：差异已展示但原文逐字节不变，且无任何备份落盘。"""
        self.seed_target()
        original = self.target.read_bytes()
        rc, out, _ = self.install(confirm=lambda _prompt: False)
        self.assertEqual(rc, 0)
        self.assertIn('+++ 新模板', out)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual([name for name in os.listdir(self.target.parent)
                          if name.startswith(ocr_setup.BACKUP_NAME)], [])


if __name__ == '__main__':
    unittest.main()
