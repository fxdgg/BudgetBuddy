#!/bin/bash
# BudgetBuddy 安装完整性校验（design.md §8.2「persona 与校验」组 / specs setup-cli validate）
#
# Provides:
#   do_validate      - setup.sh validate 分发入口：安装完整性校验报告
#                      （逐项 ✓/✗ + 失败清单 + 总结；exit 0 通过 / 1 失败）
#   setup_validate   - 别名（任务契约名，与 do_validate 完全等价）
#
# 校验内容:
#   ① 文件完整性: 按平台结构清单（agents 10 / commands budget×3+opsx×4 /
#      skills 6 / rules 12 / hooks（仅 codebuddy）/ lib 基础层 4 /
#      setup.sh / budget-models.json / personas.json），落点按 platform.sh
#      探测（design.md §10 安装落点）
#   ② JSON 数据校验: budget-models.json 可解析且 roles 恰为十角色键；
#      personas.json 可解析且内置五主题齐全、每主题 roles 完整覆盖 11 键
#   ③ hooks 注入状态查询: hooks.sh 就位时调 budget_check_hooks（信息性，
#      不计入通过/失败项）；未就位跳过提示
#
# 落点决策（platform.sh 探测结果，design.md §10）:
#   codebuddy（project/global）: 结构根 = 安装根（setup.sh 同目录，
#       agents/commands/skills/rules/hooks 与管理面同根）
#   opencode: 结构根 = agent 目录父目录（.opencode/ 或 ~/.config/opencode/）；
#       管理面（lib/setup.sh/models/personas）= 安装根（~/.budgetbuddy/，A3）；
#       rules 校验 AGENTS.fragment.md 的 12 个 rule 区块标记
#
# Dependencies（setup.sh source 基础层后分发调用）:
#   colors.sh    - budget_print_*
#   platform.sh  - detect_platform / BUDGET_SUITE_AGENTS（§6 十角色清单）
#   hooks.sh     - budget_check_hooks（可选，就位时复用）
#   setup.sh 顶层导出 - BUDGET_SETUP_DIR / BUDGET_LIB_DIR / BUDGET_PYTHON

# ─── 结构清单常量 ─────────────────────────────────────────────────────────
# commands（§11: budget 组 3 + opsx 组 4）
_budget_validate_budget_commands=(goal start status)
_budget_validate_opsx_commands=(apply archive explore propose)

# skills（§8.2: budget-workflow + budget-notify + openspec×4）
_budget_validate_skills=(
    budget-workflow budget-notify
    openspec-apply-change openspec-archive-change openspec-explore openspec-propose
)

# rules 12 主名（codebuddy 落点 rules/budget-<name>.mdc；opencode 为
# AGENTS.fragment.md 内 <!-- budget-<name>:begin --> 区块）
_budget_validate_rules=(
    coder-guard cpp-style css-style go-style java-style leader-no-code
    python-style rtk sql-style trpc-style typescript-style workflow-enforcement
)

# lib 基础层（setup.sh 硬依赖 4 文件）
_budget_validate_base_libs=(colors.sh utils.sh platform.sh shell.sh)

# ─── 内部辅助：结构根定位 ─────────────────────────────────────────────────
_budget_validate_structure_dir() {
    # 结构文件根（agents/commands/skills/rules/hooks 的父目录）:
    #   codebuddy → 安装根（BUDGET_SETUP_DIR，结构与管理面同根）
    #   opencode  → agent 目录父目录（.opencode/ 或 ~/.config/opencode/）
    if [[ "${BUDGET_PLATFORM_KIND:-}" == "opencode" && -n "${BUDGET_AGENTS_DIR:-}" ]]; then
        dirname "$BUDGET_AGENTS_DIR"
    else
        echo "$BUDGET_SETUP_DIR"
    fi
}

# ─── 内部辅助：单文件存在性检查（✓/✗ + 计数 + 失败清单）──────────────────
_budget_validate_check() {
    # 用法: _budget_validate_check <显示标签> <绝对路径>
    # 全局副作用: _budget_validate_total（总项数）与 _budget_validate_failed
    # （失败标签清单，供总结输出；调用方初始化）。
    local label="$1"
    local path="$2"
    _budget_validate_total=$((_budget_validate_total + 1))
    if [[ -f "$path" ]]; then
        budget_print_success "$label"
    else
        budget_print_error "${label}（缺失: ${path}）"
        _budget_validate_failed+=("$label")
    fi
}

# ─── JSON 数据校验（②；Python heredoc，env 传参）────────────────────────
_budget_validate_json() {
    # 用法: _budget_validate_json <models_file> <personas_file>
    # stdout 输出逐项 ✓/✗ 行；exit code = 失败项数（0-4）。
    # 文件缺失时跳过该项（① 文件完整性已报告，不重复计失败）。
    BUDGET_VALIDATE_MODELS="$1" \
    BUDGET_VALIDATE_PERSONAS="$2" \
        "${BUDGET_PYTHON:-python3}" << 'PYEOF'
import json
import os
import sys

MODEL_ROLES = (
    'architect', 'coder_lite', 'coder_standard', 'coder_senior', 'reviewer',
    'reviewer_b', 'tester', 'recorder', 'director', 'goal_evaluator',
)
BUILTIN_THEMES = ('default', 'genshin', 'sanguo', 'shuihu', 'tech-legends')
ROLE_KEYS = frozenset((
    'leader', 'architect', 'coder-lite', 'coder-standard', 'coder-senior',
    'reviewer', 'reviewer-b', 'tester', 'recorder', 'director', 'goal-evaluator',
))

failures = 0

models_path = os.environ.get('BUDGET_VALIDATE_MODELS', '')
if os.path.isfile(models_path):
    data = None
    try:
        with open(models_path, encoding='utf-8') as handle:
            data = json.load(handle)
        print('[✓] budget-models.json: JSON 解析 OK')
    except (OSError, ValueError) as exc:
        print('[✗] budget-models.json: JSON 解析失败（%s）' % exc)
        print('[✗] budget-models.json: roles 键集无法校验（解析失败）')
        failures += 2
        data = None
    if data is not None:
        roles = data.get('roles') if isinstance(data, dict) else None
        if isinstance(roles, list) and sorted(roles) == sorted(MODEL_ROLES):
            print('[✓] budget-models.json: roles 十角色键集 OK')
        else:
            print('[✗] budget-models.json: roles 键集不符（期望十角色）')
            failures += 1

personas_path = os.environ.get('BUDGET_VALIDATE_PERSONAS', '')
if os.path.isfile(personas_path):
    data = None
    try:
        with open(personas_path, encoding='utf-8') as handle:
            data = json.load(handle)
        print('[✓] personas.json: JSON 解析 OK')
    except (OSError, ValueError) as exc:
        print('[✗] personas.json: JSON 解析失败（%s）' % exc)
        print('[✗] personas.json: 主题键集无法校验（解析失败）')
        failures += 2
        data = None
    if data is not None:
        themes = data.get('themes') if isinstance(data, dict) else None
        problems = []
        if not isinstance(themes, dict) or not themes:
            problems.append('themes 缺失或为空')
        else:
            missing = [name for name in BUILTIN_THEMES if name not in themes]
            if missing:
                problems.append('内置主题缺失（%s）' % ', '.join(missing))
            bad = sorted(
                name for name, theme in themes.items()
                if not isinstance(theme, dict)
                or not isinstance(theme.get('roles'), dict)
                or not ROLE_KEYS <= set(theme['roles']))
            if bad:
                problems.append('主题 roles 未完整覆盖 11 键（%s）' % ', '.join(bad))
        if problems:
            print('[✗] personas.json: %s' % '；'.join(problems))
            failures += 1
        else:
            print('[✓] personas.json: %d 主题 × 11 角色键 OK' % len(themes))

sys.exit(min(failures, 200))
PYEOF
}

# ─── 主入口（setup.sh validate 分发契约）─────────────────────────────────
do_validate() {
    budget_print_header

    # 平台探测（当前 shell 调用取变量副作用；stdout 丢弃）
    detect_platform >/dev/null || true
    if [[ "${BUDGET_PLATFORM_KIND:-unknown}" == "unknown" ]]; then
        budget_print_error "未检测到 BudgetBuddy 安装形态，无法确定校验落点"
        budget_print_info "提示: BUDGET_PLATFORM=codebuddy|opencode 显式指定平台"
        return 1
    fi

    local kind="${BUDGET_PLATFORM_KIND:-}"
    local structure_dir
    structure_dir="$(_budget_validate_structure_dir)"

    budget_print_info "平台: $kind:${BUDGET_PLATFORM_SCOPE:-}${BUDGET_PLATFORM_ROOT:+ (root: $BUDGET_PLATFORM_ROOT)}"
    budget_print_info "结构根: $structure_dir"
    budget_print_info "管理面: $BUDGET_SETUP_DIR"
    echo ""

    _budget_validate_total=0
    _budget_validate_failed=()

    # ---- ① 文件完整性 ----
    echo "── 文件完整性 ──"

    # agents（10，§6 十角色；BUDGET_AGENTS_DIR 由 platform.sh 探测）
    local name
    for name in "${BUDGET_SUITE_AGENTS[@]}"; do
        _budget_validate_check "agents/$name.md" "$BUDGET_AGENTS_DIR/$name.md"
    done

    # commands（budget×3 + opsx×4；codebuddy commands/<group>/<name>.md，
    # opencode command/<group>-<name>.md，design.md §10 落点）
    local cmd
    if [[ "$kind" == "opencode" ]]; then
        for cmd in "${_budget_validate_budget_commands[@]}"; do
            _budget_validate_check "command/budget-$cmd.md" "$structure_dir/command/budget-$cmd.md"
        done
        for cmd in "${_budget_validate_opsx_commands[@]}"; do
            _budget_validate_check "command/opsx-$cmd.md" "$structure_dir/command/opsx-$cmd.md"
        done
    else
        for cmd in "${_budget_validate_budget_commands[@]}"; do
            _budget_validate_check "commands/budget/$cmd.md" "$structure_dir/commands/budget/$cmd.md"
        done
        for cmd in "${_budget_validate_opsx_commands[@]}"; do
            _budget_validate_check "commands/opsx/$cmd.md" "$structure_dir/commands/opsx/$cmd.md"
        done
    fi

    # skills（6；codebuddy skills/，opencode skill/，design.md §10）
    local skills_root="skills"
    if [[ "$kind" == "opencode" ]]; then
        skills_root="skill"
    fi
    local skill
    for skill in "${_budget_validate_skills[@]}"; do
        _budget_validate_check "$skills_root/$skill/SKILL.md" "$structure_dir/$skills_root/$skill/SKILL.md"
    done

    # rules（12；codebuddy 逐文件 .mdc / opencode AGENTS.fragment.md 12 区块）
    local rule
    if [[ "$kind" == "opencode" ]]; then
        local fragment=""
        local candidate
        # 候选: 结构根 fragment（源形态）> 结构根 AGENTS.md（安装器合并形态，
        # design.md §10）> 管理面 fragment
        for candidate in "$structure_dir/AGENTS.fragment.md" \
                          "$structure_dir/AGENTS.md" \
                          "$BUDGET_SETUP_DIR/AGENTS.fragment.md"; do
            if [[ -f "$candidate" ]]; then
                fragment="$candidate"
                break
            fi
        done
        if [[ -z "$fragment" ]]; then
            _budget_validate_total=$((_budget_validate_total + 1))
            budget_print_error "AGENTS.fragment.md（缺失: $structure_dir/AGENTS.fragment.md）"
            _budget_validate_failed+=("AGENTS.fragment.md")
        else
            for rule in "${_budget_validate_rules[@]}"; do
                _budget_validate_total=$((_budget_validate_total + 1))
                if grep -qF "<!-- budget-$rule:begin -->" "$fragment"; then
                    budget_print_success "AGENTS.fragment.md 区块 budget-$rule"
                else
                    budget_print_error "AGENTS.fragment.md 区块 budget-${rule}（缺失标记）"
                    _budget_validate_failed+=("AGENTS.fragment.md 区块 budget-$rule")
                fi
            done
        fi
    else
        for rule in "${_budget_validate_rules[@]}"; do
            _budget_validate_check "rules/budget-$rule.mdc" "$structure_dir/rules/budget-$rule.mdc"
        done
    fi

    # hooks（仅 codebuddy；opencode 无 hooks 机制，design.md §9）
    if [[ "$kind" == "codebuddy" ]]; then
        _budget_validate_check "hooks/budget-notify-hook.py" "$structure_dir/hooks/budget-notify-hook.py"
    fi

    # lib 基础层（setup.sh 硬依赖 4 文件）
    for name in "${_budget_validate_base_libs[@]}"; do
        _budget_validate_check "lib/$name" "$BUDGET_LIB_DIR/$name"
    done

    # 管理面（setup.sh / budget-models.json / personas.json）
    _budget_validate_check "setup.sh" "$BUDGET_SETUP_DIR/setup.sh"
    _budget_validate_check "budget-models.json" "$BUDGET_SETUP_DIR/budget-models.json"
    _budget_validate_check "personas.json" "$BUDGET_SETUP_DIR/personas.json"
    echo ""

    # ---- ② JSON 数据校验 ----
    echo "── JSON 数据校验 ──"
    local models_file="$BUDGET_SETUP_DIR/budget-models.json"
    local personas_file="$BUDGET_SETUP_DIR/personas.json"
    if [[ -f "$models_file" || -f "$personas_file" ]]; then
        local json_rc=0
        _budget_validate_json "$models_file" "$personas_file" || json_rc=$?
        # 存在的文件各贡献 2 项（解析 + 键集）；json_rc = 失败项数
        if [[ -f "$models_file" ]]; then
            _budget_validate_total=$((_budget_validate_total + 2))
        fi
        if [[ -f "$personas_file" ]]; then
            _budget_validate_total=$((_budget_validate_total + 2))
        fi
        if [[ "$json_rc" -gt 0 ]]; then
            _budget_validate_failed+=("JSON 数据校验（$json_rc 项失败，详见上方 ✗ 行）")
        fi
    else
        budget_print_info "models/personas 文件均缺失，跳过 JSON 数据校验（文件完整性已报告）"
    fi
    echo ""

    # ---- ③ hooks 注入状态查询（信息性，不计入通过/失败）----
    echo "── hooks 注入状态 ──"
    if declare -f budget_check_hooks &>/dev/null; then
        budget_check_hooks || true
    else
        budget_print_info "hooks 模块未安装（lib/hooks.sh），跳过注入状态查询"
    fi
    echo ""

    # ---- ④ 总结 ----
    local failed_count=${#_budget_validate_failed[@]}
    if [[ "$failed_count" -eq 0 ]]; then
        budget_print_success "全部检查通过（$_budget_validate_total 项）"
        return 0
    fi
    budget_print_error "校验失败: $failed_count 项（共 $_budget_validate_total 项检查）"
    budget_print_info "失败清单:"
    for name in "${_budget_validate_failed[@]}"; do
        budget_print_info "  - $name"
    done
    budget_print_info "修复建议: budget setup update 刷新管理面数据，或重新安装补全结构文件"
    return 1
}

# 任务契约别名（与 do_validate 等价）
setup_validate() {
    do_validate "$@"
}
