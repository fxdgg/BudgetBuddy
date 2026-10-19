#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy settings.json hooks 注入引擎（design.md §9/§12-A11；specs/notify R5）。

由 lib/hooks.sh 编排调用（参数一律经环境变量传递，不经命令行）：
  SETTINGS_FILE - CodeBuddy settings.json 路径
  HOOK_CMD      - hook 命令串（含 budget-notify-hook.py 实际路径）

Actions（ACTION 环境变量）：
  check              - 查询 superpowers 插件启用状态（stdout: true/false）
  check_hooks        - 查询注入状态（stdout: 单行 JSON，hooks/superpowers 两键）
  inject_all         - superpowers 插件 + 三事件 hooks 一次注入（幂等）
  inject_superpowers - 仅注入 superpowers 插件（幂等）
  inject_hooks       - 仅注入三事件 hooks（幂等）
  remove_hooks       - 移除本套件全部注入项（保留用户已有内容）

写入纪律（specs/notify「CodeBuddy hooks 三事件通知」）：
  - 注入前备份 settings.json.bak-budget：备份内容与当前一致时跳过；
    当前已含本套件痕迹时不覆盖原始备份（保护恢复点）
  - 临时文件 + 原子 rename 写入
  - 解析失败不写回（stderr 报错 exit 1，原文件保持原样）
  - 键序保持：json.load 依文件序解析（dict 保序），注入项追加，dump 不排序
  - 移除精确到 hook 条目级（仅删 command 含 budget-notify-hook.py 的条目），
    用户在同一 matcher 下的自有 hooks 保留
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

# 本套件注入项识别标记（幂等判定与移除精确定位的共同基准）
HOOK_MARKER = 'budget-notify-hook.py'
SUPERPOWERS_KEY = 'superpowers@codebuddy-plugins-official'
BACKUP_SUFFIX = '.bak-budget'
HOOK_TIMEOUT_SECONDS = 10

# 三事件注入形态（design.md §9）：
#   Notification - permission_prompt / idle_prompt 两 matcher
#   PreToolUse   - Bash matcher（沙箱越权命令通知）
#   SubagentStop - 无 matcher（子代理完成通知）
NOTIFICATION_MATCHERS = ('permission_prompt', 'idle_prompt')
PRETOOLUSE_MATCHER = 'Bash'


def _out(line: str) -> None:
    print(line)


def _fail(message: str) -> None:
    print(f'error: {message}', file=sys.stderr)


def _settings_path() -> str:
    path = os.environ.get('SETTINGS_FILE', '')
    if not path:
        _fail('SETTINGS_FILE 环境变量未设置')
        sys.exit(1)
    return path


def _require_hook_cmd() -> str:
    hook_cmd = os.environ.get('HOOK_CMD', '')
    if not hook_cmd:
        _fail('HOOK_CMD 环境变量未设置')
        sys.exit(1)
    return hook_cmd


def _dump(data: dict) -> str:
    """序列化（保持键序：sort_keys 缺省 False，注入项追加在既有键之后）。"""
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def _atomic_write(path: str, content: str | bytes) -> None:
    """临时文件 + 原子 rename 写入（specs/notify R5；失败不产生半成品）。"""
    dir_name = os.path.dirname(path) or '.'
    fd, tmp_path = tempfile.mkstemp(prefix='.settings-', suffix='.tmp', dir=dir_name)
    try:
        if isinstance(content, bytes):
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(content)
                tmp.flush()
                os.fsync(tmp.fileno())
        else:
            with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
                tmp.write(content)
                tmp.flush()
                os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _load_settings(path: str) -> tuple[dict | None, bool]:
    """严格读取（写操作用）：解析失败报错 exit 1，原文件不写回保持原样。"""
    if not os.path.isfile(path):
        return None, False
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        _fail(f'settings.json 解析失败: {path}（{type(exc).__name__}；原文件未修改）')
        sys.exit(1)
    if not isinstance(data, dict):
        _fail(f'settings.json 顶层必须是 JSON 对象: {path}（原文件未修改）')
        sys.exit(1)
    return data, True


def _load_lenient(path: str) -> dict | None:
    """容错读取（查询操作用）：缺失/解析失败/非对象 → None，不报错退出。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _iter_hook_entries(data: dict):
    """遍历 (matcher, hook) 全部 hook 条目（结构非法的节点跳过）。"""
    hooks = data.get('hooks')
    if not isinstance(hooks, dict):
        return
    for matchers in hooks.values():
        if not isinstance(matchers, list):
            continue
        for matcher in matchers:
            if not isinstance(matcher, dict):
                continue
            hook_list = matcher.get('hooks')
            if not isinstance(hook_list, list):
                continue
            for hook in hook_list:
                yield matcher, hook


def _is_suite_hook(hook: object) -> bool:
    """hook 条目是否为本套件注入项（command 含 budget-notify-hook.py）。"""
    return isinstance(hook, dict) and HOOK_MARKER in str(hook.get('command', ''))


def _has_suite_hook_entries(data: dict) -> bool:
    """是否存在本套件 hook 条目（任一事件下命中即真）。"""
    return any(_is_suite_hook(hook) for _, hook in _iter_hook_entries(data))


def _is_superpowers_enabled(data: dict) -> bool:
    """superpowers 插件是否已启用（enabledPlugins 键值为 true）。"""
    plugins = data.get('enabledPlugins')
    return isinstance(plugins, dict) and plugins.get(SUPERPOWERS_KEY) is True


def _has_suite_marks(data: dict) -> bool:
    """当前 settings 是否已含本套件痕迹（superpowers 键或任一 hook 条目）。"""
    return _is_superpowers_enabled(data) or _has_suite_hook_entries(data)


def _backup_before_inject(path: str) -> bool:
    """注入前备份磁盘原始内容（specs/notify R5「注入前备份」Scenario）。

    备份注入前的磁盘字节（保留用户原始格式，恢复点语义精确）。
    返回是否执行了备份写入：
    - 文件不存在 → 无可备份，跳过
    - 备份内容与当前磁盘内容一致 → 跳过（任务约定：不重复备份）
    - 不一致且当前含本套件痕迹 → 跳过（不覆盖原始恢复点）
    - 不一致且当前干净 → 重备份（用户在干净状态上修改过，保存最新干净态）
    """
    if not os.path.isfile(path):
        return False
    try:
        with open(path, 'rb') as handle:
            current_bytes = handle.read()
    except OSError:
        return False
    backup = path + BACKUP_SUFFIX
    if os.path.isfile(backup):
        try:
            with open(backup, 'rb') as handle:
                existing_bytes = handle.read()
        except OSError:
            existing_bytes = None
        if existing_bytes == current_bytes:
            return False
        data = _load_lenient(path)
        if data is None or _has_suite_marks(data):
            return False
    _atomic_write(backup, current_bytes)
    return True


def _event_has_suite(data: dict, event_name: str) -> bool:
    """指定事件下是否已有本套件 hook 条目（事件级幂等判定）。"""
    hooks = data.get('hooks')
    if not isinstance(hooks, dict):
        return False
    matchers = hooks.get(event_name)
    if not isinstance(matchers, list):
        return False
    for matcher in matchers:
        if not isinstance(matcher, dict):
            continue
        hook_list = matcher.get('hooks')
        if not isinstance(hook_list, list):
            continue
        if any(_is_suite_hook(hook) for hook in hook_list):
            return True
    return False


def _append_matcher(data: dict, event_name: str, entry: dict) -> None:
    """向事件列表追加 matcher 条目（事件列表不存在时创建；注入项追加在尾部）。"""
    hooks = data.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        return
    matchers = hooks.get(event_name)
    if not isinstance(matchers, list):
        matchers = []
        hooks[event_name] = matchers
    matchers.append(entry)


def _command_entry(hook_cmd: str) -> dict:
    return {'type': 'command', 'command': hook_cmd, 'timeout': HOOK_TIMEOUT_SECONDS}


def _inject_hook_entries(data: dict, hook_cmd: str) -> bool:
    """注入三事件 hooks（事件级幂等：该事件已有本套件条目则跳过该事件）。"""
    if not isinstance(data.get('hooks'), dict) and 'hooks' in data:
        return False  # hooks 节点被用户写成非对象 → 不动（不破坏用户结构）
    changed = False
    if not _event_has_suite(data, 'Notification'):
        for matcher_name in NOTIFICATION_MATCHERS:
            _append_matcher(data, 'Notification', {
                'matcher': matcher_name, 'hooks': [_command_entry(hook_cmd)],
            })
        changed = True
    if not _event_has_suite(data, 'PreToolUse'):
        _append_matcher(data, 'PreToolUse', {
            'matcher': PRETOOLUSE_MATCHER, 'hooks': [_command_entry(hook_cmd)],
        })
        changed = True
    if not _event_has_suite(data, 'SubagentStop'):
        _append_matcher(data, 'SubagentStop', {
            'hooks': [_command_entry(hook_cmd)],
        })
        changed = True
    return changed


def _inject_superpowers_entry(data: dict) -> bool:
    """注入 superpowers 插件（幂等；enabledPlugins 非对象时不破坏用户结构）。"""
    if _is_superpowers_enabled(data):
        return False
    plugins = data.get('enabledPlugins')
    if plugins is None:
        data['enabledPlugins'] = {}
        plugins = data['enabledPlugins']
    if not isinstance(plugins, dict):
        return False
    plugins[SUPERPOWERS_KEY] = True
    return True


def _remove_suite_entries(data: dict) -> bool:
    """移除本套件注入项（hook 条目级精确删除 + superpowers 键；保留用户内容）。

    - matcher 的 hooks 列表仅剔除本套件条目；剔后非空则保留该 matcher
    - matcher 剔后 hooks 为空 → 丢弃该 matcher；事件列表空 → 删除事件键
    - hooks 节点空 → 删除 hooks 键；enabledPlugins 剔后空 → 删除该键
    """
    changed = False
    hooks = data.get('hooks')
    if isinstance(hooks, dict):
        hooks_touched = False
        for event_name in list(hooks.keys()):
            matchers = hooks[event_name]
            if not isinstance(matchers, list):
                continue
            kept_matchers = []
            for matcher in matchers:
                if not isinstance(matcher, dict):
                    kept_matchers.append(matcher)
                    continue
                hook_list = matcher.get('hooks')
                if not isinstance(hook_list, list):
                    kept_matchers.append(matcher)
                    continue
                kept_hooks = [hook for hook in hook_list if not _is_suite_hook(hook)]
                if kept_hooks:
                    if len(kept_hooks) != len(hook_list):
                        matcher['hooks'] = kept_hooks
                        hooks_touched = True
                    kept_matchers.append(matcher)
                else:
                    hooks_touched = True  # matcher 的 hooks 全为本套件 → 丢弃
            if kept_matchers:
                if len(kept_matchers) != len(matchers):
                    hooks[event_name] = kept_matchers
            else:
                del hooks[event_name]
                hooks_touched = True
        if hooks_touched and not hooks:
            del data['hooks']
        changed = changed or hooks_touched

    plugins = data.get('enabledPlugins')
    if isinstance(plugins, dict) and SUPERPOWERS_KEY in plugins:
        del plugins[SUPERPOWERS_KEY]
        if not plugins:
            del data['enabledPlugins']
        changed = True
    return changed


# ─── Actions ─────────────────────────────────────────────────────────────


def action_check() -> None:
    """查询 superpowers 插件启用状态（容错：损坏文件按未启用处理）。"""
    data = _load_lenient(os.environ.get('SETTINGS_FILE', ''))
    _out('true' if data and _is_superpowers_enabled(data) else 'false')


def action_check_hooks() -> None:
    """查询注入状态（单行 JSON：hooks/superpowers 两键，容错读取）。"""
    data = _load_lenient(os.environ.get('SETTINGS_FILE', ''))
    result = {
        'hooks': bool(data) and _has_suite_hook_entries(data),
        'superpowers': bool(data) and _is_superpowers_enabled(data),
    }
    _out(json.dumps(result, sort_keys=True))


def _write_injection(path: str, data: dict, changed: bool) -> None:
    """注入类写回：有变更 → 备份 + 原子写（输出 injected）；无变更 → no_change。"""
    if not changed:
        _out('no_change')
        return
    _backup_before_inject(path)
    _atomic_write(path, _dump(data))
    _out('injected')


def action_inject_all() -> None:
    """superpowers 插件 + 三事件 hooks 一次注入（单次读改写，备份只落一次）。"""
    path = _settings_path()
    hook_cmd = _require_hook_cmd()
    data, _ = _load_settings(path)
    if data is None:
        data = {}
    changed = _inject_superpowers_entry(data)
    changed = _inject_hook_entries(data, hook_cmd) or changed
    _write_injection(path, data, changed)


def action_inject_superpowers() -> None:
    """仅注入 superpowers 插件（安装器单独启用插件的复用入口）。"""
    path = _settings_path()
    data, _ = _load_settings(path)
    if data is None:
        data = {}
    _write_injection(path, data, _inject_superpowers_entry(data))


def action_inject_hooks() -> None:
    """仅注入三事件 hooks。"""
    path = _settings_path()
    hook_cmd = _require_hook_cmd()
    data, _ = _load_settings(path)
    if data is None:
        data = {}
    _write_injection(path, data, _inject_hook_entries(data, hook_cmd))


def action_remove_hooks() -> None:
    """移除本套件注入项（不备份：保留 inject 前的原始恢复点不被覆盖）。"""
    path = _settings_path()
    data, exists = _load_settings(path)
    if not exists or data is None:
        _out('no_change')
        return
    if not _remove_suite_entries(data):
        _out('no_change')
        return
    if data:
        _atomic_write(path, _dump(data))
    else:
        # 移除后为空对象 → 删除文件（恢复本套件创建前的「不存在」状态）
        try:
            os.unlink(path)
        except OSError as exc:
            _fail(f'settings.json 删除失败: {type(exc).__name__}')
            sys.exit(1)
    _out('removed')


ACTIONS = {
    'check': action_check,
    'check_hooks': action_check_hooks,
    'inject_all': action_inject_all,
    'inject_superpowers': action_inject_superpowers,
    'inject_hooks': action_inject_hooks,
    'remove_hooks': action_remove_hooks,
}


def main() -> None:
    action = os.environ.get('ACTION', '')
    if not action:
        _fail('ACTION 环境变量未设置；可用: ' + ', '.join(sorted(ACTIONS)))
        sys.exit(1)
    handler = ACTIONS.get(action)
    if handler is None:
        _fail(f'未知 ACTION: {action}；可用: ' + ', '.join(sorted(ACTIONS)))
        sys.exit(1)
    try:
        handler()
    except SystemExit:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        # 兜底：任何内部错误仅记录异常类型名，不写回 settings.json
        _fail(f'内部错误: {type(exc).__name__}')
        sys.exit(1)


if __name__ == '__main__':
    main()
