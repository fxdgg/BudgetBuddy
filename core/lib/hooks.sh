#!/bin/bash
# BudgetBuddy hooks 注入编排 + superpowers 插件启用（design.md §9/§12-A11/D3）
#
# 提供:
#   budget_inject_hooks       - settings.json 注入（codebuddy：三事件 +
#                               superpowers（inject_all）；claudecode：
#                               三事件（inject_hooks + HOOK_EVENTS_JSON
#                               清单，无插件机制）；init.sh 桩入口，函数
#                               存在即被自动调用）
#   budget_remove_hooks       - 移除本套件注入项（保留用户已有 hooks）
#   budget_check_hooks        - 查询当前注入状态
#   budget_inject_superpowers - 仅启用 superpowers 插件（安装器复用入口；
#                               claudecode 形态跳过）
#
# 依赖（setup.sh source 基础层后分发调用）:
#   colors.sh    - budget_print_*
#   platform.sh  - detect_platform（BUDGET_PLATFORM_KIND/SCOPE/ROOT）
#   setup.sh 顶层导出 - $BUDGET_PYTHON / $BUDGET_LIB_DIR / $BUDGET_SETUP_DIR /
#                       $BUDGET_GLOBAL
#
# 实现纪律: settings.json 读改写统一由 lib/hooks_inject.py 承担（注入前
# 备份 + 临时文件原子写 + 幂等重入 + 键序保持 + 移除精确删除），本模块
# 仅做 settings.json / hook 脚本路径定位、注入事件集数据（claudecode
# 清单经 HOOK_EVENTS_JSON 传入引擎）与结果呈现。

# claudecode 平台注入事件清单（design.md D2/D3）：Notification /
# PermissionRequest matcher "*"（官方 matcher 通配语义）+ SubagentStop
# 无 matcher（空数组 → 注入无 matcher 条目）。
BUDGET_CLAUDECODE_HOOK_EVENTS_JSON='[{"event":"Notification","matchers":["*"]},{"event":"PermissionRequest","matchers":["*"]},{"event":"SubagentStop","matchers":[]}]'

# ─── 内部辅助：settings.json 定位（codebuddy / claudecode 形态）──────────
# 探测规则（对齐 init.sh Step 5/6 落点约定）:
#   BUDGET_GLOBAL=1 或全局形态 → ~/.codebuddy/settings.json（claudecode
#                                同理 ~/.claude/settings.json）
#   项目级                     → <平台根>/.codebuddy/settings.json
#                                （claudecode 为 <平台根>/.claude/settings.json）
# opencode/unknown 形态（无 hooks 机制）→ return 1（stdout 无输出）。
_budget_hooks_settings_file() {
    detect_platform >/dev/null || true
    local kind="${BUDGET_PLATFORM_KIND:-unknown}"
    if [[ "$kind" != "codebuddy" && "$kind" != "claudecode" ]]; then
        return 1
    fi
    local settings_dir
    if [[ "$kind" == "claudecode" ]]; then
        settings_dir=".claude"
    else
        settings_dir=".codebuddy"
    fi
    if [[ "${BUDGET_GLOBAL:-0}" == "1" || "${BUDGET_PLATFORM_SCOPE:-}" != "project" ]]; then
        echo "$HOME/$settings_dir/settings.json"
    else
        echo "${BUDGET_PLATFORM_ROOT:-}/$settings_dir/settings.json"
    fi
}

# ─── 内部辅助：hook 命令串构造（挂 budget-notify-hook.py 实际路径）──────
# 用法: _budget_hooks_hook_cmd [kind]
#   kind 缺省时读 BUDGET_PLATFORM_KIND（显式 settings_file 快照场景）；
#   非 claudecode（含未探测）一律按 codebuddy 路径（既有行为不变）。
# 形态决策:
#   项目级安装 → 相对路径 .codebuddy/hooks/...（claudecode 为
#                .claude/hooks/...；hook 运行时 CWD=项目根）
#   全局形态   → setup.sh 同目录 hooks/ 的绝对路径（全局安装与源形态共用；
#                不存在时回退 ~/.codebuddy/hooks/（claudecode 为
#                ~/.claude/hooks/）安装约定路径）
# 命令自带 test -f 守卫：hook 脚本缺失时静默跳过，不阻塞宿主平台。
_budget_hooks_hook_cmd() {
    local python_cmd="${BUDGET_PYTHON:-python3}"
    local kind="${1:-${BUDGET_PLATFORM_KIND:-unknown}}"
    local hooks_dir
    if [[ "$kind" == "claudecode" ]]; then
        hooks_dir=".claude"
    else
        hooks_dir=".codebuddy"
    fi
    local hook_rel="$hooks_dir/hooks/budget-notify-hook.py"
    local hook_global="$HOME/$hooks_dir/hooks/budget-notify-hook.py"
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
# 用法: _budget_hooks_engine <action> <settings_file> [hook_cmd] [events_json]
# stdout 透传引擎输出（injected/no_change/removed/true/false/JSON）；
# events_json 非空时以 HOOK_EVENTS_JSON 传入引擎（注入事件清单，仅
# inject_hooks/inject_all 消费）；引擎 exit 非零（解析失败等）时调用方
# 按 rc 处理。
_budget_hooks_engine() {
    local action="$1"
    local settings_file="$2"
    local hook_cmd="${3:-}"
    local events_json="${4:-}"
    local engine="${BUDGET_LIB_DIR:-}/hooks_inject.py"
    if [[ ! -f "$engine" ]]; then
        budget_print_error "hooks 注入引擎缺失: $engine"
        return 1
    fi
    if [[ -n "$events_json" ]]; then
        SETTINGS_FILE="$settings_file" ACTION="$action" HOOK_CMD="$hook_cmd" \
            HOOK_EVENTS_JSON="$events_json" "${BUDGET_PYTHON:-python3}" "$engine"
    else
        SETTINGS_FILE="$settings_file" ACTION="$action" HOOK_CMD="$hook_cmd" \
            "${BUDGET_PYTHON:-python3}" "$engine"
    fi
}

# ─── hooks 注入（codebuddy：三事件 + superpowers；claudecode：三事件）──
# 用法: budget_inject_hooks [settings_file]
#   显式传入 settings_file（reinstall 恢复场景：卸载已清除探测依据
#   setup.sh，探测必然 unknown；安装器 inject_hooks_* 场景：多平台共装
#   时探测会命中他平台——如 codebuddy 先装后再装 claudecode，.codebuddy/
#   setup.sh 就位使探测误判 kind=codebuddy）时跳过探测直接操作该文件；
#   未传时按当前形态探测定位。显式 settings_file 的调用方（安装器子进程
#   必须如此）负责预设 BUDGET_PLATFORM_KIND/SCOPE/ROOT 形态变量快照，
#   保证 hook_cmd 落点与 settings_file 同形态，且不依赖 detect_platform
#   探测结果。
#   kind 分派（design.md D3）：codebuddy → inject_all（现行为不变，无
#   HOOK_EVENTS_JSON，引擎默认三事件）；claudecode → inject_hooks +
#   claudecode 三事件清单（无 superpowers 插件机制）。
budget_inject_hooks() {
    local settings_file="${1:-}"
    local kind="${BUDGET_PLATFORM_KIND:-unknown}"
    if [[ -z "$settings_file" ]]; then
        # 子 shell 探测形态（命令替换不传播变量副作用 → 不在当前 shell
        # 回填 BUDGET_PLATFORM_*，codebuddy 路径 hook_cmd 构造输入保持
        # 改动前行为）；探测行形如 codebuddy:project:<path> / unknown。
        local platform_line
        platform_line="$(detect_platform 2>/dev/null)" || true
        kind="${platform_line%%:*}"
        settings_file="$(_budget_hooks_settings_file)" || {
            budget_print_info "非 codebuddy/claudecode 形态，跳过 hooks 注入（该平台无 hooks 机制）"
            return 0
        }
    fi
    if [[ "$kind" == "claudecode" && -z "${BUDGET_PLATFORM_SCOPE:-}" ]]; then
        # claudecode 形态变量未就位（子 shell 探测副作用不传播）→ 当前
        # shell 直接探测回填（hook_cmd 项目级相对路径定位需要 SCOPE/ROOT；
        # 仅 claudecode 执行，codebuddy 路径不回填以保持既有行为）
        detect_platform >/dev/null || true
        kind="${BUDGET_PLATFORM_KIND:-unknown}"
    fi
    local hook_cmd
    hook_cmd="$(_budget_hooks_hook_cmd "$kind")"
    local result rc=0

    if [[ "$kind" == "claudecode" ]]; then
        budget_print_info "注入 hooks 到: $settings_file"
        result="$(_budget_hooks_engine inject_hooks "$settings_file" "$hook_cmd" \
            "$BUDGET_CLAUDECODE_HOOK_EVENTS_JSON" 2>&1)" || rc=$?
        if [[ "$rc" -ne 0 ]]; then
            budget_print_error "hooks 注入失败（settings.json 未被修改）:"
            echo "$result" >&2
            return 1
        fi
        case "$result" in
            *injected*)
                budget_print_success "已注入 Notification/PermissionRequest/SubagentStop 三事件 hooks"
                budget_print_info "备份: ${settings_file}.bak-budget（注入前状态，可随时恢复）"
                ;;
            *no_change*)
                budget_print_info "hooks 已配置（幂等跳过，无重复注入）"
                ;;
            *)
                budget_print_warning "hooks 注入返回未知状态: $result"
                ;;
        esac
        return 0
    fi

    budget_print_info "注入 hooks 到: $settings_file"
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
    local kind="${BUDGET_PLATFORM_KIND:-unknown}"
    if [[ -z "${BUDGET_PLATFORM_KIND:-}" ]]; then
        # 子 shell 探测形态（不在当前 shell 回填形态变量，理由同
        # budget_inject_hooks；探测行形如 codebuddy:project:<path>）
        local platform_line
        platform_line="$(detect_platform 2>/dev/null)" || true
        kind="${platform_line%%:*}"
    fi
    if [[ "$kind" == "claudecode" ]]; then
        budget_print_info "claudecode 形态无插件机制，跳过 superpowers 插件启用"
        return 0
    fi
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
            budget_print_info "非 codebuddy/claudecode 形态，跳过 hooks 移除"
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

# ─── 注入状态查询（hooks + superpowers 两项；claudecode 仅 hooks）────────
budget_check_hooks() {
    local kind="${BUDGET_PLATFORM_KIND:-unknown}"
    if [[ -z "${BUDGET_PLATFORM_KIND:-}" ]]; then
        # 子 shell 探测形态（不在当前 shell 回填形态变量，理由同
        # budget_inject_hooks；探测行形如 codebuddy:project:<path>）
        local platform_line
        platform_line="$(detect_platform 2>/dev/null)" || true
        kind="${platform_line%%:*}"
    fi
    local settings_file
    settings_file="$(_budget_hooks_settings_file)" || {
        budget_print_info "非 codebuddy/claudecode 形态，无 hooks 注入机制"
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
    # summary 为单行 JSON {"hooks": bool, "superpowers": bool}；
    # claudecode 形态无插件机制 → 不显示 superpowers 行
    BUDGET_HOOKS_SUMMARY="$summary" BUDGET_HOOKS_KIND="$kind" \
        "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os

try:
    data = json.loads(os.environ.get('BUDGET_HOOKS_SUMMARY', '{}'))
except ValueError:
    data = {}
hooks_on = data.get('hooks') is True
print('hooks 注入: %s' % ('已注入（三事件）✓' if hooks_on else '未注入'))
if os.environ.get('BUDGET_HOOKS_KIND') != 'claudecode':
    sp_on = data.get('superpowers') is True
    print('superpowers 插件: %s' % ('已启用 ✓' if sp_on else '未启用'))
PYEOF
    return 0
}
