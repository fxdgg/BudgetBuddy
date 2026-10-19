#!/bin/bash
# BudgetBuddy uninstall module — setup uninstall / reinstall 子命令实现
# （design.md §8.1/§10/§12-A12②）
#
# Provides:
#   do_uninstall [--yes] [--purge] - 卸载（按本地清单或已知结构删除）
#   do_reinstall [--yes]           - uninstall（不 purge 用户数据）+ init 组合
#
# Dependencies（setup.sh source 基础层后分发调用）:
#   colors.sh   - budget_print_* / YELLOW CYAN GREEN NC
#   utils.sh    - budget_global_data_dir
#   platform.sh - detect_platform / BUDGET_SUITE_AGENTS（本套件 agent 名单）
#   shell.sh    - budget_detect_shell_rc（rc fallback 函数块清理定位）
#   init.sh     - do_init（reinstall Phase 2；就位检查后调用）
#   setup.sh 顶层导出 - BUDGET_SETUP_DIR / BUDGET_LIB_DIR / BUDGET_GLOBAL / BUDGET_PYTHON
#
# 删除策略（双路径，design.md §10 / §12-A12②）:
#   ① 清单路径：<安装根>/.budget-manifest.json 存在 → 按清单删除（离线可用，
#      清单外一律保留）；条目路径越界（绝对路径 / 含 ..）跳过并告警
#   ② 已知结构路径（本地安装形态无清单：source 部署/直接拷贝）：按本套件
#      产物枚举删除（agents 10 个 / budget+opsx 命令 / budget-* 与 openspec-*
#      skill / budget-*.mdc 规则 / hooks / lib 已知文件 / setup.sh /
#      budget-models.json / personas.json / docs）。已知结构清理在清单模式
#      下恒定运行（幂等残留扫描——清单外用户自建文件一律保留，仅套件
#      专属命名空间（前缀/名单）命中删除）
#
# 安装根定位（探测驱动）:
#   codebuddy:project → <root>/.codebuddy/；codebuddy:global → ~/.codebuddy/
#   opencode → 管理面 ~/.budgetbuddy/（A3）+ 平台结构目录（BUDGET_AGENTS_DIR
#   所在 agent/ 的父目录：~/.config/opencode/ 或 <root>/.opencode/）
#
# 用户数据保护（P0）：.budget/ 与 ~/.budgetbuddy/ 默认保留（opencode 形态
# 仅删其中的管理面产物，用户数据文件保留），--purge 显式删除。
#
# 非交互通道（任一命中即跳过交互确认）:
#   1. --yes / -y（函数参数）  2. BUDGET_UNINSTALL_YES=1（环境变量）
#   3. reinstall 组合内部调用（BUDGET_UNINSTALL_YES=1 注入）
#   stdin EOF 走默认 N 取消（卸载为破坏性操作，保守默认；与 init/update
#   的默认 Y 相反是有意设计）。
#
# 幂等约定（重复 uninstall 不报错）：对不存在文件/目录静默跳过（rm -f /
#   rm -rf || true）；探测失败（已卸载）时仅执行全局清理并正常退出。

# ─── 已知结构清单常量（design.md §8.2 lib 24 文件 + docs 产物）──────────

BUDGET_KNOWN_LIB_FILES=(
    colors.sh utils.sh platform.sh shell.sh
    init.sh update.sh uninstall.sh
    models.sh preset.sh model_resolver.py guard.sh rtk.sh
    persona.sh persona_expand.py validate.sh budget-state.py display.py
    interactive.sh quickstart.py run_summary.py banner.py
    notify.sh hooks.sh hooks_inject.py
)

# 管理面 docs 产物（codebuddy 2 项 / opencode 4 项，routing docs 映射）
BUDGET_KNOWN_DOCS_FILES=(
    MODEL_SELECTION.md PERSONAS.md architecture.md setup-notes.md
)

# ─── 内部辅助：非交互判定 ───────────────────────────────────────────────

_budget_uninstall_noninteractive() {
    # --yes / BUDGET_UNINSTALL_YES=1 时返回 0（跳过交互确认）
    [[ "${BUDGET_UNINSTALL_YES:-0}" == "1" ]] && return 0
    return 1
}

# ─── 内部辅助：交互确认（破坏性操作，默认取消）──────────────────────────

_budget_uninstall_confirm() {
    # 卸载确认：[y/N]，stdin EOF / 空 / 非 y 一律取消。
    if _budget_uninstall_noninteractive; then
        return 0
    fi
    local choice=""
    read -r -p "  确认卸载 BudgetBuddy? [y/N] " choice || true
    case "${choice:-N}" in
        [Yy]*) return 0 ;;
        *)     return 1 ;;
    esac
}

_budget_reinstall_confirm() {
    # 重装确认：[y/N]，stdin EOF / 空 / 非 y 一律取消。
    if [[ "${BUDGET_REINSTALL_YES:-0}" == "1" ]]; then
        return 0
    fi
    echo ""
    echo -e "  ${YELLOW}重装将执行以下操作:${NC}"
    echo -e "    1. 卸载本套件产物（${CYAN}保留用户数据${NC}：.budget/ 与 ~/.budgetbuddy/）"
    echo -e "    2. 重新初始化数据面（hooks / 包装器 / 数据目录）"
    echo -e "    ${YELLOW}结构文件（agents/skills/rules/lib 等）需经 install.sh 或源码重装${NC}"
    echo ""
    local choice=""
    read -r -p "  确认重装? [y/N] " choice || true
    case "${choice:-N}" in
        [Yy]*) return 0 ;;
        *)     return 1 ;;
    esac
}

# ─── 内部辅助：安装根定位（探测驱动；stdout 输出根路径，unknown 输出空）──

_budget_uninstall_install_root() {
    # 依赖调用前 detect_platform 已完成（BUDGET_PLATFORM_* 变量就位）。
    local kind="${BUDGET_PLATFORM_KIND:-unknown}"
    if [[ "$kind" == "codebuddy" ]]; then
        if [[ "${BUDGET_PLATFORM_SCOPE:-}" == "project" && -n "${BUDGET_PLATFORM_ROOT:-}" ]]; then
            echo "$BUDGET_PLATFORM_ROOT/.codebuddy"
        else
            echo "$HOME/.codebuddy"
        fi
        return 0
    fi
    if [[ "$kind" == "opencode" ]]; then
        # 管理面根（A3：setup.sh/lib/models/personas/docs 统一 ~/.budgetbuddy/）
        echo "$HOME/.budgetbuddy"
        return 0
    fi
    echo ""
    return 0
}

# ─── 内部辅助：manifest 清单条目解析（stdout 相对路径行）────────────────

_budget_uninstall_manifest_entries() {
    # 解析 <安装根>/.budget-manifest.json（A12② 格式：{"files": {<相对路径>: <sha256>}}）。
    # 安全：绝对路径 / 含 .. 的越界条目跳过并 stderr 告警；解析失败 exit 1
    # （调用方进程替换吞掉退出码，stderr 告警透传，退化为已知结构模式）。
    local manifest_file="$1"
    BUDGET_MANIFEST_FILE="$manifest_file" "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os
import sys

try:
    with open(os.environ['BUDGET_MANIFEST_FILE'], encoding='utf-8') as handle:
        data = json.load(handle)
except (OSError, ValueError) as exc:
    print('清单解析失败（退化为已知结构删除）: %s' % exc, file=sys.stderr)
    sys.exit(1)
files = data.get('files', {})
if not isinstance(files, dict):
    print('清单 files 字段非对象（退化为已知结构删除）', file=sys.stderr)
    sys.exit(1)
for rel in sorted(files):
    if not isinstance(rel, str) or not rel:
        continue
    parts = rel.replace('\\', '/').split('/')
    if rel.startswith('/') or '..' in parts:
        print('清单条目路径越界，已跳过: %s' % rel, file=sys.stderr)
        continue
    print(rel)
PYEOF
}

# ─── 内部辅助：已知结构收集（stdout 绝对路径行，仅实际存在项）────────────

_budget_uninstall_collect_codebuddy() {
    # codebuddy 安装根（.codebuddy/ 或 ~/.codebuddy/）下本套件产物枚举。
    # 命名空间纪律：仅套件专属名单/前缀命中（agents 10 名单、commands 的
    # budget/opsx 组目录、skills 的 budget-*/openspec-* 前缀、rules 的
    # budget-*.mdc 前缀、lib 已知 24 文件 + *.pyc）；清单外用户自建文件
    # （如 agents/my-agent.md、skills/my-skill/）一律不命中。
    local root="$1"
    if [[ ! -d "$root" ]]; then
        return 0
    fi
    local name path
    for name in "${BUDGET_SUITE_AGENTS[@]}"; do
        path="$root/agents/$name.md"
        if [[ -f "$path" ]]; then
            echo "$path"
        fi
    done
    for name in budget opsx; do
        path="$root/commands/$name"
        if [[ -d "$path" ]]; then
            echo "$path"
        fi
    done
    for path in "$root"/skills/budget-* "$root"/skills/openspec-*; do
        if [[ -e "$path" ]]; then
            echo "$path"
        fi
    done
    for path in "$root"/rules/budget-*.mdc; do
        if [[ -e "$path" ]]; then
            echo "$path"
        fi
    done
    if [[ -f "$root/hooks/budget-notify-hook.py" ]]; then
        echo "$root/hooks/budget-notify-hook.py"
    fi
    for name in "${BUDGET_KNOWN_LIB_FILES[@]}"; do
        path="$root/lib/$name"
        if [[ -f "$path" ]]; then
            echo "$path"
        fi
    done
    for path in "$root"/lib/*.pyc; do
        if [[ -e "$path" ]]; then
            echo "$path"
        fi
    done
    for name in MODEL_SELECTION.md PERSONAS.md; do
        path="$root/docs/$name"
        if [[ -f "$path" ]]; then
            echo "$path"
        fi
    done
    if [[ -f "$root/setup.sh" ]]; then
        echo "$root/setup.sh"
    fi
    if [[ -f "$root/budget-models.json" ]]; then
        echo "$root/budget-models.json"
    fi
    if [[ -f "$root/personas.json" ]]; then
        echo "$root/personas.json"
    fi
    return 0
}

_budget_uninstall_collect_opencode_mgmt() {
    # opencode 管理面根（~/.budgetbuddy/，A3）下本套件产物枚举。
    # 用户数据（projects/ bin/ memory/ notify.json persona-active.json）
    # 不在枚举内——默认保留；--purge 时整体删除（do_uninstall purge 段）。
    local root="$HOME/.budgetbuddy"
    if [[ ! -d "$root" ]]; then
        return 0
    fi
    local name path
    for name in "${BUDGET_KNOWN_LIB_FILES[@]}"; do
        path="$root/lib/$name"
        if [[ -f "$path" ]]; then
            echo "$path"
        fi
    done
    for path in "$root"/lib/*.pyc; do
        if [[ -e "$path" ]]; then
            echo "$path"
        fi
    done
    for name in "${BUDGET_KNOWN_DOCS_FILES[@]}"; do
        path="$root/docs/$name"
        if [[ -f "$path" ]]; then
            echo "$path"
        fi
    done
    if [[ -f "$root/setup.sh" ]]; then
        echo "$root/setup.sh"
    fi
    if [[ -f "$root/budget-models.json" ]]; then
        echo "$root/budget-models.json"
    fi
    if [[ -f "$root/personas.json" ]]; then
        echo "$root/personas.json"
    fi
    return 0
}

_budget_uninstall_collect_opencode_platform() {
    # opencode 平台结构目录（~/.config/opencode/ 或 <root>/.opencode/）下
    # 本套件产物枚举：agent/{10 名单}.md、command/budget-*.md + opsx-*.md、
    # skill/budget-* + openspec-*。AGENTS.md 标记区块清理独立处理（不删文件）。
    local agents_dir="${BUDGET_AGENTS_DIR:-}"
    if [[ -z "$agents_dir" || ! -d "$agents_dir" ]]; then
        return 0
    fi
    local struct_root
    struct_root="$(dirname "$agents_dir")"
    local name path
    for name in "${BUDGET_SUITE_AGENTS[@]}"; do
        path="$struct_root/agent/$name.md"
        if [[ -f "$path" ]]; then
            echo "$path"
        fi
    done
    for path in "$struct_root"/command/budget-*.md "$struct_root"/command/opsx-*.md; do
        if [[ -e "$path" ]]; then
            echo "$path"
        fi
    done
    for path in "$struct_root"/skill/budget-* "$struct_root"/skill/openspec-*; do
        if [[ -e "$path" ]]; then
            echo "$path"
        fi
    done
    return 0
}

# ─── 内部辅助：删除计划（stdout 绝对路径行；manifest + 已知结构去重）────

_budget_uninstall_plan() {
    # 用法: _budget_uninstall_plan <install_root> <platform_kind>
    # 输出：实际存在的待删绝对路径（排序去重）。仅收集不删除。
    local install_root="$1"
    local platform_kind="$2"
    {
        if [[ -n "$install_root" && -f "$install_root/.budget-manifest.json" ]]; then
            # || true 兜底：清单解析失败（exit 1）时管道不因 pipefail 中断，
            # stderr 告警透传后自然退化为已知结构删除
            _budget_uninstall_manifest_entries "$install_root/.budget-manifest.json" \
                | while IFS= read -r rel; do
                    if [[ -n "$rel" ]]; then
                        echo "$install_root/$rel"
                    fi
                done || true
        fi
        if [[ "$platform_kind" == "codebuddy" && -n "$install_root" ]]; then
            _budget_uninstall_collect_codebuddy "$install_root"
        elif [[ "$platform_kind" == "opencode" ]]; then
            _budget_uninstall_collect_opencode_mgmt
            _budget_uninstall_collect_opencode_platform
        fi
    } | sort -u | while IFS= read -r target; do
        if [[ -n "$target" && -e "$target" ]]; then
            echo "$target"
        fi
    done
    return 0
}

# ─── 内部辅助：settings.json hooks 清理（hooks.sh 就位时调用）───────────

_budget_uninstall_clean_settings() {
    # 调用点 + 桩：hooks 清理编排归 lib/hooks.sh budget_remove_hooks（与
    # init 的 _budget_init_hooks_inject 对称）；本函数负责：
    #   1. hooks.sh 未加载（旧版形态）时补 source
    #   2. 显式传参 settings_file（删除计划已清 setup.sh → 探测必然
    #      unknown，budget_remove_hooks 显式参数跳过探测直接操作该文件）
    #   3. 结果验证：清理后 grep budget-notify-hook 残留，残留则降级
    #      告警（不误报清理成功）
    local settings_file="$1"
    if [[ -z "$settings_file" || ! -f "$settings_file" ]]; then
        return 0
    fi
    if ! declare -f budget_remove_hooks &>/dev/null \
        && [[ -f "${BUDGET_LIB_DIR:-}/hooks.sh" ]]; then
        # shellcheck disable=SC1090  # 动态路径 source
        source "$BUDGET_LIB_DIR/hooks.sh" 2>/dev/null || true
    fi
    if declare -f budget_remove_hooks &>/dev/null; then
        if budget_remove_hooks "$settings_file"; then
            # 结果验证：残留检查（防探测失效误报清理成功）
            if grep -q "budget-notify-hook" "$settings_file" 2>/dev/null; then
                budget_print_warning "settings.json 仍含 BudgetBuddy hooks 残留，请手动检查: $settings_file"
            else
                budget_print_success "已清理 settings.json 的 BudgetBuddy hooks 注入: $settings_file"
            fi
        else
            budget_print_warning "settings.json hooks 清理失败，请手动检查: $settings_file"
        fi
        return 0
    fi
    if grep -q "budget-notify-hook" "$settings_file" 2>/dev/null; then
        budget_print_warning "settings.json 含 BudgetBuddy hooks 注入，请手动清理: $settings_file"
        budget_print_info "hooks 清理模块（lib/hooks.sh）就位后将随 uninstall 自动清理"
    else
        budget_print_info "settings.json 无 BudgetBuddy hooks 注入，跳过清理"
    fi
    return 0
}

# ─── 内部辅助：AGENTS.md 标记区块清理（opencode）────────────────────────

_budget_uninstall_clean_agents_md() {
    # 删除 <!-- BudgetBuddy:begin/end --> 标记区块（区块外内容逐行保留）；
    # 剩余内容仅空白时删除整个文件（安装器合并产物）。临时文件 + 原子替换。
    local agents_md="$1"
    if [[ -z "$agents_md" || ! -f "$agents_md" ]]; then
        return 0
    fi
    if ! grep -q "<!-- BudgetBuddy:begin -->" "$agents_md" 2>/dev/null; then
        return 0
    fi
    local tmp="${agents_md}.tmp.$$"
    if ! awk '
        /<!-- BudgetBuddy:begin -->/ { skip = 1; next }
        /<!-- BudgetBuddy:end -->/ { skip = 0; next }
        !skip { print }
    ' "$agents_md" > "$tmp" 2>/dev/null; then
        rm -f "$tmp" 2>/dev/null || true
        budget_print_warning "AGENTS.md 区块清理失败: $agents_md"
        return 0
    fi
    if [[ -z "$(tr -d '[:space:]' < "$tmp" 2>/dev/null)" ]]; then
        rm -f "$tmp" "$agents_md" 2>/dev/null || true
        budget_print_success "AGENTS.md 仅含 BudgetBuddy 区块，已删除: $agents_md"
    else
        if mv "$tmp" "$agents_md" 2>/dev/null; then
            budget_print_success "已清理 AGENTS.md 的 BudgetBuddy 标记区块: $agents_md"
        else
            rm -f "$tmp" 2>/dev/null || true
            budget_print_warning "AGENTS.md 区块清理失败: $agents_md"
        fi
    fi
    return 0
}

# ─── 内部辅助：rc 文件 budget() fallback 函数块清理 ──────────────────────

_budget_uninstall_clean_rc() {
    # 删除 shell.sh budget_inject_func 注入的标记函数块（起止标记明确，
    # 区块外 rc 内容不触碰；与注入逻辑对称的反向操作）。
    local rc_file=""
    rc_file="$(budget_detect_shell_rc)"
    if [[ -z "$rc_file" || ! -f "$rc_file" ]]; then
        return 0
    fi
    if ! grep -q "# BudgetBuddy shell function (fallback)" "$rc_file" 2>/dev/null; then
        return 0
    fi
    local tmp="${rc_file}.tmp.$$"
    if awk '/^# BudgetBuddy shell function \(fallback\)/{skip=1} skip && /^# end BudgetBuddy shell function/{skip=0; next} !skip' \
        "$rc_file" > "$tmp" 2>/dev/null && mv "$tmp" "$rc_file" 2>/dev/null; then
        budget_print_success "已清理 rc 文件的 budget() fallback 函数: $rc_file"
    else
        rm -f "$tmp" 2>/dev/null || true
        budget_print_warning "rc 文件 fallback 函数清理失败，请手动检查: $rc_file"
    fi
    return 0
}

# ─── 内部辅助：空目录清理（仅套件管理目录，rmdir 只删空目录）────────────

_budget_uninstall_clean_empty_dirs() {
    # 深层目录在前（commands/budget 先于 commands）；rmdir 对非空目录
    # 失败静默（用户自建文件保留时目录保留）。
    local root="$1"
    local platform_kind="$2"
    if [[ ! -d "$root" ]]; then
        return 0
    fi
    local -a managed_dirs
    if [[ "$platform_kind" == "codebuddy" ]]; then
        managed_dirs=(agents commands/budget commands/opsx commands skills hooks lib rules docs)
    else
        managed_dirs=(lib docs)
    fi
    local d
    for d in "${managed_dirs[@]}"; do
        if [[ -d "$root/$d" ]] && rmdir "$root/$d" 2>/dev/null; then
            budget_print_info "已删除空目录: ${root}/$d"
        fi
    done
    return 0
}

# ─── 内部辅助：卸载核心执行（无交互；do_uninstall / do_reinstall 复用）──

_budget_uninstall_execute() {
    # 用法: _budget_uninstall_execute <install_root> <platform_kind> <purge>
    #   purge: "true" 删除 .budget/ 与 ~/.budgetbuddy/；"false" 保留（默认）
    # 依赖调用前 detect_platform 已完成（BUDGET_PLATFORM_ROOT / BUDGET_AGENTS_DIR）。
    local install_root="$1"
    local platform_kind="$2"
    local purge="$3"

    local manifest_file=""
    if [[ -n "$install_root" && -f "$install_root/.budget-manifest.json" ]]; then
        manifest_file="$install_root/.budget-manifest.json"
    fi

    # 1) settings.json hooks 清理（codebuddy 形态；先于文件删除——hooks
    #    引擎 lib/hooks_inject.py 在删除计划内，删除后清理必然引擎缺失）
    if [[ "$platform_kind" == "codebuddy" && -n "$install_root" ]]; then
        _budget_uninstall_clean_settings "$install_root/settings.json"
    fi

    # 2) 删除计划（manifest + 已知结构；幂等：不存在项已被过滤）
    local removed=0
    if [[ -n "$install_root" ]]; then
        local target
        while IFS= read -r target; do
            if [[ -z "$target" ]]; then
                continue
            fi
            if rm -rf "$target" 2>/dev/null; then
                removed=$((removed + 1))
            fi
        done < <(_budget_uninstall_plan "$install_root" "$platform_kind")
    fi
    if [[ "$removed" -gt 0 ]]; then
        budget_print_success "已删除 $removed 个本套件文件"
    else
        budget_print_info "无待删除的本套件文件（可能已卸载）"
    fi

    # 3) AGENTS.md 标记区块清理（opencode 形态）
    if [[ "$platform_kind" == "opencode" ]]; then
        local agents_md=""
        if [[ "${BUDGET_PLATFORM_SCOPE:-}" == "project" && -n "${BUDGET_PLATFORM_ROOT:-}" ]]; then
            agents_md="$BUDGET_PLATFORM_ROOT/AGENTS.md"
        else
            agents_md="$HOME/.config/opencode/AGENTS.md"
        fi
        _budget_uninstall_clean_agents_md "$agents_md"
    fi

    # 4) 空目录清理（套件管理目录；rmdir 只删空目录）
    if [[ -n "$install_root" ]]; then
        _budget_uninstall_clean_empty_dirs "$install_root" "$platform_kind"
    fi
    if [[ "$platform_kind" == "opencode" && -n "${BUDGET_AGENTS_DIR:-}" ]]; then
        local struct_root
        struct_root="$(dirname "$BUDGET_AGENTS_DIR")"
        local d
        for d in agent command skill; do
            if [[ -d "$struct_root/$d" ]] && rmdir "$struct_root/$d" 2>/dev/null; then
                budget_print_info "已删除空目录: $struct_root/$d"
            fi
        done
    fi

    # 5) 用户数据处理（P0：默认保留 .budget/ 与 ~/.budgetbuddy/）
    if [[ "$purge" == "true" ]]; then
        budget_print_warning "purge 模式：删除用户数据目录"
        if [[ -n "${BUDGET_PLATFORM_ROOT:-}" && -d "$BUDGET_PLATFORM_ROOT/.budget" ]]; then
            rm -rf "$BUDGET_PLATFORM_ROOT/.budget" 2>/dev/null || true
            budget_print_info "已删除: $BUDGET_PLATFORM_ROOT/.budget"
        fi
        if [[ -n "${BUDGET_DIR:-}" && -d "${BUDGET_DIR}" ]]; then
            rm -rf "${BUDGET_DIR}" 2>/dev/null || true
            budget_print_info "已删除: ${BUDGET_DIR}（BUDGET_DIR 覆盖目录）"
        fi
        if [[ -d "$HOME/.budgetbuddy" ]]; then
            rm -rf "$HOME/.budgetbuddy" 2>/dev/null || true
            budget_print_info "已删除: $HOME/.budgetbuddy"
        fi
    else
        budget_print_info "用户数据已保留: .budget/ 与 ~/.budgetbuddy/（--purge 显式删除）"
    fi

    # 6) rc fallback 函数块清理 + 包装器移除
    _budget_uninstall_clean_rc
    local wrapper="$HOME/.local/bin/budget"
    if [[ -f "$wrapper" ]]; then
        rm -f "$wrapper" 2>/dev/null || true
        budget_print_success "已移除 budget 命令包装器: $wrapper"
    else
        budget_print_info "budget 命令包装器不存在，跳过（${wrapper}）"
    fi

    # 7) 清单文件与 setup.sh 自身最后删除（运行中进程不受影响）
    if [[ -n "$manifest_file" ]]; then
        rm -f "$manifest_file" 2>/dev/null || true
        budget_print_info "已删除: 安装清单（${manifest_file}）"
    fi
    if [[ -n "$install_root" && -f "$install_root/setup.sh" ]]; then
        rm -f "$install_root/setup.sh" 2>/dev/null || true
        budget_print_info "已删除: $install_root/setup.sh"
    fi
    return 0
}

# ─── uninstall 子命令入口（setup.sh 分发：uninstall → uninstall.sh）─────

do_uninstall() {
    # ---- 参数解析（双通道：--yes/--purge 参数 + BUDGET_* 环境变量）----
    # setup.sh 分发层透传子命令参数（do_uninstall "$@"）；环境变量通道
    # （BUDGET_UNINSTALL_YES / BUDGET_UNINSTALL_PURGE）与参数通道等效，
    # 供脚本化调用与直调场景使用。
    local purge=false
    if [[ "${BUDGET_UNINSTALL_PURGE:-0}" == "1" ]]; then
        purge=true
    fi
    local _uninstall_arg
    for _uninstall_arg in "$@"; do
        case "$_uninstall_arg" in
            --yes|-y) BUDGET_UNINSTALL_YES=1 ;;
            --purge)  purge=true ;;
            *) budget_print_warning "uninstall: 忽略未知参数 $_uninstall_arg" ;;
        esac
    done
    unset _uninstall_arg

    budget_print_header

    # ---- Step 1/4: 探测平台定位安装目录 ----
    budget_print_info "Step 1/4: 探测平台与安装目录"
    # 当前 shell 调用取变量副作用（stdout 丢弃；探测失败时 stderr 透传详情）
    detect_platform >/dev/null || true
    local platform_kind="${BUDGET_PLATFORM_KIND:-unknown}"
    local install_root=""
    install_root="$(_budget_uninstall_install_root)"

    if [[ "$platform_kind" == "unknown" ]]; then
        budget_print_warning "未检测到 BudgetBuddy 安装形态（可能已卸载）"
        budget_print_info "将仅执行全局清理（rc fallback / 包装器 / 数据目录提示）"
    else
        budget_print_info "运行平台: $platform_kind:${BUDGET_PLATFORM_SCOPE:-}${BUDGET_PLATFORM_ROOT:+ (root: $BUDGET_PLATFORM_ROOT)}"
        budget_print_info "安装目录: $install_root"
    fi
    echo ""

    # ---- Step 2/4: 删除计划预览（双路径：清单 / 已知结构）----
    budget_print_info "Step 2/4: 收集删除计划"
    local plan_text="" plan_count=0
    if [[ -n "$install_root" ]]; then
        plan_text="$(_budget_uninstall_plan "$install_root" "$platform_kind")"
        plan_count="$(printf '%s\n' "$plan_text" | grep -c '.' || true)"
    fi
    if [[ -n "$install_root" && -f "$install_root/.budget-manifest.json" ]]; then
        budget_print_info "删除策略: 按本地清单（.budget-manifest.json）+ 已知结构残留扫描"
    elif [[ -n "$install_root" ]]; then
        budget_print_info "删除策略: 本地无安装清单，按已知结构清单删除（source 部署/直接拷贝形态）"
    fi
    if [[ "$plan_count" -gt 0 ]]; then
        echo -e "  ${YELLOW}以下本套件产物将被删除（${plan_count} 项）:${NC}"
        printf '%s\n' "$plan_text" | while IFS= read -r target; do
            if [[ -n "$target" ]]; then
                echo "  - $target"
            fi
        done
    else
        budget_print_info "无待删除的本套件文件（可能已卸载）"
    fi
    echo ""

    # ---- Step 3/4: 用户数据说明 + 确认 ----
    budget_print_info "Step 3/4: 用户数据说明与确认"
    if [[ "$purge" == "true" ]]; then
        echo -e "  ${RED}purge 模式：.budget/ 与 ~/.budgetbuddy/ 将被删除（不可恢复）${NC}"
    else
        echo -e "  ${CYAN}用户数据默认保留:${NC}"
        echo -e "    - ${BUDGET_PLATFORM_ROOT:-<项目根>}/.budget/（项目数据）"
        echo -e "    - $HOME/.budgetbuddy/（全局数据；opencode 形态仅删其中管理面产物）"
        echo -e "  ${CYAN}如需彻底清理，请加 --purge 参数${NC}"
    fi
    if ! _budget_uninstall_confirm; then
        budget_print_info "已取消卸载（未做任何修改）"
        return 0
    fi
    echo ""

    # ---- Step 4/4: 执行卸载 ----
    budget_print_info "Step 4/4: 执行卸载"
    _budget_uninstall_execute "$install_root" "$platform_kind" "$purge"

    # ---- 完成汇总 ----
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  卸载完成！${NC}"
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo ""
    if [[ "$purge" != "true" ]]; then
        echo -e "  用户数据已保留: .budget/ 与 ~/.budgetbuddy/"
        echo -e "  彻底清理: ${CYAN}budget setup uninstall --purge${NC}"
    fi
    echo -e "  重新安装: ${CYAN}install.sh${NC}（release 安装）或源码部署后 ${CYAN}budget setup init${NC}"
    echo ""
    return 0
}

# ─── reinstall 子命令入口（uninstall + init 组合，design.md §8.1）───────
# 注：setup.sh 分发层 require 提示指向 update.sh（T9a 分发表），实现归
# uninstall.sh（与 do_uninstall 同文件组合复用；两文件均被 setup.sh 加载）。

do_reinstall() {
    # ---- 参数解析 ----
    local _reinstall_arg
    for _reinstall_arg in "$@"; do
        case "$_reinstall_arg" in
            --yes|-y) BUDGET_REINSTALL_YES=1 ;;
            *) budget_print_warning "reinstall: 忽略未知参数 $_reinstall_arg" ;;
        esac
    done
    unset _reinstall_arg

    budget_print_header

    # ---- 探测定位（预览与卸载共用）----
    budget_print_info "Phase 0: 探测平台与安装目录"
    detect_platform >/dev/null || true
    local platform_kind="${BUDGET_PLATFORM_KIND:-unknown}"
    local install_root=""
    install_root="$(_budget_uninstall_install_root)"
    # 形态快照（Phase 2 hooks 恢复用）：卸载清除探测依据（setup.sh）后
    # do_init 重新探测必然 unknown，全局回退路径跳过 hooks 注入——需按
    # 快照恢复形态变量并显式定位 settings.json 直调注入。
    local orig_scope="${BUDGET_PLATFORM_SCOPE:-}"
    local orig_root="${BUDGET_PLATFORM_ROOT:-}"
    local settings_file=""
    if [[ "$platform_kind" == "codebuddy" ]]; then
        if [[ "$orig_scope" == "project" && -n "$orig_root" ]]; then
            settings_file="$orig_root/.codebuddy/settings.json"
        else
            settings_file="$HOME/.codebuddy/settings.json"
        fi
    fi
    if [[ "$platform_kind" == "unknown" ]]; then
        budget_print_warning "未检测到 BudgetBuddy 安装形态（可能已卸载），执行全局重置"
    else
        budget_print_info "运行平台: $platform_kind:${BUDGET_PLATFORM_SCOPE:-}${BUDGET_PLATFORM_ROOT:+ (root: $BUDGET_PLATFORM_ROOT)}"
        budget_print_info "安装目录: $install_root"
    fi
    echo ""

    # ---- 交互确认（非交互通道直接通过；取消时不做任何修改）----
    if ! _budget_reinstall_confirm; then
        budget_print_info "已取消重装（未做任何修改）"
        return 0
    fi

    # ---- hooks 引擎暂存（Phase 1 删除 lib 后 Phase 2 恢复注入仍需引擎）----
    # hooks_inject.py 为自包含单文件（仅标准库依赖），暂存副本供 Phase 2
    # 恢复注入使用；暂存失败（无写权限等）降级为恢复时直调（引擎可能缺失，
    # warning 提示补全，不阻断重装主流程）。
    local hooks_engine_dir=""
    if [[ "$platform_kind" == "codebuddy" && -n "$settings_file" \
          && -f "${BUDGET_LIB_DIR:-}/hooks_inject.py" ]]; then
        hooks_engine_dir="$(mktemp -d 2>/dev/null || mktemp -d -t budget-hooks)" || hooks_engine_dir=""
        if [[ -z "$hooks_engine_dir" ]] \
            || ! cp "${BUDGET_LIB_DIR}/hooks_inject.py" "$hooks_engine_dir/hooks_inject.py" 2>/dev/null; then
            [[ -n "$hooks_engine_dir" ]] && rm -rf "$hooks_engine_dir" 2>/dev/null || true
            hooks_engine_dir=""
        fi
    fi

    # ---- Phase 1/2: 卸载（不 purge 用户数据；非交互）----
    budget_print_info "Phase 1/2: 卸载本套件产物（保留用户数据）"
    BUDGET_UNINSTALL_YES=1 _budget_uninstall_execute "$install_root" "$platform_kind" "false"
    echo ""

    # ---- Phase 2/2: 重新初始化（两级回退）----
    budget_print_info "Phase 2/2: 重新初始化"
    if ! declare -f do_init &>/dev/null; then
        budget_print_error "init 模块未就位（lib/init.sh），无法完成重装"
        budget_print_info "请重新安装本套件后运行 budget setup init"
        [[ -n "$hooks_engine_dir" ]] && rm -rf "$hooks_engine_dir" 2>/dev/null || true
        return 1
    fi
    if BUDGET_INIT_YES=1 do_init --yes; then
        budget_print_success "初始化完成"
    else
        # 卸载清除了安装形态（setup.sh 已删 → 探测 unknown）→ 回退全局初始化
        budget_print_warning "安装形态已清除，回退全局数据初始化"
        if ! BUDGET_GLOBAL=1 BUDGET_INIT_YES=1 do_init --yes; then
            budget_print_error "全局初始化失败，重装未完成"
            [[ -n "$hooks_engine_dir" ]] && rm -rf "$hooks_engine_dir" 2>/dev/null || true
            return 1
        fi
    fi

    # ---- hooks 恢复（codebuddy 形态）----
    # do_init 全局回退路径探测 unknown → 跳过 hooks 注入（Step 5 仅
    # codebuddy 形态执行）；卸载已真正清理 settings.json（P1-1 修复后
    # 不再依赖残留巧合），重装必须重新注入。按 Phase 0 快照恢复形态
    # 变量（hook_cmd 落点与 settings_file 同形态）后显式定位直调注入；
    # 引擎用 Phase 1 前暂存副本（安装形态 lib 已删）。幂等：do_init 探测
    # 命中残留形态时已注入过 → 引擎 no_change 跳过。
    if [[ "$platform_kind" == "codebuddy" && -n "$settings_file" ]] \
        && declare -f budget_inject_hooks &>/dev/null; then
        BUDGET_PLATFORM_KIND="$platform_kind"
        BUDGET_PLATFORM_SCOPE="$orig_scope"
        BUDGET_PLATFORM_ROOT="$orig_root"
        budget_print_info "恢复 hooks 注入（重装前已清理，按卸载前形态定位）"
        local hooks_rc=0
        if [[ -n "$hooks_engine_dir" ]]; then
            BUDGET_LIB_DIR="$hooks_engine_dir" budget_inject_hooks "$settings_file" || hooks_rc=$?
        else
            budget_inject_hooks "$settings_file" || hooks_rc=$?
        fi
        if [[ "$hooks_rc" -eq 0 ]]; then
            budget_print_success "hooks 已随重装恢复: $settings_file"
        else
            budget_print_warning "hooks 恢复失败，可运行 budget setup init 补全"
        fi
    fi
    [[ -n "$hooks_engine_dir" ]] && rm -rf "$hooks_engine_dir" 2>/dev/null || true

    # ---- 完成汇总 ----
    echo ""
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  重装完成！${NC}"
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  用户数据已保留: .budget/ 与 ~/.budgetbuddy/（persona / notify / memory）"
    echo -e "  结构文件（agents / skills / rules / lib 等）已清除，重装途径:"
    echo -e "    - ${CYAN}install.sh${NC}（release 安装，含 SHA256 校验）"
    echo -e "    - 源码部署后运行 ${CYAN}budget setup init${NC}"
    echo ""
    return 0
}
