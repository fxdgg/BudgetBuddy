#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan-brand 门禁单测。

在临时目录构造完整仓库结构（core/dist/scripts + 顶层文件），
以子进程运行门禁脚本，验证退出码、命中定位与豁免/范围边界行为。

违禁词样本一律运行时字符串拼接构造，本文件不出现完整违禁词字面量
（tests/ 位于扫描范围之外，拼接构造属双保险约束）。
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / 'scripts' / 'scan-brand.py'

# 违禁词样本（运行时拼接构造，见模块 docstring）。
SAMPLE_PLAIN = 'beg' + 'gar'
SAMPLE_MIXED = 'BeGg' + 'Ar'
SAMPLE_PREFIXED = 'BEGG' + 'AR_HOME'
SAMPLE_CN = '腾' + '讯'

# 摘要截断长度上限（与门禁脚本规格一致）。
SUMMARY_LIMIT = 120


def run_scanner(root: Path, script: Path = SCRIPT_PATH) -> subprocess.CompletedProcess:
    """以子进程运行门禁脚本，返回执行结果（不因非零退出码抛错）。"""
    return subprocess.run(
        [sys.executable, str(script), '--root', str(root)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )


class ScanBrandGateTests(unittest.TestCase):
    """门禁行为验证：退出码、输出定位、自身豁免与范围边界。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write_file(self, relpath: str, text: str) -> None:
        """在临时仓库内写入文本文件（自动创建父目录）。"""
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')

    def write_bytes_file(self, relpath: str, data: bytes) -> None:
        """在临时仓库内写入二进制文件（自动创建父目录）。"""
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def test_clean_tree_exit_zero(self):
        """全部扫描范围干净：exit 0 且输出不含样本词。"""
        self.write_file('core/agents/demo.md', '中性内容\n')
        self.write_file('dist/codebuddy/agents/demo.md', '中性内容\n')
        self.write_file('scripts/build.py', 'print("ok")\n')
        self.write_file('install.sh', 'echo ok\n')
        self.write_file('README.md', 'hello\n')
        self.write_file('README_CN.md', '你好\n')
        self.write_file('CHANGELOG.md', 'v0.1.0\n')
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn(SAMPLE_PLAIN, proc.stdout)

    def test_hit_location_and_exit_code(self):
        """命中违禁词：exit 1，输出「文件:行号:摘要」且定位准确。"""
        content = '第一行干净\n第二行包含 ' + SAMPLE_PLAIN + ' 词\n第三行干净\n'
        self.write_file('core/agents/bad.md', content)
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('core/agents/bad.md:2:', proc.stdout)
        self.assertIn(SAMPLE_PLAIN, proc.stdout)
        self.assertNotIn('core/agents/bad.md:1:', proc.stdout)
        self.assertNotIn('core/agents/bad.md:3:', proc.stdout)

    def test_multiple_line_hits(self):
        """同一文件多行命中：行号逐行准确报告。"""
        content = SAMPLE_PLAIN + ' at 1\nclean line\n' + SAMPLE_PLAIN + ' at 3\n'
        self.write_file('core/multi.md', content)
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('core/multi.md:1:', proc.stdout)
        self.assertIn('core/multi.md:3:', proc.stdout)
        self.assertNotIn('core/multi.md:2:', proc.stdout)

    def test_case_insensitive_variant(self):
        """大小写混合变体：同样命中。"""
        self.write_file('dist/codebuddy/variant.md', 'variant: ' + SAMPLE_MIXED + '\n')
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('dist/codebuddy/variant.md:1:', proc.stdout)

    def test_uppercase_prefix_variant(self):
        """全大写带下划线后缀变体：同样命中（scripts 下其他文件正常扫描）。"""
        self.write_file('scripts/build.py', 'export ' + SAMPLE_PREFIXED + '=1\n')
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('scripts/build.py:1:', proc.stdout)

    def test_chinese_word_hit(self):
        """中文违禁词：命中且定位到顶层单文件。"""
        self.write_file('README_CN.md', '介绍 ' + SAMPLE_CN + ' 云服务\n')
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('README_CN.md:1:', proc.stdout)

    def test_binary_file_skipped_with_warning(self):
        """无法解码的二进制文件：跳过、stderr 告警、不视为命中。"""
        binary = b'\x89PNG\r\n\x1a\n\x00\xff\xfe' + SAMPLE_PLAIN.encode('utf-8')
        self.write_bytes_file('core/assets/logo.bin', binary)
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('core/assets/logo.bin', proc.stderr)

    def test_nul_byte_file_skipped_with_warning(self):
        """可解码但含 NUL 字节的文件：按非文本跳过并告警。"""
        self.write_bytes_file('scripts/data.txt', b'clean\x00binary-ish')
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('scripts/data.txt', proc.stderr)

    def test_scanner_skips_itself(self):
        """词表载体豁免：脚本副本位于 scripts/ 内，自身不被扫描。"""
        dest = self.root / 'scripts' / 'scan-brand.py'
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SCRIPT_PATH, dest)
        proc = run_scanner(self.root, script=dest)
        self.assertEqual(proc.returncode, 0)

    def test_other_scripts_file_still_scanned(self):
        """自身豁免不影响 scripts/ 下其他文件：副本干净 + 其他文件命中。"""
        dest = self.root / 'scripts' / 'scan-brand.py'
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SCRIPT_PATH, dest)
        self.write_file('scripts/build.py', 'value = "' + SAMPLE_PLAIN + '"\n')
        proc = run_scanner(self.root, script=dest)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('scripts/build.py:1:', proc.stdout)

    def test_pycache_directory_skipped(self):
        """__pycache__/ 目录整体跳过：.pyc 不扫描、无告警、不计入扫描数。"""
        self.write_bytes_file(
            'scripts/__pycache__/build.cpython-312.pyc',
            b'\x80\x04\x95\x00' + SAMPLE_PLAIN.encode('utf-8'))
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, '')
        self.assertNotIn('__pycache__', proc.stdout)
        self.assertIn('扫描完成：0 个文本文件', proc.stdout)

    def test_out_of_scope_directories_ignored(self):
        """范围外目录（tests/docs/openspec/其他）：即使含样本词也不命中。"""
        self.write_file('tests/evil.md', SAMPLE_PLAIN + '\n')
        self.write_file('docs/evil.md', SAMPLE_PLAIN + '\n')
        self.write_file('openspec/evil.md', SAMPLE_PLAIN + '\n')
        self.write_file('other/evil.md', SAMPLE_PLAIN + '\n')
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 0)

    def test_empty_root_exit_zero(self):
        """空仓库（扫描路径全部不存在）：exit 0 且无告警。"""
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, '')

    def test_summary_line_truncated(self):
        """超长命中行：摘要截断至不超过 120 字符。"""
        long_line = 'x' * 200 + ' tail ' + SAMPLE_PLAIN
        self.write_file('core/long.md', long_line + '\n')
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 1)
        hit_lines = [ln for ln in proc.stdout.splitlines() if ln.startswith('core/long.md:1:')]
        self.assertEqual(len(hit_lines), 1)
        summary = hit_lines[0].split(':', 2)[2]
        self.assertLessEqual(len(summary), SUMMARY_LIMIT)

    def test_summary_reports_hit_count(self):
        """多文件命中：汇总行报告命中总数，逐文件定位准确。"""
        self.write_file('core/a.md', SAMPLE_PLAIN + '\n')
        self.write_file('dist/b.md', SAMPLE_PLAIN + '\n')
        proc = run_scanner(self.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('core/a.md:1:', proc.stdout)
        self.assertIn('dist/b.md:1:', proc.stdout)
        self.assertIn('违禁词命中 2 处', proc.stdout)


if __name__ == '__main__':
    unittest.main()
