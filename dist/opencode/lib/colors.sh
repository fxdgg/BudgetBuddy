#!/bin/bash
# BudgetBuddy colors/printing utilities

# ─── ANSI 颜色码降级（Windows 非 Git Bash 终端 / 管道重定向）────────────
budget_colors_enabled() {
    # 管道或文件重定向时禁用颜色
    [[ ! -t 1 ]] && return 1
    # Windows Git Bash/MSYS2 支持 ANSI，放行
    [[ -n "${MSYSTEM:-}" ]] && return 0
    # Linux/macOS 终端支持 ANSI
    case "$(uname -s 2>/dev/null)" in
        Linux|Darwin) return 0 ;;
    esac
    # 其他环境（原生 cmd.exe 等）禁用
    return 1
}

if budget_colors_enabled; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[1;33m'
    CYAN=$'\033[0;36m'
    BOLD=$'\033[1m'
    NC=$'\033[0m'
else
    RED=""
    GREEN=""
    YELLOW=""
    CYAN=""
    BOLD=""
    NC=""
fi

budget_print_header() {
    echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║  BudgetBuddy · 多 Agent 省钱研发工作流套件            ║${NC}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║  - 用法: budget <子命令>（budget help 查看全集）      ║${NC}"
    echo -e "${CYAN}║  - 模型预设: budget setup agent preset <档位>         ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
}

budget_print_success() { echo -e "${GREEN}[✓]${NC} $1"; }
budget_print_info() { echo -e "${CYAN}[i]${NC} $1"; }
budget_print_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
budget_print_error() { echo -e "${RED}[✗]${NC} $1"; }
