#!/bin/bash
# BudgetBuddy persona 主题管理（design.md §8.5 / specs/setup-cli「personas 五主题」）
#
# Provides:
#   do_persona [list|set <theme>|expand [theme]|show|help|<theme>]
#       setup.sh persona 分发入口（setup.sh 契约函数名 do_persona；
#       裸主题名等价 set，specs「主题切换」Scenario: budget setup persona sanguo）
#   setup_persona ...
#       别名（任务契约名；与 do_persona 完全等价）
#
# Dependencies（setup.sh source 基础层后分发调用）:
#   colors.sh    - budget_print_*
#   utils.sh     - budget_project_data_dir / budget_global_data_dir（budget_data_dir 契约）
#   platform.sh  - detect_platform（BUDGET_PLATFORM_KIND/SCOPE/ROOT 变量副作用）
#   BUDGET_PYTHON / BUDGET_LIB_DIR / BUDGET_SETUP_DIR / BUDGET_GLOBAL（setup.sh 顶层导出）
#
# 数据落点（design.md §8.4 读取优先级，budget_data_dir 契约）:
#   读取: BUDGET_DIR > 项目 .budget/（向上查找，文件级优先）> 全局 ~/.budgetbuddy/
#   写入: BUDGET_DIR > 项目 .budget/（已存在目录或平台项目根新建）> 全局 ~/.budgetbuddy/
#
# JSON 一律由 lib/persona_expand.py 承担（env 传参，无 shell 字符串插值）；
# 本模块仅做路径定位、目录创建与结果呈现。

# ─── personas.json 源定位 ─────────────────────────────────────────────────
_budget_persona_personas_file() {
    # 按序探测（stdout 输出路径；未找到 return 1）:
    #   ① BUDGET_PERSONAS_FILE 显式覆盖（测试/直调）
    #   ② codebuddy 项目级 <root>/.codebuddy/personas.json（非 BUDGET_GLOBAL=1）
    #   ③ BUDGET_SETUP_DIR/personas.json（安装形态：codebuddy 项目/全局、
    #      opencode 管理面 ~/.budgetbuddy/）
    #   ④ 全局数据目录 ~/.budgetbuddy/personas.json（init 落位）
    #   ⑤ BUDGET_SETUP_DIR/personas/personas.json（core 源形态）
    if [[ -n "${BUDGET_PERSONAS_FILE:-}" && -f "$BUDGET_PERSONAS_FILE" ]]; then
        echo "$BUDGET_PERSONAS_FILE"
        return 0
    fi
    if [[ "${BUDGET_PLATFORM_KIND:-}" == "codebuddy" && -n "${BUDGET_PLATFORM_ROOT:-}" \
          && "${BUDGET_GLOBAL:-0}" != "1" \
          && -f "$BUDGET_PLATFORM_ROOT/.codebuddy/personas.json" ]]; then
        echo "$BUDGET_PLATFORM_ROOT/.codebuddy/personas.json"
        return 0
    fi
    local candidate
    for candidate in "$BUDGET_SETUP_DIR/personas.json" \
                     "$(budget_global_data_dir)/personas.json" \
                     "$BUDGET_SETUP_DIR/personas/personas.json"; do
        if [[ -f "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

# ─── persona-active.json 读取定位（文件级优先级）─────────────────────────
_budget_persona_active_file() {
    # 读取优先级（design.md §8.4）: BUDGET_DIR > 项目 .budget/ > 全局 ~/.budgetbuddy/
    # 项目级文件存在即生效；不存在时降级全局级（与 notify.json 双级降级一致）。
    # 皆无 → return 1（运行时降级 default 主题）。
    local candidate
    if [[ -n "${BUDGET_DIR:-}" ]]; then
        candidate="$BUDGET_DIR/persona-active.json"
        if [[ -f "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
        return 1
    fi
    local project_dir
    project_dir="$(budget_project_data_dir)"
    if [[ -n "$project_dir" && -f "$project_dir/persona-active.json" ]]; then
        echo "$project_dir/persona-active.json"
        return 0
    fi
    candidate="$(budget_global_data_dir)/persona-active.json"
    if [[ -f "$candidate" ]]; then
        echo "$candidate"
        return 0
    fi
    return 1
}

# ─── persona set 写入目录决策 ─────────────────────────────────────────────
_budget_persona_write_dir() {
    # 写入目录（design.md §8.4 / budget_data_dir 契约）:
    #   BUDGET_DIR 显式覆盖 > BUDGET_GLOBAL=1 → 全局 > 项目 .budget/
    #   （向上查找已存在目录；否则平台项目根 <root>/.budget 新建）> 全局兜底
    if [[ -n "${BUDGET_DIR:-}" ]]; then
        echo "$BUDGET_DIR"
        return 0
    fi
    if [[ "${BUDGET_GLOBAL:-0}" != "1" ]]; then
        local project_dir
        project_dir="$(budget_project_data_dir)"
        if [[ -n "$project_dir" ]]; then
            echo "$project_dir"
            return 0
        fi
        if [[ "${BUDGET_PLATFORM_SCOPE:-}" == "project" && -n "${BUDGET_PLATFORM_ROOT:-}" ]]; then
            echo "$BUDGET_PLATFORM_ROOT/.budget"
            return 0
        fi
    fi
    budget_global_data_dir
}

# ─── 用法提示 ─────────────────────────────────────────────────────────────
_budget_persona_usage() {
    cat << 'EOF'
用法: budget setup persona <子命令>

子命令:
  list              列出可用主题（标记当前主题）
  set <theme>       切换主题（写入 persona-active.json，11 键角色映射）
  expand [theme]    展开主题，输出 11 键角色称呼映射（--json 机器可读）
  show              显示当前主题详情
  <theme>           等价 set <theme>（如: budget setup persona sanguo）

数据落点:
  读取: .budget/persona-active.json > ~/.budgetbuddy/persona-active.json
  写入: 项目 .budget/（平台项目根）或全局 ~/.budgetbuddy/（BUDGET_GLOBAL=1）
EOF
}

# ─── set 子命令实现 ───────────────────────────────────────────────────────
_budget_persona_set() {
    local theme="${1:-}"
    if [[ -z "$theme" ]]; then
        budget_print_error "用法: budget setup persona set <theme>"
        budget_print_info "查看可用主题: budget setup persona list"
        return 1
    fi
    local write_dir
    write_dir="$(_budget_persona_write_dir)"
    local write_file="$write_dir/persona-active.json"
    if ! mkdir -p "$write_dir"; then
        budget_print_error "数据目录创建失败: $write_dir"
        return 1
    fi
    # expand.py set 失败时已向 stderr 输出错误详情（含可用主题清单）
    local rc=0
    BUDGET_PERSONAS_FILE="$personas_file" \
    BUDGET_PERSONA_ACTIVE="$write_file" \
    BUDGET_PERSONA_THEME="$theme" \
        "${BUDGET_PYTHON:-python3}" "$BUDGET_LIB_DIR/persona_expand.py" set || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        budget_print_error "主题切换失败: ${theme}（详见上方错误详情）"
        return 1
    fi
    budget_print_success "角色主题已生效: $write_file"
    # 切换后展示 11 键角色映射（对齐参照交互：切换即预览）
    echo ""
    BUDGET_PERSONAS_FILE="$personas_file" \
    BUDGET_PERSONA_ACTIVE="$write_file" \
    BUDGET_PERSONA_THEME="$theme" \
        "${BUDGET_PYTHON:-python3}" "$BUDGET_LIB_DIR/persona_expand.py" expand
    return 0
}

# ─── expand 子命令实现 ────────────────────────────────────────────────────
_budget_persona_expand() {
    # expand [theme] [--json]：输出 11 键角色称呼映射
    local theme="" json_flag=""
    local arg
    for arg in "$@"; do
        case "$arg" in
            --json) json_flag="1" ;;
            *) if [[ -z "$theme" ]]; then theme="$arg"; fi ;;
        esac
    done
    local cmd_args=(expand)
    if [[ -n "$json_flag" ]]; then
        cmd_args+=("--json")
    fi
    BUDGET_PERSONAS_FILE="$personas_file" \
    BUDGET_PERSONA_ACTIVE="$active_file" \
    BUDGET_PERSONA_THEME="$theme" \
        "${BUDGET_PYTHON:-python3}" "$BUDGET_LIB_DIR/persona_expand.py" "${cmd_args[@]}"
}

# ─── 主入口（setup.sh persona 分发契约）──────────────────────────────────
do_persona() {
    local action="${1:-list}"
    # 平台探测（当前 shell 调用取变量副作用；stdout 丢弃）
    detect_platform >/dev/null || true

    local personas_file
    personas_file="$(_budget_persona_personas_file)" || personas_file=""
    if [[ -z "$personas_file" ]]; then
        budget_print_error "personas.json 未找到（请先完成安装或更新：budget setup update）"
        return 1
    fi

    local active_file
    active_file="$(_budget_persona_active_file)" || active_file=""

    case "$action" in
        list)
            shift
            # --json 透传（机器可读模式：仅输出 JSON 行，无装饰输出）
            local json_flag=""
            local list_arg
            for list_arg in "$@"; do
                case "$list_arg" in
                    --json) json_flag="1" ;;
                esac
            done
            if [[ -n "$json_flag" ]]; then
                BUDGET_PERSONAS_FILE="$personas_file" \
                BUDGET_PERSONA_ACTIVE="$active_file" \
                    "${BUDGET_PYTHON:-python3}" "$BUDGET_LIB_DIR/persona_expand.py" list --json
            else
                budget_print_info "personas.json: $personas_file"
                echo ""
                BUDGET_PERSONAS_FILE="$personas_file" \
                BUDGET_PERSONA_ACTIVE="$active_file" \
                    "${BUDGET_PYTHON:-python3}" "$BUDGET_LIB_DIR/persona_expand.py" list
                echo ""
                budget_print_info "切换: budget setup persona set <theme>"
                budget_print_info "详情: docs/PERSONAS.md"
            fi
            ;;
        set)
            shift
            _budget_persona_set "$@"
            ;;
        expand)
            shift
            _budget_persona_expand "$@"
            ;;
        show)
            BUDGET_PERSONAS_FILE="$personas_file" \
            BUDGET_PERSONA_ACTIVE="$active_file" \
                "${BUDGET_PYTHON:-python3}" "$BUDGET_LIB_DIR/persona_expand.py" show
            ;;
        help|-h|--help)
            _budget_persona_usage
            ;;
        *)
            # 裸主题名等价 set（specs「主题切换」Scenario）
            _budget_persona_set "$action"
            ;;
    esac
    return 0
}

# 任务契约别名（与 do_persona 等价）
setup_persona() {
    do_persona "$@"
}
