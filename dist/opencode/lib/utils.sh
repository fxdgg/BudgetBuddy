#!/bin/bash
# BudgetBuddy utilities

# ─── Windows / MSYS2 兼容检测 ────────────────────────────────────────────
# 检测当前是否运行在 Windows Git Bash / MSYS2 环境下
budget_is_windows() {
    [[ -n "${MSYSTEM:-}" ]] && return 0
    case "$(uname -s 2>/dev/null)" in
        MINGW*|MSYS*|CYGWIN*) return 0 ;;
    esac
    return 1
}

# 创建临时目录，Windows 下自动转换路径格式供原生程序使用
budget_mktemp_dir() {
    local tmp
    tmp=$(mktemp -d 2>/dev/null || mktemp -d -t budget)
    if budget_is_windows && command -v cygpath &>/dev/null; then
        tmp=$(cygpath -m "$tmp")
    fi
    echo "$tmp"
}

# 跨平台 sed 原地编辑（macOS 需要 -i ''，Linux/Git Bash 用 -i）
budget_sed_inplace() {
    local pattern="$1"
    local file="$2"
    case "$(uname -s 2>/dev/null)" in
        Darwin) sed -i '' "$pattern" "$file" ;;
        *)      sed -i  "$pattern" "$file" ;;
    esac
}

# 检测 Python 可执行命令（Windows 上通常为 python 而非 python3）
budget_resolve_python() {
    if [[ -n "${BUDGET_PYTHON:-}" ]] && command -v "$BUDGET_PYTHON" &>/dev/null; then
        echo "$BUDGET_PYTHON"
        return 0
    fi
    if command -v python3 &>/dev/null; then
        echo "python3"
    elif command -v python &>/dev/null; then
        echo "python"
    else
        echo "python3"  # fallback，让后续报错自然产生
    fi
    return 0
}

# 读取 JSON 文件的点路径字段
# 用法: budget_json_get <file> <a.b.c> [default]
# 文件缺失/解析失败/路径不存在时输出 default（缺省空串）；
# dict/list 值输出 JSON 文本（ensure_ascii=False）。
budget_json_get() {
    local file="$1"
    local path="$2"
    local default="${3:-}"
    if [[ ! -f "$file" ]]; then
        echo "$default"
        return 0
    fi
    local result=""
    result=$(BUDGET_JSON_FILE="$file" BUDGET_JSON_PATH="$path" \
        "${BUDGET_PYTHON:-python3}" -c '
import json, os
try:
    with open(os.environ["BUDGET_JSON_FILE"], encoding="utf-8") as f:
        value = json.load(f)
    for key in os.environ["BUDGET_JSON_PATH"].split("."):
        value = value.get(key) if isinstance(value, dict) else None
        if value is None:
            break
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False))
    elif value is not None:
        print(value)
except Exception:
    pass
' 2>/dev/null) || true
    if [[ -n "$result" ]]; then
        echo "$result"
    else
        echo "$default"
    fi
}

# ─── 数据目录约定（design.md §8.4）──────────────────────────────────────
# 全局数据目录：~/.budgetbuddy/（固定；Coder Guard 等跨会话数据落点）
budget_global_data_dir() {
    echo "$HOME/.budgetbuddy"
}

# 项目级数据目录：向上查找 .budget/（最多 10 层父目录）；未找到输出空串
budget_project_data_dir() {
    local dir
    dir="$(pwd -P)"
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if [[ -d "$dir/.budget" ]]; then
            echo "$dir/.budget"
            return 0
        fi
        [[ "$dir" == "/" ]] && break
        dir="$(dirname "$dir")"
    done
    return 0
}

# 生效数据目录（读取优先级，design.md §8.4）：
#   BUDGET_DIR 显式覆盖 > 项目级 .budget/ > 全局 ~/.budgetbuddy/
budget_data_dir() {
    if [[ -n "${BUDGET_DIR:-}" ]]; then
        echo "$BUDGET_DIR"
        return 0
    fi
    local project_dir
    project_dir="$(budget_project_data_dir)"
    if [[ -n "$project_dir" ]]; then
        echo "$project_dir"
        return 0
    fi
    budget_global_data_dir
}

# ─── budget CLI 包装器写入（~/.local/bin/budget）────────────────────────
# 设计归属：包装器写入发生在 init 流程（lib/init.sh 的 do_init 调用本函数，
# design.md §8.1「budget CLI 包装器」）；本函数仅提供写入能力。
# 先删旧文件再写入，防止旧版软链接导致 cat > 跟随链接覆盖 setup.sh 本体；
# 幂等重装不产生坏符号链接（每次覆盖写入 + chmod +x）。
budget_install_wrapper() {
    local wrapper_dir="$HOME/.local/bin"
    mkdir -p "$wrapper_dir"
    rm -f "$wrapper_dir/budget"
    local wrapper="$wrapper_dir/budget"
    cat > "$wrapper" << 'WRAPPER_EOF'
#!/bin/bash
# BUDGET_WRAPPER_MARKER: this is the budget dispatch wrapper, not setup.sh
# budget wrapper — auto-detect project setup.sh, fallback to global
_detect() {
    local dir
    dir="$(pwd)"
    while [[ "$dir" != "/" ]]; do
        if [[ -f "$dir/.codebuddy/setup.sh" ]]; then
            # 防止 wrapper 误覆盖 setup.sh 本体时自递归：跳过含 wrapper marker 的文件
            if head -2 "$dir/.codebuddy/setup.sh" 2>/dev/null | grep -q "BUDGET_WRAPPER_MARKER"; then
                dir="$(dirname "$dir")"
                continue
            fi
            echo "$dir/.codebuddy/setup.sh"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    local candidate
    for candidate in "$HOME/.codebuddy/setup.sh" "$HOME/.budgetbuddy/setup.sh"; do
        if [[ -f "$candidate" ]]; then
            if head -2 "$candidate" 2>/dev/null | grep -q "BUDGET_WRAPPER_MARKER"; then
                continue
            fi
            echo "$candidate"
            return 0
        fi
    done
    return 1
}
target="$(_detect)"
if [[ -z "$target" ]]; then
    echo "budget: no BudgetBuddy setup.sh found (try running 'budget setup init' first)" >&2
    exit 1
fi
exec bash "$target" "$@"
WRAPPER_EOF
    chmod +x "$wrapper"
}
