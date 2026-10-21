#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy 模型解析与 agent frontmatter 重写辅助（design.md §3.2/§7/§8.1）。

shell 侧（lib/models.sh、lib/preset.sh）经 CLI 调用；本模块承担全部模型数据
解析与 agent 产物 frontmatter 的 model 字段读写，保证 YAML 处理安全（shell
不做字符串级 frontmatter 处理）。

子命令：
    resolve      别名/裸 ID/provider-model 形态解析（按平台输出最终 model 值）
    preset       预设档位查询（输出 "<agent 文件名>=<model>" 行）
    list-presets 列出平台全部预设档位明细（人读格式）
    current      当前 agent model 值查询（输出 "<agent 文件名>=<model>" 行）
    rewrite      批量重写 agent frontmatter model 字段（preset/custom/inherit）

平台清单数据驱动（add-claudecode-platform D5）：--platform 不再硬编码枚举，
接受任意值并在加载 budget-models.json 后校验 ∈ platforms 键集（新增平台零
代码）。resolve 平台策略仅 opencode 特判 provider/model，其余平台（codebuddy
/claudecode 及后续）统一走 catalog_id 裸 ID 默认策略；frontmatter 读写仅触碰
model 一行（claudecode camelCase 键 permissionMode/maxTurns 等不受影响，
model 键名与中立源一致）。

角色名映射：agent 文件名（连字符，coder-lite）与 model_role 键（下划线，
coder_lite）经 budget-models.json 的 roles 键集双向校验，仅已知角色参与
重写，未知角色报错跳过。

退出码：0 成功；1 错误（文件/参数/预设名非法等）；2 未知名（resolve 未命中）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# frontmatter 顶层 model 行（列首无缩进；不匹配 model_role/models 等相近前缀键）
MODEL_LINE_RE = re.compile(r'^model[ \t]*:')

# model 行插入锚点键（name/description/mode：双平台产物均含其中之一，
# 插入位置取锚点键最后出现行之后，与构建产物字段顺序一致）
ANCHOR_LINE_RE = re.compile(r'^(name|description|mode)[ \t]*:')

# 预设档位展示标签（仅呈现用；档位数据以 budget-models.json 为准）
PRESET_LABELS = {
    'economic': '省钱优先',
    'balanced': '均衡（构建默认）',
    'quality': '质量优先',
}


def load_json(path: str) -> dict:
    """加载 JSON 文件；失败时输出错误并以退出码 1 终止。"""
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError:
        print(f'error: 文件不存在: {path}', file=sys.stderr)
        sys.exit(1)
    except (json.JSONDecodeError, OSError) as exc:
        print(f'error: JSON 解析失败 {path}: {exc}', file=sys.stderr)
        sys.exit(1)


def build_catalog(data: dict) -> dict:
    """构建模型 ID → 厂商组索引（paid 优先，同 ID 首次出现为准）。"""
    catalog: dict = {}
    models = data.get('models', {})
    for section in ('paid', 'free'):
        for vendor, entries in models.get(section, {}).items():
            for entry in entries:
                model_id = entry.get('id', '')
                if model_id and model_id not in catalog:
                    catalog[model_id] = vendor
    return catalog


def _unknown_input_message(name: str, aliases: dict) -> str:
    """未知名错误信息（附可用别名列表，specs/model-presets custom 场景）。"""
    available = ', '.join(sorted(aliases)) if aliases else '（无）'
    return f'未知模型名: {name}（不在别名表与模型目录中）\n可用别名: {available}'


def validate_platform(data: dict, platform: str) -> str | None:
    """校验 --platform 值 ∈ budget-models.json platforms 键集（数据驱动）。

    与使用语境一致的最小动态化方案：运行时安装形态无 core/platform/*.yaml
    可 glob，平台真值源即 budget-models.json 的 platforms 键集（构建期已做
    双清单一致性校验）。返回错误信息或 None。
    """
    platforms = data.get('platforms', {})
    if platform not in platforms:
        available = ', '.join(sorted(platforms)) or '（无）'
        return (f'未知平台: {platform}（不在 budget-models.json platforms 键集），'
                f'可用: {available}')
    return None


def resolve_model(name: str, platform: str, data: dict,
                   custom: bool = False) -> tuple[str | None, str | None]:
    """解析输入为平台最终 model 值。

    codebuddy/claudecode（默认策略，catalog_id 裸 ID）：别名/裸 ID → 裸 ID；
        provider/model 形态原样保留（第三方模型如 presence-glm/glm-5.3、方舟
        volcengine 接入等，信任用户，不剥离）。
    opencode（特判）：别名/裸 ID → 经 provider_map 转换为 provider/model；
        provider/model 形态直接使用。

    custom=True 时：未知输入（不在别名表与预算目录）原样返回，支持用户已
        在 CodeBuddy 客户端配置的第三方模型（方舟/Presence/讯飞/doubao 等）
        直接经 budget setup agent custom <id> 分配。

    返回 (value, error)：成功时 error 为 None；失败时 value 为 None。
    """
    text = name.strip()
    if not text:
        return None, '输入为空'
    aliases = data.get('aliases', {})
    alias_lower = {key.lower(): value for key, value in aliases.items()}
    catalog = build_catalog(data)
    id_lower = {key.lower(): key for key in catalog}

    bare = alias_lower.get(text.lower())
    if bare is None:
        bare = id_lower.get(text.lower())
    if bare is None:
        if custom:
            # 信任用户提供的第三方模型 ID（方舟/Presence/讯飞/doubao 等），原样返回
            return text, None
        if '/' not in text:
            return None, _unknown_input_message(text, aliases)

    if platform == 'opencode':
        if '/' in text:
            return text, None
        if bare is None:
            if custom:
                return text, None
            return None, (
                f'模型 {text} 不在目录中，无法确定 opencode provider'
                '（目录可能过期，可运行 budget setup models 更新）')
        vendor = catalog.get(bare)
        if vendor is None:
            return None, (
                f'模型 {bare} 不在目录中，无法确定 opencode provider'
                '（目录可能过期，可运行 budget setup models 更新）')
        provider = data.get('provider_map', {}).get(vendor)
        if not provider:
            return None, f'厂商组 {vendor} 缺少 provider_map 映射（budget-models.json 数据异常）'
        return f'{provider}/{bare}', None

    # codebuddy/claudecode（默认策略）：provider/model 形态——若裸 ID 已在预算
    # 目录/别名中则剥离为裸 ID（如 zhipu/glm-5.2 → glm-5.2），否则视为第三方
    # 接入模型（方舟/Presence/讯飞等）原样保留（如 presence-glm/glm-5.3 →
    # presence-glm/glm-5.3，信任用户配置）
    if '/' in text:
        bare_part = text.rsplit('/', 1)[1]
        if bare_part in id_lower or bare_part in alias_lower:
            return bare_part, None
        return text, None
    return bare, None


def get_preset_lines(data: dict, platform: str, preset_name: str) -> tuple[list | None, str | None]:
    """预设档位 → "<agent 文件名>=<model>" 行列表（角色键转连字符文件名形态）。"""
    presets = data.get('platforms', {}).get(platform, {}).get('presets', {})
    preset = presets.get(preset_name)
    if preset is None:
        available = ', '.join(sorted(presets)) or '（无）'
        return None, f'预设 "{preset_name}" 不存在（平台 {platform}），可用: {available}'
    lines = [f'{role.replace("_", "-")}={preset[role]}' for role in sorted(preset)]
    return lines, None


def list_presets_text(data: dict, platform: str) -> tuple[str | None, str | None]:
    """平台全部预设档位明细（人读格式，档位名排序）。"""
    presets = data.get('platforms', {}).get(platform, {}).get('presets', {})
    if not presets:
        return None, f'平台 {platform} 无预设数据（budget-models.json 异常）'
    chunks = []
    for name in sorted(presets):
        label = PRESET_LABELS.get(name, '')
        title = f'{name} — {label}（{len(presets[name])} 角色）:' if label else \
            f'{name}（{len(presets[name])} 角色）:'
        body = '\n'.join(
            f'  {role.replace("_", "-")} → {presets[name][role]}'
            for role in sorted(presets[name]))
        chunks.append(title + '\n' + body)
    return '\n\n'.join(chunks), None


def read_model_value(path: str) -> tuple[str | None, str | None]:
    """读取 agent 文件 frontmatter 顶层 model 字段值（引号剥离）。

    返回 (value, error)：无 model 字段时 value 为 None 且 error 为 None；
    无 frontmatter/读取失败时 value 与 error 均按错误路径返回。
    """
    try:
        with open(path, encoding='utf-8') as handle:
            content = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        return None, f'读取失败: {exc}'
    lines = content.splitlines()
    if not lines or lines[0].strip() != '---':
        return None, '无 frontmatter'
    for line in lines[1:]:
        if line.strip() == '---':
            break
        if MODEL_LINE_RE.match(line):
            value = line.split(':', 1)[1].strip().strip('\'"')
            return value, None
    return None, None


def get_current_lines(agents_dir: str, roles: list) -> tuple[list | None, str | None]:
    """当前 agent model 值 → "<agent 文件名>=<model>" 行列表（仅本套件角色）。

    model 字段缺失的 agent 输出空值行（"coder-lite="），供 diff 对比。
    """
    if not os.path.isdir(agents_dir):
        return None, f'agent 目录不存在: {agents_dir}'
    role_by_filename = {role.replace('_', '-'): role for role in roles}
    lines = []
    for name in sorted(os.listdir(agents_dir)):
        if not name.endswith('.md'):
            continue
        base = name[:-3]
        if base not in role_by_filename:
            continue
        value, error = read_model_value(os.path.join(agents_dir, name))
        if error:
            print(f'[!] {base}: {error}（按未设置处理）', file=sys.stderr)
        lines.append(f'{base}={value or ""}')
    return lines, None


def _line_ending(line: str) -> str:
    """提取行尾换行符（CRLF/LF/无）。"""
    if line.endswith('\r\n'):
        return '\r\n'
    if line.endswith('\n'):
        return '\n'
    return ''


def rewrite_agent_file(path: str, new_model: str | None) -> tuple[bool, str]:
    """重写 agent 文件 frontmatter 顶层 model 字段（design.md §3.2）。

    new_model 为 None 时删除 model 行（inherit：双平台均删除字段、跟随主会话）；
    否则替换现有值；无 model 行时插入（锚点：name/description/mode 最后出现
    行之后）。仅触碰 model 一行，frontmatter 其余字段与正文逐字节保留。

    返回 (ok, detail)：ok=False 时文件未被修改，detail 为原因。
    """
    try:
        with open(path, encoding='utf-8') as handle:
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

    model_idx = None
    for idx in range(1, close_idx):
        if MODEL_LINE_RE.match(lines[idx]):
            model_idx = idx
            break

    if new_model is None:
        if model_idx is None:
            return True, 'unchanged'
        del lines[model_idx]
        detail = 'removed'
    elif model_idx is not None:
        lines[model_idx] = f'model: {new_model}{_line_ending(lines[model_idx])}'
        detail = 'replaced'
    else:
        anchor_idx = 1
        for idx in range(1, close_idx):
            if ANCHOR_LINE_RE.match(lines[idx]):
                anchor_idx = idx + 1
        ending = _line_ending(lines[anchor_idx - 1]) or '\n'
        lines.insert(anchor_idx, f'model: {new_model}{ending}')
        detail = 'inserted'

    try:
        with open(path, 'w', encoding='utf-8', newline='') as handle:
            handle.write(''.join(lines))
    except OSError as exc:
        return False, f'写入失败: {exc}'
    return True, detail


def cmd_rewrite(data: dict, args: argparse.Namespace) -> int:
    """批量重写 agent frontmatter model 字段（preset/custom/inherit）。"""
    platform = args.platform
    agents_dir = args.agents_dir
    roles = data.get('roles', [])
    role_by_filename = {role.replace('_', '-'): role for role in roles}

    preset_map = None
    if args.mode == 'preset':
        presets = data.get('platforms', {}).get(platform, {}).get('presets', {})
        preset_map = presets.get(args.preset)
        if preset_map is None:
            available = ', '.join(sorted(presets)) or '（无）'
            print(f'error: 预设 "{args.preset}" 不存在（平台 {platform}），可用: {available}',
                  file=sys.stderr)
            return 1
    if args.mode == 'custom' and not args.model:
        print('error: custom 模式缺少 --model 参数', file=sys.stderr)
        return 1

    if not os.path.isdir(agents_dir):
        print(f'error: agent 目录不存在: {agents_dir}', file=sys.stderr)
        return 1
    names = sorted(name for name in os.listdir(agents_dir) if name.endswith('.md'))
    if not names:
        print(f'error: agent 目录中无 .md 文件: {agents_dir}', file=sys.stderr)
        return 1

    known_count = 0
    failed_count = 0
    for name in names:
        base = name[:-3]
        role = role_by_filename.get(base)
        if role is None:
            print(f'[!] 跳过未知角色 agent: {base}（不在 budget-models.json roles 中）',
                  file=sys.stderr)
            continue
        known_count += 1
        if args.mode == 'preset':
            new_model = preset_map.get(role)
            if new_model is None:
                print(f'[!] 跳过 {base}: 预设 "{args.preset}" 未覆盖角色 {role}',
                      file=sys.stderr)
                failed_count += 1
                continue
        elif args.mode == 'custom':
            new_model = args.model
        else:
            new_model = None
        ok, detail = rewrite_agent_file(os.path.join(agents_dir, name), new_model)
        if not ok:
            print(f'[!] 跳过 {base}: {detail}', file=sys.stderr)
            failed_count += 1
            continue
        if new_model is None:
            print(f'  {base} → 跟随主会话')
        else:
            print(f'  {base} → {new_model}')

    if known_count == 0:
        print(f'error: 未找到本套件 agent 文件（roles 映射零命中）: {agents_dir}',
              file=sys.stderr)
        return 1
    if failed_count:
        print(f'warning: {failed_count} 个 agent 未重写（详见上方提示）', file=sys.stderr)
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description='BudgetBuddy model resolver（模型解析与 agent frontmatter 重写）')
    parser.add_argument('--models', required=True, help='budget-models.json 路径')
    sub = parser.add_subparsers(dest='action', required=True)

    p_resolve = sub.add_parser('resolve', help='解析别名/ID → 平台最终 model 值')
    p_resolve.add_argument('--input', required=True, help='输入（别名/裸 ID/provider-model）')
    # --platform 接受任意值，main 入口按 budget-models.json platforms 键集
    # 校验（数据驱动，与 build.py 构建期 glob 双清单一致性校验呼应）
    p_resolve.add_argument('--platform', required=True)
    p_resolve.add_argument('--custom', action='store_true',
                           help='自定义覆写模式：未知模型 ID 原样返回（支持第三方模型）')

    p_preset = sub.add_parser('preset', help='预设档位查询（agent=模型 行）')
    p_preset.add_argument('--name', required=True, help='预设名')
    p_preset.add_argument('--platform', required=True)

    p_list = sub.add_parser('list-presets', help='列出平台全部预设明细')
    p_list.add_argument('--platform', required=True)

    p_current = sub.add_parser('current', help='当前 agent model 值查询（agent=模型 行）')
    p_current.add_argument('--agents-dir', required=True, help='agent 目录路径')

    p_rewrite = sub.add_parser('rewrite', help='批量重写 agent frontmatter model 字段')
    p_rewrite.add_argument('--agents-dir', required=True, help='agent 目录路径')
    p_rewrite.add_argument('--platform', required=True)
    p_rewrite.add_argument('--mode', required=True, choices=('preset', 'custom', 'inherit'),
                           help='重写模式')
    p_rewrite.add_argument('--preset', default='', help='预设名（mode=preset 时必填）')
    p_rewrite.add_argument('--model', default='', help='模型值（mode=custom 时必填）')

    args = parser.parse_args()
    data = load_json(args.models)

    # 平台校验（数据驱动：携带 --platform 的子命令统一校验，未知值报错并列出
    # 可用平台——与 build.py「未知 --platform 值显式报错」口径一致）
    if getattr(args, 'platform', None) is not None:
        error = validate_platform(data, args.platform)
        if error:
            print(f'error: {error}', file=sys.stderr)
            sys.exit(1)

    if args.action == 'resolve':
        value, error = resolve_model(args.input, args.platform, data,
                                     custom=getattr(args, 'custom', False))
        if error:
            print(f'error: {error}', file=sys.stderr)
            sys.exit(2)
        print(value)
    elif args.action == 'preset':
        lines, error = get_preset_lines(data, args.platform, args.name)
        if error:
            print(f'error: {error}', file=sys.stderr)
            sys.exit(1)
        print('\n'.join(lines))
    elif args.action == 'list-presets':
        text, error = list_presets_text(data, args.platform)
        if error:
            print(f'error: {error}', file=sys.stderr)
            sys.exit(1)
        print(text)
    elif args.action == 'current':
        lines, error = get_current_lines(args.agents_dir, data.get('roles', []))
        if error:
            print(f'error: {error}', file=sys.stderr)
            sys.exit(1)
        if lines:
            print('\n'.join(lines))
    elif args.action == 'rewrite':
        sys.exit(cmd_rewrite(data, args))


if __name__ == '__main__':
    main()
