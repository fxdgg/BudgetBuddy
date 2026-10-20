#!/bin/bash
# BudgetBuddy 交互原语（design.md §8.2「交互与汇总」组）
#
# 提供（budget_ 前缀，供 init 确认交互复用与 quickstart 问答共用）:
#   budget_read_confirm "<提示>" [Y|N]
#       确认问答（默认 Y；返回 0=是 / 1=否）
#   budget_read_choice "<提示>" "<选项1|选项2|...>" [默认值]
#       选项问答（stdout 输出所选值；无效输入回退默认值）
#   budget_read_input "<提示>" [默认值]
#       自由输入（stdout 输出输入值；空输入回退默认值）
#
# EOF 容错（非交互调用 / stdin 关闭，与 shell.sh 风格一致）:
#   read 一律 ``|| true`` 兜底，空输入与未识别输入统一回退默认值
#   （缺省时取选项集首项），不崩溃、不挂起。
#
# 输出纪律：提示文本经 read -p 走 stderr，stdout 仅承载结果值，
# 调用方可安全捕获（$(...)）。
#
# 依赖（setup.sh source 基础层后分发调用）: colors.sh（可选，本模块
# 自身不依赖颜色；被 source 时无任何副作用，仅定义函数）。

# ─── 确认问答 ────────────────────────────────────────────────────────────
budget_read_confirm() {
    # 用法: budget_read_confirm "<提示>" [Y|N]
    # Y/y/yes/是 → 返回 0；N/n/no/否 → 返回 1；
    # 空输入（EOF）/未识别输入 → 按默认值（缺省 Y）。
    local prompt="$1"
    local default="${2:-Y}"
    local answer=""
    read -r -p "$prompt" answer || true
    if [[ -z "$answer" ]]; then
        answer="$default"
    fi
    case "$answer" in
        [Yy]|[Yy][Ee][Ss]|是)
            return 0
            ;;
        [Nn]|[Nn][Oo]|否)
            return 1
            ;;
        *)
            # 未识别输入按默认值兜底（EOF 容错的最后一道防线）
            if [[ "$default" =~ ^[Yy]$ ]]; then
                return 0
            fi
            return 1
            ;;
    esac
}

# ─── 选项问答 ────────────────────────────────────────────────────────────
budget_read_choice() {
    # 用法: budget_read_choice "<提示>" "<选项1|选项2|...>" [默认值]
    # stdout 输出所选值；空输入（EOF）/无效输入 → 默认值（缺省取首项）。
    local prompt="$1"
    local choices="$2"
    local default="${3:-}"
    local answer=""
    read -r -p "$prompt" answer || true
    if [[ -z "$answer" ]]; then
        answer="$default"
    fi

    local options=()
    IFS='|' read -r -a options <<< "$choices"
    if [[ "${#options[@]}" -eq 0 || -z "${options[0]}" ]]; then
        # 选项集为空：直接回显输入（调用方自行校验）
        echo "$answer"
        return 0
    fi
    if [[ -z "$default" ]]; then
        default="${options[0]}"
    fi

    local option
    local matched=""
    for option in "${options[@]}"; do
        if [[ "$answer" == "$option" ]]; then
            matched="$option"
            break
        fi
    done
    if [[ -z "$matched" ]]; then
        matched="$default"
    fi
    echo "$matched"
}

# ─── 自由输入 ────────────────────────────────────────────────────────────
budget_read_input() {
    # 用法: budget_read_input "<提示>" [默认值]
    # stdout 输出输入值；空输入（EOF）→ 默认值（缺省空串）。
    local prompt="$1"
    local default="${2:-}"
    local answer=""
    read -r -p "$prompt" answer || true
    if [[ -z "$answer" ]]; then
        answer="$default"
    fi
    echo "$answer"
}
