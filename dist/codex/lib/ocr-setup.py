#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BudgetBuddy OCR 预审集成管理 — budget setup ocr（agent 集成 design.md D8）。

OCR 机器预审（OpenCodeReview `ocr` CLI）的安装与状态检测子命令：检测 CLI、
检测模型配置、把项目规范规则模板安装到 OCR 全局层 `~/.opencodereview/rule.json`，
并输出降级语义说明。非门禁——未装 CLI / 未装规则时 BudgetBuddy 审查全流程照常。

行为（design.md D8 / specs/setup-cli/spec.md「budget setup ocr 子命令」）：
    ① CLI 检测：`command -v ocr`（shutil.which）；缺失时输出安装指引
       （npm i -g @alibaba-group/open-code-review），不阻断，继续后续步骤。
    ② 模型配置检测（存在 ocr 时）：环境变量 OCR_LLM_URL/OCR_LLM_TOKEN/OCR_LLM_MODEL
       或 ~/.opencodereview/ 配置文件任一命中即视为已配置；未命中输出
       「delegate 模式可忽略」提示、不阻断、退出码 0。
    ③ 规则模板安装：模板定位优先 ocr-setup.py __file__ 同目录的 ocr-rule.json
       （BUDGET_LIB_DIR 环境变量显式覆盖；两者均无模板 → 报错提示模块未安装并
       指引 budget setup update，非零退出）。目标 ~/.opencodereview/rule.json：
       目录不存在时 os.makedirs 创建（权限失败非零退出提示手动创建）；目标不存在
       则写入 / 内容相同幂等 no-op / 内容不同先备份（默认 rule.json.bak，.bak 已
       存在时改用时间戳后缀 rule.json.bak.<YYYYMMDDHHMMSS>，不覆盖既有备份）+
       差异展示 + 确认后覆盖；stdin 非 TTY 的非交互环境默认跳过覆盖、输出手动路径、
       退出码 0。写文件用同目录临时文件原子写（tempfile.mkstemp + os.replace，
       对齐 core/lib/autorun.py _atomic_write 先例）。
    ④ 降级语义输出：结尾说明未装 CLI / 未装规则时 BudgetBuddy 全流程照常。

平台无关：不依赖 codebuddy 安装态、不写 agent 文件、不写平台状态文件；无
detect_platform 逻辑，codebuddy/opencode/claudecode/codex 四形态行为一致。

环境变量：
    OCR_LLM_URL / OCR_LLM_TOKEN / OCR_LLM_MODEL（模型配置检测，仅判断存在性、
        不回显值，凭据纪律）
    BUDGET_LIB_DIR（规则模板目录显式覆盖，setup.sh 注入形态）

退出码：0 成功（含 CLI 缺失 / 模型配置未检出 / 非交互跳过覆盖等降级场景）；
1 错误（模板源缺失 / 目录创建失败 / 备份失败 / 写入失败）。
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import sys
import tempfile
from datetime import datetime
from typing import Callable

# ─── 常量 ─────────────────────────────────────────────────────────────────────

# 规则模板文件名（与 ocr-setup.py 同目录，经 _build_lib 字节平移分发，D8）
RULE_TEMPLATE_NAME = 'ocr-rule.json'

# OCR 全局层目标路径（相对 HOME）
TARGET_RELPATH = ('.opencodereview', 'rule.json')

# 备份文件名（目标同目录；.bak 已存在时改用时间戳后缀）
BACKUP_NAME = 'rule.json.bak'

# 备份时间戳后缀格式（YYYYMMDDHHMMSS）
BACKUP_TS_FORMAT = '%Y%m%d%H%M%S'

# CLI 安装指引（缺失时不阻断）
INSTALL_GUIDANCE = 'npm i -g @alibaba-group/open-code-review'

# 模型配置检测环境变量（仅判断存在性，不回显值）
MODEL_ENV_KEYS = ('OCR_LLM_URL', 'OCR_LLM_TOKEN', 'OCR_LLM_MODEL')

# ─── 模板 / 目标路径解析（可注入，便于单测 mock）───────────────────────────────


def resolve_template_path(template_path: str | None = None) -> str | None:
    """定位规则模板（design D8）。

    显式 template_path 权威：不存在即返回 None、不回退（供单测注入「模板缺失」）；
    否则 BUDGET_LIB_DIR 优先，其次 __file__ 同目录，两者均无 → None。
    """
    if template_path is not None:
        return template_path if os.path.isfile(template_path) else None
    candidates = []
    lib_dir = os.environ.get('BUDGET_LIB_DIR', '')
    if lib_dir:
        candidates.append(os.path.join(lib_dir, RULE_TEMPLATE_NAME))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), RULE_TEMPLATE_NAME))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def resolve_target_path(target_path: str | None = None) -> str:
    """目标路径：显式 target_path 优先，否则 ~/.opencodereview/rule.json。"""
    if target_path is not None:
        return target_path
    return os.path.join(os.path.expanduser('~'), *TARGET_RELPATH)

# ─── CLI / 模型配置检测 ───────────────────────────────────────────────────────


def check_model_config(home_dir: str | None = None) -> bool:
    """检测模型配置可用性（design D8）：环境变量三键任一命中，或 ~/.opencodereview/
    存在配置文件（任一非规则文件）即视为已配置。

    仅判断存在性，不回显任何值（凭据纪律）；排除本命令自装的 rule.json 与备份文件，
    避免重装后把规则文件误判为模型配置。
    """
    if any(os.environ.get(key) for key in MODEL_ENV_KEYS):
        return True
    config_dir = os.path.join(home_dir or os.path.expanduser('~'), '.opencodereview')
    if not os.path.isdir(config_dir):
        return False
    try:
        entries = os.listdir(config_dir)
    except OSError:
        return False
    for entry in entries:
        if entry == 'rule.json' or entry.startswith('rule.json.'):
            continue
        if os.path.isfile(os.path.join(config_dir, entry)):
            return True
    return False

# ─── 文件读写与原子写（对齐 autorun.py _atomic_write 先例）────────────────────


def _read_file(path: str) -> str | None:
    """读取文件全文；缺失或读取失败返回 None。"""
    try:
        with open(path, encoding='utf-8') as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def _atomic_write(path: str, content: str) -> None:
    """同目录临时文件原子写（mkstemp + os.replace），保留原文件权限位。"""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(prefix='.ocr-', dir=directory)
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

# ─── 备份 / 差异展示 / 交互确认 ────────────────────────────────────────────────


def compute_backup_path(target_path: str) -> str:
    """计算备份路径：默认 rule.json.bak；.bak 已存在时改用时间戳后缀
    rule.json.bak.<YYYYMMDDHHMMSS>（不覆盖任何既有备份）。"""
    directory = os.path.dirname(target_path)
    default = os.path.join(directory, BACKUP_NAME)
    if not os.path.exists(default):
        return default
    ts = datetime.now().strftime(BACKUP_TS_FORMAT)
    return f'{default}.{ts}'


def print_diff(old_content: str, new_content: str) -> None:
    """明示差异摘要（difflib unified_diff）。"""
    diff = list(difflib.unified_diff(
        old_content.splitlines(), new_content.splitlines(),
        fromfile='当前 rule.json', tofile='新模板', lineterm=''))
    if not diff:
        print('  （差异无法逐行展示，将以模板整体覆盖）')
        return
    for line in diff:
        print(line)


def interactive_confirm(prompt: str) -> bool:
    """交互确认：读取 stdin，y/yes 视为覆盖；EOF/其他视为保持原文件。"""
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in ('y', 'yes')

# ─── 规则模板安装（design D8 / spec「budget setup ocr 子命令」③）──────────────


def install_rules(template_path: str, target_path: str, *,
                  confirm: Callable[[str], bool] | None = None,
                  is_tty: bool | None = None) -> int:
    """安装规则模板到目标。

    目标不存在 → 写入；内容相同 → 幂等 no-op（不重写）；内容不同 → 备份 + 差异
    展示 + 确认后覆盖（取消保持原文件；非交互默认跳过覆盖）。返回退出码。
    """
    template_content = _read_file(template_path)
    if template_content is None:
        print(f'error: 无法读取规则模板: {template_path}', file=sys.stderr)
        return 1

    target_dir = os.path.dirname(os.path.abspath(target_path))
    if not os.path.isdir(target_dir):
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as exc:
            print(f'error: 无法创建目标目录 {target_dir}: {exc}', file=sys.stderr)
            print('提示：请手动创建该目录后重试，或检查目录写权限。', file=sys.stderr)
            return 1

    target_content = _read_file(target_path)
    if target_content is None:
        try:
            _atomic_write(target_path, template_content)
        except OSError as exc:
            print(f'error: 规则安装写入失败: {exc}', file=sys.stderr)
            return 1
        print(f'[✓] 规则已安装: {target_path}')
        return 0

    if target_content == template_content:
        print(f'[i] 规则已是最新（幂等 no-op，不重写）: {target_path}')
        return 0

    print(f'[!] 目标规则与模板内容不同: {target_path}')
    print_diff(target_content, template_content)

    if confirm is not None:
        answer = bool(confirm('确认以模板覆盖现有规则？[y/N] '))
    else:
        tty = sys.stdin.isatty() if is_tty is None else is_tty
        if not tty:
            print('[i] 非交互环境（stdin 非 TTY），默认跳过覆盖，保持现有规则。')
            print(f'  如需更新，可手动将模板写入 {target_path}（模板: {template_path}）。')
            return 0
        answer = interactive_confirm('确认以模板覆盖现有规则？[y/N] ')

    if not answer:
        print('[i] 已取消，保持现有规则不变。')
        return 0

    backup = compute_backup_path(target_path)
    try:
        shutil.copyfile(target_path, backup)
    except OSError as exc:
        print(f'error: 备份现有规则失败（中止覆盖，不修改原文件）: {exc}', file=sys.stderr)
        return 1
    try:
        _atomic_write(target_path, template_content)
    except OSError as exc:
        print(f'error: 规则覆盖写入失败: {exc}', file=sys.stderr)
        return 1
    print(f'[✓] 已备份现有规则至 {backup}')
    print(f'[✓] 规则已更新: {target_path}')
    return 0

# ─── main ────────────────────────────────────────────────────────────────────


def main(argv: list | None = None, *,
         confirm: Callable[[str], bool] | None = None,
         is_tty: bool | None = None,
         template_path: str | None = None,
         target_path: str | None = None) -> int:
    """入口：CLI 检测 → 模型配置检测 → 规则模板安装 → 降级语义输出。"""
    parser = argparse.ArgumentParser(
        prog='budget setup ocr',
        description='OCR 预审集成安装与状态检测（非门禁，未安装不阻断 BudgetBuddy 全流程）')
    parser.parse_args(argv)

    cli = shutil.which('ocr')
    if cli is None:
        print('[i] 未检测到 OCR CLI（command -v ocr 失败）。')
        print(f'  安装指引: {INSTALL_GUIDANCE}')
        print('  未安装 CLI 时 BudgetBuddy 审查全流程照常（预审步骤静默跳过）。')
    else:
        print(f'[i] 检测到 OCR CLI: {cli}')
        if check_model_config():
            print('[i] 检测到模型配置（环境变量或 ~/.opencodereview/ 配置文件）。')
        else:
            print('[i] 未检测到模型配置（OCR_LLM_URL/OCR_LLM_TOKEN/OCR_LLM_MODEL '
                  '与 ~/.opencodereview/ 配置文件均未命中）。')
            print('  若使用 delegate 模式可忽略此提示（委托评审无需额外 key）。')

    template = resolve_template_path(template_path)
    if template is None:
        print('error: 未找到规则模板 ocr-rule.json（模块未安装或安装不完整）。', file=sys.stderr)
        print('提示：请运行 budget setup update 更新安装后重试。', file=sys.stderr)
        return 1

    target = resolve_target_path(target_path)
    rc = install_rules(template, target, confirm=confirm, is_tty=is_tty)
    if rc != 0:
        return rc

    print()
    print('[i] 降级语义：OCR 预审为可选增强，未安装 CLI 或未安装规则时，'
          'BudgetBuddy 审查全流程照常运行（reviewer/reviewer-b 均会静默降级）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
