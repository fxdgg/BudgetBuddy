#!/bin/bash
# BudgetBuddy update module — setup update / diff 子命令实现（design.md §8.1/§8.4/§12-A9）
#
# Provides:
#   do_update            - 增量更新流程（Step 1-5：探测/lib 同步/管理面刷新/hooks/diff）
#   do_diff [preset]     - 当前 agent model 值 vs 指定预设对比表（默认 balanced）
#
# Dependencies（setup.sh source 基础层后分发调用）:
#   colors.sh   - budget_print_* / YELLOW CYAN GREEN NC
#   utils.sh    - budget_global_data_dir / budget_mktemp_dir
#   platform.sh - detect_platform（当前 shell 调用取变量副作用）
#   preset.sh   - budget_get_current_models / budget_preset_table（T10a 契约，
#                 输出 "<agent>=<model>" 行；do_diff 的查询数据源）
#   init.sh     - _budget_init_sync_lib / _budget_init_personas_src /
#                 _budget_init_hooks_inject（T9b 契约；就位时复用，未就位内置等效）
#   setup.sh 顶层导出 - BUDGET_SETUP_DIR / BUDGET_LIB_DIR / BUDGET_MODELS_FILE /
#                       BUDGET_GLOBAL / BUDGET_PYTHON
#
# 版本策略（A9）：不做在线版本协商（无 latest.json / 无升级探测服务端）。
# update 的「最新版」= 当前安装目录（BUDGET_SETUP_DIR）内的管理面数据；
# 在线重装归 install.sh（T11，release zip + SHA256 校验）。
#
# 非交互通道（任一命中即跳过交互确认）:
#   1. do_update --yes / -y（函数参数）
#   2. BUDGET_UPDATE_YES=1（环境变量）
#   3. stdin EOF（read 失败 || true 兜底，默认 Y 继续——update 非破坏用户数据）
#
# 幂等约定（重复 update 不报错）:
#   - lib 同步内容一致跳过；源即目标（管理面形态）跳过
#   - 管理面数据刷新为覆盖语义（与 init 的「存在即保留」相反，任务契约），
#     但用户数据 persona-active.json / notify.json / memory/ 一律不触碰
#   - hooks 注入幂等（T10d 契约）；diff 为只读展示

# ─── 内部辅助：非交互判定 ───────────────────────────────────────────────

_budget_update_noninteractive() {
    # --yes / BUDGET_UPDATE_YES=1 时返回 0（跳过交互确认）
    [[ "${BUDGET_UPDATE_YES:-0}" == "1" ]] && return 0
    return 1
}

# ─── 内部辅助：交互确认 ─────────────────────────────────────────────────

_budget_update_confirm() {
    # update 总确认：展示操作概要并询问；非交互通道直接通过。
    # read 一律 || true 兜底：stdin EOF（非交互调用）走默认 Y 继续执行
    # （update 保留全部用户数据，保守性与 init 一致）。
    local global_dir="$1"
    if _budget_update_noninteractive; then
        return 0
    fi
    echo ""
    echo -e "  ${YELLOW}更新将执行以下操作:${NC}"
    echo -e "    1. 同步 lib 模块到全局单点: ${CYAN}${global_dir}/lib${NC}"
    echo -e "    2. 刷新管理面数据（budget-models.json / personas.json，${YELLOW}覆盖语义${NC}）"
    echo -e "    3. 重新注入 hooks（codebuddy 形态，模块就位时）"
    echo -e "    4. 展示 agent model 配置对比（diff）"
    echo ""
    echo -e "  ${CYAN}用户数据（persona-active.json / notify.json / memory/）一律保留${NC}"
    echo ""
    local choice=""
    read -r -p "  继续更新? [Y/n] " choice || true
    case "${choice:-Y}" in
        [Nn]*) return 1 ;;
        *)     return 0 ;;
    esac
}

# ─── 内部辅助：lib 全局单点同步（A4）────────────────────────────────────

_budget_update_sync_lib() {
    # $BUDGET_LIB_DIR → 目标目录（~/.budgetbuddy/lib/）。
    # 优先复用 T9b init 的同步函数（_budget_init_sync_lib）；init.sh 未就位时
    # 使用内置等效实现。纪律与 init 一致：排除 *.pyc（禁 pyc 分发）、
    # 源即目标跳过、内容一致跳过（幂等）。
    local dest_dir="$1"
    if declare -f _budget_init_sync_lib &>/dev/null; then
        _budget_init_sync_lib "$dest_dir"
        return $?
    fi
    local src_dir="${BUDGET_LIB_DIR:-}"
    if [[ -z "$src_dir" || ! -d "$src_dir" ]]; then
        budget_print_warning "lib 源目录缺失（${src_dir:-空}），跳过同步"
        return 0
    fi
    local src_real dest_real
    src_real="$(cd "$src_dir" 2>/dev/null && pwd -P)" || return 0
    dest_real="$(cd "$dest_dir" 2>/dev/null && pwd -P)" || return 0
    if [[ "$src_real" == "$dest_real" ]]; then
        return 0
    fi
    if ! mkdir -p "$dest_dir"; then
        budget_print_error "lib 目标目录创建失败: $dest_dir"
        return 1
    fi
    local item dest_file synced=0
    for item in "$src_dir"/*; do
        if [[ ! -f "$item" ]]; then
            continue
        fi
        case "${item##*/}" in
            *.pyc) continue ;;
        esac
        dest_file="$dest_dir/${item##*/}"
        if [[ ! -f "$dest_file" ]] || ! cmp -s "$item" "$dest_file"; then
            if ! cp -f "$item" "$dest_file"; then
                budget_print_error "lib 同步失败: $item"
                return 1
            fi
            synced=$((synced + 1))
        fi
    done
    if [[ "$synced" -gt 0 ]]; then
        budget_print_success "已同步 lib 模块到 ${dest_dir}（$synced 个文件）"
    fi
    return 0
}

# ─── 内部辅助：personas.json 源定位 ─────────────────────────────────────

_budget_update_personas_src() {
    # 优先复用 T9b init 的源探测（_budget_init_personas_src：codebuddy 项目级
    # → 全局 → 全局数据目录 → setup.sh 同目录 → core 源形态）；
    # init.sh 未就位时使用内置简化探测（安装形态 / core 源形态）。
    if declare -f _budget_init_personas_src &>/dev/null; then
        _budget_init_personas_src
        return $?
    fi
    if [[ -f "$BUDGET_SETUP_DIR/personas.json" ]]; then
        echo "$BUDGET_SETUP_DIR/personas.json"
        return 0
    fi
    if [[ -f "$BUDGET_SETUP_DIR/personas/personas.json" ]]; then
        echo "$BUDGET_SETUP_DIR/personas/personas.json"
        return 0
    fi
    return 1
}

# ─── 内部辅助：文件物理路径（不存在输出空串）────────────────────────────

_budget_update_realpath_file() {
    local file="$1"
    if [[ ! -e "$file" ]]; then
        echo ""
        return 0
    fi
    local dir base
    dir="$(cd "$(dirname "$file")" 2>/dev/null && pwd -P)" || { echo ""; return 0; }
    base="$(basename "$file")"
    echo "$dir/$base"
}

# ─── 内部辅助：管理面数据覆盖刷新（任务契约：与 init 的保留语义相反）────

_budget_update_refresh_file() {
    # 用法: _budget_update_refresh_file <src> <dest> <label>
    # 覆盖语义：目标已存在也刷新为源版本（用户对管理面数据的本地修改会被
    # 覆盖——这是 update 的预期行为；用户数据不在刷新范围）。
    # 源缺失告警跳过；源即目标跳过；内容一致跳过（幂等）。
    local src="$1"
    local dest="$2"
    local label="$3"
    if [[ -z "$src" || ! -f "$src" ]]; then
        budget_print_warning "$label 源文件缺失，跳过刷新"
        return 0
    fi
    local src_real dest_real
    src_real="$(_budget_update_realpath_file "$src")"
    dest_real="$(_budget_update_realpath_file "$dest")"
    if [[ -n "$src_real" && "$src_real" == "$dest_real" ]]; then
        budget_print_info "$label 源即目标（${dest}），跳过"
        return 0
    fi
    if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then
        budget_print_info "$label 已是最新，跳过（${dest}）"
        return 0
    fi
    if cp -f "$src" "$dest" 2>/dev/null; then
        budget_print_success "已刷新 $label: ${dest}（覆盖为安装目录版本）"
        return 0
    fi
    budget_print_error "$label 刷新失败: $src → $dest"
    return 1
}

_budget_update_admin_data() {
    # 管理面数据（budget-models.json / personas.json）覆盖刷新。
    # 落位条件与 init 对齐（design.md §8.4）：opencode/claudecode 任意形态 /
    # codebuddy 全局 / BUDGET_GLOBAL=1 → 全局数据目录；
    # codebuddy 项目级 → 管理面数据位于安装目录本身，随安装包更新。
    local global_dir="$1"
    local platform_kind="$2"
    local platform_scope="$3"

    local need_admin=false
    if [[ "$platform_kind" == "opencode" || "$platform_kind" == "claudecode" \
          || ( "$platform_kind" == "codebuddy" && "$platform_scope" == "global" ) \
          || "${BUDGET_GLOBAL:-0}" == "1" ]]; then
        need_admin=true
    fi
    if [[ "$need_admin" != "true" ]]; then
        budget_print_info "项目级形态：管理面数据位于安装目录（${BUDGET_SETUP_DIR}），随安装包更新"
        return 0
    fi

    if ! _budget_update_refresh_file "$BUDGET_MODELS_FILE" \
        "$global_dir/budget-models.json" "模型目录"; then
        return 1
    fi
    local personas_src=""
    personas_src="$(_budget_update_personas_src)" || personas_src=""
    if ! _budget_update_refresh_file "$personas_src" \
        "$global_dir/personas.json" "persona 主题数据"; then
        return 1
    fi
    return 0
}

# ─── 内部辅助：hooks 注入调用点（T10d 就位时注入）───────────────────────

_budget_update_hooks_inject() {
    # 优先复用 T9b init 的注入编排调用点（_budget_init_hooks_inject：
    # budget_inject_hooks 已定义 → 调用；模块文件在 → 补 source 后调用；
    # 未就位 → 提示跳过）；init.sh 未就位时内联等效桩。
    if declare -f _budget_init_hooks_inject &>/dev/null; then
        _budget_init_hooks_inject
        return $?
    fi
    if declare -f budget_inject_hooks &>/dev/null; then
        budget_inject_hooks
        return $?
    fi
    if [[ -f "${BUDGET_LIB_DIR:-}/hooks.sh" && -f "${BUDGET_LIB_DIR:-}/hooks_inject.py" ]]; then
        # shellcheck disable=SC1090  # 动态路径 source
        source "$BUDGET_LIB_DIR/hooks.sh" 2>/dev/null || true
        if declare -f budget_inject_hooks &>/dev/null; then
            budget_inject_hooks
            return $?
        fi
    fi
    budget_print_warning "hooks 注入模块未安装，可稍后运行 budget setup init 补全"
    return 0
}

# ─── diff 核心渲染（do_diff 实现 + do_update Step 5 复用）───────────────
# 数据源：preset.sh 契约函数（T10a）：
#   budget_get_current_models  - 当前全部 agent 的 model 值（"agent=model" 行）
#   budget_preset_table <name> - 指定预设的 agent→模型表（"agent=model" 行）
# 两表按 agent 名 join，输出对齐对比表（✓ 一致 / ✗ 差异）。

_budget_diff_render() {
    local preset_name="${1:-balanced}"

    if ! declare -f budget_get_current_models &>/dev/null \
       || ! declare -f budget_preset_table &>/dev/null; then
        budget_print_error "diff 查询函数未就位（lib/preset.sh）"
        budget_print_info "请先完成安装或更新：budget setup update"
        return 1
    fi

    # 平台探测（budget_get_current_models 内部亦探测；此处先显式探测给出友好错误）
    detect_platform >/dev/null || true
    if [[ "${BUDGET_PLATFORM_KIND:-unknown}" == "unknown" ]]; then
        budget_print_error "未检测到 BudgetBuddy 平台形态，无法定位 agent 目录"
        budget_print_info "提示：可设置 BUDGET_PLATFORM=codebuddy|claudecode|opencode 显式指定平台"
        return 1
    fi

    local current_out="" preset_out="" rc=0
    current_out="$(budget_get_current_models)" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        budget_print_error "当前 agent model 值读取失败（agent 目录: ${BUDGET_AGENTS_DIR:-空}）"
        return 1
    fi
    rc=0
    preset_out="$(budget_preset_table "$preset_name")" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        budget_print_error "预设 '${preset_name}' 查询失败（可用档位: economic / balanced / quality）"
        return 1
    fi

    # 两表经临时文件传递，python join 渲染（bash 3.2 无关联数组，macOS 兼容）
    local tmp_dir=""
    tmp_dir="$(budget_mktemp_dir)"
    if [[ -z "$tmp_dir" || ! -d "$tmp_dir" ]]; then
        budget_print_error "diff 临时目录创建失败"
        return 1
    fi
    printf '%s\n' "$current_out" > "$tmp_dir/current.txt" || true
    printf '%s\n' "$preset_out" > "$tmp_dir/preset.txt" || true
    # || py_rc=$? 兜底：setup.sh set -e 下 python 失败不退出（捕获退出码）
    local py_rc=0
    BUDGET_DIFF_CURRENT="$tmp_dir/current.txt" \
    BUDGET_DIFF_PRESET="$tmp_dir/preset.txt" \
    BUDGET_DIFF_PRESET_NAME="$preset_name" \
    BUDGET_DIFF_PLATFORM="${BUDGET_PLATFORM_KIND:-}" \
        "${BUDGET_PYTHON:-python3}" << 'PYEOF' || py_rc=$?
import os
import sys


def load_lines(path):
    table = {}
    try:
        with open(path, encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line or '=' not in line:
                    continue
                agent, model = line.split('=', 1)
                table[agent.strip()] = model.strip()
    except (OSError, UnicodeDecodeError) as exc:
        print('diff 输入读取失败: %s' % exc, file=sys.stderr)
        sys.exit(1)
    return table


current = load_lines(os.environ['BUDGET_DIFF_CURRENT'])
preset = load_lines(os.environ['BUDGET_DIFF_PRESET'])
preset_name = os.environ.get('BUDGET_DIFF_PRESET_NAME', 'balanced')
platform = os.environ.get('BUDGET_DIFF_PLATFORM', '-')

agents = sorted(set(current) | set(preset))
rows = []
same = diff = 0
for agent in agents:
    cur = current.get(agent)
    pre = preset.get(agent)
    if cur is None:
        cur_disp = '（不在安装中）'
    elif cur == '':
        cur_disp = '（未设置）'
    else:
        cur_disp = cur
    if pre is None:
        pre_disp = '（预设未覆盖）'
    elif pre == '':
        pre_disp = '（未设置）'
    else:
        pre_disp = pre
    if cur is not None and pre is not None and cur == pre:
        status = '✓ 一致'
        same += 1
    else:
        status = '✗ 差异'
        diff += 1
    rows.append((agent, cur_disp, pre_disp, status))

print('当前配置 vs 预设 %s（平台 %s）：' % (preset_name, platform))
print('')
if not rows:
    print('（无 agent 数据）')
    sys.exit(0)
headers = ('Agent', '当前 Model', '预设 Model', '状态')
widths = []
for i, header in enumerate(headers):
    widths.append(max([len(header)] + [len(row[i]) for row in rows]))
fmt = '  ' + '  '.join('%-' + str(w) + 's' for w in widths)
print(fmt % headers)
print('  ' + '-' * (sum(widths) + 2 * (len(widths) - 1)))
for row in rows:
    print(fmt % row)
print('')
print('共 %d 个 agent：%d 个一致，%d 个差异。' % (len(rows), same, diff))
if diff:
    print('应用预设: budget setup agent preset %s' % preset_name)
else:
    print('当前配置与预设 %s 完全一致。' % preset_name)
PYEOF
    rm -rf "$tmp_dir" 2>/dev/null || true
    return "$py_rc"
}

# ─── diff 子命令入口（setup.sh 分发：diff → update.sh:do_diff）──────────

do_diff() {
    local preset_name="${1:-balanced}"
    budget_print_header
    _budget_diff_render "$preset_name"
}

# ─── update 子命令入口（setup.sh 分发：update → update.sh:do_update）────

do_update() {
    # ---- 参数解析（--yes/-y → 非交互）----
    # setup.sh 分发层当前无参调用（T9a 契约），参数通道供直调与未来透传使用；
    # 环境变量 BUDGET_UPDATE_YES=1 与 stdin EOF 为等效非交互通道。
    local _update_arg
    for _update_arg in "$@"; do
        case "$_update_arg" in
            --yes|-y) BUDGET_UPDATE_YES=1 ;;
            *) budget_print_warning "update: 忽略未知参数 $_update_arg" ;;
        esac
    done
    unset _update_arg

    budget_print_header

    # ---- Step 1/5: 重新探测平台（design.md §8.3）----
    budget_print_info "Step 1/5: 平台探测"
    # 当前 shell 调用取变量副作用（stdout 丢弃；探测失败时 stderr 透传详情）
    detect_platform >/dev/null || true
    local platform_kind="${BUDGET_PLATFORM_KIND:-unknown}"
    local platform_scope="${BUDGET_PLATFORM_SCOPE:-}"
    local global_only=false

    if [[ "$platform_kind" == "unknown" ]]; then
        if [[ "${BUDGET_GLOBAL:-0}" == "1" ]]; then
            budget_print_warning "未检测到安装形态（BUDGET_GLOBAL=1 全局模式），仅执行全局数据同步"
            global_only=true
        else
            budget_print_error "未检测到 BudgetBuddy 安装形态（三级探测均未命中）"
            budget_print_info "请先安装本套件，或设置 BUDGET_PLATFORM=codebuddy|claudecode|opencode 显式指定平台"
            budget_print_info "或设置 BUDGET_GLOBAL=1 执行纯全局数据同步"
            return 1
        fi
    else
        budget_print_info "运行平台: $platform_kind:$platform_scope${BUDGET_PLATFORM_ROOT:+ (root: $BUDGET_PLATFORM_ROOT)}"
    fi
    echo ""

    local global_dir=""
    global_dir="$(budget_global_data_dir)"

    # ---- 交互确认（非交互通道直接通过；取消时不做任何修改）----
    if ! _budget_update_confirm "$global_dir"; then
        budget_print_info "已取消更新（未做任何修改）"
        return 0
    fi

    # ---- Step 2/5: lib 全局单点同步（A4：skill 运行时引用 ~/.budgetbuddy/lib/）----
    budget_print_info "Step 2/5: lib 全局单点同步（${global_dir}/lib）"
    if ! mkdir -p "$global_dir/lib"; then
        budget_print_error "全局数据目录创建失败: $global_dir/lib"
        return 1
    fi
    if ! _budget_update_sync_lib "$global_dir/lib"; then
        return 1
    fi
    echo ""

    # ---- Step 3/5: 管理面数据刷新（覆盖语义；用户数据保留）----
    budget_print_info "Step 3/5: 管理面数据刷新（覆盖语义；用户数据保留）"
    if ! _budget_update_admin_data "$global_dir" "$platform_kind" "$platform_scope"; then
        return 1
    fi
    echo ""

    # ---- Step 4/5: hooks 注入重跑（codebuddy 形态；T10d 就位时）----
    if [[ "$platform_kind" == "codebuddy" ]]; then
        budget_print_info "Step 4/5: hooks 注入（Notification/PreToolUse/SubagentStop）"
        _budget_update_hooks_inject || true
    else
        budget_print_info "Step 4/5: 非 codebuddy 形态，跳过 hooks 注入"
    fi
    echo ""

    # ---- Step 5/5: diff 展示（agent model 变化提示；只读不阻断）----
    if [[ "$global_only" == "true" ]]; then
        budget_print_info "Step 5/5: 无安装形态，跳过 diff 展示"
    else
        budget_print_info "Step 5/5: agent model 配置对比（vs balanced 预设）"
        if ! _budget_diff_render "balanced"; then
            budget_print_warning "diff 展示失败（不影响更新结果）"
        fi
    fi
    echo ""

    # ---- 完成汇总 ----
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  更新完成！${NC}"
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  全局数据目录:  $global_dir"
    echo -e "  用户数据:      已保留（persona-active.json / notify.json / memory/）"
    echo ""
    echo -e "  后续操作:"
    echo -e "    运行 ${CYAN}budget setup show${NC} 查看 Agent 模型配置"
    echo -e "    运行 ${CYAN}budget setup diff${NC} 对比其他预设（economic / quality）"
    echo -e "    运行 ${CYAN}budget setup agent preset <档位>${NC} 应用预设"
    echo ""
    return 0
}
