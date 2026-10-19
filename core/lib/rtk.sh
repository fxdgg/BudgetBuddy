#!/bin/bash
# BudgetBuddy RTK 工具适配（design.md §8.2「模型与护栏」组 / §16.1，T10a）
#
# 提供:
#   budget_rtk_available         - 探测 rtk 命令（PATH 优先，常见安装路径兜底，
#                                  含 Windows rtk.exe 形态）；可用时输出实际
#                                  路径并 return 0，不可用静默 return 1
#   budget_rtk_compress [file]   - 压缩指定文件内容（无参数时读 stdin）；rtk
#                                  可用时经 rtk 代理输出压缩结果，不可用或
#                                  调用失败时静默降级透传原文（不阻断调用方）
#   budget_rtk_status            - 状态查询：可用性 + 版本 + token 节省统计
#                                  （rtk gain）；未安装仅提示可选，恒 return 0
#
# 依赖（setup.sh source 基础层后按存在性加载）:
#   colors.sh    - budget_print_info / budget_print_error
#
# 加载关系：setup.sh 可选模块加载列表已含 rtk.sh（存在才 source，函数就位）；
# 分发表未注册 rtk 子命令——本模块供工作流可选调用（stats 展示 / hooks 链路
# 扩展），不承担独立子命令入口。
#
# 语义呼应：本文件是 RTK 运行时封装（探测 / 压缩 / 状态查询）；
# core/rules/budget-rtk.md 是 agent 侧行为约束（直接写原生命令、hook 自动
# 转换、回退机制）。RTK 为通用开源 CLI 代理工具（终端输出压缩 60-90%），
# 非本套件硬依赖——未安装时全部函数静默降级，工作流不受影响。

# ─── 探测 ────────────────────────────────────────────────────────────────

# rtk 实际命令定位：PATH 优先（Git Bash 下可解析 rtk.exe）；常见安装路径兜底
budget_rtk_available() {
    local candidate
    if command -v rtk &>/dev/null; then
        command -v rtk
        return 0
    fi
    for candidate in "$HOME/.local/bin/rtk" "$HOME/.cargo/bin/rtk" "$HOME/bin/rtk"; do
        if [[ -x "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

# ─── 压缩（降级透传）────────────────────────────────────────────────────

# 压缩文件内容或 stdin 输入（rtk 可用时经 rtk 代理 cat，输出自动压缩）：
#   budget_rtk_compress <file>   压缩该文件内容
#   budget_rtk_compress          压缩 stdin 输入（先缓存临时文件，rtk 失败
#                                时原文仍可重放）
# 降级语义：rtk 不可用 / 调用失败 → 静默透传原文，恒不因 RTK 缺失报错。
budget_rtk_compress() {
    local rtk_cmd input_file="${1:-}" tmp_file=""

    # stdin 模式：缓存到临时文件（rtk 失败降级时原文可重放）
    if [[ -z "$input_file" ]]; then
        tmp_file="$(mktemp "${TMPDIR:-/tmp}/budget-rtk-XXXXXX" 2>/dev/null)" || {
            budget_print_error "budget_rtk_compress: 临时文件创建失败"
            return 1
        }
        cat > "$tmp_file"
        input_file="$tmp_file"
    fi

    if [[ ! -f "$input_file" ]]; then
        budget_print_error "budget_rtk_compress: 文件不存在: $input_file"
        if [[ -n "$tmp_file" ]]; then
            rm -f "$tmp_file"
        fi
        return 1
    fi

    # 探测失败 → 空串（显式兜底避免 set -e 退出；降级透传）
    rtk_cmd="$(budget_rtk_available 2>/dev/null)" || rtk_cmd=""
    if [[ -n "$rtk_cmd" ]]; then
        "$rtk_cmd" cat "$input_file" 2>/dev/null || cat "$input_file" 2>/dev/null || true
    else
        cat "$input_file" 2>/dev/null || true
    fi

    if [[ -n "$tmp_file" ]]; then
        rm -f "$tmp_file"
    fi
    return 0
}

# ─── 状态查询 ────────────────────────────────────────────────────────────

# RTK 状态：可用性 + 版本 + token 节省统计（rtk gain）。
# 供工作流 / stats 展示可选调用；未安装仅提示（RTK 为可选工具），
# 恒 return 0（状态查询不作为失败语义，不阻断调用方）。
budget_rtk_status() {
    local rtk_cmd version
    rtk_cmd="$(budget_rtk_available 2>/dev/null)" || rtk_cmd=""
    if [[ -z "$rtk_cmd" ]]; then
        budget_print_info "RTK: 未安装（可选工具，不影响 BudgetBuddy 工作流）"
        return 0
    fi
    version="$("$rtk_cmd" --version 2>/dev/null || "$rtk_cmd" -V 2>/dev/null || true)"
    if [[ -n "$version" ]]; then
        budget_print_info "RTK: 已安装（${version}）"
    else
        budget_print_info "RTK: 已安装（${rtk_cmd}）"
    fi
    # token 节省统计（rtk gain；失败静默跳过，不影响状态输出）
    "$rtk_cmd" gain 2>/dev/null || true
    return 0
}
