#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy persona 主题展开引擎（design.md §8.5 / specs/setup-cli「personas 五主题」）。

由 lib/persona.sh 编排调用，也可独立执行。路径与主题一律经命令行参数或
BUDGET_* 环境变量传递（禁止 shell 字符串插值进 Python 代码）：

  --personas / BUDGET_PERSONAS_FILE   personas.json 路径（主题目录）
  --active   / BUDGET_PERSONA_ACTIVE  persona-active.json 路径（当前主题）
  --theme    / BUDGET_PERSONA_THEME   目标主题键

子命令：
  list [--json]   列出全部主题（标记当前主题）
  validate        校验主题存在且 roles 11 键齐全（成功输出 yes，exit 0）
  set             展开主题写入 persona-active.json（原子写、键排序）
  expand [--json] 输出主题 11 键角色称呼映射（不写文件）
  current         输出当前主题键（无 active 文件时输出默认主题）
  greeting        输出当前主题称呼（greeting）
  show            展示当前主题详情（主题 / 称呼 / 11 键映射 / 生效文件）

11 键角色集（design.md §8.5：leader + §6 十角色，共 11 键）：
  leader / architect / coder-lite / coder-standard / coder-senior /
  reviewer / reviewer-b / tester / recorder / director / goal-evaluator

自定义主题校验：roles 键集必须完整覆盖 11 键（缺失即报错 exit 1，未知键
 stderr 告警）；report_templates 必须含 5 个汇报模板键。写入纪律：临时
文件 + 原子 rename + sort_keys 幂等（与 guard.sh / hooks_inject.py 一致）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from typing import NoReturn

# 展示顺序（leader 主会话在前，其余按 design.md §6 角色清单序）
ROLE_ORDER = (
    'leader', 'architect', 'coder-lite', 'coder-standard', 'coder-senior',
    'reviewer', 'reviewer-b', 'tester', 'recorder', 'director',
    'goal-evaluator',
)
ROLE_KEYS = frozenset(ROLE_ORDER)

REPORT_TEMPLATE_KEYS = frozenset((
    'task_complete', 'review_pass', 'review_reject', 'test_pass', 'test_fail',
))

DEFAULT_THEME = 'default'


def fail(message: str, hint: str | None = None) -> NoReturn:
    """stderr 输出错误 JSON（键排序）并以退出码 1 终止。"""
    payload = {'error': message}
    if hint:
        payload['hint'] = hint
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    sys.exit(1)


def load_json(path: str, label: str) -> dict:
    """严格加载 JSON 文件（缺失/格式错误/非对象 → fail 终止）。"""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError:
        fail(f'{label} 不存在: {path}')
    except (OSError, ValueError) as exc:
        fail(f'{label} 读取失败: {path}（{exc}）')
    if not isinstance(data, dict):
        fail(f'{label} 顶层必须是 JSON 对象: {path}')
    return data


def load_json_quiet(path: str) -> dict | None:
    """容错加载 JSON 文件（缺失/格式错误/非对象 → None，不终止）。"""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def atomic_write_json(path: str, data: dict) -> None:
    """临时文件 + 原子 rename 写 JSON（键排序幂等；失败清理临时文件）。"""
    dir_name = os.path.dirname(path) or '.'
    try:
        fd, tmp_path = tempfile.mkstemp(prefix='.persona-', suffix='.tmp', dir=dir_name)
    except OSError as exc:
        fail(f'persona-active.json 写入失败: {path}（{exc}）')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False, sort_keys=True)
            tmp.write('\n')
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
    except OSError as exc:
        fail(f'persona-active.json 写入失败: {path}（{exc}）')
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ─── 路径与主题解析 ──────────────────────────────────────────────────────


def resolve_personas(args: argparse.Namespace) -> str:
    """personas.json 路径（参数 > 环境变量；缺失即 fail）。"""
    path = args.personas or os.environ.get('BUDGET_PERSONAS_FILE', '')
    if not path:
        fail('未指定 personas.json 路径（--personas 或 BUDGET_PERSONAS_FILE）')
    if not os.path.isfile(path):
        fail(
            f'personas.json 不存在: {path}',
            '请先完成安装或更新：budget setup update',
        )
    return path


def resolve_active(args: argparse.Namespace) -> str:
    """persona-active.json 路径（参数 > 环境变量；允许为空串=未设置）。"""
    return args.active or os.environ.get('BUDGET_PERSONA_ACTIVE', '')


def resolve_theme_arg(args: argparse.Namespace) -> str:
    """目标主题键（参数 > 环境变量；允许为空串=按当前主题推导）。"""
    return args.theme or os.environ.get('BUDGET_PERSONA_THEME', '')


def themes_of(data: dict) -> dict:
    """themes 映射（缺失/为空/非对象 → fail）。"""
    themes = data.get('themes')
    if not isinstance(themes, dict) or not themes:
        fail('personas.json 缺少 themes 或 themes 为空')
    return themes


def default_theme_of(data: dict) -> str:
    """默认主题键（_meta.default_theme，缺失/非法回退 default）。"""
    theme = data.get('_meta', {}).get('default_theme', DEFAULT_THEME)
    if not isinstance(theme, str) or not theme:
        return DEFAULT_THEME
    return theme


def current_theme(args: argparse.Namespace, data: dict) -> str:
    """当前主题键：active 文件 > personas.json 默认主题。"""
    active_path = resolve_active(args)
    if active_path and os.path.isfile(active_path):
        active = load_json_quiet(active_path)
        if active:
            theme = active.get('theme')
            if isinstance(theme, str) and theme:
                return theme
    return default_theme_of(data)


def require_theme(themes: dict, theme_name: str) -> None:
    """主题存在性校验（不存在 → fail 并附可用主题清单）。"""
    if theme_name not in themes:
        available = ', '.join(sorted(themes))
        fail(f"主题 '{theme_name}' 不存在", f'可用主题: {available}')


# ─── 主题校验与展开 ──────────────────────────────────────────────────────


def validate_theme_roles(themes: dict, theme_name: str) -> None:
    """自定义主题校验：roles 完整覆盖 11 键 + report_templates 5 键。"""
    theme = themes[theme_name]
    roles = theme.get('roles')
    if not isinstance(roles, dict):
        fail(f"主题 '{theme_name}' 缺少 roles 映射")
    missing = sorted(ROLE_KEYS - set(roles))
    if missing:
        fail(
            f"主题 '{theme_name}' roles 缺失 {len(missing)} 个键: {', '.join(missing)}",
            'roles 必须完整覆盖 11 键（leader + 十角色，design.md §8.5）',
        )
    extra = sorted(set(roles) - ROLE_KEYS)
    if extra:
        print(
            json.dumps(
                {'warning': f"主题 '{theme_name}' roles 含未知键: {', '.join(extra)}"},
                ensure_ascii=False, sort_keys=True,
            ),
            file=sys.stderr,
        )
    templates = theme.get('report_templates')
    if not isinstance(templates, dict):
        fail(f"主题 '{theme_name}' 缺少 report_templates")
    missing_templates = sorted(REPORT_TEMPLATE_KEYS - set(templates))
    if missing_templates:
        fail(
            f"主题 '{theme_name}' report_templates 缺失: {', '.join(missing_templates)}",
        )


def build_active(themes: dict, theme_name: str) -> dict:
    """展开主题为 persona-active.json 结构（11 键 → 角色名映射）。"""
    validate_theme_roles(themes, theme_name)
    theme = themes[theme_name]
    roles = {}
    for role in ROLE_ORDER:
        info = theme['roles'].get(role)
        if isinstance(info, dict):
            roles[role] = info.get('name', role)
        else:
            roles[role] = str(info)
    return {
        'greeting': theme.get('greeting', ''),
        'report_templates': theme.get('report_templates', {}),
        'roles': roles,
        'theme': theme_name,
    }


# ─── 子命令实现 ──────────────────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> int:
    """list：列出全部主题（标记当前主题）。"""
    path = resolve_personas(args)
    data = load_json(path, 'personas.json')
    themes = themes_of(data)
    active_theme = current_theme(args, data)
    if args.json:
        payload = {
            'current': active_theme,
            'default': default_theme_of(data),
            'themes': [
                {
                    'current': key == active_theme,
                    'description': theme.get('description', ''),
                    'key': key,
                    'name': theme.get('name', key),
                    'name_en': theme.get('name_en', ''),
                }
                for key, theme in sorted(themes.items())
                if isinstance(theme, dict)
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    print('可用角色主题:')
    for key, theme in sorted(themes.items()):
        if not isinstance(theme, dict):
            continue
        marker = '  ← 当前' if key == active_theme else ''
        name_en = theme.get('name_en', '')
        suffix = f' ({name_en})' if name_en else ''
        print('  %-14s %s%s%s' % (key, theme.get('name', key), suffix, marker))
        description = theme.get('description', '')
        if description:
            print('                  %s' % description)
    print('')
    print('切换: budget setup persona set <theme>')
    print('展开: budget setup persona expand [<theme>]')
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """validate：主题存在且 roles 11 键齐全（成功输出 yes）。"""
    path = resolve_personas(args)
    data = load_json(path, 'personas.json')
    themes = themes_of(data)
    theme_name = resolve_theme_arg(args)
    if not theme_name:
        fail('未指定主题（--theme 或 BUDGET_PERSONA_THEME）')
    require_theme(themes, theme_name)
    validate_theme_roles(themes, theme_name)
    print('yes')
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    """set：展开主题写入 persona-active.json（原子写、键排序）。"""
    path = resolve_personas(args)
    data = load_json(path, 'personas.json')
    themes = themes_of(data)
    theme_name = resolve_theme_arg(args)
    if not theme_name:
        fail(
            '未指定主题（--theme 或 BUDGET_PERSONA_THEME）',
            '用法: budget setup persona set <theme>',
        )
    require_theme(themes, theme_name)
    active_path = resolve_active(args)
    if not active_path:
        fail('未指定 persona-active.json 路径（--active 或 BUDGET_PERSONA_ACTIVE）')
    active = build_active(themes, theme_name)
    atomic_write_json(active_path, active)
    theme = themes[theme_name]
    print('已切换角色主题: %s — %s' % (theme_name, theme.get('name', theme_name)))
    if active['greeting']:
        print('称呼: %s' % active['greeting'])
    print('写入: %s' % active_path)
    return 0


def cmd_expand(args: argparse.Namespace) -> int:
    """expand：输出主题 11 键角色称呼映射（不写文件）。"""
    path = resolve_personas(args)
    data = load_json(path, 'personas.json')
    themes = themes_of(data)
    theme_name = resolve_theme_arg(args)
    if not theme_name:
        theme_name = current_theme(args, data)
    require_theme(themes, theme_name)
    active = build_active(themes, theme_name)
    if args.json:
        print(json.dumps({
            'greeting': active['greeting'],
            'roles': active['roles'],
            'theme': theme_name,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    theme = themes[theme_name]
    print('主题: %s — %s' % (theme_name, theme.get('name', theme_name)))
    if active['greeting']:
        print('称呼: %s' % active['greeting'])
    print('角色映射（11 键）:')
    for role in ROLE_ORDER:
        print('  %-16s → %s' % (role, active['roles'][role]))
    return 0


def cmd_current(args: argparse.Namespace) -> int:
    """current：输出当前主题键（active 文件 > 默认主题）。"""
    path = resolve_personas(args)
    data = load_json(path, 'personas.json')
    themes_of(data)
    print(current_theme(args, data))
    return 0


def cmd_greeting(args: argparse.Namespace) -> int:
    """greeting：输出当前主题称呼（active 文件优先，回退主题定义）。"""
    path = resolve_personas(args)
    data = load_json(path, 'personas.json')
    themes = themes_of(data)
    theme_name = current_theme(args, data)
    greeting = ''
    active_path = resolve_active(args)
    if active_path and os.path.isfile(active_path):
        active = load_json_quiet(active_path)
        if active and active.get('theme') == theme_name:
            value = active.get('greeting')
            if isinstance(value, str):
                greeting = value
    if not greeting:
        theme = themes.get(theme_name)
        if isinstance(theme, dict):
            value = theme.get('greeting')
            if isinstance(value, str):
                greeting = value
    print(greeting)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """show：当前主题详情（主题 / 称呼 / 11 键映射 / 生效文件）。"""
    path = resolve_personas(args)
    data = load_json(path, 'personas.json')
    themes = themes_of(data)
    active_path = resolve_active(args)
    active_data = None
    if active_path and os.path.isfile(active_path):
        active_data = load_json_quiet(active_path)

    theme_name = ''
    if active_data:
        candidate = active_data.get('theme')
        if isinstance(candidate, str):
            theme_name = candidate
    if theme_name not in themes:
        theme_name = default_theme_of(data)
    require_theme(themes, theme_name)

    # 角色映射：active 文件（theme 匹配且 11 键齐全）优先，否则即时展开
    roles = None
    if active_data and active_data.get('theme') == theme_name:
        candidate_roles = active_data.get('roles')
        if isinstance(candidate_roles, dict) and ROLE_KEYS <= set(candidate_roles):
            roles = {role: str(candidate_roles.get(role, role)) for role in ROLE_ORDER}
    if roles is None:
        roles = build_active(themes, theme_name)['roles']

    theme = themes[theme_name]
    print('当前主题: %s — %s' % (theme_name, theme.get('name', theme_name)))
    greeting = ''
    if active_data and active_data.get('theme') == theme_name:
        value = active_data.get('greeting')
        if isinstance(value, str):
            greeting = value
    if not greeting and isinstance(theme.get('greeting'), str):
        greeting = theme['greeting']
    if greeting:
        print('称呼: %s' % greeting)
    print('角色映射（11 键）:')
    for role in ROLE_ORDER:
        print('  %-16s → %s' % (role, roles[role]))
    if active_data:
        print('生效文件: %s' % active_path)
    else:
        print('生效文件: （未设置，使用默认主题）')
    return 0


# ─── 参数解析 ────────────────────────────────────────────────────────────


class PersonaArgumentParser(argparse.ArgumentParser):
    """参数错误统一退出码 1（与业务错误一致）。"""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(
            json.dumps({'error': f'参数错误: {message}'}, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        sys.exit(1)


def build_parser() -> PersonaArgumentParser:
    """构造子命令解析器（公共路径选项在子命令前后均可出现）。"""
    parser = PersonaArgumentParser(
        prog='persona_expand',
        description='BudgetBuddy persona 主题展开引擎（design.md §8.5）',
    )
    parser.add_argument(
        '--personas', default=os.environ.get('BUDGET_PERSONAS_FILE', ''),
        help='personas.json 路径（默认取 BUDGET_PERSONAS_FILE）')
    parser.add_argument(
        '--active', default=os.environ.get('BUDGET_PERSONA_ACTIVE', ''),
        help='persona-active.json 路径（默认取 BUDGET_PERSONA_ACTIVE）')
    parser.add_argument(
        '--theme', default=os.environ.get('BUDGET_PERSONA_THEME', ''),
        help='目标主题键（默认取 BUDGET_PERSONA_THEME）')

    # 公共路径选项的子命令侧副本（persona.sh 编排与直调两种传参顺序兼容；
    # default=SUPPRESS 确保未出现时不覆盖主解析器已解析的值/默认值）
    common = PersonaArgumentParser(add_help=False)
    common.add_argument('--personas', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument('--active', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument('--theme', default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    sub = parser.add_subparsers(
        dest='command', required=True, parser_class=PersonaArgumentParser)

    p_list = sub.add_parser('list', parents=[common], help='列出全部主题')
    p_list.add_argument('--json', action='store_true', help='JSON 输出（键排序）')
    p_list.set_defaults(func=cmd_list)

    p_validate = sub.add_parser(
        'validate', parents=[common], help='校验主题存在且 11 键齐全')
    p_validate.set_defaults(func=cmd_validate)

    p_set = sub.add_parser(
        'set', parents=[common], help='展开主题写入 persona-active.json')
    p_set.set_defaults(func=cmd_set)

    p_expand = sub.add_parser('expand', parents=[common], help='输出主题 11 键角色映射')
    p_expand.add_argument('--json', action='store_true', help='JSON 输出（键排序）')
    p_expand.set_defaults(func=cmd_expand)

    p_current = sub.add_parser('current', parents=[common], help='输出当前主题键')
    p_current.set_defaults(func=cmd_current)

    p_greeting = sub.add_parser('greeting', parents=[common], help='输出当前主题称呼')
    p_greeting.set_defaults(func=cmd_greeting)

    p_show = sub.add_parser('show', parents=[common], help='展示当前主题详情')
    p_show.set_defaults(func=cmd_show)

    return parser


def main() -> int:
    """入口：解析子命令并分发（错误 exit 1）。"""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
