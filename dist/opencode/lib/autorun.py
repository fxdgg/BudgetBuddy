#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy AutoRun 管理 — budget setup autorun（agent-autorun design.md D4/D5/D7）。

子代理免审批（CodeBuddy frontmatter enabledAutoRun）的用户选择机制：用户选择
持久化于全局状态文件，经行级补丁作用于当前探测到的安装态 agent 文件，安装期
经 apply 全量重放（design.md D4/D5）。

子命令：
    list    双栏查看全局状态清单 + 当前安装态实况（只读，任何平台可用）
    on      开启指定 agent 的 AutoRun（免人工审批，输出安全知情提示）
    off     关闭指定 agent 的 AutoRun（删除 enabledAutoRun 行，恢复逐条确认）
    apply   全量对齐（清单内 on、清单外 off；内部命令：安装重放与状态修复）

状态文件：~/.budgetbuddy/auto-run.json，{"agents": [...]}（排序确定、indent 2、
sort_keys，全局单点，不设项目级覆盖；全局固定路径先例 notify.json）。种子化
口径：状态文件缺失时 on/off 先扫描已安装 agent，仅「enabledAutoRun 行存在且
值解析为 true」进基线（false 行视为用户显式关闭，不翻转）；状态文件存在后为
唯一真源（此后 IDE 手动变更不再被吸收，差异经 list 双栏暴露）。

作用域：on/off 补丁落当前探测到的安装态（BUDGET_PLATFORM_KIND/BUDGET_AGENTS_DIR
等，setup.sh 分发层 detect_platform 探测后 export 注入；未注入时本模块兜底九级
探测，对齐 quickstart.py）。多项目级安装需逐项目各执行一次 on/off。

平台降级（D2）：opencode/claudecode/codex 三形态无 per-subagent 免审批开关，
on/off/apply 输出替代审批机制指引后 exit 0 零修改（状态文件也不写）；list 只读
可用。codex 素材 frontmatter 规格仅 name/description（specs/codex-platform），
enabledAutoRun 不被读取，补丁即污染素材文档。

环境变量：
    BUDGET_PLATFORM_KIND / BUDGET_PLATFORM_SCOPE / BUDGET_PLATFORM_ROOT /
    BUDGET_AGENTS_DIR（setup.sh 注入）/ BUDGET_PLATFORM（显式平台，兜底探测时生效）

退出码：0 成功（含非 codebuddy 平台降级指引与 list 只读展示）；1 错误
（unknown 形态 / 状态文件损坏 / 目录缺失 / 补丁失败）；2 未知 agent 名。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from typing import Callable

# ─── 常量 ─────────────────────────────────────────────────────────────────────

# 状态文件（全局单点，D4）
STATE_FILE_RELPATH = ('.budgetbuddy', 'auto-run.json')

# 免审批 bash 模式数据文件（build 期生成、随 CodeBuddy dist 分发，D7）
BASH_PATTERNS_FILE = '.bash-patterns.json'

# frontmatter 顶层 enabledAutoRun 行（列首无缩进）
AUTORUN_LINE_RE = re.compile(r'^enabledAutoRun[ \t]*:')

# 插入锚点键（name/description/mode：复刻 model_resolver.rewrite_agent_file，
# 插入位置取锚点键最后出现行之后，与构建产物字段顺序一致）
ANCHOR_LINE_RE = re.compile(r'^(name|description|mode)[ \t]*:')

# 套件 agent 名清单（兜底九级探测判定目录是否含本套件 agent，对齐 quickstart.py）
SUITE_AGENTS = (
    'architect', 'coder-lite', 'coder-standard', 'coder-senior', 'reviewer',
    'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
)

# 非 codebuddy 平台替代审批机制指引（D2 降级：on/off/apply 输出后 exit 0 零修改）
PLATFORM_GUIDANCE = {
    'opencode': [
        'OpenCode 替代审批机制：',
        '  - permission map：edit/bash 的 allow 值即免审批（4 个执行类 agent 既有映射已等价）',
        '  - 审批弹窗中选择 always（会话级记住）',
        '  - --auto 全局模式',
    ],
    'claudecode': [
        'Claude Code 替代审批机制：',
        '  - settings.json 的 permissions.allow 规则（按命令模式放行）',
        '  - 会话权限模式（acceptEdits / bypassPermissions 等）',
    ],
    'codex': [
        'Codex 替代审批机制：',
        '  - Codex 素材 frontmatter 仅 name/description，无 enabledAutoRun 开关'
        '（写入即污染素材文档），本命令未做任何修改',
        '  - spawn 派工权限边界：由 Leader 在派工 prompt 中显式声明',
        '  - 会话内审批由 Codex 自身审批机制承担',
    ],
}

# ─── 平台探测（环境变量注入优先，兜底九级探测对齐 quickstart.py）──────────────


def _has_suite_agents(directory: str) -> bool:
    """判断目录是否含本套件 agent 文件（任一命中即算）。"""
    if not os.path.isdir(directory):
        return False
    return any(
        os.path.isfile(os.path.join(directory, name + '.md'))
        for name in SUITE_AGENTS
    )


def _has_codex_skill(directory: str) -> bool:
    """判断目录是否为 codex 套件 skill 目录（对齐 quickstart.py / platform.sh：
    目录名 budget-workflow + SKILL.md 存在双条件，防同名目录误判）。"""
    if not os.path.isdir(directory):
        return False
    if os.path.basename(os.path.realpath(directory)) != 'budget-workflow':
        return False
    return os.path.isfile(os.path.join(directory, 'SKILL.md'))


def _walk_up(predicate: Callable[[str], bool], max_levels: int = 10) -> str | None:
    """从 cwd 向上最多 max_levels 层查找满足 predicate 的目录；未命中返回 None。"""
    directory = os.path.realpath(os.getcwd())
    for _ in range(max_levels):
        if predicate(directory):
            return directory
        if directory == os.path.sep:
            break
        directory = os.path.dirname(directory)
    return None


def _fallback_detect_platform() -> dict:
    """兜底九级探测（BUDGET_PLATFORM 显式 > codebuddy 项目 > codebuddy 全局 >
    claudecode 项目 > claudecode 全局 > codex 项目 > codex 全局 > opencode 项目 >
    opencode 全局 > unknown）。

    与 quickstart.py _detect_platform 同构；仅在 setup.sh 未注入形态变量时生效
    （直调 / 冒烟 / 测试场景）。返回 {kind, scope, root, agents_dir}。
    """
    home = os.path.expanduser('~')
    result = {'kind': 'unknown', 'scope': '', 'root': '', 'agents_dir': ''}
    explicit = os.environ.get('BUDGET_PLATFORM', '')
    if explicit in ('codebuddy', 'claudecode', 'codex', 'opencode'):
        agents_dir = {
            'codebuddy': os.path.join(home, '.codebuddy', 'agents'),
            'claudecode': os.path.join(home, '.claude', 'agents'),
            'codex': os.path.join(home, '.codex', 'skills',
                                  'budget-workflow', 'agents'),
            'opencode': os.path.join(home, '.config', 'opencode', 'agent'),
        }[explicit]
        result.update(kind=explicit, scope='global', agents_dir=agents_dir)
        return result

    root = _walk_up(lambda d: os.path.isfile(os.path.join(d, '.codebuddy', 'setup.sh')))
    if root:
        result.update(kind='codebuddy', scope='project', root=root,
                      agents_dir=os.path.join(root, '.codebuddy', 'agents'))
        return result
    if os.path.isfile(os.path.join(home, '.codebuddy', 'setup.sh')):
        result.update(kind='codebuddy', scope='global',
                      agents_dir=os.path.join(home, '.codebuddy', 'agents'))
        return result
    root = _walk_up(lambda d: _has_suite_agents(os.path.join(d, '.claude', 'agents')))
    if root:
        result.update(kind='claudecode', scope='project', root=root,
                      agents_dir=os.path.join(root, '.claude', 'agents'))
        return result
    if _has_suite_agents(os.path.join(home, '.claude', 'agents')):
        result.update(kind='claudecode', scope='global',
                      agents_dir=os.path.join(home, '.claude', 'agents'))
        return result
    root = _walk_up(lambda d: _has_codex_skill(
        os.path.join(d, '.codex', 'skills', 'budget-workflow')))
    if root:
        result.update(kind='codex', scope='project', root=root,
                      agents_dir=os.path.join(root, '.codex', 'skills',
                                              'budget-workflow', 'agents'))
        return result
    if _has_codex_skill(os.path.join(home, '.codex', 'skills', 'budget-workflow')):
        result.update(kind='codex', scope='global',
                      agents_dir=os.path.join(home, '.codex', 'skills',
                                              'budget-workflow', 'agents'))
        return result
    root = _walk_up(lambda d: _has_suite_agents(os.path.join(d, '.opencode', 'agent')))
    if root:
        result.update(kind='opencode', scope='project', root=root,
                      agents_dir=os.path.join(root, '.opencode', 'agent'))
        return result
    if _has_suite_agents(os.path.join(home, '.config', 'opencode', 'agent')):
        result.update(kind='opencode', scope='global',
                      agents_dir=os.path.join(home, '.config', 'opencode', 'agent'))
        return result
    return result


def resolve_platform() -> dict:
    """形态解析：BUDGET_PLATFORM_KIND 等环境变量（setup.sh 分发前 export）优先；
    未注入时兜底九级探测。kind=unknown 表示九级探测均未命中。"""
    kind = os.environ.get('BUDGET_PLATFORM_KIND', '')
    if kind:
        return {
            'kind': kind,
            'scope': os.environ.get('BUDGET_PLATFORM_SCOPE', ''),
            'root': os.environ.get('BUDGET_PLATFORM_ROOT', ''),
            'agents_dir': os.environ.get('BUDGET_AGENTS_DIR', ''),
        }
    return _fallback_detect_platform()

# ─── 状态文件读写（损坏绝不覆盖写，D4）────────────────────────────────────────


def state_file_path() -> str:
    """全局状态文件路径 ~/.budgetbuddy/auto-run.json。"""
    return os.path.join(os.path.expanduser('~'), *STATE_FILE_RELPATH)


def load_state_file() -> dict:
    """读取状态文件 → {'status': 'ok'|'missing'|'corrupt', 'agents': [...], 'error': str}。

    missing：文件不存在（on/off 将种子化基线；apply 视为无需重放）。
    corrupt：JSON 解析失败或结构非法（on/off/apply 必须非零退出且不覆盖写；
        list 只读展示损坏与修复路径）。
    """
    path = state_file_path()
    if not os.path.isfile(path):
        return {'status': 'missing', 'agents': [], 'error': ''}
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        return {'status': 'corrupt', 'agents': [], 'error': str(exc)}
    if not isinstance(data, dict) or not isinstance(data.get('agents'), list):
        return {'status': 'corrupt', 'agents': [], 'error': '结构非法（应为 {"agents": [...]}）'}
    agents = sorted({str(name) for name in data['agents'] if isinstance(name, str)})
    return {'status': 'ok', 'agents': agents, 'error': ''}


def _atomic_write(path: str, content: str) -> None:
    """同目录临时文件原子写（mkstemp + os.replace），保留原文件权限位。"""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(prefix='.autorun-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if os.path.exists(path):
            os.chmod(tmp_path, os.stat(path).st_mode & 0o777)
        else:
            os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except OSError:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def write_state_file(agents: list) -> None:
    """写状态文件（agents 排序去重、indent 2、sort_keys、末尾换行，原子写）。"""
    path = state_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = json.dumps({'agents': sorted(set(agents))}, indent=2, sort_keys=True) + '\n'
    _atomic_write(path, content)

# ─── agent 文件读取与行级补丁（算法复刻 model_resolver.rewrite_agent_file）─────


def installed_agent_names(agents_dir: str) -> list:
    """已安装 agent 名清单（agents 目录 .md 主名；.bash-patterns.json 等非 .md 天然忽略）。"""
    if not os.path.isdir(agents_dir):
        return []
    return sorted(name[:-3] for name in os.listdir(agents_dir) if name.endswith('.md'))


def _line_ending(line: str) -> str:
    """提取行尾换行符（CRLF/LF/无）。"""
    if line.endswith('\r\n'):
        return '\r\n'
    if line.endswith('\n'):
        return '\n'
    return ''


def read_autorun_value(path: str) -> str | None:
    """读取 frontmatter enabledAutoRun 值（归一化 'true'/'false'）。

    行缺失、无 frontmatter 或读取失败时返回 None（调用方按「未设置」处理）。

    读取用 newline='' 关停 universal newlines 翻译，保证 CRLF 文件逐字节保留
    （补丁写侧同样 newline=''，与 model_resolver 写侧一致）。
    """
    try:
        with open(path, encoding='utf-8', newline='') as handle:
            content = handle.read()
    except (OSError, UnicodeDecodeError):
        return None
    lines = content.splitlines()
    if not lines or lines[0].strip() != '---':
        return None
    for line in lines[1:]:
        if line.strip() == '---':
            break
        if AUTORUN_LINE_RE.match(line):
            value = line.split(':', 1)[1].strip().strip('\'"').lower()
            return 'true' if value == 'true' else 'false'
    return None


def patch_agent_file(path: str, enable: bool) -> tuple[bool, str]:
    """enabledAutoRun 行级补丁（D4：复刻 rewrite_agent_file 算法）。

    enable=True：有行则改值 true、无行则在锚点行（name/description/mode 最后
        出现行之后）插入；enable=False：删除该行（无行则 unchanged）。
    保留原行尾（CRLF/LF）、临时文件原子写、仅触碰该一行，frontmatter 其余字段
    与正文逐字节保留；重复执行字节级稳定（幂等）。

    返回 (ok, detail)：ok=False 时文件未被修改，detail 为原因；
    detail ∈ inserted/replaced/removed/unchanged。

    读取用 newline='' 关停 universal newlines 翻译（与写侧一致），否则 CRLF
    文件会被静默转为 LF，违背「保留原行尾」规格。
    """
    try:
        with open(path, encoding='utf-8', newline='') as handle:
            content = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        return False, f'读取失败: {exc}'

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        return False, '无 frontmatter（首行非 ---）'
    close_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == '---':
            close_idx = idx
            break
    if close_idx is None:
        return False, 'frontmatter 未闭合（缺少结束 ---）'

    field_idx = None
    for idx in range(1, close_idx):
        if AUTORUN_LINE_RE.match(lines[idx]):
            field_idx = idx
            break

    if enable:
        if field_idx is not None:
            lines[field_idx] = f'enabledAutoRun: true{_line_ending(lines[field_idx])}'
            detail = 'replaced'
        else:
            anchor_idx = 1
            for idx in range(1, close_idx):
                if ANCHOR_LINE_RE.match(lines[idx]):
                    anchor_idx = idx + 1
            ending = _line_ending(lines[anchor_idx - 1]) or '\n'
            lines.insert(anchor_idx, f'enabledAutoRun: true{ending}')
            detail = 'inserted'
    else:
        if field_idx is None:
            return True, 'unchanged'
        del lines[field_idx]
        detail = 'removed'

    try:
        _atomic_write(path, ''.join(lines))
    except OSError as exc:
        return False, f'写入失败: {exc}'
    return True, detail


def seed_from_installed(agents_dir: str) -> list:
    """种子化基线：仅「enabledAutoRun 行存在且值解析为 true」的 agent 进基线。

    false 行视为用户显式关闭，不进基线（防 install 重放把手动关闭翻转为开启，
    D4 种子化口径 / spec「种子化不翻转手动关闭」）。
    """
    return [
        name for name in installed_agent_names(agents_dir)
        if read_autorun_value(os.path.join(agents_dir, name + '.md')) == 'true'
    ]

# ─── on 安全知情提示（bash 模式数据来源：D7）─────────────────────────────────


def load_bash_patterns(agents_dir: str) -> dict | None:
    """读取 agents/.bash-patterns.json；缺失/损坏/结构异常返回 None（降级）。"""
    path = os.path.join(agents_dir, BASH_PATTERNS_FILE)
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def agent_bash_allow(patterns: dict | None, agent: str) -> list | None:
    """目标 agent 的 bash_allow 清单；patterns 缺失或无该 agent 条目返回 None。"""
    if patterns is None:
        return None
    agents = patterns.get('agents')
    if not isinstance(agents, dict):
        return None
    entry = agents.get(agent)
    if not isinstance(entry, dict) or not isinstance(entry.get('bash_allow'), list):
        return None
    return [str(pattern) for pattern in entry['bash_allow']]


def _pattern_risk_note(pattern: str) -> str:
    """bash 模式风险标注（`*` 与 git 类醒目提示，spec「on 输出安全知情提示」）。"""
    if pattern == '*':
        return '   ← 任意 shell 命令免审批（含 rm -rf / git push -f 等高危操作），请谨慎开启'
    if 'git' in pattern:
        return '   ← git 类命令免审批（push --force / clean -fd / checkout -- . 等高危），请谨慎开启'
    return ''


def print_on_security_notice(agent: str, agents_dir: str) -> None:
    """on 安全知情提示：免审批语义 + 目标 agent 将免审批的 bash 模式（D7）。

    数据文件缺失（旧安装）时降级为通用知情提示（不列具体模式）且不阻断开启；
    bash_allow 为 [] 时明示无 bash 权限。
    """
    print(f'[安全知情] AutoRun 开启后，{agent} 权限范围内的所有工具调用将免人工审批'
          '（审批是最后一道人工闸门，请确认信任该 agent 将执行的任务内容）。')
    allow = agent_bash_allow(load_bash_patterns(agents_dir), agent)
    if allow is None:
        print(f'  未找到 {BASH_PATTERNS_FILE} 或其中无 {agent} 条目'
              '（旧安装未重建 dist），暂无法列出具体 bash 模式；升级安装后可获得模式清单。开启照常完成。')
        return
    if not allow:
        print('  该 agent 未配置任何 bash 权限（bash_allow 为空），AutoRun 不影响 bash 调用。')
        return
    print('  将免审批的 bash 模式：')
    for pattern in allow:
        print(f'    {pattern}{_pattern_risk_note(pattern)}')


def print_scope_note(platform: dict) -> None:
    """on/off 作用域明示：补丁落当前探测安装态；多项目级安装需逐项目执行（D4）。"""
    print(f'[i] 补丁作用域：当前探测到的安装态 {platform["kind"]}:{platform["scope"]}'
          f'（root: {platform["root"] or "-"}，agents 目录: {platform["agents_dir"]}）')
    if platform['scope'] == 'project':
        print('[i] 多项目级安装时，全局状态文件记录选择、补丁只落当前项目——'
              '其他项目需各自执行一次 on/off。')

# ─── 子命令：list（只读，任何平台可用）───────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> int:
    """双栏输出：全局状态清单 + 当前安装态实况逐 agent 比对（D4）。

    只读：任何情况（含状态文件损坏）退出码 0，不改写任何文件。
    """
    state = load_state_file()
    print(f'═══ 全局状态清单（{state_file_path()}）═══')
    if state['status'] == 'ok':
        if state['agents']:
            for name in state['agents']:
                print(f'  {name}')
        else:
            print('  （空——尚未开启任何 agent）')
    elif state['status'] == 'missing':
        print('  未初始化（状态文件不存在）。')
        print('  运行 budget setup autorun on/off <agent> 将按当前安装态种子化基线'
              '（仅 enabledAutoRun: true 进基线）。')
    else:
        print(f'  损坏（JSON 解析失败: {state["error"]}）')
        print(f'  修复：编辑或删除 {state_file_path()}，或运行 budget setup autorun on/off 修复。')
        print('  （list 只读，不承担修复职责，状态文件字节不被改写）')

    print()
    print('═══ 当前安装态实况 ═══')
    platform = resolve_platform()
    kind = platform['kind']
    if kind == 'unknown':
        print('  未检测到安装形态（九级探测未命中）。on/off/apply 需先安装 BudgetBuddy'
              ' 或以 BUDGET_PLATFORM=codebuddy|claudecode|codex|opencode 显式指定；'
              'list 只读可用。')
        return 0
    if kind in PLATFORM_GUIDANCE:
        print(f'  平台 {kind}:{platform["scope"]} 无 AutoRun 机制'
              '（替代审批机制见 budget setup autorun on 在该平台的输出指引）。')
        return 0
    agents_dir = platform['agents_dir']
    print(f'  平台: {kind}:{platform["scope"]}'
          f'（root: {platform["root"] or "-"}，agents 目录: {agents_dir or "-"}）')
    if not agents_dir or not os.path.isdir(agents_dir):
        print(f'  agent 目录不存在: {agents_dir or "（空，未探测到）"}')
        return 0

    actual = []
    for name in installed_agent_names(agents_dir):
        value = read_autorun_value(os.path.join(agents_dir, name + '.md'))
        if value == 'true':
            actual.append(name)
        if value == 'true':
            mark = 'enabledAutoRun: true（免审批）'
        elif value == 'false':
            mark = 'enabledAutoRun: false（显式关闭）'
        else:
            mark = '未设置（逐条确认）'
        print(f'  {name:<16} {mark}')

    if state['status'] != 'ok':
        print('  （状态栏异常，差异比对略；修复状态文件后可比对）')
        return 0
    state_set = set(state['agents'])
    only_state = sorted(state_set - set(actual))
    only_actual = sorted(set(actual) - state_set)
    if not only_state and not only_actual:
        print('  状态清单与安装态一致。')
        return 0
    if only_state:
        print(f'  差异: 状态清单含 {", ".join(only_state)}，但安装态未开启'
              '（可运行 autorun on 归位，或等待下次 install 重放）')
    if only_actual:
        print(f'  差异: 安装态已开启 {", ".join(only_actual)}，但不在状态清单'
              '（可能为 IDE 手动变更；状态文件存在后为唯一真源，install 重放将按清单覆盖）')
    return 0

# ─── 子命令：on / off ────────────────────────────────────────────────────────


def cmd_on_off(args: argparse.Namespace, enable: bool) -> int:
    """on/off：校验 → 读/种子化状态 → 安全提示（on）→ 行级补丁 → 原子写状态。"""
    platform = resolve_platform()
    kind = platform['kind']

    if kind == 'unknown':
        print('error: 未检测到 BudgetBuddy 安装形态（九级探测未命中），无法定位 agent 目录',
              file=sys.stderr)
        print('提示：请先完成安装（budget setup init 或 install.sh），'
              '或设置 BUDGET_PLATFORM=codebuddy|claudecode|codex|opencode 显式指定平台后重试',
              file=sys.stderr)
        return 1
    if kind in PLATFORM_GUIDANCE:
        print(f'[i] 当前平台 {kind}:{platform["scope"]} 无 AutoRun 机制'
              '（子代理无 per-subagent 免审批开关），未做任何修改。')
        for line in PLATFORM_GUIDANCE[kind]:
            print(line)
        return 0

    agents_dir = platform['agents_dir']
    if not agents_dir or not os.path.isdir(agents_dir):
        print(f'error: agent 目录不存在: {agents_dir or "（空，未探测到）"}', file=sys.stderr)
        return 1
    installed = installed_agent_names(agents_dir)

    unknown_names = [name for name in args.agents if name not in installed]
    if unknown_names:
        print(f'error: 未知 agent 名: {", ".join(unknown_names)}', file=sys.stderr)
        print(f'可用 agent 名（{agents_dir} 下 .md 主名）: {", ".join(installed) or "（无）"}',
              file=sys.stderr)
        return 2

    state = load_state_file()
    if state['status'] == 'corrupt':
        print(f'error: 状态文件损坏（JSON 解析失败），已中止: {state_file_path()}', file=sys.stderr)
        print(f'  {state["error"]}', file=sys.stderr)
        print('提示：编辑或删除该文件后重试（budget setup autorun list 可只读查看）；'
              '绝不覆盖写，以防用户基线永久丢失。', file=sys.stderr)
        return 1

    agents = state['agents']
    if state['status'] == 'missing':
        agents = seed_from_installed(agents_dir)
        print('[i] 状态文件缺失，已按安装态种子化基线（仅 enabledAutoRun: true 进基线）: '
              f'{", ".join(agents) or "（无）"}')

    print_scope_note(platform)

    if enable:
        for agent in args.agents:
            print()
            print_on_security_notice(agent, agents_dir)

    failed = []
    for agent in args.agents:
        ok, detail = patch_agent_file(os.path.join(agents_dir, agent + '.md'), enable)
        if not ok:
            failed.append(f'{agent}: {detail}')
        elif enable:
            print(f'[✓] {agent} 已开启 AutoRun（{agents_dir}/{agent}.md: {detail}）')
        else:
            print(f'[✓] {agent} 已关闭 AutoRun（{agents_dir}/{agent}.md: {detail}），'
                  '恢复逐条确认（IDE 弹窗「允许一次」仍可用）')

    if failed:
        print('error: 以下 agent 补丁失败，状态文件未更新（避免状态与安装态不一致）:',
              file=sys.stderr)
        for item in failed:
            print(f'  {item}', file=sys.stderr)
        return 1

    new_agents = set(agents)
    if enable:
        new_agents |= set(args.agents)
    else:
        new_agents -= set(args.agents)
    try:
        write_state_file(sorted(new_agents))
    except OSError as exc:
        print(f'error: 状态文件写入失败: {exc}', file=sys.stderr)
        return 1
    print(f'[✓] 状态文件已更新: {state_file_path()}'
          f'（{len(new_agents)} 个 agent: {", ".join(sorted(new_agents)) or "（空）"}）')
    if not enable and not new_agents:
        print('[i] 清单已空：后续 install 重放将关闭全部 agent 的 AutoRun。')
    return 0

# ─── 子命令：apply（内部命令：安装重放与状态修复）─────────────────────────────


def cmd_apply(args: argparse.Namespace) -> int:
    """全量对齐：清单内 on、清单外 off（对已安装 agents 目录所有 .md，D4/D5）。

    无状态文件时无需重放（dist 默认值成立）；状态文件损坏时非零退出且绝不
    覆盖写（install 路径上仅告警不阻断，installer spec 既有场景）。
    """
    platform = resolve_platform()
    kind = platform['kind']

    if kind == 'unknown':
        print('error: 未检测到 BudgetBuddy 安装形态（九级探测未命中），无法重放 AutoRun 状态',
              file=sys.stderr)
        print('提示：请先完成安装，或设置 BUDGET_PLATFORM=codebuddy|claudecode|codex|opencode 显式指定',
              file=sys.stderr)
        return 1
    if kind in PLATFORM_GUIDANCE:
        print(f'[i] 当前平台 {kind} 无 AutoRun 机制，apply 无需重放，未做任何修改。')
        return 0

    agents_dir = platform['agents_dir']
    if not agents_dir or not os.path.isdir(agents_dir):
        print(f'error: agent 目录不存在: {agents_dir or "（空，未探测到）"}', file=sys.stderr)
        return 1

    state = load_state_file()
    if state['status'] == 'corrupt':
        print(f'error: 状态文件损坏，重放中止（绝不覆盖写）: {state_file_path()}', file=sys.stderr)
        print('提示：编辑或删除该文件后重试，或运行 budget setup autorun list 只读检查',
              file=sys.stderr)
        return 1
    if state['status'] == 'missing':
        print('[i] 无状态文件（~/.budgetbuddy/auto-run.json 不存在），无需重放'
              '（dist 默认值成立）')
        return 0

    enabled = set(state['agents'])
    installed = installed_agent_names(agents_dir)
    changed = 0
    failed = []
    for name in installed:
        ok, detail = patch_agent_file(os.path.join(agents_dir, name + '.md'), name in enabled)
        if not ok:
            failed.append(f'{name}: {detail}')
        elif detail != 'unchanged':
            changed += 1
    missing = sorted(enabled - set(installed))
    if missing:
        print(f'[!] 状态清单中的 agent 未安装（跳过）: {", ".join(missing)}', file=sys.stderr)
    if failed:
        print('error: 以下 agent 重放失败:', file=sys.stderr)
        for item in failed:
            print(f'  {item}', file=sys.stderr)
        return 1
    print(f'[✓] AutoRun 状态重放完成: {changed} 个 agent 文件变更'
          f'（清单内 {len(enabled)} 个开启，其余关闭）')
    return 0

# ─── main ────────────────────────────────────────────────────────────────────


def main(argv: list | None = None) -> int:
    """入口：解析子命令并分发（list 只读 / on / off / apply）。"""
    parser = argparse.ArgumentParser(
        description='BudgetBuddy AutoRun 管理（budget setup autorun）：'
                    '子代理免审批的用户选择机制')
    sub = parser.add_subparsers(dest='action', required=True)

    sub.add_parser('list', help='双栏查看全局状态清单与当前安装态实况（只读，任何平台可用）')

    p_on = sub.add_parser('on', help='开启指定 agent 的 AutoRun（免人工审批）')
    p_on.add_argument('agents', nargs='+', help='agent 名（已安装 agents 目录 .md 主名）')

    p_off = sub.add_parser('off', help='关闭指定 agent 的 AutoRun（恢复逐条确认）')
    p_off.add_argument('agents', nargs='+', help='agent 名（已安装 agents 目录 .md 主名）')

    sub.add_parser('apply', help='全量对齐安装态与状态清单（内部命令：安装重放/状态修复）')

    args = parser.parse_args(argv)
    if args.action == 'list':
        return cmd_list(args)
    if args.action == 'apply':
        return cmd_apply(args)
    return cmd_on_off(args, enable=args.action == 'on')


if __name__ == '__main__':
    sys.exit(main())
