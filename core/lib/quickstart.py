#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy 快速上手向导 — budget setup quickstart（别名 tour/wizard）。

交互式 8 步引导（design.md §8.1/§8.2；specs/setup-cli「quickstart 入口可用」）：
欢迎与简介 → 环境检查 → 初始化引导 → 角色主题选择 → 模型预设选择 →
通知配置引导 → 工作流演示 → 完成页。零第三方依赖（Python stdlib only）。

用法（经 setup.sh 分发，setup.sh 以 exec 直调本脚本、不传参数）:
    budget setup quickstart          # 别名: budget setup tour / budget setup wizard

直调（冒烟/CI）:
    python3 lib/quickstart.py --non-interactive

交互容错:
    - 非交互环境（无 tty / stdin EOF / --non-interactive）：全部步骤走默认值，
      不执行任何配置变更（仅输出指引与说明），保证冒烟/CI 安全
    - 每步可跳过：单步 EOF 取该步默认值继续；Ctrl-C 任意时刻优雅退出（exit 0）
    - --interactive：强制交互模式（stdin 非 tty 时仍读取 stdin，供测试注入）

命令面调用纪律（任务硬性约束）:
    向导中所有配置动作一律 subprocess bash 调 setup.sh 命令面
    （budget setup init / persona set / agent preset），不 source、不 import
    任何 lib 模块——与并行任务（T10c persona/interactive 等）零耦合，
    模块未就位时由 setup.sh 分发层报错、本向导容错降级为手动指引。

环境变量（setup.sh exec 时导出；直调时自行兜底探测）:
    BUDGET_SETUP_DIR  setup.sh 所在目录
    BUDGET_GLOBAL     "1" 全局模式
    BUDGET_PLATFORM   显式平台（codebuddy|claudecode|codex|opencode，跳过探测）
    BUDGET_DIR        运行时数据目录覆盖
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from typing import Callable

try:
    import readline  # noqa: F401  # input() 行编辑增强（部分平台不可用，可选）
except ImportError:
    pass

# ─── ANSI 颜色（非 tty / dumb 终端自动降级，语义对齐 lib/colors.sh）─────────


def _colors_enabled() -> bool:
    if not sys.stdout.isatty():
        return False
    return os.environ.get('TERM', '') != 'dumb'


if _colors_enabled():
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    CYAN = '\033[0;36m'
    BOLD = '\033[1m'
    NC = '\033[0m'
else:
    RED = ''
    GREEN = ''
    YELLOW = ''
    CYAN = ''
    BOLD = ''
    NC = ''

# ─── CJK 宽度感知的边框辅助 ────────────────────────────────────────────────

_RE_ANSI = re.compile(r'\x1b\[[0-9;]*m')
_BOX_WIDTH = 56


def _vis_width(text: str) -> int:
    """显示宽度（CJK 全角计 2，其余计 1），忽略 ANSI 转义序列。"""
    width = 0
    for char in _RE_ANSI.sub('', text):
        width += 2 if unicodedata.east_asian_width(char) in ('F', 'W') else 1
    return width


def _box_line(text: str, color: str = CYAN, width: int = _BOX_WIDTH, left: int = 0) -> str:
    """生成 ║...║ 内的填充行（CJK 宽度对齐）。"""
    pad = max(0, width - _vis_width(text) - left)
    return f'{color}║{NC}{" " * left}{text}{" " * pad}{color}║{NC}'


def _box_center(text: str, color: str = CYAN, width: int = _BOX_WIDTH) -> str:
    """居中边框行。"""
    left = max(0, (width - _vis_width(text)) // 2)
    return _box_line(text, color, width, left=left)


def _box_top(color: str = CYAN, width: int = _BOX_WIDTH) -> str:
    return f'{color}╔{"═" * width}╗{NC}'


def _box_bottom(color: str = CYAN, width: int = _BOX_WIDTH) -> str:
    return f'{color}╚{"═" * width}╝{NC}'


def _box_empty(color: str = CYAN, width: int = _BOX_WIDTH) -> str:
    return _box_line('', color, width)


# ─── 环境定位（setup.sh / 数据目录；探测链对齐 lib 各模块约定）──────────────

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
_HOME = os.path.expanduser('~')


def _locate_setup_script() -> str:
    """定位 setup.sh：① BUDGET_SETUP_DIR（setup.sh exec 时导出）② lib 同级
    （安装形态与 core 源形态共用）③ ~/.budgetbuddy/（opencode 管理面，A3）
    ④ ~/.codebuddy/（codebuddy 全局）。未找到返回空串（命令调用容错降级）。"""
    candidates = []
    setup_dir = os.environ.get('BUDGET_SETUP_DIR', '')
    if setup_dir:
        candidates.append(os.path.join(setup_dir, 'setup.sh'))
    candidates.append(os.path.join(os.path.dirname(_LIB_DIR), 'setup.sh'))
    candidates.append(os.path.join(_HOME, '.budgetbuddy', 'setup.sh'))
    candidates.append(os.path.join(_HOME, '.codebuddy', 'setup.sh'))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return ''


_SETUP_SCRIPT = _locate_setup_script()

# ─── 向导状态 ──────────────────────────────────────────────────────────────

_NON_INTERACTIVE = False  # main() 入口按参数与 tty 检测设置
_TOTAL_STEPS = 8

# ─── 平台探测（语义对齐 lib/platform.sh 七分支；纯只读文件系统检查）─────────

_SUITE_AGENTS = (
    'architect', 'coder-lite', 'coder-standard', 'coder-senior', 'reviewer',
    'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
)


def _has_suite_agents(directory: str) -> bool:
    """判断目录是否含本套件 agent 文件（任一命中即算，对齐 platform.sh）。"""
    if not os.path.isdir(directory):
        return False
    return any(
        os.path.isfile(os.path.join(directory, name + '.md'))
        for name in _SUITE_AGENTS
    )


def _has_codex_skill(directory: str) -> bool:
    """判断目录是否为 codex 套件 skill 目录（对齐 platform.sh 签名校验：
    目录名 budget-workflow + SKILL.md 存在双条件，防同名目录误判）。"""
    if not os.path.isdir(directory):
        return False
    if os.path.basename(os.path.realpath(directory)) != 'budget-workflow':
        return False
    return os.path.isfile(os.path.join(directory, 'SKILL.md'))


def _walk_up(predicate: Callable[[str], bool], max_levels: int = 10):
    """从 cwd 向上最多 max_levels 层查找满足 predicate 的目录；未命中返回 None。"""
    directory = os.path.realpath(os.getcwd())
    for _ in range(max_levels):
        if predicate(directory):
            return directory
        if directory == os.path.sep:
            break
        directory = os.path.dirname(directory)
    return None


def _detect_platform() -> dict:
    """运行时平台探测（对齐 platform.sh 七分支：BUDGET_PLATFORM 显式 >
    codebuddy 项目级 > codebuddy 全局 > claudecode 项目级 > claudecode
    全局 > codex 项目级 > codex 全局 > opencode 项目级 > opencode 全局 >
    unknown）。"""
    result = {'kind': 'unknown', 'scope': '', 'root': '', 'agents_dir': ''}
    explicit = os.environ.get('BUDGET_PLATFORM', '')
    if explicit == 'codebuddy':
        result.update(kind='codebuddy', scope='global',
                      agents_dir=os.path.join(_HOME, '.codebuddy', 'agents'))
        return result
    if explicit == 'claudecode':
        result.update(kind='claudecode', scope='global',
                      agents_dir=os.path.join(_HOME, '.claude', 'agents'))
        return result
    if explicit == 'codex':
        result.update(kind='codex', scope='global',
                      agents_dir=os.path.join(_HOME, '.codex', 'skills',
                                              'budget-workflow', 'agents'))
        return result
    if explicit == 'opencode':
        result.update(kind='opencode', scope='global',
                      agents_dir=os.path.join(_HOME, '.config', 'opencode', 'agent'))
        return result

    root = _walk_up(lambda d: os.path.isfile(os.path.join(d, '.codebuddy', 'setup.sh')))
    if root:
        result.update(kind='codebuddy', scope='project', root=root,
                      agents_dir=os.path.join(root, '.codebuddy', 'agents'))
        return result
    if os.path.isfile(os.path.join(_HOME, '.codebuddy', 'setup.sh')):
        result.update(kind='codebuddy', scope='global',
                      agents_dir=os.path.join(_HOME, '.codebuddy', 'agents'))
        return result
    root = _walk_up(lambda d: _has_suite_agents(os.path.join(d, '.claude', 'agents')))
    if root:
        result.update(kind='claudecode', scope='project', root=root,
                      agents_dir=os.path.join(root, '.claude', 'agents'))
        return result
    if _has_suite_agents(os.path.join(_HOME, '.claude', 'agents')):
        result.update(kind='claudecode', scope='global',
                      agents_dir=os.path.join(_HOME, '.claude', 'agents'))
        return result
    root = _walk_up(lambda d: _has_codex_skill(os.path.join(d, '.codex', 'skills',
                                                           'budget-workflow')))
    if root:
        result.update(kind='codex', scope='project', root=root,
                      agents_dir=os.path.join(root, '.codex', 'skills',
                                              'budget-workflow', 'agents'))
        return result
    if _has_codex_skill(os.path.join(_HOME, '.codex', 'skills', 'budget-workflow')):
        result.update(kind='codex', scope='global',
                      agents_dir=os.path.join(_HOME, '.codex', 'skills',
                                              'budget-workflow', 'agents'))
        return result
    root = _walk_up(lambda d: _has_suite_agents(os.path.join(d, '.opencode', 'agent')))
    if root:
        result.update(kind='opencode', scope='project', root=root,
                      agents_dir=os.path.join(root, '.opencode', 'agent'))
        return result
    if _has_suite_agents(os.path.join(_HOME, '.config', 'opencode', 'agent')):
        result.update(kind='opencode', scope='global',
                      agents_dir=os.path.join(_HOME, '.config', 'opencode', 'agent'))
        return result
    return result

# ─── 数据目录（对齐 lib/utils.sh budget_*_data_dir 读取优先级）─────────────


def _global_data_dir() -> str:
    """全局数据目录（~/.budgetbuddy/，design.md §8.4）。"""
    return os.path.join(_HOME, '.budgetbuddy')


def _project_data_dir() -> str:
    """向上查找项目级 .budget/（最多 10 层）；未找到返回空串。"""
    root = _walk_up(lambda d: os.path.isdir(os.path.join(d, '.budget')))
    return os.path.join(root, '.budget') if root else ''


def _effective_data_dir() -> str:
    """生效数据目录：BUDGET_DIR 覆盖 > 项目 .budget/ > 全局 ~/.budgetbuddy/。"""
    override = os.environ.get('BUDGET_DIR', '')
    if override:
        return override
    project = _project_data_dir()
    return project if project else _global_data_dir()


def _is_initialized() -> bool:
    """初始化状态判定：~/.budgetbuddy/ 全局骨架或 budget 包装器任一存在。"""
    wrapper = os.path.join(_HOME, '.local', 'bin', 'budget')
    return os.path.isdir(_global_data_dir()) or os.path.isfile(wrapper)

# ─── persona 主题清单（动态读取 personas.json，失败降级内嵌清单）───────────

_FALLBACK_THEMES = (
    ('default', '专业模式 — 标准专业命名，无角色扮演'),
    ('genshin', '原神 — 提瓦特大陆体系，契约之神统御七国'),
    ('sanguo', '三国 — 军师+五虎将体系，运筹帷幄决胜千里'),
    ('shuihu', '水浒 — 梁山好汉体系，替天行道聚义堂协作'),
    ('tech-legends', '技术传奇 — 顶级工程师阵容'),
)


def _locate_personas_file() -> str:
    """探测 personas.json（对齐 init.sh 落位链的只读子集）。"""
    candidates = []
    setup_dir = os.environ.get('BUDGET_SETUP_DIR', '')
    if setup_dir:
        candidates.append(os.path.join(setup_dir, 'personas.json'))
    candidates.append(os.path.join(os.path.dirname(_LIB_DIR), 'personas.json'))
    candidates.append(os.path.join(os.path.dirname(_LIB_DIR), 'personas', 'personas.json'))
    candidates.append(os.path.join(_HOME, '.budgetbuddy', 'personas.json'))
    candidates.append(os.path.join(_HOME, '.codebuddy', 'personas.json'))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return ''


def _load_persona_themes() -> list:
    """读取主题清单 [(key, 描述)]；personas.json 缺失/损坏时降级内嵌清单。

    展示顺序：default 首位（默认推荐项），其余按键名字母序。"""
    path = _locate_personas_file()
    if not path:
        return list(_FALLBACK_THEMES)
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return list(_FALLBACK_THEMES)
    themes = data.get('themes') if isinstance(data, dict) else None
    if not isinstance(themes, dict) or not themes:
        return list(_FALLBACK_THEMES)
    ordered_keys = sorted(themes, key=lambda key: (key != 'default', key))
    result = []
    for key in ordered_keys:
        info = themes[key] if isinstance(themes[key], dict) else {}
        description = str(info.get('description') or info.get('name') or key)
        result.append((key, description))
    return result


def _read_persona_active() -> str:
    """读取生效 persona-active.json 的主题名（项目级优先）；缺失返回空串。"""
    candidates = []
    project_dir = _project_data_dir()
    if project_dir:
        candidates.append(os.path.join(project_dir, 'persona-active.json'))
    candidates.append(os.path.join(_global_data_dir(), 'persona-active.json'))
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return ''
        if isinstance(data, dict) and data.get('theme'):
            return str(data['theme'])
    return ''

# ─── 通知配置检测（双级降级，对齐 lib/notify.sh 定位语义）──────────────────


def _detect_notify_config() -> dict:
    """定位生效 notify.json（项目 .budget/ > 全局 ~/.budgetbuddy/，不合并）。

    返回 {path, enabled, channels}；无配置返回空 dict。"""
    candidates = []
    project_dir = _project_data_dir()
    if project_dir:
        candidates.append(os.path.join(project_dir, 'notify.json'))
    candidates.append(os.path.join(_global_data_dir(), 'notify.json'))
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {'path': path, 'enabled': None, 'channels': 0}
        if not isinstance(data, dict):
            return {'path': path, 'enabled': None, 'channels': 0}
        channels = data.get('channels')
        channel_count = len(channels) if isinstance(channels, dict) else 0
        return {'path': path, 'enabled': data.get('enabled'), 'channels': channel_count}
    return {}

# ─── 交互原语（非交互模式直接返回默认值，不读取 stdin）─────────────────────


def _prompt_choice(prompt_text: str, options: list, default_index: int = 0) -> int:
    """编号列表选择；返回选中索引（0 基）。非交互/单步 EOF 取默认值。"""
    print(prompt_text)
    print()
    for index, (key, description) in enumerate(options):
        marker = ' ← 默认' if index == default_index else ''
        print(f'  {GREEN}{index + 1}{NC}) {YELLOW}{key}{NC} — {description}{marker}')
    print()
    if _NON_INTERACTIVE:
        print(f'{CYAN}[i]{NC} 非交互模式：使用默认选项 {default_index + 1}'
              f'（{options[default_index][0]}）')
        print()
        return default_index
    try:
        choice = input(f'请选择 [1-{len(options)}]（默认 {default_index + 1}）: ').strip()
    except EOFError:
        print()
        return default_index
    if not choice:
        return default_index
    try:
        index = int(choice) - 1
    except ValueError:
        index = -1
    if 0 <= index < len(options):
        return index
    print(f'{RED}无效输入，使用默认选项 {default_index + 1}{NC}')
    return default_index


def _prompt_yes_no(prompt_text: str, default: bool = True) -> bool:
    """是否确认；非交互/单步 EOF 取默认值。"""
    default_str = 'Y/n' if default else 'y/N'
    hint = '默认是' if default else '默认否'
    if _NON_INTERACTIVE:
        print(f'{CYAN}[i]{NC} 非交互模式：{prompt_text}（{hint}）')
        print()
        return default
    try:
        answer = input(f'{prompt_text} ({default_str}，{hint}): ').strip()
    except EOFError:
        print()
        return default
    if not answer:
        return default
    return answer.lower() in ('y', 'yes')

# ─── setup.sh 命令面调用（一律 subprocess bash，不 source/import 模块）─────


def _run_setup_command(args: list, extra_env: dict | None = None,
                       timeout: int = 120) -> bool:
    """经 setup.sh 命令面执行子命令（输出流式透传）；返回是否成功。"""
    if not _SETUP_SCRIPT or not os.path.isfile(_SETUP_SCRIPT):
        print(f'{RED}[✗] 找不到 setup.sh（已探测 BUDGET_SETUP_DIR、lib 同级与全局落点）{NC}')
        return False
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    try:
        # 先冲刷父进程缓冲，保证父/子输出顺序与终端一致（重定向场景）
        sys.stdout.flush()
        result = subprocess.run(
            ['bash', _SETUP_SCRIPT] + list(args),
            env=env,
            timeout=timeout,
        )
    except FileNotFoundError:
        print(f'{RED}[✗] 无法执行 bash{NC}')
        return False
    except subprocess.TimeoutExpired:
        print(f'{RED}[✗] 子命令执行超时: budget setup {" ".join(args)}{NC}')
        return False
    return result.returncode == 0


def _print_step(step_num: int, title: str) -> None:
    """打印步骤标题（N/8 进度标记，供输出断言与用户定位）。"""
    print()
    print(f'{CYAN}═══ 步骤 {step_num}/{_TOTAL_STEPS}: {title} ═══{NC}')
    print()

# ─── 步骤 1/8: 欢迎与项目简介 ──────────────────────────────────────────────


def step1_welcome() -> None:
    """欢迎页：banner + 项目简介（多 Agent 省钱工作流、四平台支持）。"""
    print(_box_top())
    print(_box_empty())
    print(_box_center(f'{BOLD}BudgetBuddy 快速上手向导{NC}'))
    print(_box_center('多 Agent 省钱研发工作流套件'))
    print(_box_empty())
    print(_box_bottom())
    print()
    print('BudgetBuddy 是什么：')
    print(f'  {CYAN}·{NC} 多 Agent 省钱工作流 — 10 个专职 Agent（架构 / 分级编码 / 双审 / 测试 / 终裁）协作交付')
    print(f'  {CYAN}·{NC} 模型分级调度 — economic / balanced / quality 三档预设，按角色匹配高性价比模型')
    print(f'  {CYAN}·{NC} 五阶段质量闸门 — 方案设计 → 评审 → 开发 → 终审 → 归档，全程 Review Gate')
    print(f'  {CYAN}·{NC} 四平台支持 — CodeBuddy / OpenCode / Claude Code / Codex 共用一套配置，改一处多平台生效')
    print()
    print(f'本向导共 {_TOTAL_STEPS} 步，每步均可跳过（直接回车取默认值，Ctrl-C 随时退出）。')

# ─── 步骤 2/8: 环境检查 ────────────────────────────────────────────────────


def _check_dependency(name: str, hint: str) -> bool:
    """检查可执行依赖（shutil.which）；缺失时输出提示（不阻断）。"""
    path = shutil.which(name)
    if path:
        print(f'  {GREEN}[✓]{NC} {name}（{path}）')
        return True
    print(f'  {YELLOW}[!]{NC} {name} 未安装 — {hint}')
    return False


def step2_environment_check() -> None:
    """环境检查：平台探测展示 + openspec/git/python3 依赖检查。"""
    platform = _detect_platform()
    if platform['kind'] == 'unknown':
        print(f'{YELLOW}[!]{NC} 未检测到 BudgetBuddy 安装形态（多级探测均未命中）')
        print('    可设置 BUDGET_PLATFORM=codebuddy|claudecode|codex|opencode 显式指定，或先运行 budget setup init')
    else:
        root_note = f'（root: {platform["root"]}）' if platform['root'] else ''
        print(f'{CYAN}[i]{NC} 运行平台: {platform["kind"]}:{platform["scope"]}{root_note}')
        print(f'{CYAN}[i]{NC} Agent 目录: {platform["agents_dir"]}')
    print()
    print('依赖检查：')
    print(f'  {GREEN}[✓]{NC} python3（{sys.executable}）')
    _check_dependency('git', '工作流版本管理与 diff 审查需要')
    _check_dependency('openspec', '变更管理（openspec propose/apply/archive）需要，可选')
    print()
    print(f'{CYAN}[i]{NC} 依赖缺失不阻断本向导；对应功能在使用时再按提示补装即可。')

# ─── 步骤 3/8: 初始化引导 ──────────────────────────────────────────────────


def step3_init_guide() -> None:
    """初始化引导：未 init 时引导执行 budget setup init；已 init 展示当前配置。"""
    if _is_initialized():
        print(f'{GREEN}[✓]{NC} 初始化状态: 已完成')
        print(f'{CYAN}[i]{NC} 生效数据目录: {_effective_data_dir()}')
        active_theme = _read_persona_active()
        if active_theme:
            print(f'{CYAN}[i]{NC} 角色主题: {active_theme}（budget setup persona list 可切换）')
        else:
            print(f'{CYAN}[i]{NC} 角色主题: 未配置（运行 budget setup init 生成默认配置）')
        notify = _detect_notify_config()
        if notify:
            status = '已启用' if notify.get('enabled') else '未启用'
            print(f'{CYAN}[i]{NC} 通知配置: {status}（{notify["channels"]} 个渠道，{notify["path"]}）')
        else:
            print(f'{CYAN}[i]{NC} 通知配置: 未配置（{os.path.join(_effective_data_dir(), "notify.json")}）')
        print()
        return

    print(f'{YELLOW}[!]{NC} 初始化状态: 未完成')
    print('    budget setup init 将创建数据目录（~/.budgetbuddy/ 与 .budget/）、')
    print('    写入 budget 命令包装器、生成 persona 与通知配置模板。')
    print()
    if _NON_INTERACTIVE:
        print(f'{CYAN}[i]{NC} 非交互模式：跳过初始化执行。')
        print(f'{CYAN}[i]{NC} 如需初始化: budget setup init')
        print()
        return
    if _prompt_yes_no('是否现在执行 budget setup init？', default=False):
        print(f'{CYAN}[i]{NC} 正在执行 budget setup init（已在本向导确认，跳过 init 自身重复确认）...')
        print()
        # 用户已确认一次，传 BUDGET_INIT_YES=1 避免 init 二次交互（init.sh 非交互通道）
        if _run_setup_command(['init'], extra_env={'BUDGET_INIT_YES': '1'}):
            print(f'{GREEN}[✓]{NC} 初始化完成')
        else:
            print(f'{YELLOW}[!]{NC} 初始化执行失败（可稍后手动运行 budget setup init）')
        print()
    else:
        print(f'{CYAN}[i]{NC} 已跳过初始化，可稍后运行 budget setup init。')
        print()

# ─── 步骤 4/8: 角色主题选择 ────────────────────────────────────────────────


def step4_persona_selection() -> None:
    """persona 选择：列出 5 主题 + 默认，选择后调 budget setup persona set。"""
    themes = _load_persona_themes()
    default_index = 0
    for index, (key, _description) in enumerate(themes):
        if key == 'default':
            default_index = index
            break
    print('角色主题（persona）为 Leader 与十个 Agent 角色赋予人格化命名与汇报风格，')
    print('随时可通过 budget setup persona set <主题> 切换。')
    print()
    index = _prompt_choice('请选择角色主题：', themes, default_index)
    theme = themes[index][0]
    if _NON_INTERACTIVE:
        print(f'{CYAN}[i]{NC} 非交互模式：已选择默认主题 {theme}，未执行。')
        print(f'{CYAN}[i]{NC} 如需应用: budget setup persona set {theme}')
        print()
        return
    print(f'{CYAN}[i]{NC} 应用角色主题: {theme}（budget setup persona set {theme}）')
    print()
    if _run_setup_command(['persona', 'set', theme]):
        print(f'{GREEN}[✓]{NC} 角色主题已应用: {theme}')
    else:
        print(f'{YELLOW}[!]{NC} 角色主题应用失败（模块未就位或主题不存在）')
        print(f'    可稍后手动执行: budget setup persona set {theme}')
    print()

# ─── 步骤 5/8: 模型预设选择 ────────────────────────────────────────────────

_PRESETS = (
    ('economic', '极低成本 — 轻量模型承担大部分角色，适合高频轻量任务'),
    ('balanced', '均衡（推荐）— 架构与审查用中高端模型、编码用高性价比模型'),
    ('quality', '优先质量 — 关键角色全部使用旗舰模型，适合复杂/高风险任务'),
)


def step5_preset_selection() -> None:
    """模型预设选择：三档说明 + 交互选择 → budget setup agent preset <档位>。"""
    print('模型预设决定各角色 Agent 使用的模型组合（10 角色 → 模型映射），')
    print('切换即时生效，随时可通过 budget setup agent preset <档位> 重设。')
    print()
    index = _prompt_choice('请选择模型预设：', list(_PRESETS), default_index=1)
    preset = _PRESETS[index][0]
    if _NON_INTERACTIVE:
        print(f'{CYAN}[i]{NC} 非交互模式：已选择默认预设 {preset}，未执行。')
        print(f'{CYAN}[i]{NC} 如需应用: budget setup agent preset {preset}')
        print()
        return
    print(f'{CYAN}[i]{NC} 应用模型预设: {preset}（budget setup agent preset {preset}）')
    print()
    if _run_setup_command(['agent', 'preset', preset]):
        print(f'{GREEN}[✓]{NC} 模型预设已应用: {preset}')
    else:
        print(f'{YELLOW}[!]{NC} 预设应用失败（未检测到平台形态或 agent 目录缺失）')
        print(f'    可稍后手动执行: budget setup agent preset {preset}')
    print()

# ─── 步骤 6/8: 通知配置引导 ────────────────────────────────────────────────


def step6_notify_guide() -> None:
    """通知配置引导：notify.json 配置说明 + 跳过选项（不收集敏感字段）。

    webhook / secret 属敏感信息，仅存于 chmod 600 的配置文件（design.md §9），
    向导不交互收集，仅输出配置指引。"""
    notify = _detect_notify_config()
    if notify:
        status = '已启用' if notify.get('enabled') else '未启用'
        print(f'{CYAN}[i]{NC} 检测到通知配置: {notify["path"]}（{status}，'
              f'{notify.get("channels", 0)} 个渠道）')
    else:
        print(f'{CYAN}[i]{NC} 未检测到通知配置'
              f'（.budget/notify.json 与 ~/.budgetbuddy/notify.json 均不存在）')
    print()
    print('工作流关键节点（评审驳回 / 任务完成 / 需要拍板等 N1-N11）可向群机器人')
    print('webhook 推送消息，支持通用 webhook 渠道（企业微信 / 钉钉 / 飞书 / 自定义）。')
    print()
    if _prompt_yes_no('是否查看通知配置说明？', default=True):
        print()
        print('配置文件（双级降级，项目级优先，不合并）：')
        print('  项目级: <项目根>/.budget/notify.json')
        print('  全局级: ~/.budgetbuddy/notify.json')
        print()
        print('配置要点：')
        print('  enabled   总开关（true 启用通知）')
        print('  channels  渠道定义（type: wecom_bot|dingtalk_bot|feishu_bot|custom + webhook，可选 secret 加签）')
        print('  events    N1-N11 各事件独立开关（enabled + channels 投递列表）')
        print()
        print(f'{YELLOW}[!]{NC} webhook / secret 为敏感字段：仅存于该文件（权限 600），不进版本库。')
    else:
        print()
        print(f'{CYAN}[i]{NC} 已跳过通知配置说明。')
    print()
    print(f'{CYAN}[i]{NC} 可稍后手动编辑配置文件，或运行 budget setup init 生成默认模板（默认关闭）。')
    print()

# ─── 步骤 7/8: 工作流演示 ──────────────────────────────────────────────────


def step7_workflow_demo() -> None:
    """工作流演示说明：/budget:start 使用演示文案 + 五阶段图示。"""
    print('工作流使用演示：')
    print()
    print(f'  在 {CYAN}CodeBuddy{NC} 主会话输入:  {CYAN}/budget:start <你的需求描述>{NC}')
    print(f'  在 {CYAN}OpenCode{NC} 主会话输入:   {CYAN}/budget-start <你的需求描述>{NC}')
    print(f'  在 {CYAN}Claude Code{NC} 主会话输入: {CYAN}/budget:start <你的需求描述>{NC}')
    print(f'  在 {CYAN}Codex{NC} 会话中输入:    {CYAN}<自然语言描述需求>{NC}（触发 budget-workflow skill）')
    print()
    print(f'  {YELLOW}[!]{NC} Codex 平台前置：需 config.toml [features] multi_agent = true，且模型为部署别名映射（见 budget setup models）。')
    print()
    print('  示例: /budget:start 实现一个用户登录模块，要求支持密码与验证码两种方式')
    print()
    print('  Leader 将自动调度 Agent 团队执行五阶段流程：')
    print()
    print(f'  {CYAN}Phase 1{NC}  方案设计   architect 起草 proposal / design / specs / tasks')
    print(f'  {CYAN}Phase 2{NC}  方案评审   reviewer + reviewer-b 双审（驳回退回修正，最多 3 轮）')
    print(f'  {CYAN}Phase 3{NC}  代码开发   coder 按任务分级实现 → tester 验证 → reviewer 审查')
    print(f'  {CYAN}Phase 4{NC}  最终审查   reviewer 全量 diff 审查')
    print(f'  {CYAN}Phase 5{NC}  归档沉淀   recorder 归档变更并提取经验')
    print()
    print(f'  长期目标模式（Goal Loop）用 {CYAN}/budget:goal{NC} 启动，追加 Phase 6 目标验证循环。')
    print(f'  运行中随时用 {CYAN}/budget:status{NC} 查看进度（OpenCode: /budget-status；Claude Code 同 CodeBuddy；Codex 用 budget status）。')
    print()

# ─── 步骤 8/8: 完成页 ──────────────────────────────────────────────────────


def step8_completion() -> None:
    """完成页：后续步骤指引（/budget:start / budget setup help / budget status）。"""
    print(_box_top(GREEN))
    print(_box_empty(GREEN))
    print(_box_center(f'{BOLD}快速上手完成！{NC}', GREEN))
    print(_box_empty(GREEN))
    print(_box_bottom(GREEN))
    print()
    print('后续步骤：')
    print(f'  {GREEN}1.{NC} {CYAN}/budget:start <需求描述>{NC} 开始你的第一次工作流（OpenCode: /budget-start；Claude Code 同 CodeBuddy；Codex 自然语言触发 skill）')
    print(f'  {GREEN}2.{NC} {CYAN}budget setup help{NC} 查看全部管理命令')
    print(f'  {GREEN}3.{NC} {CYAN}budget status{NC} 查看运行状态与配置概览')
    print(f'  {GREEN}4.{NC} {CYAN}budget setup quickstart{NC} 随时重跑本向导（别名 tour / wizard）')
    print()

# ─── 主流程 ────────────────────────────────────────────────────────────────


def main(argv: list | None = None) -> int:
    """向导主入口：解析参数 → 判定交互模式 → 依次执行 8 步（异常兜底 exit 0）。"""
    global _NON_INTERACTIVE
    args = list(sys.argv[1:] if argv is None else argv)
    if '--non-interactive' in args:
        _NON_INTERACTIVE = True
    elif '--interactive' in args:
        _NON_INTERACTIVE = False
    elif not sys.stdin.isatty():
        _NON_INTERACTIVE = True

    if _NON_INTERACTIVE:
        print(f'{CYAN}[i]{NC} 非交互模式（未检测到终端输入）：全部步骤使用默认值，不执行任何配置变更。')
        print(f'{CYAN}[i]{NC} 如需交互式配置，请在终端中运行: budget setup quickstart')
        print()

    try:
        _print_step(1, '欢迎与项目简介')
        step1_welcome()
        _print_step(2, '环境检查')
        step2_environment_check()
        _print_step(3, '初始化引导')
        step3_init_guide()
        _print_step(4, '角色主题选择')
        step4_persona_selection()
        _print_step(5, '模型预设选择')
        step5_preset_selection()
        _print_step(6, '通知配置引导')
        step6_notify_guide()
        _print_step(7, '工作流演示')
        step7_workflow_demo()
        _print_step(8, '完成')
        step8_completion()
    except KeyboardInterrupt:
        print()
        print()
        print(f'{YELLOW}[!]{NC} 已退出向导（可随时重新运行 budget setup quickstart）。')
        return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
