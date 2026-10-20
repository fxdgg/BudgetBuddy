#!/bin/bash
# budget-notify — 通知环境加载脚本（非敏感变量导出）
# 用法: eval "$(bash <skill 安装目录>/load-env.sh)"
# 定位生效配置文件（项目级 .budget/notify.json > 全局 ~/.budgetbuddy/notify.json，
# 双级降级不合并），仅导出非敏感变量：
#   BUDGET_NOTIFY_ENABLED — 生效配置的 enabled 值（"1"/"0"；无配置时 "0"）
#   BUDGET_NOTIFY_CONFIG — 生效配置文件绝对路径（无配置时不导出）
# 敏感字段（webhook/secret）一律不经环境变量传递。

# 定位生效配置文件：项目级 > 全局（不合并，先到先得）。
NOTIFY_FILE=""
if [[ -f ".budget/notify.json" ]]; then
    NOTIFY_FILE=".budget/notify.json"
elif [[ -f "$HOME/.budgetbuddy/notify.json" ]]; then
    NOTIFY_FILE="$HOME/.budgetbuddy/notify.json"
fi

# 无配置或 python3 缺失：仅导出 ENABLED=0（供 Leader 快速短路），exit 0。
if [[ -z "$NOTIFY_FILE" ]] || ! command -v python3 >/dev/null 2>&1; then
    echo 'export BUDGET_NOTIFY_ENABLED=0'
    exit 0
fi

# python3 解析 enabled 值并输出非敏感 export 语句：路径经 shlex.quote 转义
# （eval 安全）；解析失败按无配置处理（ENABLED=0）。任何失败均静默 exit 0。
python3 - "$NOTIFY_FILE" <<'PYEOF'
import json
import os
import shlex
import sys

path = sys.argv[1]
try:
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
except (OSError, ValueError):
    print('export BUDGET_NOTIFY_ENABLED=0')
    sys.exit(0)

enabled = 1 if isinstance(data, dict) and data.get('enabled') is True else 0
print(f'export BUDGET_NOTIFY_ENABLED={enabled}')
print(f'export BUDGET_NOTIFY_CONFIG={shlex.quote(os.path.abspath(path))}')
PYEOF

exit 0
