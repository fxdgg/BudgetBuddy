#!/bin/bash
# BudgetBuddy init module — setup init 子命令实现（design.md §8.1/§8.4/§9/§10）
#
# Provides:
#   do_init [--yes|-y]  - 安装初始化全流程（Step 1-7）
#
# Dependencies（setup.sh source 基础层后分发调用）:
#   colors.sh   - budget_print_* / RED GREEN YELLOW CYAN BOLD NC
#   utils.sh    - budget_install_wrapper / budget_json_get / budget_global_data_dir
#   platform.sh - detect_platform（当前 shell 调用取变量副作用）
#   shell.sh    - budget_inject_func（rc fallback 函数注入）
#   setup.sh 顶层导出 - BUDGET_SETUP_DIR / BUDGET_LIB_DIR / BUDGET_MODELS_FILE /
#                       BUDGET_GLOBAL / BUDGET_PYTHON
#
# 非交互通道（任一命中即跳过交互确认，全部走默认值继续）:
#   1. do_init --yes / -y（函数参数）
#   2. BUDGET_INIT_YES=1（环境变量）
#   3. stdin EOF（read 失败 || true 兜底，与 shell.sh 风格一致）
#
# 幂等约定（重复 init 不破坏已有数据，specs/setup-cli「数据目录与优先级」）:
#   - notify.json / persona-active.json 已存在则跳过（用户配置优先）
#   - 管理面数据（budget-models.json / personas.json）目标已存在则保留
#     （更新语义归 lib/update.sh）
#   - 目录已存在不报错（mkdir -p）；.gitignore 标记区块全局唯一

# ─── 内部辅助：非交互判定 ───────────────────────────────────────────────

_budget_init_noninteractive() {
    # --yes / BUDGET_INIT_YES=1 时返回 0（跳过交互确认）
    [[ "${BUDGET_INIT_YES:-0}" == "1" ]] && return 0
    return 1
}

# ─── 内部辅助：交互确认 ─────────────────────────────────────────────────

_budget_init_confirm() {
    # init 总确认：展示操作概要并询问；非交互通道直接通过。
    # read 一律 || true 兜底：stdin EOF（非交互调用）走默认 Y 继续执行。
    local global_dir="$1"
    local data_dir="$2"
    if _budget_init_noninteractive; then
        return 0
    fi
    echo ""
    echo -e "  ${YELLOW}初始化将执行以下操作:${NC}"
    echo -e "    1. 创建全局数据目录: ${CYAN}$global_dir${NC}"
    echo -e "    2. 初始化数据文件: ${CYAN}$data_dir${NC}（已存在的文件一律跳过，不覆盖）"
    echo -e "    3. 写入 budget 命令包装器: ${CYAN}$HOME/.local/bin/budget${NC}"
    echo ""
    local choice=""
    read -r -p "  继续初始化? [Y/n] " choice || true
    case "${choice:-Y}" in
        [Nn]*) return 1 ;;
        *)     return 0 ;;
    esac
}

# ─── 内部辅助：personas.json 源定位 ─────────────────────────────────────

_budget_init_personas_src() {
    # 按序探测 personas.json 源（stdout 输出路径；未找到 return 1）:
    #   ① codebuddy 项目级（探测 root；BUDGET_GLOBAL=1 时跳过）
    #   ② codebuddy 全局（~/.codebuddy/）
    #   ③ 全局数据目录（~/.budgetbuddy/，opencode 管理面 A3 / init 已落位）
    #   ④ setup.sh 同目录（安装形态）与 core 源形态（personas/ 子目录）
    if [[ "${BUDGET_PLATFORM_KIND:-}" == "codebuddy" ]]; then
        if [[ -n "${BUDGET_PLATFORM_ROOT:-}" && "${BUDGET_GLOBAL:-0}" != "1" \
              && -f "$BUDGET_PLATFORM_ROOT/.codebuddy/personas.json" ]]; then
            echo "$BUDGET_PLATFORM_ROOT/.codebuddy/personas.json"
            return 0
        fi
        if [[ -f "$HOME/.codebuddy/personas.json" ]]; then
            echo "$HOME/.codebuddy/personas.json"
            return 0
        fi
    fi
    local candidate
    candidate="$(budget_global_data_dir)/personas.json"
    if [[ -f "$candidate" ]]; then
        echo "$candidate"
        return 0
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

# ─── 内部辅助：管理面数据落位（目标不存在时拷贝）────────────────────────

_budget_init_copy_if_absent() {
    # 用法: _budget_init_copy_if_absent <src> <dest> <label>
    # 目标已存在时保留（用户可能自定义，更新语义归 lib/update.sh）；
    # 源缺失时告警跳过（数据未就位不阻断 init 主流程）。
    local src="$1"
    local dest="$2"
    local label="$3"
    if [[ ! -f "$src" ]]; then
        budget_print_warning "$label 源文件缺失（${src}），跳过落位"
        return 0
    fi
    if [[ -f "$dest" ]]; then
        budget_print_info "$label 已存在，保留不覆盖（${dest}）"
        return 0
    fi
    if cp "$src" "$dest" 2>/dev/null; then
        budget_print_success "已落位 $label: $dest"
        return 0
    fi
    budget_print_error "$label 拷贝失败: $src → $dest"
    return 1
}

# ─── 内部辅助：lib 全局单点同步（A4）────────────────────────────────────

_budget_init_sync_lib() {
    # $BUDGET_LIB_DIR → 目标目录（~/.budgetbuddy/lib/）。
    # skill 运行时引用 $HOME/.budgetbuddy/lib/budget-state.py 的全局单点
    # （design.md §12-A4），由 init 建立该落点。
    # 纪律：排除 *.pyc（禁 pyc 分发）；源即目标（opencode 管理面形态，
    # setup.sh 本就位于 ~/.budgetbuddy/）时跳过；内容一致跳过（幂等）。
    local dest_dir="$1"
    local src_dir="${BUDGET_LIB_DIR:-}"
    if [[ -z "$src_dir" || ! -d "$src_dir" ]]; then
        return 0
    fi
    local src_real
    local dest_real
    src_real="$(cd "$src_dir" 2>/dev/null && pwd -P)" || return 0
    dest_real="$(cd "$dest_dir" 2>/dev/null && pwd -P)" || return 0
    if [[ "$src_real" == "$dest_real" ]]; then
        return 0
    fi
    local item
    local dest_file
    local synced=0
    for item in "$src_dir"/*; do
        [[ -f "$item" ]] || continue
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

# ─── 内部辅助：persona-active.json 默认写入（若无）──────────────────────

_budget_init_persona_template() {
    # 展开逻辑实现（stdout 输出主题名；失败 exit 1 + stderr 单行原因）
    BUDGET_PERSONAS_SRC="$1" BUDGET_PERSONA_ACTIVE="$2" \
        "${BUDGET_PYTHON:-python3}" - << 'PYEOF'
import json
import os
import sys
import tempfile

personas_file = os.environ['BUDGET_PERSONAS_SRC']
active_file = os.environ['BUDGET_PERSONA_ACTIVE']

try:
    with open(personas_file, encoding='utf-8') as handle:
        data = json.load(handle)
except (OSError, ValueError) as exc:
    print('personas.json 读取失败: %s' % exc, file=sys.stderr)
    sys.exit(1)

themes = data.get('themes', {})
theme_name = data.get('_meta', {}).get('default_theme', 'default')
if theme_name not in themes:
    theme_name = 'default'
if theme_name not in themes:
    print('personas.json 缺少 default 主题', file=sys.stderr)
    sys.exit(1)

theme_data = themes[theme_name]
roles = {}
for role, info in theme_data.get('roles', {}).items():
    roles[role] = info.get('name', role) if isinstance(info, dict) else info
active = {
    'theme': theme_name,
    'greeting': theme_data.get('greeting', ''),
    'roles': roles,
    'report_templates': theme_data.get('report_templates', {}),
}

dir_name = os.path.dirname(active_file) or '.'
fd, tmp_path = tempfile.mkstemp(prefix='.persona-', suffix='.tmp', dir=dir_name)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
        json.dump(active, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp_path, active_file)
except Exception as exc:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    print('persona-active.json 写入失败: %s' % exc, file=sys.stderr)
    sys.exit(1)
print(theme_name)
PYEOF
}

_budget_init_write_persona() {
    # 从 personas.json 展开默认主题（_meta.default_theme，缺省 default）写入
    # persona-active.json（design.md §8.5 结构：theme/greeting/roles/
    # report_templates；roles 为 11 键 → 角色名映射）。
    # 写入纪律：临时文件 + 原子 rename（与 hooks_inject 一致）。
    # 非致命失败：persona 缺失时运行时降级用 default（design.md §8.4）。
    local personas_src="$1"
    local active_file="$2"
    local result
    result="$(_budget_init_persona_template "$personas_src" "$active_file")" || result=""
    if [[ -n "$result" ]]; then
        budget_print_success "已写入默认 persona 配置: ${active_file}（主题: ${result}）"
        budget_print_info "切换主题: budget setup persona list"
        return 0
    fi
    budget_print_warning "persona 默认配置写入失败（personas.json 缺失或格式错误）"
    return 0
}

# ─── 内部辅助：notify.json 默认模板写入（若无）──────────────────────────

_budget_init_notify_template() {
    # 写入 notify.json 默认模板（specs/notify R1 schema：enabled + channels +
    # events N1..N11；安全默认全关）。写入纪律：临时文件 + 原子 rename +
    # chmod 600（webhook/secret 敏感字段仅存于该文件，design.md §9）。
    BUDGET_NOTIFY_FILE="$1" "${BUDGET_PYTHON:-python3}" - << 'PYEOF'
import json
import os
import sys
import tempfile

notify_file = os.environ['BUDGET_NOTIFY_FILE']
events = {}
for i in range(1, 12):
    events['N%d' % i] = {'enabled': False, 'channels': []}
template = {
    'enabled': False,
    'channels': {},
    'events': events,
}

try:
    dir_name = os.path.dirname(notify_file) or '.'
    fd, tmp_path = tempfile.mkstemp(prefix='.notify-', suffix='.tmp', dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            json.dump(template, tmp, indent=2, ensure_ascii=False)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, notify_file)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
except Exception as exc:
    print('notify.json 写入失败: %s' % exc, file=sys.stderr)
    sys.exit(1)
PYEOF
}

_budget_init_write_notify() {
    local notify_file="$1"
    if _budget_init_notify_template "$notify_file"; then
        budget_print_success "已写入通知配置模板: ${notify_file}（默认关闭）"
        budget_print_info "该文件将存放 webhook/secret 敏感字段，已设权限 600，请勿放宽"
        budget_print_info "编辑渠道配置后将 enabled 改为 true 启用通知"
    else
        budget_print_warning "通知配置模板写入失败: ${notify_file}（可手动创建）"
    fi
    return 0
}

# ─── 内部辅助：.gitignore 标记区块幂等追加（design.md §8.4）─────────────

_budget_init_ensure_gitignore() {
    # 无 # BudgetBuddy:begin/end 标记区块则追加 .budget/ 忽略项；
    # 已有区块跳过（幂等）；区块外内容不触碰（仅追加）。
    local project_root="$1"
    local gitignore="$project_root/.gitignore"
    local begin_marker="# BudgetBuddy:begin"
    local end_marker="# BudgetBuddy:end"

    if grep -qF "$begin_marker" "$gitignore" 2>/dev/null; then
        budget_print_info "gitignore 已含 BudgetBuddy 标记区块，跳过（${gitignore}）"
        return 0
    fi
    if ! {
        echo ""
        echo "$begin_marker"
        echo ".budget/"
        echo "$end_marker"
    } >> "$gitignore" 2>/dev/null; then
        budget_print_error "gitignore 写入失败: $gitignore"
        return 1
    fi
    budget_print_success "已追加 .budget/ 忽略区块到 $gitignore"
    return 0
}

# ─── 内部辅助：hooks 注入调用点 + 就位检测桩（design.md §9）─────────────

_budget_init_hooks_inject() {
    # hooks 注入编排调用点：codebuddy → Notification/PreToolUse/SubagentStop
    # 三事件 + superpowers；claudecode → Notification/PermissionRequest/
    # SubagentStop 三事件（无插件机制）；事件集与形态分派归 lib/hooks.sh
    # budget_inject_hooks（kind 判定）。注入前备份 settings.json.bak-budget +
    # 临时文件原子写 + 幂等重入（specs/notify「CodeBuddy hooks 三事件通知」）。
    # 本函数为调用点 + 桩：
    #   - budget_inject_hooks 已定义（setup.sh 自动加载 hooks.sh 后）→ 调用
    #   - 模块文件在但函数未加载（旧版 setup.sh 分发场景）→ 补 source 后调用
    #   - 未就位 → 跳过并提示补全（不阻断 init 主流程）
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

# ─── 内部辅助：superpowers 插件启用检测（A11；注入归 T10d hooks.sh）─────

_budget_init_check_superpowers() {
    # 检测 settings.json 的 enabledPlugins（SKILL_NS="superpowers:" 前缀的
    # skill 引用依赖该插件，design.md §9/§12-A11）。本任务仅检测与提示；
    # 注入动作归 T10d lib/hooks.sh（hooks 注入同时启用插件）。
    local settings_file="$1"
    local enabled
    enabled="$(budget_json_get "$settings_file" \
        "enabledPlugins.superpowers@codebuddy-plugins-official" "false")"
    # budget_json_get 对 JSON true 输出 Python 字面量 "True"
    if [[ "$enabled" == "True" ]]; then
        budget_print_info "superpowers 插件: 已在 settings.json 中启用 ✓"
        budget_print_info "重启 CodeBuddy 后即可加载 superpowers skills"
        return 0
    fi
    budget_print_warning "superpowers 插件未启用（skill 引用依赖 superpowers: 前缀）"
    budget_print_info "请重启 CodeBuddy 后执行 /plugin superpowers，或手动编辑/创建:"
    budget_print_info "  $settings_file"
    budget_print_info "  enabledPlugins 增加 \"superpowers@codebuddy-plugins-official\": true"
    budget_print_info "hooks 注入模块（T10d）就位后将随 init 自动启用，当前仅提示"
    return 0
}

# ─── 初始化主流程（setup.sh 分发入口）───────────────────────────────────

do_init() {
    # ---- 参数解析（--yes/-y → 非交互）----
    # setup.sh 分发层当前无参调用（T9a 契约），参数通道供直调与未来透传使用；
    # 环境变量 BUDGET_INIT_YES=1 与 stdin EOF 为等效非交互通道。
    local _init_arg
    for _init_arg in "$@"; do
        case "$_init_arg" in
            --yes|-y) BUDGET_INIT_YES=1 ;;
            *) budget_print_warning "init: 忽略未知参数 $_init_arg" ;;
        esac
    done
    unset _init_arg

    budget_print_header

    # ---- Step 1/7: 平台探测与环境检查（design.md §8.3）----
    budget_print_info "Step 1/7: 平台探测与环境检查"
    # 当前 shell 调用取变量副作用（stdout 丢弃；探测失败时 stderr 透传详情）
    detect_platform >/dev/null || true
    local platform_kind="${BUDGET_PLATFORM_KIND:-unknown}"
    local platform_scope="${BUDGET_PLATFORM_SCOPE:-}"
    local platform_root="${BUDGET_PLATFORM_ROOT:-}"

    if [[ "$platform_kind" == "unknown" ]]; then
        if [[ "${BUDGET_GLOBAL:-0}" == "1" ]]; then
            budget_print_warning "未检测到已安装形态（BUDGET_GLOBAL=1 全局模式），仅执行全局初始化"
            budget_print_warning "hooks 注入与 superpowers 插件检测步骤将跳过"
        else
            budget_print_error "未检测到 BudgetBuddy 安装形态（多级探测均未命中）"
            budget_print_info "请先安装本套件，或设置 BUDGET_PLATFORM=codebuddy|claudecode|codex|opencode 显式指定平台"
            budget_print_info "或设置 BUDGET_GLOBAL=1 执行纯全局数据目录初始化"
            return 1
        fi
    else
        budget_print_info "运行平台: $platform_kind:$platform_scope${platform_root:+ (root: $platform_root)}"
    fi
    echo ""

    # ---- 生效数据目录决策（design.md §8.4 读取优先级）----
    # BUDGET_DIR 显式覆盖 > BUDGET_GLOBAL=1/全局形态 → ~/.budgetbuddy/
    # > 项目形态 → <root>/.budget/
    local global_dir
    global_dir="$(budget_global_data_dir)"
    local data_dir
    if [[ -n "${BUDGET_DIR:-}" ]]; then
        data_dir="$BUDGET_DIR"
    elif [[ "${BUDGET_GLOBAL:-0}" == "1" || "$platform_scope" != "project" ]]; then
        data_dir="$global_dir"
    else
        data_dir="$platform_root/.budget"
    fi

    # personas.json 源定位（Step 2 管理面落位与 Step 3 默认展开共用）
    local personas_src
    personas_src="$(_budget_init_personas_src)" || personas_src=""

    # ---- 交互确认（非交互通道直接通过；取消时不做任何修改）----
    if ! _budget_init_confirm "$global_dir" "$data_dir"; then
        budget_print_info "已取消初始化（未做任何修改）"
        return 0
    fi

    # ---- Step 2/7: 全局数据目录（~/.budgetbuddy/ 骨架 + 管理面数据落位）----
    budget_print_info "Step 2/7: 初始化全局数据目录 $global_dir"
    if ! mkdir -p "$global_dir/bin" "$global_dir/lib" "$global_dir/projects" "$global_dir/docs"; then
        budget_print_error "全局数据目录创建失败: $global_dir"
        return 1
    fi
    # lib 全局单点同步（A4：skill 运行时引用 $HOME/.budgetbuddy/lib/）
    if ! _budget_init_sync_lib "$global_dir/lib"; then
        return 1
    fi
    # 管理面数据落位（opencode/claudecode 任意形态 / codebuddy 全局 /
    # BUDGET_GLOBAL=1；design.md §8.4 全局数据目录含 budget-models.json 与
    # personas.json——opencode 与 claudecode 管理面统一 ~/.budgetbuddy/，A3）
    local need_admin_data=false
    if [[ "$platform_kind" == "opencode" || "$platform_kind" == "claudecode" \
          || "$platform_kind" == "codex" \
          || ( "$platform_kind" == "codebuddy" && "$platform_scope" == "global" ) \
          || "${BUDGET_GLOBAL:-0}" == "1" ]]; then
        need_admin_data=true
    fi
    if [[ "$need_admin_data" == "true" ]]; then
        if ! _budget_init_copy_if_absent "$BUDGET_MODELS_FILE" \
            "$global_dir/budget-models.json" "模型目录"; then
            return 1
        fi
        if ! _budget_init_copy_if_absent "$personas_src" \
            "$global_dir/personas.json" "persona 主题数据"; then
            return 1
        fi
    fi
    echo ""

    # ---- Step 3/7: 生效数据目录（persona-active.json / notify.json / memory/）----
    budget_print_info "Step 3/7: 初始化数据目录 $data_dir"
    if ! mkdir -p "$data_dir/memory"; then
        budget_print_error "数据目录创建失败: $data_dir"
        return 1
    fi

    # persona-active.json 默认值写入（若无；用户配置优先，幂等不覆盖）
    local persona_active="$data_dir/persona-active.json"
    if [[ -f "$persona_active" ]]; then
        budget_print_info "persona 配置已存在，跳过（${persona_active}）"
    elif [[ -z "$personas_src" ]]; then
        budget_print_warning "personas.json 未找到，跳过 persona 默认配置写入"
    else
        _budget_init_write_persona "$personas_src" "$persona_active"
    fi

    # notify.json 默认模板写入（若无；chmod 600，specs/notify R1）
    local notify_file="$data_dir/notify.json"
    if [[ -f "$notify_file" ]]; then
        budget_print_info "通知配置已存在，跳过（${notify_file}）"
    else
        _budget_init_write_notify "$notify_file"
    fi

    # gitignore 标记区块幂等追加（项目形态时；design.md §8.4）
    if [[ "$platform_scope" == "project" && -n "$platform_root" \
          && "${BUDGET_GLOBAL:-0}" != "1" ]]; then
        if ! _budget_init_ensure_gitignore "$platform_root"; then
            return 1
        fi
    fi
    echo ""

    # ---- Step 4/7: budget CLI 包装器（~/.local/bin/budget，design.md §8.1）----
    budget_print_info "Step 4/7: 写入 budget CLI 包装器"
    if ! budget_install_wrapper; then
        budget_print_error "包装器写入失败: $HOME/.local/bin/budget"
        return 1
    fi
    budget_print_success "全局命令已就绪: $HOME/.local/bin/budget"
    # PATH 检查提示（新终端生效前可用 rc fallback 函数）
    if ! echo "$PATH" | tr ':' '\n' | grep -qF "$HOME/.local/bin"; then
        budget_print_warning "PATH 未包含 $HOME/.local/bin（新终端生效前可用 budget shell 函数）"
    fi
    # shell 函数 fallback 注入（幂等；shell.sh 提供）
    if budget_inject_func; then
        budget_print_info "已注入 budget() shell 函数到 rc 文件（PATH fallback）"
    fi
    echo ""

    # ---- Step 5/7: hooks 注入（codebuddy/claudecode 形态，design.md §9/D4）----
    if [[ "$platform_kind" == "codebuddy" ]]; then
        budget_print_info "Step 5/7: hooks 注入（Notification/PreToolUse/SubagentStop）"
        _budget_init_hooks_inject || true
    elif [[ "$platform_kind" == "claudecode" ]]; then
        budget_print_info "Step 5/7: hooks 注入（Notification/PermissionRequest/SubagentStop）"
        _budget_init_hooks_inject || true
    elif [[ "$platform_kind" == "codex" ]]; then
        budget_print_info "Step 5/7: Codex 平台 hooks 实验态不分发，跳过 hooks 注入"
    else
        budget_print_info "Step 5/7: 非 codebuddy/claudecode 形态，跳过 hooks 注入"
    fi
    echo ""

    # ---- Step 6/7: superpowers 插件启用检测（A11；提示，注入归 T10d）----
    if [[ "$platform_kind" == "codebuddy" ]]; then
        budget_print_info "Step 6/7: 检测 superpowers 插件启用状态"
        local settings_file
        if [[ "${BUDGET_GLOBAL:-0}" == "1" || "$platform_scope" == "global" ]]; then
            settings_file="$HOME/.codebuddy/settings.json"
        else
            settings_file="$platform_root/.codebuddy/settings.json"
        fi
        _budget_init_check_superpowers "$settings_file" || true
    else
        budget_print_info "Step 6/7: 非 codebuddy 形态，跳过 superpowers 插件检测"
    fi
    echo ""

    # ---- Step 7/7: 完成汇总 ----
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  初始化完成！${NC}"
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  全局数据目录:  $global_dir"
    if [[ "$data_dir" != "$global_dir" ]]; then
        echo -e "  项目数据目录:  $data_dir"
    fi
    echo -e "  通知配置:      ${notify_file}（默认关闭，编辑后启用）"
    echo ""
    echo -e "  后续操作:"
    echo -e "    运行 ${CYAN}budget setup show${NC} 查看 Agent 模型配置"
    echo -e "    运行 ${CYAN}budget setup persona list${NC} 查看/切换角色主题"
    echo -e "    运行 ${CYAN}budget setup quickstart${NC} 进入快速上手向导"
    echo -e "    运行 ${CYAN}budget setup init shell${NC} 配置 CLI 一键启动别名"
    echo ""
    return 0
}
