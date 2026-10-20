#!/bin/bash
# BudgetBuddy hooks 注入编排 + superpowers 插件启用（design.md §9/§12-A11）
#
# 提供:
#   budget_inject_hooks       - settings.json 注入（三事件 + superpowers；
#                               init.sh 桩入口，函数存在即被自动调用）
#   budget_remove_hooks       - 移除本套件注入项（保留用户已有 hooks）
#   budget_check_hooks        - 查询当前注入状态
#   budget_inject_superpowers - 仅启用 superpowers 插件（安装器复用入口）
#
# 依赖（setup.sh source 基础层后分发调用）:
#   colors.sh    - budget_print_*
#   platform.sh  - detect_platform（BUDGET_PLATFORM_KIND/SCOPE/ROOT）
#   setup.sh 顶层导出 - $BUDGET_PYTHON / $BUDGET_LIB_DIR / $BUDGET_SETUP_DIR /
#                       $BUDGET_GLOBAL
#
# 实现纪律: settings.json 读改写统一由 lib/hooks_inject.py 承担（注入前
# 备份 + 临时文件原子写 + 幂等重入 + 键序保持 + 移除精确删除），本模块
# 仅做 settings.json / hook 脚本路径定位与结果呈现。

# ─── 内部辅助：settings.json 定位（codebuddy 形态）──────────────────────
# 探测规则（对齐 init.sh Step 5/6 落点约定）:
#   BUDGET_GLOBAL=1 或全局形态 → ~/.codebuddy/settings.json
#   codebuddy 项目级           → <平台根>/.codebuddy/settings.json
# 非 codebuddy 形态（opencode/claudecode 无 hooks 机制）→ return 1（stdout 无输出）。
_budget_hooks_settings_file() {
    detect_platform >/dev/null || true
    if [[ "${BUDGET_PLATFORM_KIND:-unknown}" != "codebuddy" ]]; then
        return 1
    fi
    if [[ "${BUDGET_GLOBAL:-0}" == "1" || "${BUDGET_PLATFORM_SCOPE:-}" != "project" ]]; then
        echo "$HOME/.codebuddy/settings.json"
    else
        echo "${BUDGET_PLATFORM_ROOT:-}/.codebuddy/settings.json"
    fi
}

# ─── 内部辅助：hook 命令串构造（挂 budget-notify-hook.py 实际路径）──────
# 形态决策:
#   项目级安装 → 相对路径 .codebuddy/hooks/...（hook 运行时 CWD=项目根）
#   全局形态   → setup.sh 同目录 hooks/ 的绝对路径（全局安装与源形态共用；
#                不存在时回退 ~/.codebuddy/hooks/ 安装约定路径）
# 命令自带 test -f 守卫：hook 脚本缺失时静默跳过，不阻塞 CodeBuddy。
_budget_hooks_hook_cmd() {
    local python_cmd="${BUDGET_PYTHON:-python3}"
    local hook_rel=".codebuddy/hooks/budget-notify-hook.py"
    local hook_global="$HOME/.codebuddy/hooks/budget-notify-hook.py"
    local hook_src="${BUDGET_SETUP_DIR:-}/hooks/budget-notify-hook.py"

    if [[ "${BUDGET_GLOBAL:-0}" != "1" && "${BUDGET_PLATFORM_SCOPE:-}" == "project" \
          && -n "${BUDGET_PLATFORM_ROOT:-}" ]]; then
        echo "test -f $hook_rel && $python_cmd $hook_rel || exit 0"
    elif [[ -n "${BUDGET_SETUP_DIR:-}" && -f "$hook_src" ]]; then
        echo "test -f \"$hook_src\" && $python_cmd \"$hook_src\" || exit 0"
    else
        echo "test -f \"$hook_global\" && $python_cmd \"$hook_global\" || exit 0"
    fi
}

# ─── 内部辅助：hooks_inject.py 统一调用入口 ─────────────────────────────
# 用法: _budget_hooks_engine <action> <settings_file> [hook_cmd]
# stdout 透传引擎输出（injected/no_change/removed/true/false/JSON）；
# 引擎 exit 非零（解析失败等）时调用方按 rc 处理。
_budget_hooks_engine() {
    local action="$1"
    local settings_file="$2"
    local hook_cmd="${3:-}"
    local engine="${BUDGET_LIB_DIR:-}/hooks_inject.py"
    if [[ ! -f "$engine" ]]; then
        budget_print_error "hooks 注入引擎缺失: $engine"
        return 1
    fi
    SETTINGS_FILE="$settings_file" ACTION="$action" HOOK_CMD="$hook_cmd" \
        "${BUDGET_PYTHON:-python3}" "$engine"
}

# ─── hooks 注入（三事件 + superpowers；init.sh 桩调用入口）──────────────
# 用法: budget_inject_hooks [settings_file]
#   显式传入 settings_file（reinstall 恢复场景：卸载已清除探测依据
#   setup.sh，探测必然 unknown）时跳过探测直接操作该文件；未传时按当前
#   形态探测定位。hook_cmd 构造仍读 BUDGET_PLATFORM_* 形态变量（显式
#   settings_file 的调用方负责先恢复形态变量快照，保证 hook_cmd 落点
#   与 settings_file 同形态）。
budget_inject_hooks() {
    local settings_file="${1:-}"
    if [[ -z "$settings_file" ]]; then
        settings_file="$(_budget_hooks_settings_file)" || {
            budget_print_info "非 codebuddy 形态，跳过 hooks 注入（该平台无 hooks 机制）"
            return 0
        }
    fi
    local hook_cmd
    hook_cmd="$(_budget_hooks_hook_cmd)"

    budget_print_info "注入 hooks 到: $settings_file"
    local result rc=0
    result="$(_budget_hooks_engine inject_all "$settings_file" "$hook_cmd" 2>&1)" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        budget_print_error "hooks 注入失败（settings.json 未被修改）:"
        echo "$result" >&2
        return 1
    fi
    case "$result" in
        *injected*)
            budget_print_success "已注入 Notification/PreToolUse/SubagentStop 三事件 hooks"
            budget_print_info "备份: ${settings_file}.bak-budget（注入前状态，可随时恢复）"
            budget_print_info "superpowers 插件已写入 enabledPlugins，重启 CodeBuddy 后生效"
            budget_print_info "如未自动加载，可手动执行: /plugin superpowers"
            ;;
        *no_change*)
            budget_print_info "hooks 已配置（幂等跳过，无重复注入）"
            ;;
        *)
            budget_print_warning "hooks 注入返回未知状态: $result"
            ;;
    esac
    return 0
}

# ─── superpowers 插件启用（检测 → 未启用注入 → 提示重启/手动执行）──────
budget_inject_superpowers() {
    local settings_file
    settings_file="$(_budget_hooks_settings_file)" || {
        budget_print_info "非 codebuddy 形态，跳过 superpowers 插件启用"
        return 0
    }

    # 已启用检测（SKILL_NS="superpowers:" 前缀的 skill 引用依赖该插件）
    local enabled rc=0
    enabled="$(_budget_hooks_engine check "$settings_file" 2>/dev/null | tail -n 1)" || rc=$?
    if [[ "$rc" -eq 0 && "$enabled" == "true" ]]; then
        budget_print_info "superpowers 插件: 已在 settings.json 中启用 ✓"
        budget_print_info "重启 CodeBuddy 后即可加载 superpowers skills"
        return 0
    fi

    budget_print_warning "superpowers 插件未启用（skill 引用依赖 superpowers: 前缀）"
    local result
    result="$(_budget_hooks_engine inject_superpowers "$settings_file" 2>&1)" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        budget_print_error "superpowers 插件启用失败（settings.json 未被修改）:"
        echo "$result" >&2
        return 1
    fi
    budget_print_info "已注入 superpowers 插件配置: $settings_file"
    budget_print_info "请重启 CodeBuddy 加载插件，或手动执行: /plugin superpowers"
    return 0
}

# ─── hooks 移除（精确删除本套件项，用户已有 hooks 保留）────────────────
# 用法: budget_remove_hooks [settings_file]
#   显式传入 settings_file（uninstall 场景：删除计划已清 setup.sh，重新
#   探测必然 unknown 并误判「非 codebuddy 形态」）时跳过探测直接操作该
#   文件；未传时按当前形态探测定位。
budget_remove_hooks() {
    local settings_file="${1:-}"
    if [[ -z "$settings_file" ]]; then
        settings_file="$(_budget_hooks_settings_file)" || {
            budget_print_info "非 codebuddy 形态，跳过 hooks 移除"
            return 0
        }
    fi
    if [[ ! -f "$settings_file" ]]; then
        budget_print_info "settings.json 不存在，无需移除: $settings_file"
        return 0
    fi

    local result rc=0
    result="$(_budget_hooks_engine remove_hooks "$settings_file" 2>&1)" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        budget_print_error "hooks 移除失败（settings.json 未被修改）:"
        echo "$result" >&2
        return 1
    fi
    case "$result" in
        *removed*)
            budget_print_success "已移除本套件 hooks 与 superpowers 注入项（用户自有配置保留）"
            if [[ ! -f "$settings_file" ]]; then
                budget_print_info "settings.json 移除后为空，已删除文件"
            fi
            ;;
        *no_change*)
            budget_print_info "未发现本套件注入项，无需移除"
            ;;
        *)
            budget_print_warning "hooks 移除返回未知状态: $result"
            ;;
    esac
    return 0
}

# ─── 注入状态查询（hooks + superpowers 两项）────────────────────────────
budget_check_hooks() {
    local settings_file
    settings_file="$(_budget_hooks_settings_file)" || {
        budget_print_info "非 codebuddy 形态，无 hooks 注入机制"
        return 0
    }
    budget_print_info "settings.json: $settings_file"
    if [[ ! -f "$settings_file" ]]; then
        budget_print_info "状态: 文件不存在（未注入）"
        return 0
    fi

    local summary rc=0
    summary="$(_budget_hooks_engine check_hooks "$settings_file" 2>/dev/null | tail -n 1)" || rc=$?
    if [[ "$rc" -ne 0 || -z "$summary" ]]; then
        budget_print_error "注入状态查询失败（settings.json 可能已损坏）"
        return 1
    fi
    # summary 为单行 JSON {"hooks": bool, "superpowers": bool}
    BUDGET_HOOKS_SUMMARY="$summary" "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os

try:
    data = json.loads(os.environ.get('BUDGET_HOOKS_SUMMARY', '{}'))
except ValueError:
    data = {}
hooks_on = data.get('hooks') is True
sp_on = data.get('superpowers') is True
print('hooks 注入: %s' % ('已注入（三事件）✓' if hooks_on else '未注入'))
print('superpowers 插件: %s' % ('已启用 ✓' if sp_on else '未启用'))
PYEOF
    return 0
}
