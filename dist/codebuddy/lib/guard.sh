#!/bin/bash
# BudgetBuddy Coder Guard 护栏（design.md §8.2/§8.4/§12-A14）
#
# Provides:
#   guard_query [coder] [tag...]   查询最近记录与降级建议
#   guard_append --coder <c> --result <success|failure> [--tags <t,...>]
#                                  追加成功/失败记录（history + summary 同步）
#                                  [--escalated-to <level>]
#   guard_summary                  汇总统计（coder × tag 计数与成功率）
#   guard_reset                    重置记录（清空 history / summary）
#   setup_guard [query|append|summary|reset] ...   setup.sh guard 子命令分发入口
#
# Dependencies（setup.sh source 基础层后分发调用）:
#   colors.sh   - budget_print_success / budget_print_info / budget_print_error
#   BUDGET_PYTHON（setup.sh 顶层导出；独立 source 时回退 python3）
#
# 语义（A14）：仅承担失败记录与分级降级（history + summary）；任务范围审计
# （修改文件清单 vs 文件范围）由 reviewer 在 Phase 3 与 phases.md 4.3 承担，
# 本模块不做范围审计。
#
# 记录文件（固定全局路径，跨会话汇总，design.md §8.4）：
#   $HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json
#   project-name = git 根目录名（git rev-parse --show-toplevel 优先，无 git
#   退 basename "$PWD"）
#
# 记录结构：
#   history: [{timestamp, coder, tags, result, escalated_to}]
#   summary: {<coder>: {<tag>: {total, success, failure}}}
#
# 降级规则（router.md Step 2 / SKILL.md P0 coder-guard）：
#   最近 5 次窗口内失败 >= 2 → 触发降级保护，改派更高级 coder
#   （coder-lite → coder-standard → coder-senior；senior 已最高 → 建议
#   Director 介入）
#   连续失败 3 次 → 建议 Director 介入（3 轮全败语义，router.md 应急处理）

# ─── 路径解析 ────────────────────────────────────────────────────────────

# project-name：git 根目录名优先，无 git 退当前目录名
guard_project_name() {
    local root
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    if [[ -n "$root" ]]; then
        basename "$root"
    else
        basename "$PWD"
    fi
}

# 记录文件路径（固定全局路径，design.md §8.4）
guard_file_path() {
    echo "$HOME/.budgetbuddy/projects/$(guard_project_name)/memory/coder-guard.json"
}

# ─── 追加记录 ────────────────────────────────────────────────────────────

guard_append() {
    local coder="" tags="" result="" escalated_to=""
    while [[ $# -gt 0 ]]; do
        local key="$1"
        local value="${2:-}"
        case "$key" in
            --coder)        coder="$value" ;;
            --tags)         tags="$value" ;;
            --result)       result="$value" ;;
            --escalated-to) escalated_to="$value" ;;
            *)
                budget_print_error "guard_append 未知参数: $key"
                return 1
                ;;
        esac
        # 成对消费：缺值时报用法错误（防 shift 越界死循环）
        if [[ $# -lt 2 ]]; then
            budget_print_error "参数 $key 缺少值"
            return 1
        fi
        shift 2
    done
    if [[ -z "$coder" || -z "$result" ]]; then
        budget_print_error "用法: guard_append --coder <coder> --result <success|failure> [--tags <tag,...>] [--escalated-to <level>]"
        return 1
    fi
    if [[ "$result" != "success" && "$result" != "failure" ]]; then
        budget_print_error "--result 仅支持 success/failure，收到: $result"
        return 1
    fi

    local guard_file
    guard_file="$(guard_file_path)"
    mkdir -p "$(dirname "$guard_file")"

    BUDGET_GUARD_FILE="$guard_file" \
    BUDGET_GUARD_CODER="$coder" \
    BUDGET_GUARD_TAGS="$tags" \
    BUDGET_GUARD_RESULT="$result" \
    BUDGET_GUARD_ESCALATED_TO="$escalated_to" \
        "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os
from datetime import datetime, timezone

guard_file = os.environ['BUDGET_GUARD_FILE']
coder = os.environ['BUDGET_GUARD_CODER']
raw_tags = os.environ.get('BUDGET_GUARD_TAGS', '')
result = os.environ['BUDGET_GUARD_RESULT']
escalated_to = os.environ.get('BUDGET_GUARD_ESCALATED_TO') or None

tags = [tag.strip() for tag in raw_tags.split(',') if tag.strip()]

# 读取已有记录（缺失/损坏时归一为空结构，不阻断追加）
data = {'history': [], 'summary': {}}
if os.path.isfile(guard_file):
    try:
        with open(guard_file, encoding='utf-8') as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {'history': [], 'summary': {}}
if not isinstance(data.get('history'), list):
    data['history'] = []
if not isinstance(data.get('summary'), dict):
    data['summary'] = {}

data['history'].append({
    'coder': coder,
    'escalated_to': escalated_to,
    'result': result,
    'tags': tags,
    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
})

# summary 计数同步（无标签记录不归桶，仅入 history）
if tags:
    coder_stats = data['summary'].setdefault(coder, {})
    for tag in tags:
        stats = coder_stats.setdefault(tag, {'failure': 0, 'success': 0, 'total': 0})
        stats['total'] = stats.get('total', 0) + 1
        if result == 'success':
            stats['success'] = stats.get('success', 0) + 1
        else:
            stats['failure'] = stats.get('failure', 0) + 1

# 原子写（临时文件 + replace，防写一半损坏；键排序幂等）
tmp_path = guard_file + '.tmp'
with open(tmp_path, 'w', encoding='utf-8') as handle:
    json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
    handle.write('\n')
os.replace(tmp_path, guard_file)

print(json.dumps({
    'coder': coder,
    'path': guard_file,
    'result': result,
    'status': 'ok',
    'tags': tags,
}, ensure_ascii=False, sort_keys=True))
PYEOF
}

# ─── 保鲜与置信（读取时加权统计，design D4；子进程失败静默跳过）──────────

# 定位 guard_metrics.py（guard.sh 同目录优先，BUDGET_LIB_DIR 兜底）
_guard_metrics_path() {
    local lib_dir
    lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
    if [[ -n "$lib_dir" && -f "$lib_dir/guard_metrics.py" ]]; then
        echo "$lib_dir/guard_metrics.py"
        return 0
    fi
    if [[ -n "${BUDGET_LIB_DIR:-}" && -f "$BUDGET_LIB_DIR/guard_metrics.py" ]]; then
        echo "$BUDGET_LIB_DIR/guard_metrics.py"
        return 0
    fi
    return 1
}

# 渲染保鲜段（JSON 经环境变量传入，内嵌 python 解析渲染中文；single=判定
# 模式单组合，list=概览/summary 的 per-coder 列表）。JSON 坏则静默跳过。
_guard_render_metrics() {
    local mode="$1" json_in="$2"
    BUDGET_GUARD_METRICS_MODE="$mode" \
    BUDGET_GUARD_METRICS_JSON="$json_in" \
        "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os
import sys

mode = os.environ.get('BUDGET_GUARD_METRICS_MODE', 'single')
raw = os.environ.get('BUDGET_GUARD_METRICS_JSON', '')
try:
    data = json.loads(raw)
except ValueError:
    raise SystemExit(0)
if not isinstance(data, dict):
    raise SystemExit(0)

conf_label = {'low': '低', 'medium': '中', 'high': '高'}

def label(value):
    return conf_label.get(value, str(value))

def stale_label(flag):
    return '是' if flag else '否'

if mode == 'single':
    n_eff = data.get('n_eff', 0.0)
    half_life = data.get('half_life_days', 30)
    print('保鲜: n_eff=%.2f（半衰期 %gd）' % (n_eff, half_life))
    print('置信: %s' % label(data.get('confidence', 'low')))
    print('陈旧: %s' % stale_label(data.get('stale', False)))
    if n_eff < 2 or data.get('stale', False):
        print('⚠ 记录陈旧/样本不足，降级建议仅供参考')
else:
    for item in data.get('per_coder') or []:
        print('  %s: n_eff=%.2f / 置信: %s / 陈旧: %s' % (
            item.get('coder', '-'), item.get('n_eff', 0.0),
            label(item.get('confidence', 'low')), stale_label(item.get('stale', False))))
PYEOF
}

# 调 guard_metrics.py 子进程并渲染保鲜段；python 缺失/非零退出/JSON 坏均静默跳过
_guard_freshness() {
    local guard_file="$1" coder="$2" tags_arg="$3"
    local metrics out
    metrics="$(_guard_metrics_path)" || return 0
    if [[ -n "$coder" ]]; then
        out="$(BUDGET_GUARD_FILE="$guard_file" "${BUDGET_PYTHON:-python3}" "$metrics" \
            --coder "$coder" ${tags_arg:+--tags "$tags_arg"} --json 2>/dev/null)" || return 0
        _guard_render_metrics single "$out"
    else
        out="$(BUDGET_GUARD_FILE="$guard_file" "${BUDGET_PYTHON:-python3}" "$metrics" \
            --json 2>/dev/null)" || return 0
        _guard_render_metrics list "$out"
    fi
}

# ─── 查询与降级判定 ──────────────────────────────────────────────────────

guard_query() {
    local coder="${1:-}"
    if [[ $# -gt 0 ]]; then
        shift
    fi
    local guard_file
    guard_file="$(guard_file_path)"

    if [[ ! -f "$guard_file" ]]; then
        budget_print_info "未找到 Coder Guard 记录: $guard_file"
        budget_print_info "工作流执行后自动生成；也可用 'budget setup guard append' 手动记录"
        return 0
    fi

    local tags_arg=""
    if [[ $# -gt 0 ]]; then
        tags_arg="$(IFS=,; echo "$*")"
    fi

    BUDGET_GUARD_FILE="$guard_file" \
    BUDGET_GUARD_CODER="$coder" \
    BUDGET_GUARD_TAGS="$tags_arg" \
        "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os

WINDOW = 5           # 降级判定窗口（router.md Step 2：最近 5 次）
FAIL_THRESHOLD = 2   # 窗口内失败阈值（SKILL.md P0 coder-guard）
DIRECTOR_STREAK = 3  # 连续失败阈值（3 轮全败 → Director，router.md 应急处理）
LEVEL_ORDER = ['coder-lite', 'coder-standard', 'coder-senior']

guard_file = os.environ['BUDGET_GUARD_FILE']
coder = os.environ.get('BUDGET_GUARD_CODER', '')
raw_tags = os.environ.get('BUDGET_GUARD_TAGS', '')
query_tags = [tag.strip() for tag in raw_tags.split(',') if tag.strip()]

try:
    with open(guard_file, encoding='utf-8') as handle:
        data = json.load(handle)
except (OSError, ValueError) as exc:
    print('记录文件解析失败: %s: %s' % (guard_file, exc))
    raise SystemExit(1)
history = data.get('history') or []
summary = data.get('summary') or {}

print('记录文件: %s' % guard_file)
print('历史记录: %d 条' % len(history))

if not coder:
    # 概览模式：最近窗口记录 + summary 概览
    for entry in history[-WINDOW:]:
        tags = ','.join(entry.get('tags') or [])
        print('  %s  %-14s %-8s tags=[%s]' % (
            entry.get('timestamp', '-'), entry.get('coder', '-'),
            entry.get('result', '-'), tags))
    if summary:
        print('汇总（coder × tag）:')
        for name in sorted(summary):
            tag_stats = summary[name]
            total = sum(stats.get('total', 0) for stats in tag_stats.values())
            failure = sum(stats.get('failure', 0) for stats in tag_stats.values())
            print('  %s: %d 次 / 失败 %d' % (name, total, failure))
    print("提示: 'budget setup guard query <coder> [tag...]' 查询特定组合的降级建议")
    raise SystemExit(0)

# 判定模式：coder（+可选 tags 交集）的最近窗口
matched = [entry for entry in history if entry.get('coder') == coder]
if query_tags:
    wanted = set(query_tags)
    matched = [entry for entry in matched if set(entry.get('tags') or []) & wanted]
window = matched[-WINDOW:]
failures = sum(1 for entry in window if entry.get('result') == 'failure')

# 连续失败（最新往回，遇非失败即中断）
streak = 0
for entry in reversed(window):
    if entry.get('result') == 'failure':
        streak += 1
    else:
        break

print('查询: %s  标签: %s' % (coder, query_tags or '(全部)'))
print('最近 %d 次窗口: 失败 %d 次（连续 %d 次）' % (len(window), failures, streak))

if len(window) < FAIL_THRESHOLD:
    print('判定: 样本不足（窗口 %d 条 < 2），可按计划分派 %s' % (len(window), coder))
elif streak >= DIRECTOR_STREAK:
    print('判定: 连续失败 %d 次，建议升级 Director 介入（3 轮全败语义）' % streak)
elif failures >= FAIL_THRESHOLD:
    if coder in LEVEL_ORDER:
        index = LEVEL_ORDER.index(coder)
        if index + 1 < len(LEVEL_ORDER):
            print('判定: 触发降级保护，建议改派 %s' % LEVEL_ORDER[index + 1])
        else:
            print('判定: 触发降级保护，%s 已是最高级 coder，建议 Director 介入' % coder)
    else:
        print('判定: 触发降级保护，建议改派更高级 coder')
else:
    print('判定: 无降级风险（失败 %d < 2），可按计划分派 %s' % (failures, coder))
PYEOF
    local query_rc=$?
    if [[ $query_rc -eq 0 ]]; then
        _guard_freshness "$guard_file" "$coder" "$tags_arg"
    fi
    return $query_rc
}

# ─── 汇总与重置 ──────────────────────────────────────────────────────────

guard_summary() {
    local guard_file
    guard_file="$(guard_file_path)"
    if [[ ! -f "$guard_file" ]]; then
        budget_print_info "未找到 Coder Guard 记录（尚无数据）"
        budget_print_info "工作流执行后自动生成；也可用 'budget setup guard append' 手动记录"
        return 0
    fi
    BUDGET_GUARD_FILE="$guard_file" "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os

with open(os.environ['BUDGET_GUARD_FILE'], encoding='utf-8') as handle:
    data = json.load(handle)
summary = data.get('summary') or {}
history = data.get('history') or []

if not summary:
    print('暂无统计数据')
else:
    for coder in sorted(summary):
        print('%s:' % coder)
        for tag in sorted(summary[coder]):
            stats = summary[coder][tag]
            total = stats.get('total', 0)
            success = stats.get('success', 0)
            failure = stats.get('failure', 0)
            rate = '%.0f%%' % (success * 100.0 / total) if total else 'N/A'
            print('  %-20s total=%-4d success=%-4d failure=%-4d rate=%s' % (
                tag, total, success, failure, rate))
print('历史记录: %d 条' % len(history))
PYEOF
    local summary_rc=$?
    if [[ $summary_rc -eq 0 ]]; then
        _guard_freshness "$guard_file" "" ""
    fi
    return $summary_rc
}

guard_reset() {
    local guard_file
    guard_file="$(guard_file_path)"
    mkdir -p "$(dirname "$guard_file")"
    BUDGET_GUARD_FILE="$guard_file" "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os

guard_file = os.environ['BUDGET_GUARD_FILE']
data = {'history': [], 'summary': {}}
tmp_path = guard_file + '.tmp'
with open(tmp_path, 'w', encoding='utf-8') as handle:
    json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
    handle.write('\n')
os.replace(tmp_path, guard_file)
PYEOF
    budget_print_success "已重置 Coder Guard 记录: $guard_file"
}

# ─── setup.sh guard 子命令分发入口（setup.sh 分发表：setup_guard "$@"）──

setup_guard() {
    local action="${1:-query}"
    case "$action" in
        query)
            if [[ $# -gt 0 ]]; then
                shift
            fi
            guard_query "$@"
            ;;
        append)
            shift
            guard_append "$@"
            ;;
        summary)
            guard_summary
            ;;
        reset)
            guard_reset
            ;;
        *)
            budget_print_error "未知操作: $action"
            budget_print_info "用法: budget setup guard [query [coder] [tag...]|append --coder <c> --result <r> [--tags <t,...>] [--escalated-to <e>]|summary|reset]"
            return 1
            ;;
    esac
}
