#!/bin/bash
# BudgetBuddy platform detection utilities（design.md §8.3）

# 检测操作系统类型
budget_detect_os() {
    case "$(uname -s 2>/dev/null)" in
        Darwin)               echo "macos" ;;
        Linux)                echo "linux" ;;
        MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
        *)                    echo "unknown" ;;
    esac
}

# 本套件 agent 文件名清单（opencode/claudecode agent 目录探测的判定基准）
BUDGET_SUITE_AGENTS=(
    architect coder-lite coder-standard coder-senior reviewer reviewer-b
    tester recorder director goal-evaluator
)

# 判断目录中是否存在本套件 agent 文件（任一命中即算）
_budget_has_suite_agents() {
    local dir="$1"
    local name
    [[ -d "$dir" ]] || return 1
    for name in "${BUDGET_SUITE_AGENTS[@]}"; do
        [[ -f "$dir/$name.md" ]] && return 0
    done
    return 1
}

# 运行时平台探测（design.md §8.3 / add-claudecode-platform D5 五分支）：
#   ① 向上查找 .codebuddy/setup.sh（最多 10 层父目录）→ codebuddy 项目级
#   ② ~/.codebuddy/setup.sh → codebuddy 全局
#   ③ 向上查找 .claude/agents/ 含本套件 agent → claudecode 项目级
#   ④ ~/.claude/agents/ 含本套件 agent → claudecode 全局
#   ⑤ .opencode/agent/（项目级，优先，向上查找）或 ~/.config/opencode/agent/
#      存在本套件 agent → opencode
#   同时命中多个形态时按探测序取先（codebuddy > claudecode > opencode）。
#   五级均未命中 → stderr 报错并列出已检测位置（不静默猜默认），
#   stdout 输出 unknown 并返回 1。
# BUDGET_PLATFORM 显式指定（codebuddy|claudecode|opencode，非交互/安装器场景）
# 时跳过探测，视为全局形态；非法值忽略并继续探测。
#
# stdout 输出格式（同时将探测结果写入全局变量，供 agent preset/custom
# 与 hooks 注入定位落点；命令替换调用时变量副作用不传播，需当前 shell
# 直接调用）：
#   codebuddy:project:<path> / codebuddy:global /
#   claudecode:project / claudecode:global /
#   opencode:project / opencode:global / unknown
# 全局变量：BUDGET_PLATFORM_KIND（codebuddy|claudecode|opencode|unknown）、
#   BUDGET_PLATFORM_SCOPE（project|global）、BUDGET_PLATFORM_ROOT
#   （项目根绝对路径，project 形态时非空）、BUDGET_AGENTS_DIR
#   （claudecode 形态下 hooks 注入由 hooks.sh 按 kind != codebuddy 跳过）。
detect_platform() {
    BUDGET_PLATFORM_KIND="unknown"
    BUDGET_PLATFORM_SCOPE=""
    BUDGET_PLATFORM_ROOT=""
    BUDGET_AGENTS_DIR=""

    # 0) BUDGET_PLATFORM 显式覆盖
    if [[ -n "${BUDGET_PLATFORM:-}" ]]; then
        case "$BUDGET_PLATFORM" in
            codebuddy)
                BUDGET_PLATFORM_KIND="codebuddy"
                BUDGET_PLATFORM_SCOPE="global"
                BUDGET_AGENTS_DIR="$HOME/.codebuddy/agents"
                echo "codebuddy:global"
                return 0
                ;;
            claudecode)
                BUDGET_PLATFORM_KIND="claudecode"
                BUDGET_PLATFORM_SCOPE="global"
                BUDGET_AGENTS_DIR="$HOME/.claude/agents"
                echo "claudecode:global"
                return 0
                ;;
            opencode)
                BUDGET_PLATFORM_KIND="opencode"
                BUDGET_PLATFORM_SCOPE="global"
                BUDGET_AGENTS_DIR="$HOME/.config/opencode/agent"
                echo "opencode:global"
                return 0
                ;;
            *)
                echo "detect_platform: BUDGET_PLATFORM 值非法（${BUDGET_PLATFORM}），已忽略" >&2
                ;;
        esac
    fi

    local dir
    local i

    # ① 向上查找 .codebuddy/setup.sh（最多 10 层父目录）
    dir="$(pwd -P)"
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if [[ -f "$dir/.codebuddy/setup.sh" ]]; then
            BUDGET_PLATFORM_KIND="codebuddy"
            BUDGET_PLATFORM_SCOPE="project"
            BUDGET_PLATFORM_ROOT="$dir"
            BUDGET_AGENTS_DIR="$dir/.codebuddy/agents"
            echo "codebuddy:project:$dir"
            return 0
        fi
        [[ "$dir" == "/" ]] && break
        dir="$(dirname "$dir")"
    done

    # ② ~/.codebuddy/setup.sh → codebuddy 全局
    if [[ -f "$HOME/.codebuddy/setup.sh" ]]; then
        BUDGET_PLATFORM_KIND="codebuddy"
        BUDGET_PLATFORM_SCOPE="global"
        BUDGET_AGENTS_DIR="$HOME/.codebuddy/agents"
        echo "codebuddy:global"
        return 0
    fi

    # ③ 向上查找 .claude/agents/ 含本套件 agent（最多 10 层父目录）→ claudecode 项目级
    dir="$(pwd -P)"
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if _budget_has_suite_agents "$dir/.claude/agents"; then
            BUDGET_PLATFORM_KIND="claudecode"
            BUDGET_PLATFORM_SCOPE="project"
            BUDGET_PLATFORM_ROOT="$dir"
            BUDGET_AGENTS_DIR="$dir/.claude/agents"
            echo "claudecode:project"
            return 0
        fi
        [[ "$dir" == "/" ]] && break
        dir="$(dirname "$dir")"
    done

    # ④ ~/.claude/agents/ 存在本套件 agent → claudecode 全局
    if _budget_has_suite_agents "$HOME/.claude/agents"; then
        BUDGET_PLATFORM_KIND="claudecode"
        BUDGET_PLATFORM_SCOPE="global"
        BUDGET_AGENTS_DIR="$HOME/.claude/agents"
        echo "claudecode:global"
        return 0
    fi

    # ⑤ .opencode/agent/（项目级，优先，向上查找）→ opencode 项目级
    dir="$(pwd -P)"
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if _budget_has_suite_agents "$dir/.opencode/agent"; then
            BUDGET_PLATFORM_KIND="opencode"
            BUDGET_PLATFORM_SCOPE="project"
            BUDGET_PLATFORM_ROOT="$dir"
            BUDGET_AGENTS_DIR="$dir/.opencode/agent"
            echo "opencode:project"
            return 0
        fi
        [[ "$dir" == "/" ]] && break
        dir="$(dirname "$dir")"
    done

    # ⑤' ~/.config/opencode/agent/ 存在本套件 agent → opencode 全局
    if _budget_has_suite_agents "$HOME/.config/opencode/agent"; then
        BUDGET_PLATFORM_KIND="opencode"
        BUDGET_PLATFORM_SCOPE="global"
        BUDGET_AGENTS_DIR="$HOME/.config/opencode/agent"
        echo "opencode:global"
        return 0
    fi

    # 五级均未命中：显式报错并列出已检测位置（不静默猜默认）
    echo "[✗] 未检测到 BudgetBuddy 安装形态（五级探测均未命中）" >&2
    echo "已检测位置：" >&2
    echo "  - $(pwd -P) 及其向上至多 10 层父目录下的 .codebuddy/setup.sh" >&2
    echo "  - $HOME/.codebuddy/setup.sh" >&2
    echo "  - $(pwd -P) 及其向上至多 10 层父目录下的 .claude/agents/（本套件 agent）" >&2
    echo "  - $HOME/.claude/agents/（本套件 agent）" >&2
    echo "  - $(pwd -P) 及其向上至多 10 层父目录下的 .opencode/agent/（本套件 agent）" >&2
    echo "  - $HOME/.config/opencode/agent/（本套件 agent）" >&2
    echo "提示：可设置 BUDGET_PLATFORM=codebuddy|claudecode|opencode 显式指定平台" >&2
    echo "unknown"
    return 1
}
