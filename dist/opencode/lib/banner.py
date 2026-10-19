#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy 统一启动横幅（design.md §8.2「交互与汇总」组）。

供 quickstart / 向导 / setup 各入口复用：同目录 ``from banner import
print_banner`` 导入，或直接执行 ``python3 banner.py``。品牌中立：不含任何
外部链接、作者署名与参照项目信息。

颜色决策（对齐 colors.sh 的降级规则）：
  - 默认自动：stdout 为终端 → 启用 ANSI；管道/重定向 → 纯文本
  - BUDGET_COLOR=1 / 0 显式覆盖（测试与非交互场景）

对齐纪律：内容行按终端显示宽度（CJK 全宽 2 列）程序化补齐，不依赖
手工空格计数，CJK 内容增删不破坏框线对齐。
"""

from __future__ import annotations

import os
import sys
import unicodedata

BOLD = '\033[1m'
CYAN = '\033[0;36m'
YELLOW = '\033[1;33m'
NC = '\033[0m'

# 框线内宽（═ 字符数；内容行显示宽度不得超过该值 - 2 列缩进）
BANNER_INNER_WIDTH = 54

# 横幅内容（标题行 + 提示行；渲染时统一左侧缩进 2 列并右侧补齐）
BANNER_TITLE_SUFFIX = '多 Agent 省钱研发工作流套件'
BANNER_ROWS = (
    '- 用法: budget <子命令>（budget help 查看全集）',
    '- 工作流: /budget:start 启动多 Agent 协作',
    '- 统计: budget setup stats（支持 --json）',
    '- 校验: budget setup validate（完整性报告）',
)


def display_width(text: str) -> int:
    """字符串终端显示宽度（CJK 全宽 2 列；ANSI 转义序列不计宽）。"""
    width = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == '\033':
            end = text.find('m', index)
            if end == -1:
                break
            index = end + 1
            continue
        width += 2 if unicodedata.east_asian_width(char) in ('F', 'W') else 1
        index += 1
    return width


def color_enabled() -> bool:
    """颜色开关：BUDGET_COLOR 显式覆盖 > stdout isatty 自动判定。"""
    override = os.environ.get('BUDGET_COLOR', '')
    if override == '1':
        return True
    if override == '0':
        return False
    return sys.stdout.isatty()


def _pad_row(content: str) -> str:
    """内容行补齐到框线内宽（左侧统一 2 列缩进，右侧补空格）。"""
    row = '  ' + content
    return row + ' ' * max(0, BANNER_INNER_WIDTH - display_width(row))


def banner_lines(color: bool | None = None) -> list[str]:
    """构造横幅全部行（含框线；color=None 时自动判定颜色）。"""
    if color is None:
        color = color_enabled()
    cyan = CYAN if color else ''
    yellow = YELLOW if color else ''
    bold = BOLD if color else ''
    nc = NC if color else ''

    lines = [cyan + '╔' + '═' * BANNER_INNER_WIDTH + '╗' + nc]
    # 标题行：BudgetBuddy 加粗 + 副标题高亮；行尾回到 cyan 使补齐空格与
    # 右边界保持框线色
    title = bold + 'BudgetBuddy' + nc + cyan + ' · ' + yellow \
        + BANNER_TITLE_SUFFIX + nc + cyan
    lines.append(cyan + '║' + _pad_row(title) + '║' + nc)
    lines.append(cyan + '╠' + '═' * BANNER_INNER_WIDTH + '╣' + nc)
    for row in BANNER_ROWS:
        lines.append(cyan + '║' + _pad_row(row) + '║' + nc)
    lines.append(cyan + '╚' + '═' * BANNER_INNER_WIDTH + '╝' + nc)
    return lines


def print_banner(color: bool | None = None) -> None:
    """输出横幅（前后各一空行；color=None 时自动判定颜色）。"""
    print()
    for line in banner_lines(color):
        print(line)
    print()


def main() -> int:
    """独立执行入口：输出横幅。"""
    print_banner()
    return 0


if __name__ == '__main__':
    sys.exit(main())
