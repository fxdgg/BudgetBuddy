#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""品牌合规门禁：扫描固定范围内文本文件中的违禁词。

扫描范围（相对 --root，不存在的路径静默跳过）：
core/、dist/、scripts/、install.sh、README.md、README_CN.md、CHANGELOG.md。

行为约定（design.md §5 / §12-A10）：
- 词表大小写不敏感，按子串匹配，任意前后缀变体均命中；
- 命中时逐行输出「相对路径:行号:该行摘要（截断）」并 exit 1，全部干净 exit 0；
- 本脚本自身位于扫描范围内，运行时跳过自身文件（词表定义载体豁免）；
- 非文本/解码失败文件跳过并向 stderr 输出告警，不视为命中、不中断扫描；
- __pycache__/ 目录整体跳过（.pyc 为非文本字节码，避免告警噪音）。

用法：python3 scripts/scan-brand.py [--root <仓库根目录>]
退出码：0=干净，1=存在命中，2=内部错误。
"""

import argparse
from collections.abc import Iterator
import os
from pathlib import Path
import sys

# 违禁词表（大小写不敏感，子串匹配）。
# 词以转义编码形式存储（本文件不出现明文，避免门禁载体自身携带标识）；
# 运行时解码为普通字符串后匹配，效果与明文字面量完全一致。
# 注意：本文件整体豁免（词表定义载体，D §12-A10），运行时跳过自身；
# 其余 scripts/ 文件仍受本门禁正常扫描约束。
FORBIDDEN_WORDS = (
    '\x62\x65\x67\x67\x61\x72',
    '\x61\x67\x65\x6e\x74\x68\x75\x62',
    '\x74\x65\x6e\x63\x65\x6e\x74',
    '\u817e\u8baf',
    '\u4e10\u5e2e',
    '\u98de\u9e3d\u4f20\u4e66',
    '\u98de\u9e3d',
    '\x77\x6f\x61\x2e\x63\x6f\x6d',
    '\x70\x69\x67\x65\x6f\x6e',
)

# 扫描范围：目录递归 + 顶层单文件。
SCAN_DIRS = ('core', 'dist', 'scripts')
SCAN_FILES = ('install.sh', 'README.md', 'README_CN.md', 'CHANGELOG.md')

# 命中行摘要的截断长度。
SUMMARY_LIMIT = 120

FORBIDDEN_WORDS_LOWER = tuple(word.lower() for word in FORBIDDEN_WORDS)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description='品牌合规门禁：扫描固定范围内的违禁词')
    parser.add_argument(
        '--root',
        default=None,
        help='仓库根目录（默认：本脚本所在目录的上两级）',
    )
    return parser.parse_args(argv)


def resolve_root(root_arg: str | None) -> Path:
    """确定扫描根目录：显式参数优先，缺省为脚本上两级（仓库根）。"""
    if root_arg:
        return Path(root_arg).resolve()
    return Path(__file__).resolve().parent.parent


def iter_candidate_files(root: Path) -> Iterator[Path]:
    """按确定顺序产出扫描范围内的候选文件（绝对路径）。

    不存在的目录/文件静默跳过；遍历按名称排序保证输出稳定；
    __pycache__/ 目录整体跳过（.pyc 为非文本字节码）。
    """
    for name in SCAN_DIRS:
        base = root / name
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            dirnames[:] = [dirname for dirname in dirnames if dirname != '__pycache__']
            for filename in sorted(filenames):
                yield Path(dirpath) / filename
    for name in SCAN_FILES:
        candidate = root / name
        if candidate.is_file():
            yield candidate


def scan_text(content: str) -> list[tuple[int, str]]:
    """返回文本内容的命中列表，元素为 (行号, 行摘要)。"""
    hits = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        lowered = line.lower()
        for word in FORBIDDEN_WORDS_LOWER:
            if word in lowered:
                hits.append((lineno, line.strip()[:SUMMARY_LIMIT]))
                break
    return hits


def _warn_skip(path: Path, root: Path, reason: str) -> None:
    """向 stderr 输出跳过告警。"""
    rel = path.relative_to(root)
    print(f'[scan-brand] 跳过非文本文件（{reason}）: {rel}', file=sys.stderr)


def scan_file(path: Path, root: Path) -> list[tuple[int, str]] | None:
    """扫描单个文件；返回命中列表，跳过时返回 None。

    解码失败（UnicodeDecodeError）、含 NUL 字节或读取失败（OSError）的
    文件视为非文本：向 stderr 输出告警并跳过，不视为命中。
    """
    try:
        with open(path, encoding='utf-8') as handle:
            content = handle.read()
    except UnicodeDecodeError:
        _warn_skip(path, root, '解码失败')
        return None
    except OSError:
        _warn_skip(path, root, '读取失败')
        return None
    if '\x00' in content:
        _warn_skip(path, root, '包含 NUL 字节')
        return None
    return scan_text(content)


def main(argv: list[str] | None = None) -> int:
    """执行扫描，返回进程退出码（0=干净，1=命中）。"""
    args = parse_args(argv)
    root = resolve_root(args.root)
    self_path = Path(__file__).resolve()
    total_hits = 0
    scanned = 0
    for path in iter_candidate_files(root):
        if path == self_path:
            # 词表定义载体豁免：跳过本脚本自身。
            continue
        hits = scan_file(path, root)
        if hits is None:
            continue
        scanned += 1
        rel = path.relative_to(root)
        for lineno, summary in hits:
            print(f'{rel}:{lineno}:{summary}')
            total_hits += 1
    if total_hits:
        print(f'[scan-brand] 违禁词命中 {total_hits} 处（已扫描 {scanned} 个文本文件）')
        return 1
    print(f'[scan-brand] 扫描完成：{scanned} 个文本文件，未发现违禁词')
    return 0


def run(argv: list[str] | None = None) -> int:
    """入口包装：兜底未预期异常，避免堆栈直接暴露给调用方。"""
    try:
        return main(argv)
    except Exception as exc:  # pylint: disable=broad-except
        print(f'[scan-brand] 内部错误: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(run())
