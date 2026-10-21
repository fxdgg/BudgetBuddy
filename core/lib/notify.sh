#!/bin/bash
# BudgetBuddy notify 命令 shell 侧 + budget status 状态查询（design.md §8.1/§9）
#
# 提供:
#   _dispatch_notify "<消息>" [事件名] - setup.sh notify 分发入口（薄封装）
#   do_notify "<消息>" [事件名]       - 通知转发核心：定位生效配置（双级降级
#                                       不合并）→ 定位 notify.py 实际路径 → 转发
#   do_status                          - budget status 状态查询：Coder Guard
#                                       汇总 + 状态机活跃变更 + agent 配置概览
#
# 依赖（setup.sh source 基础层后分发调用）:
#   colors.sh    - budget_print_*
#   utils.sh     - budget_global_data_dir / budget_data_dir
#   platform.sh  - detect_platform（BUDGET_PLATFORM_KIND/SCOPE/ROOT）
#   preset.sh    - budget_get_current_models（do_status 的 agent 概览；可选，
#                  未就位时降级提示）
#   setup.sh 顶层导出 - $BUDGET_PYTHON / $BUDGET_LIB_DIR / $BUDGET_SETUP_DIR
#
# 通知永不阻塞主流程：未配置静默跳过（specs/notify R1）；转发失败不改变
# 退出码语义（notify.py 自身全程 exit 0，外层再兜底 || true）。

# ─── 内部辅助：生效通知配置定位（双级降级，不合并）──────────────────────
# 项目 .budget/notify.json 存在即生效，否则降级全局 ~/.budgetbuddy/notify.json；
# 皆无 → return 1（stdout 无输出）。
_budget_notify_config_file() {
    local project_cfg=".budget/notify.json"
    local global_cfg
    global_cfg="$(budget_global_data_dir)/notify.json"
    if [[ -f "$project_cfg" ]]; then
        echo "$project_cfg"
        return 0
    fi
    if [[ -f "$global_cfg" ]]; then
        echo "$global_cfg"
        return 0
    fi
    return 1
}

# ─── 内部辅助：notify.py 实际路径定位（产物安装后落点探测链）────────────
# ① setup.sh 同目录 skills/（core 源形态与 codebuddy 安装形态共用：
#    skills 平移到 <安装根>/skills/budget-notify/notify.py）
# ② platform.sh 探测安装根（opencode/claudecode/codex 管理面形态：setup.sh
#    在 ~/.budgetbuddy/ 而 skills 落平台结构目录；codebuddy 各形态兜底）。
#    claudecode/codex 落点与 opencode 同构（skills 目录在平台结构根下，复数
#    skills/ 区别于 opencode 单数 skill/）；hooks 降级（不注入）但 notify
#    CLI 必须可用（add-claudecode-platform D5 / add-codex-platform D5）。
# 全部未命中 → return 1（调用方报错）。
_budget_locate_notify_py() {
    local candidate="${BUDGET_SETUP_DIR:-}/skills/budget-notify/notify.py"
    if [[ -f "$candidate" ]]; then
        echo "$candidate"
        return 0
    fi

    detect_platform >/dev/null || true
    case "${BUDGET_PLATFORM_KIND:-unknown}:${BUDGET_PLATFORM_SCOPE:-}" in
        codebuddy:project) candidate="${BUDGET_PLATFORM_ROOT:-}/.codebuddy/skills/budget-notify/notify.py" ;;
        codebuddy:global)  candidate="$HOME/.codebuddy/skills/budget-notify/notify.py" ;;
        claudecode:project) candidate="${BUDGET_PLATFORM_ROOT:-}/.claude/skills/budget-notify/notify.py" ;;
        claudecode:global)  candidate="$HOME/.claude/skills/budget-notify/notify.py" ;;
        codex:project)      candidate="${BUDGET_PLATFORM_ROOT:-}/.codex/skills/budget-notify/notify.py" ;;
        codex:global)       candidate="$HOME/.codex/skills/budget-notify/notify.py" ;;
        opencode:project)  candidate="${BUDGET_PLATFORM_ROOT:-}/.opencode/skill/budget-notify/notify.py" ;;
        opencode:global)   candidate="$HOME/.config/opencode/skill/budget-notify/notify.py" ;;
        *)                 candidate="" ;;
    esac
    if [[ -n "$candidate" && -f "$candidate" ]]; then
        echo "$candidate"
        return 0
    fi
    return 1
}

# ─── 通知转发核心（do_notify）───────────────────────────────────────────
do_notify() {
    local message="${1:-}"
    local event="${2:-}"
    if [[ -z "$message" ]]; then
        budget_print_error "用法: budget notify \"<消息>\" [事件名(N1..N11)]"
        return 1
    fi

    # 1) 定位生效配置（双级降级不合并；皆无 → 静默跳过，specs/notify R1）
    local config_file=""
    config_file="$(_budget_notify_config_file)" || config_file=""
    if [[ -z "$config_file" ]]; then
        budget_print_info "未配置通知（.budget/notify.json 与 ~/.budgetbuddy/notify.json 均不存在），跳过"
        return 0
    fi

    # 2) 定位 notify.py（产物安装后实际路径；找不到报错，任务硬性要求）
    local notify_py=""
    notify_py="$(_budget_locate_notify_py)" || notify_py=""
    if [[ -z "$notify_py" ]]; then
        budget_print_error "notify.py 未找到（已探测 setup.sh 同目录 skills/ 与平台安装根）"
        budget_print_info "请先完成安装或更新: budget setup init"
        return 1
    fi

    # 3) 转发（BUDGET_NOTIFY_CONFIG 显式传递生效配置路径；消息/事件经
    #    argv 传递不经 shell 二次插值；webhook/secret 仅存于配置文件）
    BUDGET_NOTIFY_CONFIG="$config_file" \
        "${BUDGET_PYTHON:-python3}" "$notify_py" "$message" "$event" || true
    return 0
}

# setup.sh notify 分发入口（契约函数名；透传参数）
_dispatch_notify() {
    do_notify "$@"
}

# ─── do_status 内部辅助：Coder Guard 汇总 ───────────────────────────────
# 固定全局路径 $HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json
# （design.md §8.4 跨会话汇总）；guard.sh 模块就位时优先复用其汇总函数
# （guard_summary），否则容错直读数据文件（history 窗口 5、失败 ≥2 降级，
# A14 语义；字段对齐 T10b guard.json：result ∈ success|failure）。
_budget_status_guard() {
    echo -e "${CYAN}── Coder Guard 汇总 ──${NC}"
    if declare -f guard_summary &>/dev/null; then
        guard_summary
        return 0
    fi
    local project_name
    project_name="$(basename "$(pwd -P)")"
    local guard_file="$HOME/.budgetbuddy/projects/$project_name/memory/coder-guard.json"
    if [[ ! -f "$guard_file" ]]; then
        budget_print_info "暂无 Coder Guard 记录（${guard_file}）"
        return 0
    fi
    BUDGET_GUARD_FILE="$guard_file" "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os

path = os.environ['BUDGET_GUARD_FILE']
try:
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
except (OSError, ValueError):
    print('（guard 记录解析失败: %s）' % path)
    raise SystemExit(0)
if not isinstance(data, dict):
    print('（guard 记录格式非对象，跳过汇总）')
    raise SystemExit(0)

history = data.get('history')
if isinstance(history, list) and history:
    window = history[-5:]
    failures = sum(
        1 for entry in window
        if isinstance(entry, dict) and entry.get('result') == 'failure')
    print('最近 %d 次记录（窗口 5）: 失败 %d 次' % (len(window), failures))
    if failures >= 2:
        print('降级判定: 已触发（失败 ≥2，后续任务路由至更低分级）')
    else:
        print('降级判定: 未触发')
    for entry in window[-3:]:
        if isinstance(entry, dict):
            coder = str(entry.get('coder', '-'))
            escalated = str(entry.get('escalated_to') or '-')
            outcome = '失败' if entry.get('result') == 'failure' else '成功'
            print('  [%s] %s → %s' % (outcome, coder, escalated))
else:
    print('暂无历史记录（history 为空）')
summary = data.get('summary')
if isinstance(summary, dict) and summary:
    print('汇总: %s' % json.dumps(summary, ensure_ascii=False)[:120])
PYEOF
    return 0
}

# ─── do_status 内部辅助：状态机活跃变更 ─────────────────────────────────
# 状态机模块（lib/budget-state.py，A4 全局单点）就位时查询活跃状态文件
# （find 子命令，T10b CLI 约定）；未就位时降级提示，不阻断 status 主流程。
_budget_status_state() {
    echo -e "${CYAN}── 工作流状态机 ──${NC}"
    if declare -f budget_state_summary &>/dev/null; then
        budget_state_summary
        return 0
    fi
    local state_py=""
    local candidate
    for candidate in "${BUDGET_LIB_DIR:-}/budget-state.py" "$HOME/.budgetbuddy/lib/budget-state.py"; do
        if [[ -f "$candidate" ]]; then
            state_py="$candidate"
            break
        fi
    done
    if [[ -z "$state_py" ]]; then
        budget_print_info "状态机模块未安装（lib/budget-state.py）"
        return 0
    fi
    # 活跃状态文件查询（find 子命令，输出 JSON {found, path, type}；
    # 失败或 found=false 按无活跃状态处理）
    local active
    active="$("${BUDGET_PYTHON:-python3}" "$state_py" find 2>/dev/null)" || active=""
    local found_path
    found_path="$(BUDGET_STATE_FIND="$active" "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os

try:
    data = json.loads(os.environ.get('BUDGET_STATE_FIND', ''))
except ValueError:
    raise SystemExit(0)
if isinstance(data, dict) and data.get('found') is True:
    print(data.get('path', ''))
PYEOF
)"
    if [[ -n "$found_path" ]]; then
        budget_print_info "活跃状态文件: ${found_path}"
    else
        budget_print_info "无活跃工作流状态（未启动或已归档）"
    fi
    return 0
}

# ─── do_status 内部辅助：agent 配置概览（复用 T10a preset.sh）───────────
_budget_status_agents() {
    echo -e "${CYAN}── Agent 模型配置 ──${NC}"
    if ! declare -f budget_get_current_models &>/dev/null; then
        budget_print_info "预设模块未安装（lib/preset.sh），跳过 agent 概览"
        return 0
    fi
    local lines rc=0
    lines="$(budget_get_current_models 2>/dev/null)" || rc=$?
    if [[ "$rc" -ne 0 || -z "$lines" ]]; then
        budget_print_info "未检测到 agent 目录或无 agent 产物"
        return 0
    fi
    echo "$lines" | sed 's/^/  /'
    return 0
}

# ─── 状态查询主入口（budget status）─────────────────────────────────────
do_status() {
    budget_print_header

    # 平台与环境概览
    detect_platform >/dev/null || true
    if [[ "${BUDGET_PLATFORM_KIND:-unknown}" == "unknown" ]]; then
        budget_print_warning "未检测到已安装的 BudgetBuddy 平台形态"
    else
        budget_print_info "运行平台: ${BUDGET_PLATFORM_KIND}:${BUDGET_PLATFORM_SCOPE}${BUDGET_PLATFORM_ROOT:+ (root: $BUDGET_PLATFORM_ROOT)}"
    fi
    budget_print_info "生效数据目录: $(budget_data_dir)"
    echo ""

    _budget_status_guard
    echo ""
    _budget_status_state
    echo ""
    _budget_status_agents
    return 0
}
