#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy 构建系统：core/ 中立源 → dist/<platform>/ 平台产物（平台清单构建期
由 core/platform/*.yaml 枚举，数据驱动，非硬编码元组）。

流程（design.md §4）：
1. 解析 core/platform/<platform>.yaml（手写 YAML 子集解析器，§12-A5）并校验 DSL schema（§3.5）；
2. 构建写入临时目录 dist/<platform>.new/，逐类别转换：agents/commands frontmatter
   重写（§3.1/§3.2）、正文变量替换（§3.3）、routing 落位（§3.5）、
   lib/models/personas/docs 处理、rules 合并（opencode AGENTS.fragment.md）；
3. 写 .manifest.json（§12-A7：按键排序、无时间戳、不含自身）；
4. 全部成功后原子替换 dist/<platform>/（失败清理 .new，旧产物保持原样）。

空 core / 数据未就位降级（§4）：agents 无文件跳过集合完备性校验；
budget-models.json 缺失跳过 model 烘焙与 MODEL_SELECTION 渲染（告警不失败）；
personas.json 缺失跳过 personas 平移。budget-models.json 就位时执行结构
校验（§7，规则对齐 budget-models.schema.json）与 MODEL_SELECTION 渲染
（A6 三占位符，T8a 实现）。

YAML 子集语法（§12-A5）：两空格缩进嵌套 map、块式 list（- item）、
块式 list 项为 map（- key: value + 缩进续行）、行内流式 {}/[]、
单/双引号与裸标量（含引号内冒号与值后行内注释）、空字符串 ""、null、
# 注释；不支持锚点/别名/tag/多行字符串/文档分隔符（显式报错含行号）。

用法：python3 scripts/build.py [--platform <platform>] [--check] [--strict] [--root DIR]
退出码：0=成功；1=构建/校验/门禁失败；2=内部错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
import re
import shutil
import subprocess
import sys

# §6 十角色清单（core/agents/ 非空时集合完备性校验基准）。
AGENT_NAMES = (
    'architect', 'coder-lite', 'coder-standard', 'coder-senior', 'reviewer',
    'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
)

# §7 roles 十角色键（model_role 形式，与 AGENT_NAMES 同序一一对应；
# budget-models.json roles 校验基准与预设映射键集）。
MODEL_ROLES = (
    'architect', 'coder_lite', 'coder_standard', 'coder_senior', 'reviewer',
    'reviewer_b', 'tester', 'recorder', 'director', 'goal_evaluator',
)

# §7 预设三档名。
PRESET_NAMES = ('economic', 'balanced', 'quality')

# §7 模型目录 paid 厂商组渲染固定顺序（未列出的组按名称字母序追加，保证确定性）。
_VENDOR_ORDER = ('claude', 'gemini', 'gpt', 'kimi', 'glm', 'minimax', 'deepseek')

# 模型条目 tier 合法枚举（对齐 budget-models.schema.json）。
_MODEL_TIERS = frozenset(('top', 'mid', 'light', 'budget', 'free'))

# §7 opencode 预设 provider 白名单（官方六系 + opencode 官方免费网关）。
OPENCODE_PROVIDERS = frozenset((
    'anthropic', 'openai', 'google', 'zhipu', 'deepseek', 'moonshotai', 'opencode',
))

# §3.1 tools 中立小写白名单。
TOOLS_WHITELIST = frozenset((
    'read', 'write', 'edit', 'bash', 'grep', 'glob', 'webfetch', 'websearch',
))

# §3.2 CodeBuddy 工具名 PascalCase 映射（复合词 WebFetch/WebSearch 按设计文档工具名表）。
_TOOL_PASCAL = {
    'read': 'Read', 'write': 'Write', 'edit': 'Edit', 'bash': 'Bash',
    'grep': 'Grep', 'glob': 'Glob', 'webfetch': 'WebFetch', 'websearch': 'WebSearch',
}

# §3.3 正文模板变量六白名单（body_variables 声明键的合法域）。
BODY_VARIABLES_WHITELIST = frozenset((
    'TASK_TOOL', 'SKILL_NS', 'PROJECT_DOC', 'AGENT_DIR', 'GUARD_PATH', 'RULES_DIR',
))

# §3.5 agent_frontmatter.emit 合法表达式精确集合（七表达式：{name}/{description}/
# {resolved_model}/{tools|pascal}/{permission_mode}/{permission_map}/{max_turns}，
# 无裸 {tools}）；形如 {xxx} 或 {xxx|pascal} 的整体表达式必须 ∈ 本集合，
# 防 yaml 演进期拼写错误或 routing 占位符混入 emit 域后静默进入产物。
EMIT_EXPRESSIONS = frozenset((
    'name', 'description', 'resolved_model', 'tools|pascal',
    'permission_mode', 'permission_map', 'max_turns',
))

# §3.5 routing 模板占位符集合（{name}=主名、{skill}=skill 目录名、
# {group}=命令组、{path}=相对路径）；routing 域字符串模板与 hook/docs
# 目标路径中出现的 {xxx} 必须全部 ∈ 本集合（防拼写错误静默落位字面量路径）。
ROUTING_PLACEHOLDERS = frozenset(('name', 'skill', 'group', 'path'))

# §3.5 DSL 顶层必填字段。
DSL_TOP_REQUIRED = (
    'platform', 'output', 'routing', 'agent_frontmatter', 'command_frontmatter',
    'command', 'body_variables',
)

# §3.5 routing 必填路径规则键（八类 + docs 显式 map；hook 为可选键）。
ROUTING_REQUIRED_KEYS = (
    'agent', 'command', 'skill', 'rule', 'models', 'personas', 'lib', 'setup', 'docs',
)

# §3.5 routing 中值必须为非空字符串的路径规则键。
ROUTING_STRING_KEYS = ('agent', 'command', 'skill', 'rule', 'models', 'personas', 'lib', 'setup')

# §3.1 命令 name 显示名的合法组前缀。
COMMAND_GROUPS = ('Budget', 'Opsx')

# §3.4 P0 一致性比对的规则文件主名。
P0_RULE_STEMS = ('budget-leader-no-code', 'budget-coder-guard', 'budget-workflow-enforcement')

# §3.4 SKILL.md 内联章节标题关键字。
P0_SKILL_HEADING_KEYWORD = '强制执行规则'

# §3.4 规则 3 分词时剔除的停用词（中英常见虚词简化表，不含否定词）。
_STOPWORDS = frozenset((
    'the', 'a', 'an', 'of', 'and', 'or', 'to', 'in', 'is', 'are', 'be',
    '的', '与', '和', '或', '在', '以', '及', '对', '于', '并',
))

# 正文模板变量匹配模式（§3.3）。
_VARIABLE_PATTERN = re.compile(r'\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}')

# 花括号占位符形态匹配模式（§3.5，emit 表达式如 {name}/{tools|pascal} 与
# routing 路径模板如 agents/{name}.md 共用）。
_EMIT_PATTERN = re.compile(r'\{([^{}]+)\}')

# 模型成本倍率形态（x0.05 / x3.50，对齐 budget-models.schema.json pattern）。
_COST_PATTERN = re.compile(r'^x[0-9]+(?:\.[0-9]+)?$')

# opencode 预设值 provider/model 形态（对齐 budget-models.schema.json pattern）。
_OPENCODE_ID_PATTERN = re.compile(r'^[a-z0-9-]+/[a-z0-9][a-z0-9.-]*$')

# 双引号字符串转义映射。
_ESCAPES = {'n': '\n', 't': '\t', '"': '"', '\\': '\\', '0': '\0'}


class BuildError(Exception):
    """构建失败（校验/转换/流程错误）。"""


class YamlParseError(Exception):
    """YAML 子集解析错误，消息含行号定位。"""

    def __init__(self, message: str, lineno: int):
        super().__init__(f'第 {lineno} 行: {message}')
        self.lineno = lineno


class QuotedStr(str):
    """输出时强制加引号的字符串（permission map 值形态，§3.2 示例带引号）。"""


def warn(message: str) -> None:
    """向 stderr 输出构建告警（不中断构建）。"""
    print(f'[build] 告警: {message}', file=sys.stderr)


# ---------------------------------------------------------------------------
# YAML 子集解析器（design.md §12-A5）
# ---------------------------------------------------------------------------

def _strip_comment(raw: str) -> str:
    """剥离行内注释：引号外且前置空白的 # 开始为注释（YAML 规范）。"""
    quote: str | None = None
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if quote is not None:
            if quote == '"' and ch == '\\':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == '#' and (i == 0 or raw[i - 1] in ' \t'):
            return raw[:i].rstrip()
        i += 1
    return raw.rstrip()


def _parse_quoted(text: str, lineno: int) -> tuple[str, str]:
    """解析 text 开头的引号字符串，返回 (字符串值, 剩余文本)。

    双引号支持 \\" \\\\ \\n \\t \\0 转义；单引号内 '' 表示字面单引号。
    """
    quote = text[0]
    buf: list[str] = []
    i = 1
    n = len(text)
    while i < n:
        ch = text[i]
        if quote == '"':
            if ch == '\\':
                if i + 1 >= n:
                    raise YamlParseError('转义字符不完整', lineno)
                nxt = text[i + 1]
                if nxt not in _ESCAPES:
                    raise YamlParseError(f'不支持的转义 \\{nxt}', lineno)
                buf.append(_ESCAPES[nxt])
                i += 2
                continue
            if ch == '"':
                return ''.join(buf), text[i + 1:]
        else:
            if ch == "'" and i + 1 < n and text[i + 1] == "'":
                buf.append("'")
                i += 2
                continue
            if ch == "'":
                return ''.join(buf), text[i + 1:]
        buf.append(ch)
        i += 1
    raise YamlParseError('引号未闭合', lineno)


def _skip_flow_ws(text: str, i: int) -> int:
    """跳过流式语法中的空白字符。"""
    while i < len(text) and text[i] in ' \t':
        i += 1
    return i


def _scalar_from_token(token: str) -> object:
    """裸标量转 Python 值：null/bool/int/float/字符串。"""
    if token in ('null', 'Null', 'NULL', '~'):
        return None
    if token in ('true', 'True', 'TRUE'):
        return True
    if token in ('false', 'False', 'FALSE'):
        return False
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


def _parse_flow_value(text: str, start: int, lineno: int) -> tuple[object, int]:
    """解析流式上下文中的单个值（嵌套流式/引号/裸标量），返回 (值, 结束位置)。"""
    i = _skip_flow_ws(text, start)
    n = len(text)
    if i >= n:
        raise YamlParseError('流式语法意外结束', lineno)
    ch = text[i]
    if ch == '[':
        return _parse_flow_list(text, i, lineno)
    if ch == '{':
        return _parse_flow_map(text, i, lineno)
    if ch in ('"', "'"):
        value, rest = _parse_quoted(text[i:], lineno)
        return value, n - len(rest)
    # 裸标量：读到流式分隔符为止。
    j = i
    while j < n and text[j] not in ',]}':
        j += 1
    token = text[i:j].strip()
    if not token:
        raise YamlParseError('流式语法存在空项', lineno)
    return _scalar_from_token(token), j


def _parse_flow_list(text: str, start: int, lineno: int) -> tuple[list, int]:
    """解析行内流式 list（[a, b, ...]），返回 (list, 结束位置)。"""
    i = start + 1  # 跳过 '['
    n = len(text)
    result: list = []
    while True:
        i = _skip_flow_ws(text, i)
        if i >= n:
            raise YamlParseError('流式 list 未闭合', lineno)
        if text[i] == ']':
            return result, i + 1
        value, i = _parse_flow_value(text, i, lineno)
        result.append(value)
        i = _skip_flow_ws(text, i)
        if i < n and text[i] == ',':
            i += 1
        elif i < n and text[i] == ']':
            return result, i + 1
        else:
            raise YamlParseError('流式 list 未闭合或存在多余字符', lineno)


def _parse_flow_map(text: str, start: int, lineno: int) -> tuple[dict, int]:
    """解析行内流式 map（{k: v, ...}），返回 (map, 结束位置)。"""
    i = start + 1  # 跳过 '{'
    n = len(text)
    result: dict = {}
    while True:
        i = _skip_flow_ws(text, i)
        if i >= n:
            raise YamlParseError('流式 map 未闭合', lineno)
        if text[i] == '}':
            return result, i + 1
        # key：引号字符串或裸标量（读到 : , } 为止）。
        if text[i] in ('"', "'"):
            key, rest = _parse_quoted(text[i:], lineno)
            i = n - len(rest)
        else:
            j = i
            while j < n and text[j] not in ':,}':
                j += 1
            key = text[i:j].strip()
            if not key:
                raise YamlParseError('流式 map 存在空键', lineno)
            i = j
        i = _skip_flow_ws(text, i)
        if i >= n or text[i] != ':':
            raise YamlParseError('流式 map 缺少键值分隔冒号', lineno)
        i += 1
        value, i = _parse_flow_value(text, i, lineno)
        if key in result:
            raise YamlParseError(f'流式 map 重复键: {key}', lineno)
        result[key] = value
        i = _skip_flow_ws(text, i)
        if i < n and text[i] == ',':
            i += 1
        elif i < n and text[i] == '}':
            return result, i + 1
        else:
            raise YamlParseError('流式 map 未闭合或存在多余字符', lineno)


def _parse_scalar(raw: str, lineno: int) -> object:
    """解析值标量（引号/流式/裸），拒绝不支持的 YAML 语法。"""
    text = raw.strip()
    if not text:
        return None
    first = text[0]
    if first == '&':
        raise YamlParseError('不支持锚点（&）', lineno)
    if first == '*':
        raise YamlParseError('不支持别名引用（*）', lineno)
    if first == '!':
        raise YamlParseError('不支持 YAML tag（!）', lineno)
    if first in ('|', '>'):
        raise YamlParseError(f'不支持多行字符串（{text}）', lineno)
    if first in ('"', "'"):
        value, rest = _parse_quoted(text, lineno)
        if rest.strip():
            raise YamlParseError(f'引号字符串后有多余内容: {rest.strip()!r}', lineno)
        return value
    if first in ('[', '{'):
        value, end = _parse_flow_value(text, 0, lineno)
        if text[end:].strip():
            raise YamlParseError(f'流式语法后有多余内容: {text[end:].strip()!r}', lineno)
        return value
    return _scalar_from_token(text)


def _split_key_value(content: str, lineno: int) -> tuple[str, str] | None:
    """切分 `key: value` 行，返回 (键原文, 值原文)；非键值形态返回 None。

    仅识别冒号后为行尾或空白的分隔（YAML 规范）；引号内的冒号不参与切分。
    """
    quote: str | None = None
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        if quote is not None:
            if quote == '"' and ch == '\\':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == ':' and (i + 1 == n or content[i + 1] in ' \t'):
            key = content[:i].strip()
            if not key:
                raise YamlParseError('存在空键名', lineno)
            return key, content[i + 1:].strip()
        i += 1
    return None


def _parse_key(key_raw: str, lineno: int) -> str:
    """解析键名（引号或裸标量）。"""
    if key_raw and key_raw[0] in ('"', "'"):
        key, rest = _parse_quoted(key_raw, lineno)
        if rest.strip():
            raise YamlParseError(f'键名后有多余内容: {rest.strip()!r}', lineno)
        return key
    return key_raw


def _preprocess_lines(text: str) -> list[tuple[int, str, int]]:
    """逐行预处理：tab 检查、注释剥离、缩进计算、不支持语法预检。

    返回 (缩进空格数, 去缩进内容, 行号) 列表（空行与纯注释行跳过）。
    """
    lines: list[tuple[int, str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if '\t' in raw:
            raise YamlParseError('不支持 tab 缩进（请统一使用空格）', lineno)
        content = _strip_comment(raw)
        stripped = content.strip()
        if not stripped:
            continue
        if stripped == '---' or stripped.startswith('--- '):
            raise YamlParseError('不支持文档分隔符（---）', lineno)
        if stripped == '...' or stripped.startswith('... '):
            raise YamlParseError('不支持文档结束标记（...）', lineno)
        indent = len(content) - len(content.lstrip(' '))
        lines.append((indent, stripped, lineno))
    return lines


def _parse_block(lines: list[tuple[int, str, int]], idx: int, indent: int) -> tuple[object, int]:
    """解析 lines[idx:] 起始缩进为 indent 的块，返回 (值, 下一行索引)。"""
    content = lines[idx][1]
    if content.startswith('- '):
        return _parse_block_list(lines, idx, indent)
    return _parse_block_map(lines, idx, indent)


def _parse_block_map(lines: list[tuple[int, str, int]], idx: int, indent: int) -> tuple[dict, int]:
    """解析块式 map：同级 `key: value` 行序列（值可嵌套子块）。"""
    result: dict = {}
    while idx < len(lines):
        cur_indent, content, lineno = lines[idx]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise YamlParseError(f'意外缩进（期望 {indent} 空格，实际 {cur_indent}）', lineno)
        kv = _split_key_value(content, lineno)
        if kv is None:
            raise YamlParseError(f'无法解析的行: {content}', lineno)
        key_raw, value_raw = kv
        key = _parse_key(key_raw, lineno)
        if key in result:
            raise YamlParseError(f'重复键: {key}', lineno)
        if value_raw:
            result[key] = _parse_scalar(value_raw, lineno)
            idx += 1
        elif idx + 1 < len(lines) and lines[idx + 1][0] > indent:
            # 值为空且下一行更深：嵌套子块。
            result[key], idx = _parse_block(lines, idx + 1, lines[idx + 1][0])
        else:
            result[key] = None
            idx += 1
    return result, idx


def _parse_block_list(lines: list[tuple[int, str, int]], idx: int, indent: int) -> tuple[list, int]:
    """解析块式 list：同级 `- item` 行序列。

    项为 `key: value` 形态时按「块式 list 项为 map」处理：将本行原地改写为
    项内容缩进（indent + 2）的 map 行，后续对齐续行由 _parse_block_map 一并消费
    （lines 为解析器内部临时结构，原地改写安全）。
    """
    result: list = []
    while idx < len(lines):
        cur_indent, content, lineno = lines[idx]
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise YamlParseError(f'意外缩进（期望 {indent} 空格，实际 {cur_indent}）', lineno)
        if not content.startswith('- '):
            break  # 同级非 list 行：交回父级（父级负责继续或报错）。
        item = content[2:].strip()
        if not item:
            raise YamlParseError('不支持的空 list 项（- 后须有内容）', lineno)
        if item.startswith('- '):
            raise YamlParseError('不支持嵌套块式 list', lineno)
        kv = _split_key_value(item, lineno)
        if kv is not None:
            lines[idx] = (indent + 2, item, lineno)
            value, idx = _parse_block_map(lines, idx, indent + 2)
        else:
            value = _parse_scalar(item, lineno)
            idx += 1
        result.append(value)
    return result, idx


def parse_yaml(text: str) -> object:
    """解析 YAML 子集文本（语法清单见模块 docstring），返回顶层结构。

    解析失败抛 YamlParseError（消息含行号定位）。
    """
    lines = _preprocess_lines(text)
    if not lines:
        return {}
    value, idx = _parse_block(lines, 0, lines[0][0])
    if idx < len(lines):
        _, content, lineno = lines[idx]
        raise YamlParseError(f'顶层块结束后仍有内容: {content}', lineno)
    return value


# ---------------------------------------------------------------------------
# YAML 序列化（frontmatter 输出）
# ---------------------------------------------------------------------------

def _needs_quote(text: str) -> bool:
    """判断字符串标量输出时是否需要引号包裹（保证产物可被解析回原值）。"""
    if text == '' or text != text.strip():
        return True
    if '\n' in text or '\r' in text:
        return True
    if text[0] in ('"', "'", '!', '&', '*', '|', '>', '{', '[', ',', '#'):
        return True
    if any(ch in text for ch in ':#*{}[]'):
        return True
    if text.lower() in ('null', '~', 'true', 'false', 'yes', 'no'):
        return True
    for conv in (int, float):
        try:
            conv(text)
            return True
        except ValueError:
            continue
    return False


def _dump_scalar(value: object) -> str:
    """标量序列化为 YAML 子集文本。"""
    if isinstance(value, QuotedStr):
        escaped = str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        return f'"{escaped}"'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if value is None:
        return 'null'
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if _needs_quote(text):
        escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        return f'"{escaped}"'
    return text


def _dump_key(key: str) -> str:
    """键名序列化（需要时加引号，如 "*" 与 "openspec/**"）。"""
    text = str(key)
    if _needs_quote(text):
        escaped = text.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return text


def dump_yaml_lines(value: dict, indent: int = 0) -> list[str]:
    """将 map 序列化为块式 YAML 行（嵌套 map 块式、list 行内流式）。"""
    prefix = '  ' * indent
    lines: list[str] = []
    for key, item in value.items():
        key_text = _dump_key(key)
        if isinstance(item, dict):
            if not item:
                lines.append(f'{prefix}{key_text}: {{}}')
            else:
                lines.append(f'{prefix}{key_text}:')
                lines.extend(dump_yaml_lines(item, indent + 1))
        elif isinstance(item, list):
            entries = ', '.join(_dump_scalar(entry) for entry in item)
            lines.append(f'{prefix}{key_text}: [{entries}]')
        else:
            lines.append(f'{prefix}{key_text}: {_dump_scalar(item)}')
    return lines


def dump_frontmatter(data: dict) -> str:
    """序列化 frontmatter 文本（含 --- 包裹，字段按插入顺序输出）。"""
    lines = dump_yaml_lines(data)
    return '---\n' + '\n'.join(lines) + '\n---\n'


# ---------------------------------------------------------------------------
# DSL schema 校验（design.md §3.5）
# ---------------------------------------------------------------------------

def _check_path_value(value: str, field: str, path: str) -> None:
    """检查单个路径值：拒绝 .. 路径片段与绝对路径（防逃逸出产物根目录）。

    `..` 按独立路径片段判定（如 `a/../b`、`../x`），`a..b` 类字面名不误伤；
    以 `/` 或 `\\` 开头视为绝对路径拒绝。
    """
    segments = re.split(r'[/\\]+', value)
    if any(seg == '..' for seg in segments):
        raise BuildError(
            f'{path}: {field} 含 ".." 路径片段，禁止逃逸出产物根目录（当前值: {value}）')
    if value.startswith('/') or value.startswith('\\'):
        raise BuildError(
            f'{path}: {field} 不得为绝对路径（当前值: {value}）')


def _check_routing_placeholders(value: str, field: str, path: str) -> None:
    """校验路由模板值中的 {xxx} 占位符 ∈ ROUTING_PLACEHOLDERS（§3.5）。

    防拼写错误（如 agents/{nmae}.md）静默落位到字面量路径。
    """
    for name in _EMIT_PATTERN.findall(value):
        if name not in ROUTING_PLACEHOLDERS:
            raise BuildError(
                f'{path}: {field} 含未知路由占位符 {{{name}}}'
                f'（合法占位符: {sorted(ROUTING_PLACEHOLDERS)}）')


def _iter_routing_path_fields(routing: dict, dsl: dict) -> Iterator[tuple[str, str]]:
    """遍历全部路由路径类字段，逐一产出 (字段名, 值)。

    覆盖（§3.5 路径模板统一防逃逸）：routing 八类字符串模板值（含可选 hook）、
    routing.docs 的目标路径（null 不分发，跳过）、extra_outputs 的 dest/source。
    """
    for key in ROUTING_STRING_KEYS:
        yield f'routing.{key}', routing[key]
    if 'hook' in routing:
        yield 'routing.hook', routing['hook']
    for src, dest in routing['docs'].items():
        if dest is not None:
            yield f'routing.docs[{src}]', dest
    for i, spec in enumerate(dsl.get('extra_outputs', [])):
        for key in ('dest', 'source'):
            if isinstance(spec.get(key), str):
                yield f'extra_outputs[{i}].{key}', spec[key]


def validate_dsl(dsl: object, path: str) -> dict:
    """校验 platform DSL schema（§3.5 字段表），不符抛 BuildError。"""
    if not isinstance(dsl, dict):
        raise BuildError(f'{path}: DSL 顶层必须是 map')
    for key in DSL_TOP_REQUIRED:
        if key not in dsl:
            raise BuildError(f'{path}: DSL 缺少顶层字段 {key}')
    if not isinstance(dsl['platform'], str) or not dsl['platform']:
        raise BuildError(f'{path}: platform 必须是非空字符串')
    output = dsl['output']
    if not isinstance(output, str) or not output.startswith('dist/') or '..' in output:
        raise BuildError(f'{path}: output 必须是形如 dist/<platform> 的相对路径')
    routing = dsl['routing']
    if not isinstance(routing, dict):
        raise BuildError(f'{path}: routing 必须是 map')
    for key in ROUTING_REQUIRED_KEYS:
        if key not in routing:
            raise BuildError(f'{path}: routing 缺少路径规则键 {key}')
    for key in ROUTING_STRING_KEYS:
        if not isinstance(routing[key], str) or not routing[key]:
            raise BuildError(f'{path}: routing.{key} 必须是非空字符串')
    if 'hook' in routing and not isinstance(routing['hook'], str):
        raise BuildError(f'{path}: routing.hook 必须是字符串（空串表示不分发）')
    docs = routing['docs']
    if not isinstance(docs, dict):
        raise BuildError(f'{path}: routing.docs 必须是显式 map（源文件名 → 目标路径或 null）')
    for src, dest in docs.items():
        if dest is not None and not isinstance(dest, str):
            raise BuildError(f'{path}: routing.docs[{src}] 的目标必须是字符串或 null')
    agent_fm = dsl['agent_frontmatter']
    if not isinstance(agent_fm, dict):
        raise BuildError(f'{path}: agent_frontmatter 必须是 map')
    emit = agent_fm.get('emit')
    if not isinstance(emit, dict) or not emit:
        raise BuildError(f'{path}: agent_frontmatter.emit 必须是非空 map')
    for out_key, expr in emit.items():
        if not isinstance(expr, str) or not expr:
            raise BuildError(f'{path}: agent_frontmatter.emit.{out_key} 表达式必须是非空字符串')
        # 形如 {xxx} 的整体表达式必须 ∈ emit 域合法表达式集合（§3.5 精确七表达式，
        # 无裸 {tools}；routing 占位符不在 emit 域），防拼写错误静默字面量输出。
        match = _EMIT_PATTERN.fullmatch(expr)
        if match is not None and match.group(1) not in EMIT_EXPRESSIONS:
            raise BuildError(
                f'{path}: agent_frontmatter.emit.{out_key} 表达式 {expr} 含未知占位符'
                f'（合法表达式: {sorted(EMIT_EXPRESSIONS)}）')
    if 'drop' in agent_fm and not isinstance(agent_fm['drop'], list):
        raise BuildError(f'{path}: agent_frontmatter.drop 必须是 list')
    if 'permission_mode_rule' in agent_fm and not isinstance(agent_fm['permission_mode_rule'], dict):
        raise BuildError(f'{path}: agent_frontmatter.permission_mode_rule 必须是 map')
    command_fm = dsl['command_frontmatter']
    if not isinstance(command_fm, dict):
        raise BuildError(f'{path}: command_frontmatter 必须是 map')
    for key in ('emit', 'drop'):
        if key not in command_fm or not isinstance(command_fm[key], list):
            raise BuildError(f'{path}: command_frontmatter.{key} 必须是 list')
    command = dsl['command']
    if not isinstance(command, dict) or not isinstance(command.get('invoke'), str):
        raise BuildError(f'{path}: command.invoke 必须是字符串')
    body_variables = dsl['body_variables']
    if not isinstance(body_variables, dict):
        raise BuildError(f'{path}: body_variables 必须是 map')
    for name in body_variables:
        if name not in BODY_VARIABLES_WHITELIST:
            raise BuildError(f'{path}: body_variables 声明了白名单之外的变量 {name}')
    if 'extra_outputs' in dsl:
        extra = dsl['extra_outputs']
        if not isinstance(extra, list):
            raise BuildError(f'{path}: extra_outputs 必须是 list')
        for i, spec in enumerate(extra):
            if not isinstance(spec, dict):
                raise BuildError(f'{path}: extra_outputs[{i}] 必须是 map（块式 list 项为 map 形态）')
            for key in ('kind', 'source', 'dest'):
                if not isinstance(spec.get(key), str) or not spec[key]:
                    raise BuildError(f'{path}: extra_outputs[{i}] 缺少非空字符串字段 {key}')
            if spec.get('kind') == 'agents_fragment':
                # routing.rule 与合并目标一致性（防 DSL 漂移）。
                if routing.get('rule') != spec.get('dest'):
                    raise BuildError(
                        f'{path}: routing.rule（{routing.get("rule")}）与 extra_outputs '
                        f'agents_fragment dest（{spec.get("dest")}）不一致')
    # 路径模板统一防逃逸 + 占位符域校验（结构校验通过后执行）：全部路由值
    # 拒绝 .. 片段与绝对路径；{xxx} 占位符必须 ∈ ROUTING_PLACEHOLDERS。
    for field, value in _iter_routing_path_fields(routing, dsl):
        _check_path_value(value, field, path)
        _check_routing_placeholders(value, field, path)
    return dsl


# ---------------------------------------------------------------------------
# frontmatter 加载与中立源校验（design.md §3.1）
# ---------------------------------------------------------------------------

def load_frontmatter(text: str, path: str) -> tuple[dict, str]:
    """加载 markdown frontmatter（--- 包裹），返回 (frontmatter, 正文)。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        raise BuildError(f'{path}: 缺少 frontmatter 起始标记（首行须为 ---）')
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            fm_text = '\n'.join(lines[1:i])
            body = '\n'.join(lines[i + 1:])
            try:
                fm = parse_yaml(fm_text)
            except YamlParseError as exc:
                raise BuildError(f'{path}: frontmatter 解析失败（{exc}）') from exc
            if not isinstance(fm, dict):
                raise BuildError(f'{path}: frontmatter 必须是键值 map')
            return fm, body
    raise BuildError(f'{path}: frontmatter 未闭合（缺少结束 ---）')


def _permission_lists(fm: dict, path: str) -> tuple[list, list]:
    """读取并校验 edit_allow/bash_allow 三态，返回 (edit_allow, bash_allow)。

    三态（§3.1）：["*"] 全放开 / 非空条目列表受限 / [] 显式全禁止；
    ["*"] 与具体条目混合或非列表形态判非法；缺省视为 ["*"]。
    """
    permissions = fm.get('permissions') or {}
    values: list[list] = []
    for key in ('edit_allow', 'bash_allow'):
        value = permissions.get(key, ['*'])
        if not isinstance(value, list):
            raise BuildError(f'{path}: permissions.{key} 必须是列表（三态之一）')
        if '*' in value and len(value) != 1:
            raise BuildError(
                f'{path}: permissions.{key} 非法三态（["*"] 不可与具体条目混合；'
                '合法形态：["*"] 全放开 / 非空条目列表 / [] 显式全禁止）')
        values.append(value)
    return values[0], values[1]


def validate_agent(fm: dict, body: str, name: str, path: str, roles: list[str] | None) -> None:
    """校验 agent 中立 frontmatter 与正文（§3.1），违规抛 BuildError。"""
    for field in ('name', 'description', 'model_role', 'tools'):
        if field not in fm:
            raise BuildError(f'{path}: agent frontmatter 缺少必填字段 {field}')
    if fm['name'] != name:
        raise BuildError(f'{path}: name（{fm["name"]}）与文件主名（{name}）不一致')
    if not isinstance(fm['description'], str) or not fm['description'].strip():
        raise BuildError(f'{path}: description 必须是非空字符串')
    if not isinstance(fm['model_role'], str) or not fm['model_role']:
        raise BuildError(f'{path}: model_role 必须是非空字符串')
    if roles is not None and fm['model_role'] not in roles:
        raise BuildError(f'{path}: model_role（{fm["model_role"]}）不在 budget-models.json roles 中')
    tools = fm['tools']
    if not isinstance(tools, list) or not tools:
        raise BuildError(f'{path}: tools 必须是非空列表')
    for tool in tools:
        if tool not in TOOLS_WHITELIST:
            raise BuildError(
                f'{path}: tools 含白名单之外的工具 {tool}（白名单: {sorted(TOOLS_WHITELIST)}）')
    permissions = fm.get('permissions')
    if permissions is not None and not isinstance(permissions, dict):
        raise BuildError(f'{path}: permissions 必须是 map')
    if isinstance(permissions, dict):
        unknown = set(permissions) - {'edit_allow', 'bash_allow'}
        if unknown:
            raise BuildError(f'{path}: permissions 含未知键 {sorted(unknown)}')
    edit_allow, bash_allow = _permission_lists(fm, path)
    # §3.1 校验⑥：tools 与 permissions 语义一致。
    if not bash_allow and 'bash' in tools:
        raise BuildError(f'{path}: bash_allow 为 []（显式禁止）但 tools 含 bash，语义不一致')
    if not edit_allow and ('write' in tools or 'edit' in tools):
        raise BuildError(f'{path}: edit_allow 为 []（显式全禁止）但 tools 含 write/edit，语义不一致')
    if 'max_turns' in fm:
        max_turns = fm['max_turns']
        if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns <= 0:
            raise BuildError(f'{path}: max_turns 必须是正整数')
    if not body.strip():
        raise BuildError(f'{path}: frontmatter 之后必须有非空正文')


def validate_command(fm: dict, body: str, path: str) -> None:
    """校验命令中立 frontmatter 与正文（§3.1 命令 schema）。"""
    for field in ('name', 'description'):
        if field not in fm:
            raise BuildError(f'{path}: 命令 frontmatter 缺少必填字段 {field}')
    name = fm['name']
    if not isinstance(name, str) or ':' not in name:
        raise BuildError(f'{path}: 命令 name 必须是形如 "<组>: <标题>" 的显示名')
    group = name.split(':', 1)[0].strip()
    if group not in COMMAND_GROUPS:
        raise BuildError(f'{path}: 命令 name 的组（{group}）须 ∈ {list(COMMAND_GROUPS)}')
    if not isinstance(fm['description'], str) or not fm['description'].strip():
        raise BuildError(f'{path}: description 必须是非空字符串')
    if 'argument-hint' in fm and not isinstance(fm['argument-hint'], str):
        raise BuildError(f'{path}: argument-hint 必须是字符串')
    if not body.strip():
        raise BuildError(f'{path}: frontmatter 之后必须有非空正文')


# ---------------------------------------------------------------------------
# frontmatter 重写与变量替换（design.md §3.2/§3.3）
# ---------------------------------------------------------------------------

def resolve_model(platform: str, model_role: str, models_data: dict, path: str) -> str:
    """按 balanced 预设解析 model_role → 模型 ID（§3.2 构建期烘焙）。"""
    try:
        value = models_data['platforms'][platform]['presets']['balanced'][model_role]
    except (KeyError, TypeError) as exc:
        raise BuildError(
            f'{path}: model_role（{model_role}）在 budget-models.json '
            f'platforms.{platform}.presets.balanced 中无映射') from exc
    if not isinstance(value, str) or not value:
        raise BuildError(f'{path}: 解析出的 model 为空')
    return value


def compute_permission_mode(fm: dict, rule: dict, path: str) -> str:
    """CodeBuddy 粗粒度 permissionMode（§3.2）：edit 全放开→acceptEdits，受限/禁止→plan。"""
    edit_allow, _ = _permission_lists(fm, path)
    state = 'edit_all' if edit_allow == ['*'] else 'edit_restricted'
    if state not in rule:
        raise BuildError(f'{path}: permission_mode_rule 缺少 {state} 映射')
    return rule[state]


def compute_permission_map(fm: dict, path: str) -> dict:
    """OpenCode 细粒度 permission map（§3.2 三分支，值为带引号形态）。"""
    edit_allow, bash_allow = _permission_lists(fm, path)
    if edit_allow == ['*']:
        edit_map: dict = {'*': QuotedStr('allow')}
    else:
        edit_map = {'*': QuotedStr('deny')}
        for pattern in edit_allow:
            edit_map[pattern] = QuotedStr('allow')
    if bash_allow == ['*']:
        bash_map: dict = {'*': QuotedStr('allow')}
    elif not bash_allow:
        bash_map = {'*': QuotedStr('deny')}
    else:
        bash_map = {'*': QuotedStr('ask')}
        for pattern in bash_allow:
            bash_map[pattern] = QuotedStr('allow')
    return {'edit': edit_map, 'bash': bash_map}


def rewrite_agent(fm: dict, body: str, dsl: dict, platform: str,
                  models_data: dict | None, path: str) -> str:
    """按 DSL emit 表重写 agent frontmatter（§3.2），返回产物全文。"""
    agent_fm = dsl['agent_frontmatter']
    emit = agent_fm['emit']
    mode_rule = agent_fm.get('permission_mode_rule', {})
    out: dict = {}
    for out_key, expr in emit.items():
        if expr == '{name}':
            out[out_key] = fm['name']
        elif expr == '{description}':
            out[out_key] = fm['description']
        elif expr == '{resolved_model}':
            if models_data is None:
                warn(f'{path}: budget-models.json 缺失，跳过 model 烘焙（产物不含 model 字段）')
                continue
            out[out_key] = resolve_model(platform, fm['model_role'], models_data, path)
        elif expr == '{tools|pascal}':
            # 白名单封闭集合（校验前置），复合词映射见 _TOOL_PASCAL。
            out[out_key] = [_TOOL_PASCAL[tool] for tool in fm['tools']]
        elif expr == '{permission_mode}':
            out[out_key] = compute_permission_mode(fm, mode_rule, path)
        elif expr == '{permission_map}':
            out[out_key] = compute_permission_map(fm, path)
        elif expr == '{max_turns}':
            # 仅源存在时输出（§3.5 emit 表约定）。
            if 'max_turns' in fm:
                out[out_key] = fm['max_turns']
        else:
            out[out_key] = expr  # 字面量（如 subagent）
    return dump_frontmatter(out) + body


def rewrite_command(fm: dict, body: str, dsl: dict) -> str:
    """按 DSL emit 列表直出命令 frontmatter 字段（§3.2 命令映射）。"""
    out: dict = {}
    for field in dsl['command_frontmatter']['emit']:
        if field in fm:
            out[field] = fm[field]
    return dump_frontmatter(out) + body


def replace_variables(text: str, body_variables: dict, path: str) -> str:
    """正文模板变量白名单精确替换（§3.3）：未知名保留原样并告警。"""

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        if name in body_variables:
            return body_variables[name]
        warn(f'{path}: 未知模板变量 {{{{{name}}}}} 保留原样（已知变量: {sorted(body_variables)}）')
        return match.group(0)

    return _VARIABLE_PATTERN.sub(_replace, text)


def route_path(template: str, fields: dict) -> str:
    """按 {name}/{skill}/{group}/{path} 占位符展开 routing 路径模板（§3.5）。"""
    result = template
    for key, value in fields.items():
        result = result.replace('{' + key + '}', value)
    return result


# ---------------------------------------------------------------------------
# 模型目录结构校验与 MODEL_SELECTION 渲染（design.md §7/§4/§12-A6）
# ---------------------------------------------------------------------------

def _ordered_vendors(groups: dict) -> list[str]:
    """厂商组固定顺序：_VENDOR_ORDER 内按序，其余按名称字母序（确定性渲染）。"""
    known = [vendor for vendor in _VENDOR_ORDER if vendor in groups]
    extra = sorted(vendor for vendor in groups if vendor not in _VENDOR_ORDER)
    return known + extra


def _validate_model_entry(entry: object, label: str, seen: dict[str, str],
                          valid_platforms: frozenset[str]) -> None:
    """校验单个模型条目（id/tier/cost/tags/platform），违规抛 BuildError。

    seen 为「模型 ID → 首次出现位置标签」映射，用于重复 ID 报错定位。
    valid_platforms 为合法 platform 取值集合（由 budget-models.json 的
    platforms 键集推导，数据内自洽校验——条目 platform 值须 ∈ 该键集）。
    """
    if not isinstance(entry, dict):
        raise BuildError(f'{label}: 模型条目必须是对象')
    for field in ('id', 'tier', 'cost', 'tags', 'platform'):
        if field not in entry:
            raise BuildError(f'{label}: 模型条目缺少必填字段 {field}')
    entry_id = entry['id']
    if not isinstance(entry_id, str) or not entry_id:
        raise BuildError(f'{label}: id 必须是非空字符串')
    if entry_id in seen:
        raise BuildError(f'{label}: 模型 ID {entry_id} 重复（首见于 {seen[entry_id]}）')
    seen[entry_id] = label
    if entry['tier'] not in _MODEL_TIERS:
        raise BuildError(f'{label}: tier（{entry["tier"]}）须 ∈ {sorted(_MODEL_TIERS)}')
    cost = entry['cost']
    if not isinstance(cost, str) or _COST_PATTERN.fullmatch(cost) is None:
        raise BuildError(f'{label}: cost（{cost}）须形如 x0.05')
    tags = entry['tags']
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
        raise BuildError(f'{label}: tags 必须是非空字符串数组')
    entry_platforms = entry['platform']
    if not isinstance(entry_platforms, list) or not entry_platforms:
        raise BuildError(f'{label}: platform 须为非空数组')
    # 键集为空视为数据未就位（只校验已有键），跳过枚举校验。
    if valid_platforms and any(item not in valid_platforms for item in entry_platforms):
        raise BuildError(
            f'{label}: platform 取值须 ∈ budget-models.json platforms 键集'
            f'（合法键集: {sorted(valid_platforms)}）')


def _validate_preset_value(value: object, platform: str, catalog: dict[str, list],
                           label: str) -> None:
    """校验预设值：默认 catalog_id 策略；opencode 特判 provider/model 格式。

    默认策略（除 opencode 外的全部平台，claudecode 及后续平台零代码接入）：
    值 ∈ 模型目录且该条目 platform 数组含本平台；opencode 单平台分支保留
    provider/model 形态与 provider 白名单校验（策略集合稳定，收敛于此）。
    """
    if not isinstance(value, str) or not value:
        raise BuildError(f'{label}: 预设值必须是非空字符串')
    if platform != 'opencode':
        if value not in catalog:
            raise BuildError(f'{label}: 预设值 {value} 不在模型目录中')
        if platform not in catalog[value]:
            raise BuildError(f'{label}: 预设值 {value} 的 platform 不含 {platform}')
        return
    if _OPENCODE_ID_PATTERN.fullmatch(value) is None:
        raise BuildError(f'{label}: opencode 预设值须为 provider/model 格式（当前 {value}）')
    provider, model = value.split('/', 1)
    if provider not in OPENCODE_PROVIDERS:
        raise BuildError(f'{label}: provider（{provider}）须 ∈ {sorted(OPENCODE_PROVIDERS)}')
    if model not in catalog:
        raise BuildError(f'{label}: 预设模型 {model} 不在模型目录中')
    if 'opencode' not in catalog[model]:
        raise BuildError(f'{label}: 预设模型 {model} 的 platform 不含 opencode')


def validate_models_data(data: dict, path: str) -> dict:
    """校验 budget-models.json 结构（§7，规则对齐 budget-models.schema.json）。

    数据就位后构建期全量校验（D §4 降级规则的恢复面：models 存在即生效）；
    校验通过返回原数据，违规抛 BuildError（消息含定位标签）。
    平台清单数据驱动：条目 platform 合法域与预设三档校验循环均遍历
    data['platforms'] 键集（数据内自洽，非硬编码枚举）。
    provider_map 构建期必含且须覆盖 models.paid/free 全部组名（schema 侧
    optional 仅兼容用户旧配置；T10a agent custom 别名解析依赖该映射）。
    """
    for key in ('_meta', 'aliases', 'roles', 'models', 'platforms'):
        if key not in data:
            raise BuildError(f'{path}: budget-models.json 缺少顶层键 {key}')
    meta = data['_meta']
    if not isinstance(meta, dict):
        raise BuildError(f'{path}: _meta 必须是对象')
    for key in ('description', 'updated_at', 'update_command'):
        value = meta.get(key)
        if not isinstance(value, str) or not value:
            raise BuildError(f'{path}: _meta.{key} 必须是非空字符串')
    unconfirmed = meta.get('unconfirmed_opencode_ids')
    if unconfirmed is not None and (
            not isinstance(unconfirmed, list)
            or any(not isinstance(item, str) or not item for item in unconfirmed)):
        raise BuildError(f'{path}: _meta.unconfirmed_opencode_ids 必须是字符串数组')
    aliases = data['aliases']
    if not isinstance(aliases, dict):
        raise BuildError(f'{path}: aliases 必须是对象（简写 → 标准 ID）')
    for alias, target in aliases.items():
        if not isinstance(target, str) or not target:
            raise BuildError(f'{path}: aliases.{alias} 必须是非空字符串')
    roles = data['roles']
    if not isinstance(roles, list) or sorted(roles) != sorted(MODEL_ROLES):
        raise BuildError(
            f'{path}: roles 必须恰为十角色键集合（期望 {list(MODEL_ROLES)}，实际 {roles}）')
    # platforms 键集前置提取（条目 platform 合法域与预设校验循环的数据源；
    # 键集为空视为数据未就位——条目枚举校验跳过、预设循环只校验已有键）。
    platforms = data['platforms']
    if not isinstance(platforms, dict):
        raise BuildError(f'{path}: platforms 必须是对象')
    platform_keys = frozenset(platforms)
    models = data['models']
    if not isinstance(models, dict):
        raise BuildError(f'{path}: models 必须是对象')
    catalog: dict[str, list] = {}
    seen: dict[str, str] = {}
    vendor_names: set[str] = set()
    for section in ('paid', 'free'):
        if section not in models:
            raise BuildError(f'{path}: models 缺少 {section} 分组')
        groups = models[section]
        if not isinstance(groups, dict):
            raise BuildError(f'{path}: models.{section} 必须是按厂商分组的对象')
        for vendor, entries in groups.items():
            vendor_names.add(vendor)
            if not isinstance(entries, list):
                raise BuildError(f'{path}: models.{section}.{vendor} 必须是数组')
            for entry in entries:
                label = f'{path}: models.{section}.{vendor}'
                _validate_model_entry(entry, label, seen, platform_keys)
                catalog[entry['id']] = list(entry['platform'])
    provider_map = data.get('provider_map')
    if not isinstance(provider_map, dict):
        raise BuildError(f'{path}: provider_map 必须是对象（厂商组 → opencode provider）')
    for vendor, provider in provider_map.items():
        if not isinstance(provider, str) or not provider:
            raise BuildError(f'{path}: provider_map.{vendor} 必须是非空字符串')
    missing_vendors = sorted(vendor_names - provider_map.keys())
    if missing_vendors:
        raise BuildError(
            f'{path}: provider_map 缺少厂商组 {missing_vendors}（agent custom 别名解析需全覆盖）')
    for platform in platforms:
        platform_data = platforms[platform]
        if not isinstance(platform_data, dict):
            raise BuildError(f'{path}: platforms.{platform} 必须是对象')
        # 可选键 note/unconfirmed_ids（D1-3 平台说明数据驱动；缺失走常量回退，
        # 文案数据迁移统一在 add-claudecode-platform 任务 2.2 落地）。
        # 空数组语义统一禁止：键存在则必须非空（与 schema minItems=1 对齐，
        # 无待确认项/无说明时直接省略键，而非写空数组占位）。
        note = platform_data.get('note')
        if note is not None and (
                not isinstance(note, list)
                or not note
                or any(not isinstance(line, str) or not line for line in note)):
            raise BuildError(f'{path}: platforms.{platform}.note 必须是非空字符串数组')
        unconfirmed = platform_data.get('unconfirmed_ids')
        if unconfirmed is not None and (
                not isinstance(unconfirmed, list)
                or not unconfirmed
                or any(not isinstance(item, str) or not item for item in unconfirmed)):
            raise BuildError(f'{path}: platforms.{platform}.unconfirmed_ids 必须是非空字符串数组')
        presets = platform_data.get('presets')
        if not isinstance(presets, dict):
            raise BuildError(f'{path}: platforms.{platform}.presets 必须是对象')
        for preset in PRESET_NAMES:
            if preset not in presets:
                raise BuildError(f'{path}: platforms.{platform}.presets 缺少 {preset} 档')
            mapping = presets[preset]
            if not isinstance(mapping, dict) or sorted(mapping) != sorted(MODEL_ROLES):
                raise BuildError(
                    f'{path}: platforms.{platform}.presets.{preset} 须覆盖全部十角色键')
            for role, value in mapping.items():
                label = f'{path}: platforms.{platform}.presets.{preset}.{role}'
                _validate_preset_value(value, platform, catalog, label)
    return data


def _render_models_table(models_data: dict) -> str:
    """生成模型目录 markdown 表（A6：paid→free、组序固定、条目按目录序）。"""
    lines: list[str] = []
    models = models_data['models']
    for section, title in (('paid', '付费模型'), ('free', '免费模型')):
        groups = models.get(section) or {}
        if not groups:
            continue
        lines.append(f'### {title}')
        lines.append('')
        lines.append('| 厂商 | 模型 ID | 档位 | 成本 | 标签 | 可用平台 | 备注 |')
        lines.append('|------|---------|------|------|------|----------|------|')
        for vendor in _ordered_vendors(groups):
            for entry in groups[vendor]:
                note = str(entry.get('note', '')).replace('|', '\\|')
                lines.append(
                    f'| {vendor} | {entry["id"]} | {entry["tier"]} | {entry["cost"]}'
                    f' | {", ".join(entry["tags"])} | {", ".join(entry["platform"])}'
                    f' | {note} |')
        lines.append('')
    return '\n'.join(lines).rstrip('\n')


def _render_preset_table(models_data: dict) -> str:
    """生成各平台三档预设表（A6：角色按 roles 序、档位 economic/balanced/quality、
    平台列按 platforms 键序——JSON 插入序，确定性由源文件保证）。"""
    roles = models_data['roles']
    platforms = models_data['platforms']
    header = ['角色']
    for platform in platforms:
        for preset in PRESET_NAMES:
            header.append(f'{platform} {preset}')
    lines = [
        '| ' + ' | '.join(header) + ' |',
        '|' + '|'.join(['------'] * len(header)) + '|',
    ]
    for role in roles:
        row = [role]
        for platform in platforms:
            for preset in PRESET_NAMES:
                row.append(models_data['platforms'][platform]['presets'][preset][role])
        lines.append('| ' + ' | '.join(row) + ' |')
    return '\n'.join(lines)


# A6 平台说明段常量回退文案（{{platform_note}} 渲染在 platforms.<p>.note 缺失时
# 沿用，保证数据迁移前双平台产物逐字节不变；文案初值迁移统一在
# add-claudecode-platform 任务 2.2 与 models 数据扩展同批落地）。
_PLATFORM_NOTE_LINES = {
    'codebuddy': (
        '- 本平台预设值为 CodeBuddy 原生模型 ID（kebab-case）；构建期以 balanced 档'
        '烘焙 agent 产物的 model 字段。',
        '- 安装后可通过 `budget setup agent preset <economic|balanced|quality>` 批量切换档位，'
        '`budget setup agent custom <模型ID或别名>` 自定义覆写（简写别名经 aliases 表解析），'
        '`budget setup agent inherit` 跟随主会话模型。',
    ),
    'opencode': (
        '- 本平台预设值为 `provider/model` 格式（anthropic/openai/google/zhipu/deepseek/'
        'moonshotai 系及 opencode 官方免费系）；使用前需在 opencode 配置中启用对应 provider。',
        '- 构建期以 balanced 档烘焙 agent 产物的 model 字段；安装后可通过 '
        '`budget setup agent preset <economic|balanced|quality>` 批量切换档位，'
        '`budget setup agent inherit` 跟随主会话模型。',
    ),
}


def _platform_unconfirmed_ids(models_data: dict, platform: str) -> list[str]:
    """读取平台待确认 ID 清单：platforms.<p>.unconfirmed_ids 优先；opencode 兼容
    读 _meta.unconfirmed_opencode_ids 旧键一个版本（新位置优先，旧键迁移在 2.2）。"""
    platform_data = (models_data.get('platforms') or {}).get(platform) or {}
    value = platform_data.get('unconfirmed_ids')
    if platform == 'opencode' and value is None:
        value = (models_data.get('_meta') or {}).get('unconfirmed_opencode_ids')
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _render_platform_note(models_data: dict, platform: str) -> str:
    """生成平台说明段（数据驱动 + 常量回退；unconfirmed_ids 非空的平台附待确认清单）。

    note 取 platforms.<p>.note（字符串数组）；缺失时回退 _PLATFORM_NOTE_LINES
    常量文案；两者皆无则告警并输出空说明段（防 KeyError 崩溃）。
    """
    platform_data = (models_data.get('platforms') or {}).get(platform) or {}
    note = platform_data.get('note')
    if isinstance(note, list) and note:
        lines = list(note)
    elif platform in _PLATFORM_NOTE_LINES:
        lines = list(_PLATFORM_NOTE_LINES[platform])
    else:
        warn(f'platforms.{platform}.note 缺失且无常量回退文案，平台说明段为空')
        lines = []
    unconfirmed = _platform_unconfirmed_ids(models_data, platform)
    if unconfirmed:
        lines.append(
            f'- 以下预设 ID 未经本机 {platform} 环境核对（待确认，上线前必须清零）：'
            + '、'.join(unconfirmed))
    return '\n'.join(lines)


def render_model_selection(template_text: str, models_data: dict, platform: str,
                           dest_rel: str) -> str:
    """MODEL_SELECTION.md 渲染管线（A6）：三占位符白名单独立于 §3.3 六变量。

    占位符替换复用 replace_variables（白名单精确匹配、未知名保留原样并告警）；
    表格按固定顺序生成（roles 序、_VENDOR_ORDER 组序），保证确定性输出。
    """
    values = {
        'models_table': _render_models_table(models_data),
        'preset_table': _render_preset_table(models_data),
        'platform_note': _render_platform_note(models_data, platform),
    }
    return replace_variables(template_text, values, dest_rel)


# ---------------------------------------------------------------------------
# P0 一致性 diff（design.md §3.4）
# ---------------------------------------------------------------------------

def _normalize_entry(text: str) -> str:
    """规范化 P0 条目（§3.4 规则 2）：strip、小写、剔除 Markdown 标记、折叠空白。"""
    lowered = text.strip().lower()
    for ch in '`*#->':
        lowered = lowered.replace(ch, ' ')
    return ' '.join(lowered.split())


def _entry_keywords(entry: str) -> set[str]:
    """条目分词（去停用词与标点）后的关键词集合（§3.4 规则 3）。"""
    tokens = re.findall(r'[a-z0-9\u4e00-\u9fff]+', entry)
    return {token for token in tokens if token not in _STOPWORDS}


def _extract_skill_p0_entries(skill_text: str) -> list[str] | None:
    """提取 SKILL.md「强制执行规则（P0）」章节的列表条目；章节缺失返回 None。"""
    entries: list[str] = []
    in_section = False
    for line in skill_text.splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            if in_section:
                break  # 下一章节开始，内联章节结束。
            if P0_SKILL_HEADING_KEYWORD in stripped:
                in_section = True
            continue
        if in_section and (stripped.startswith('- ') or stripped.startswith('* ')):
            entries.append(stripped[2:])
    if not in_section:
        return None
    return entries


def check_p0_consistency(core_dir: Path) -> list[str]:
    """P0 一致性 diff（§3.4 规则 1-4）；数据未就位时返回空列表。

    规则侧条目 = 三个 P0 规则文件全文；SKILL 侧条目 = 内联章节列表项；
    逐对按规范化关键词 80% 双向包含率判定，不一致产出告警。
    """
    rules_dir = core_dir / 'rules'
    rule_entries: list[str] = []
    for stem in P0_RULE_STEMS:
        rule_file = rules_dir / f'{stem}.md'
        if not rule_file.is_file():
            return []  # rules 数据未就位（T7 前降级跳过）。
        rule_entries.append(_read_text(rule_file, f'core/rules/{stem}.md'))
    skill_file = core_dir / 'skills' / 'budget-workflow' / 'SKILL.md'
    if not skill_file.is_file():
        return []  # SKILL.md 未就位（T3a 前降级跳过）。
    skill_entries = _extract_skill_p0_entries(_read_text(skill_file, 'skills/budget-workflow/SKILL.md'))
    if skill_entries is None:
        return []  # 内联章节未就位。
    warnings: list[str] = []
    if len(rule_entries) != len(skill_entries):
        warnings.append(
            f'P0 一致性: 条目数不一致（core/rules 侧 {len(rule_entries)} 条，'
            f'SKILL.md 内联章节 {len(skill_entries)} 条）')
        return warnings
    for i, (rule_entry, skill_entry) in enumerate(zip(rule_entries, skill_entries)):
        rule_keywords = _entry_keywords(_normalize_entry(rule_entry))
        skill_keywords = _entry_keywords(_normalize_entry(skill_entry))
        if not rule_keywords or not skill_keywords:
            warnings.append(f'P0 一致性: 第 {i + 1} 对条目分词后为空，无法比对')
            continue
        common = rule_keywords & skill_keywords
        rule_rate = len(common) / len(rule_keywords)
        skill_rate = len(common) / len(skill_keywords)
        if rule_rate < 0.8 or skill_rate < 0.8:
            warnings.append(
                f'P0 一致性: 第 {i + 1} 对条目关键词双向包含率不足 80%'
                f'（{rule_rate:.0%}/{skill_rate:.0%}）')
    return warnings


# ---------------------------------------------------------------------------
# 文件读写与构建流程（design.md §4）
# ---------------------------------------------------------------------------

def _read_text(path: Path, rel: str) -> str:
    """UTF-8 读取文本文件，失败转 BuildError。"""
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        raise BuildError(f'读取 {rel} 失败: {exc}') from exc


def _write_text(path: Path, text: str) -> None:
    """UTF-8 无 BOM、LF 写出文本文件（自动创建父目录，保证末尾换行）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith('\n'):
        text += '\n'
    try:
        with open(path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
    except OSError as exc:
        raise BuildError(f'写出 {path} 失败: {exc}') from exc


def _copy_file(src: Path, dest: Path) -> None:
    """字节平移文件（自动创建父目录，保持源文件字节一致）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(src, dest)
    except OSError as exc:
        raise BuildError(f'平移 {src} → {dest} 失败: {exc}') from exc


def _iter_files(directory: Path, suffix: str | None = None) -> list[Path]:
    """按路径排序遍历目录下全部文件（保证确定性）。

    统一剔除（§12-A8）：.gitkeep 占位、__pycache__ 目录、.pyc、.DS_Store
    构建噪音——防产物与 manifest 收录运行时缓存（build-release.sh 的 zip -x
    仅兜底文件层面，挡不住 manifest 条目）。
    """
    if not directory.is_dir():
        return []
    result = []
    for path in sorted(directory.rglob('*')):
        if not path.is_file():
            continue
        if path.name in ('.gitkeep', '.DS_Store') or path.suffix == '.pyc':
            continue
        if '__pycache__' in path.parts:
            continue
        if suffix is None or path.suffix == suffix:
            result.append(path)
    return result


def _build_models(core_dir: Path, dist_dir: Path, dsl: dict) -> dict | None:
    """平移 budget-models.json 并解析校验；缺失时降级返回 None（D §4）。"""
    src = core_dir / 'models' / 'budget-models.json'
    if not src.is_file():
        warn('core/models/budget-models.json 缺失：跳过 models 平移与 model 烘焙（降级规则 D §4）')
        return None
    _copy_file(src, dist_dir / dsl['routing']['models'])
    text = _read_text(src, 'core/models/budget-models.json')
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BuildError(f'core/models/budget-models.json 不是合法 JSON: {exc}') from exc
    if not isinstance(data, dict):
        raise BuildError('core/models/budget-models.json 顶层必须是对象')
    validate_models_data(data, 'core/models/budget-models.json')
    return data


def _build_agents(core_dir: Path, dist_dir: Path, dsl: dict, platform: str,
                  models_data: dict | None, roles: list[str] | None) -> None:
    """转换 agents：§3.1 校验 → frontmatter 重写 → 变量替换 → routing 落位。"""
    agents_dir = core_dir / 'agents'
    template = dsl['routing']['agent']
    body_variables = dsl['body_variables']
    agent_files = _iter_files(agents_dir, suffix='.md')
    for stray in _iter_files(agents_dir):
        if stray.suffix != '.md':
            raise BuildError(
                f'core/agents/ 仅允许 .md 文件（发现 {stray.relative_to(core_dir.parent)}）')
    names: list[str] = []
    for src in agent_files:
        name = src.stem
        # 报错/告警路径用仓库相对形态（core/agents/x.md，与 models 报错一致）。
        rel = src.relative_to(core_dir.parent).as_posix()
        if src.parent != agents_dir:
            raise BuildError(f'core/agents/ 不支持子目录（发现 {rel}）')
        fm, body = load_frontmatter(_read_text(src, rel), rel)
        validate_agent(fm, body, name, rel, roles)
        names.append(fm['name'])
        output = rewrite_agent(fm, body, dsl, platform, models_data, rel)
        output = replace_variables(output, body_variables, rel)
        _write_text(dist_dir / route_path(template, {'name': name}), output)
    if agent_files:
        # 集完备性校验（§3.1 校验①；目录为空时跳过，D §4 降级规则）。
        missing = sorted(set(AGENT_NAMES) - set(names))
        extra = sorted(set(names) - set(AGENT_NAMES))
        if missing or extra:
            raise BuildError(
                f'core/agents/ 集合完备性校验失败（期望 §6 十角色清单）: '
                f'缺失 {missing} / 多余 {extra}')


def _build_commands(core_dir: Path, dist_dir: Path, dsl: dict) -> None:
    """转换 commands：§3.1 命令校验 → frontmatter 重写 → 变量替换 → routing 落位。"""
    commands_dir = core_dir / 'commands'
    if not commands_dir.is_dir():
        return
    template = dsl['routing']['command']
    body_variables = dsl['body_variables']
    for child in sorted(commands_dir.iterdir()):
        if child.name == '.gitkeep':
            continue  # 空 core 骨架占位文件（_iter_files 同样跳过）。
        if not child.is_dir():
            raise BuildError(f'core/commands/ 仅允许子目录（发现 {child.name}）')
        group = child.name
        if group not in ('budget', 'opsx'):
            raise BuildError(f'core/commands/ 仅允许 budget/opsx 子目录（发现 {group}）')
        for stray in _iter_files(child):
            if stray.suffix != '.md':
                raise BuildError(f'core/commands/{group}/ 仅允许 .md 文件（发现 {stray.name}）')
        for src in _iter_files(child, suffix='.md'):
            name = src.stem
            rel = src.relative_to(core_dir).as_posix()
            fm, body = load_frontmatter(_read_text(src, rel), rel)
            validate_command(fm, body, rel)
            output = rewrite_command(fm, body, dsl)
            output = replace_variables(output, body_variables, rel)
            _write_text(dist_dir / route_path(template, {'group': group, 'name': name}), output)


def _build_skills(core_dir: Path, dist_dir: Path, dsl: dict) -> None:
    """平移 skills：.md 做变量替换，其余字节平移；routing.skill 落位。"""
    skills_dir = core_dir / 'skills'
    if not skills_dir.is_dir():
        return
    template = dsl['routing']['skill']
    body_variables = dsl['body_variables']
    for child in sorted(skills_dir.iterdir()):
        if child.name == '.gitkeep':
            continue  # 空 core 骨架占位文件（_iter_files 同样跳过）。
        if not child.is_dir():
            raise BuildError(f'core/skills/ 仅允许子目录（发现 {child.name}）')
        skill = child.name
        dest_base = dist_dir / route_path(template, {'skill': skill})
        for src in _iter_files(child):
            rel = src.relative_to(child).as_posix()
            if src.suffix == '.md':
                text = _read_text(src, f'skills/{skill}/{rel}')
                text = replace_variables(text, body_variables, f'skills/{skill}/{rel}')
                _write_text(dest_base / rel, text)
            else:
                _copy_file(src, dest_base / rel)


def _has_agents_fragment(dsl: dict) -> bool:
    """判断 DSL 是否声明 agents_fragment 合并产物（opencode 形态）。"""
    return any(spec.get('kind') == 'agents_fragment' for spec in dsl.get('extra_outputs', []))


def _build_rules(core_dir: Path, dist_dir: Path, dsl: dict) -> None:
    """转换 rules：codebuddy 逐文件落位改名；opencode 由 extra_outputs 合并处理。"""
    if _has_agents_fragment(dsl):
        return  # rules 走 AGENTS.fragment 合并管线（extra_outputs）。
    rules_dir = core_dir / 'rules'
    template = dsl['routing']['rule']
    body_variables = dsl['body_variables']
    for stray in _iter_files(rules_dir):
        if stray.suffix != '.md':
            raise BuildError(f'core/rules/ 仅允许 .md 文件（发现 {stray.name}）')
    for src in _iter_files(rules_dir, suffix='.md'):
        stem = src.stem
        # {name} = 主名去 budget- 前缀（产物 rules/budget-<name>.mdc 与源主名一致）。
        name = stem[len('budget-'):] if stem.startswith('budget-') else stem
        rel = src.relative_to(core_dir).as_posix()
        text = replace_variables(_read_text(src, rel), body_variables, rel)
        _write_text(dist_dir / route_path(template, {'name': name}), text)


def _build_hooks(core_dir: Path, dist_dir: Path, dsl: dict) -> None:
    """平移 hooks：routing.hook 单文件落位；空串表示本平台不分发。"""
    hook_files = _iter_files(core_dir / 'hooks')
    if not hook_files:
        return
    hook_dest = dsl['routing'].get('hook', '')
    if not hook_dest:
        warn('core/hooks/ 存在文件但本平台 routing.hook 为空（不分发）')
        return
    if len(hook_files) != 1:
        raise BuildError(f'core/hooks/ 仅支持单个 hook 文件（发现 {len(hook_files)} 个）')
    _copy_file(hook_files[0], dist_dir / hook_dest)


def _build_personas(core_dir: Path, dist_dir: Path, dsl: dict) -> None:
    """平移 personas.json；缺失时降级跳过（D §4）。"""
    src = core_dir / 'personas' / 'personas.json'
    if not src.is_file():
        warn('core/personas/personas.json 缺失：跳过 personas 平移（降级规则 D §4）')
        return
    _copy_file(src, dist_dir / dsl['routing']['personas'])


def _build_lib(core_dir: Path, dist_dir: Path, dsl: dict) -> None:
    """字节平移 lib/ 全部文件。"""
    lib_dir = core_dir / 'lib'
    dest_base = dist_dir / dsl['routing']['lib']
    for src in _iter_files(lib_dir):
        _copy_file(src, dest_base / src.relative_to(lib_dir))


def _build_setup(core_dir: Path, dist_dir: Path, dsl: dict) -> None:
    """平移 setup.sh；缺失时告警跳过（T9a 前增量构建场景，与 models/personas 风格一致）。"""
    src = core_dir / 'setup.sh'
    if not src.is_file():
        warn('core/setup.sh 缺失：跳过 setup 平移（T9a 前增量构建场景）')
        return
    _copy_file(src, dist_dir / dsl['routing']['setup'])


def _build_docs(core_dir: Path, dist_dir: Path, dsl: dict, models_data: dict | None,
                platform: str) -> None:
    """处理 docs：routing.docs 显式映射（null 不分发；模板经渲染管线，不平移）。"""
    docs_dir = core_dir / 'docs'
    docs_map = dsl['routing']['docs']
    doc_files = _iter_files(docs_dir)
    for src in doc_files:
        if src.parent != docs_dir:
            raise BuildError(f'core/docs/ 不支持子目录（发现 {src.relative_to(core_dir)}）')
        if src.name not in docs_map:
            raise BuildError(
                f'core/docs/{src.name} 未在 routing.docs 中声明（显式映射，无文件名特判）')
    for filename in sorted(set(docs_map) - {src.name for src in doc_files}):
        warn(f'core/docs/{filename} 在 routing.docs 中声明但源文件缺失，跳过')
    for src in doc_files:
        dest_rel = docs_map[src.name]
        if dest_rel is None:
            continue  # null = 本平台不分发。
        if src.name.endswith('.template.md'):
            _render_doc_template(src, dest_rel, dist_dir, models_data, platform)
        else:
            _copy_file(src, dist_dir / dest_rel)


def _render_doc_template(src: Path, dest_rel: str, dist_dir: Path,
                         models_data: dict | None, platform: str) -> None:
    """模板类 docs 渲染挂接（A6）：数据缺失按 D §4 降级跳过（告警不失败）。"""
    if models_data is None:
        warn(f'{src.name} 渲染跳过：budget-models.json 缺失（降级规则 D §4）')
        return
    template_text = _read_text(src, f'core/docs/{src.name}')
    rendered = render_model_selection(template_text, models_data, platform, dest_rel)
    _write_text(dist_dir / dest_rel, rendered)


def _build_extra_outputs(core_dir: Path, dist_dir: Path, dsl: dict) -> None:
    """生成平台附加产物（opencode AGENTS.fragment.md 合并声明）。"""
    body_variables = dsl['body_variables']
    for i, spec in enumerate(dsl.get('extra_outputs', [])):
        kind = spec['kind']
        if kind != 'agents_fragment':
            raise BuildError(f'extra_outputs[{i}]: 不支持的 kind {kind}')
        source = spec['source']
        category = source.split('/', 1)[0] if '/' in source else source
        if source != f'{category}/**':
            raise BuildError(f'extra_outputs[{i}]: source 仅支持 "<目录>/**" 形态（当前 {source}）')
        markers = spec.get('markers')
        if not isinstance(markers, list) or len(markers) != 2:
            raise BuildError(f'extra_outputs[{i}]: markers 必须是 [begin, end] 两个标记')
        rule_files = _iter_files(core_dir / category, suffix='.md')
        fragment = merge_rules_fragment(rule_files, markers)
        fragment = replace_variables(fragment, body_variables, spec['dest'])
        _write_text(dist_dir / spec['dest'], fragment)


def merge_rules_fragment(rule_files: list[Path], markers: list[str]) -> str:
    """合并 rules 为单文件（§3.5）：外层标记包裹 + 每条规则二级标记区块。"""
    begin, end = markers
    parts: list[str] = [begin, '']
    for rule_file in rule_files:
        rule_name = rule_file.stem
        content = _read_text(rule_file, str(rule_file))
        parts.append(f'<!-- {rule_name}:begin -->')
        parts.append(content.rstrip('\n'))
        parts.append(f'<!-- {rule_name}:end -->')
        parts.append('')
    parts.append(end)
    return '\n'.join(parts) + '\n'


def _sha256_file(path: Path) -> str:
    """计算文件 SHA256 十六进制摘要。"""
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
    except OSError as exc:
        raise BuildError(f'读取 {path} 失败: {exc}') from exc
    return digest.hexdigest()


def gen_manifest(dist_dir: Path) -> dict:
    """生成 .manifest.json 数据（§12-A7：按键排序、无时间戳、不含自身）。"""
    files: dict[str, str] = {}
    for path in sorted(dist_dir.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(dist_dir).as_posix()
        if rel == '.manifest.json':
            continue
        files[rel] = _sha256_file(path)
    return {'files': files}


def _atomic_replace(new_dir: Path, final_dir: Path, old_dir: Path) -> None:
    """原子替换：旧目录先改名 .old，.new 改名顶替，成功后删除 .old。"""
    if final_dir.exists():
        final_dir.rename(old_dir)
    try:
        new_dir.rename(final_dir)
    except OSError:
        if old_dir.exists() and not final_dir.exists():
            old_dir.rename(final_dir)  # 尽力恢复旧产物。
        raise
    if old_dir.exists():
        shutil.rmtree(old_dir)


def _extract_roles(models_data: dict) -> list[str] | None:
    """从 budget-models.json 提取 roles 键列表（§7）；缺失返回 None。"""
    roles = models_data.get('roles')
    if isinstance(roles, list):
        return roles
    return None


def _build_all(core_dir: Path, dist_dir: Path, dsl: dict, platform: str) -> None:
    """逐类别转换（design.md §4 构建流程）。"""
    models_data = _build_models(core_dir, dist_dir, dsl)
    roles = _extract_roles(models_data) if models_data is not None else None
    _build_agents(core_dir, dist_dir, dsl, platform, models_data, roles)
    _build_commands(core_dir, dist_dir, dsl)
    _build_skills(core_dir, dist_dir, dsl)
    _build_rules(core_dir, dist_dir, dsl)
    _build_hooks(core_dir, dist_dir, dsl)
    _build_personas(core_dir, dist_dir, dsl)
    _build_lib(core_dir, dist_dir, dsl)
    _build_setup(core_dir, dist_dir, dsl)
    _build_docs(core_dir, dist_dir, dsl, models_data, platform)
    _build_extra_outputs(core_dir, dist_dir, dsl)


def build_platform(root: Path, platform: str, strict: bool = False) -> None:
    """构建单平台产物（原子流程，design.md §4）。"""
    core_dir = root / 'core'
    dsl_path = core_dir / 'platform' / f'{platform}.yaml'
    if not dsl_path.is_file():
        raise BuildError(f'缺少平台 DSL 文件: {dsl_path}')
    dsl_rel = f'core/platform/{platform}.yaml'
    try:
        dsl = parse_yaml(_read_text(dsl_path, dsl_rel))
    except YamlParseError as exc:
        raise BuildError(f'{dsl_rel}: YAML 解析失败（{exc}）') from exc
    dsl = validate_dsl(dsl, dsl_rel)
    if dsl['platform'] != platform:
        raise BuildError(f'{dsl_rel}: platform 字段（{dsl["platform"]}）与文件名不一致')
    output = dsl['output']
    final_dir = root / output
    new_dir = root / f'{output}.new'
    old_dir = root / f'{output}.old'
    for stale in (new_dir, old_dir):
        if stale.exists():
            shutil.rmtree(stale)  # 清理上次失败/中断遗留的临时目录。
    new_dir.mkdir(parents=True)
    try:
        _build_all(core_dir, new_dir, dsl, platform)
        manifest = gen_manifest(new_dir)
        manifest_text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
        _write_text(new_dir / '.manifest.json', manifest_text)
        # P0 一致性（§3.4）：数据未就位时跳过；
        # --strict 升级为失败（替换前判定，保原子性）。
        p0_warnings = check_p0_consistency(core_dir)
        for message in p0_warnings:
            warn(message)
        if strict and p0_warnings:
            raise BuildError('--strict: P0 一致性告警升级为失败（见上方告警）')
        _atomic_replace(new_dir, final_dir, old_dir)
        print(f'[build] {platform}: 构建完成 → {final_dir}（{len(manifest["files"])} 个文件入清单）')
    except BaseException:
        shutil.rmtree(new_dir, ignore_errors=True)  # 失败清理临时目录，旧产物保持原样。
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def discover_platforms(root: Path) -> list[str]:
    """构建期枚举平台清单：glob core/platform/*.yaml（按名称排序，确定性）。"""
    platform_dir = root / 'core' / 'platform'
    if not platform_dir.is_dir():
        raise BuildError(f'缺少平台 DSL 目录: {platform_dir}')
    platforms = sorted(path.stem for path in platform_dir.glob('*.yaml'))
    if not platforms:
        raise BuildError(f'{platform_dir} 下无平台 DSL 文件（core/platform/*.yaml）')
    return platforms


def _check_platform_lists_consistency(root: Path, yaml_platforms: list[str]) -> None:
    """双清单一致性校验（D1）：core/platform/*.yaml 集合 == models.json platforms 键集。

    models 缺失（降级路径 D §4）或 platforms 键集为空（数据未就位）时跳过；
    双向不一致显式报错并列出两侧差异，不静默跳过任一平台（消除 glob 与
    数据两真值源漂移）。
    """
    models_path = root / 'core' / 'models' / 'budget-models.json'
    if not models_path.is_file():
        return
    try:
        data = json.loads(models_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError(f'core/models/budget-models.json 读取或解析失败: {exc}') from exc
    if not isinstance(data, dict):
        raise BuildError('core/models/budget-models.json 顶层必须是对象')
    platforms = data.get('platforms')
    if not isinstance(platforms, dict) or not platforms:
        return  # platforms 键集为空：数据未就位，只校验已有键（跳过一致性）。
    only_yaml = sorted(set(yaml_platforms) - platforms.keys())
    only_data = sorted(platforms.keys() - set(yaml_platforms))
    if only_yaml or only_data:
        raise BuildError(
            f'平台双清单不一致: core/platform/*.yaml 独有 {only_yaml}，'
            f'budget-models.json platforms 键集独有 {only_data}（两侧必须一致）')


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析命令行参数。

    --platform 合法域不在 argparse choices 固化（choices 依赖 --root 指向的
    仓库，构建启动时由 main 依 core/platform/*.yaml 枚举结果动态校验）。
    """
    parser = argparse.ArgumentParser(description='BudgetBuddy 构建系统：core/ → dist/ 平台产物转换')
    parser.add_argument(
        '--platform', default=None, metavar='<platform>',
        help='仅构建指定平台（可用平台由 core/platform/*.yaml 枚举，默认构建全部平台）')
    parser.add_argument('--check', action='store_true', help='构建成功后运行品牌门禁 scan-brand.py')
    parser.add_argument('--strict', action='store_true', help='将 P0 一致性告警升级为失败（CI 用）')
    parser.add_argument('--root', default=None, help='仓库根目录（默认：本脚本上两级）')
    return parser.parse_args(argv)


def resolve_root(root_arg: str | None) -> Path:
    """确定仓库根目录：显式参数优先，缺省为脚本上两级。"""
    if root_arg:
        return Path(root_arg).resolve()
    return Path(__file__).resolve().parent.parent


def run_brand_scan(root: Path) -> int:
    """运行品牌门禁（--check），返回门禁退出码。"""
    script = Path(__file__).resolve().parent / 'scan-brand.py'
    if not script.is_file():
        raise BuildError(f'--check 需要门禁脚本 {script}（T1b 产出）')
    proc = subprocess.run([sys.executable, str(script), '--root', str(root)], check=False)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    """执行构建，返回进程退出码（0=成功）。"""
    args = parse_args(argv)
    root = resolve_root(args.root)
    available = discover_platforms(root)
    if args.platform is not None and args.platform not in available:
        raise BuildError(
            f'未知平台 {args.platform}（可用平台: {available}，'
            '平台清单由 core/platform/*.yaml 枚举）')
    _check_platform_lists_consistency(root, available)
    platforms = [args.platform] if args.platform else available
    for platform in platforms:
        build_platform(root, platform, strict=args.strict)
    if args.check:
        if run_brand_scan(root) != 0:
            print('[build] 品牌门禁未通过（--check）', file=sys.stderr)
            return 1
    return 0


def run(argv: list[str] | None = None) -> int:
    """入口包装：兜底异常，返回进程退出码。"""
    try:
        return main(argv)
    except BuildError as exc:
        print(f'[build] 构建失败: {exc}', file=sys.stderr)
        return 1
    except Exception as exc:  # pylint: disable=broad-except
        print(f'[build] 内部错误: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(run())
