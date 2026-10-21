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
#      skills 6 / rules 12 / hooks（codebuddy/claudecode）/ lib 基础层 4 /
#      setup.sh / budget-models.json / personas.json），落点按 platform.sh
#      探测（design.md §10 安装落点）
#   ② JSON 数据校验: budget-models.json 可解析且 roles 恰为十角色键；
#      personas.json 可解析且内置五主题齐全、每主题 roles 完整覆盖 11 键
#   ③ hooks 注入状态查询: hooks.sh 就位时调 budget_check_hooks（信息性，
#      不计入通过/失败项；claudecode 形态输出三事件注入状态，不显示
#      superpowers 行）；未就位跳过提示
#
# 落点决策（platform.sh 探测结果，design.md §10）:
#   codebuddy（project/global）: 结构根 = 安装根（setup.sh 同目录，
#       agents/commands/skills/rules/hooks 与管理面同根）
#   opencode: 结构根 = agent 目录父目录（.opencode/ 或 ~/.config/opencode/）；
#       管理面（lib/setup.sh/models/personas）= 安装根（~/.budgetbuddy/，A3）；
#       rules 校验 AGENTS.fragment.md 的 12 个 rule 区块标记
#   claudecode: 结构根 = agents 目录父目录（.claude/ 或 ~/.claude/，复数
#       agents/commands/skills/hooks 与 codebuddy 同构）；管理面同 opencode 共享
#       ~/.budgetbuddy/（A3）；rules 校验 CLAUDE.fragment.md（安装器合并进
#       CLAUDE.md：项目根或 ~/.claude/CLAUDE.md）的 12 个 rule 区块标记
#   codex: 结构根 = .codex/（项目）或 ~/.codex/（全局，按 SCOPE/ROOT 定位）；
#       管理面同 opencode/claudecode 共享 ~/.budgetbuddy/（A3）；校验
#       skills/budget-workflow 完整性（agents×10 / commands×7 / rules×12 /
#       codex-runtime.md）、AGENTS.md 轻量区块 12 条索引标记（项目根或
#       ~/.codex/AGENTS.md）与 config.toml multi_agent 启用状态
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
    #   claudecode → agents 目录父目录（.claude/ 或 ~/.claude/）
    #   codex → .codex/（项目）或 ~/.codex/（全局，按 SCOPE/ROOT 定位——
    #       BUDGET_AGENTS_DIR 为 skill 深层素材目录，不适用父目录回溯）
    if [[ "${BUDGET_PLATFORM_KIND:-}" == "codex" ]]; then
        if [[ "${BUDGET_PLATFORM_SCOPE:-}" == "project" && -n "${BUDGET_PLATFORM_ROOT:-}" ]]; then
            echo "$BUDGET_PLATFORM_ROOT/.codex"
        else
            echo "$HOME/.codex"
        fi
    elif [[ ( "${BUDGET_PLATFORM_KIND:-}" == "opencode" || "${BUDGET_PLATFORM_KIND:-}" == "claudecode" ) \
          && -n "${BUDGET_AGENTS_DIR:-}" ]]; then
        dirname "$BUDGET_AGENTS_DIR"
    else
        echo "$BUDGET_SETUP_DIR"
    fi
}

# ─── 内部辅助：codex config.toml multi_agent 启用检查 ─────────────────────
_budget_validate_codex_multi_agent() {
    # 用法: _budget_validate_codex_multi_agent <config_file>
    # [features] 段内 multi_agent = true 检查（段头行首精确，防
    # [features.xxx] 子串误判；容忍 = 两侧空格变体）。返回 0 = 已启用。
    local config_file="$1"
    [[ -f "$config_file" ]] || return 1
    awk '
        /^\[/ { in_features = ($0 ~ /^\[features\][ \t]*(#.*)?$/) }
        in_features && $0 ~ /^multi_agent[ \t]*=[ \t]*true[ \t]*(#.*)?$/ { found = 1 }
        END { exit (found ? 0 : 1) }
    ' "$config_file" 2>/dev/null
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
        budget_print_info "提示: BUDGET_PLATFORM=codebuddy|claudecode|opencode|codex 显式指定平台"
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

    # agents（10，§6 十角色；BUDGET_AGENTS_DIR 由 platform.sh 探测；codex
    # 落 skill 内素材目录 skills/budget-workflow/agents/——按结构根计算，
    # 不依赖探测变量）
    local agents_dir="$BUDGET_AGENTS_DIR"
    local agents_label="agents"
    if [[ "$kind" == "codex" ]]; then
        agents_dir="$structure_dir/skills/budget-workflow/agents"
        agents_label="skills/budget-workflow/agents"
    fi
    local name
    for name in "${BUDGET_SUITE_AGENTS[@]}"; do
        _budget_validate_check "$agents_label/$name.md" "$agents_dir/$name.md"
    done

    # commands（budget×3 + opsx×4；codebuddy/claudecode commands/<group>/<name>.md
    # （分组目录同构），opencode command/<group>-<name>.md，codex 落 skill 内
    # commands/<group>-<name>.md（design.md §10 / D1 落点））
    local cmd
    if [[ "$kind" == "opencode" ]]; then
        for cmd in "${_budget_validate_budget_commands[@]}"; do
            _budget_validate_check "command/budget-$cmd.md" "$structure_dir/command/budget-$cmd.md"
        done
        for cmd in "${_budget_validate_opsx_commands[@]}"; do
            _budget_validate_check "command/opsx-$cmd.md" "$structure_dir/command/opsx-$cmd.md"
        done
    elif [[ "$kind" == "codex" ]]; then
        for cmd in "${_budget_validate_budget_commands[@]}"; do
            _budget_validate_check "skills/budget-workflow/commands/budget-$cmd.md" \
                "$structure_dir/skills/budget-workflow/commands/budget-$cmd.md"
        done
        for cmd in "${_budget_validate_opsx_commands[@]}"; do
            _budget_validate_check "skills/budget-workflow/commands/opsx-$cmd.md" \
                "$structure_dir/skills/budget-workflow/commands/opsx-$cmd.md"
        done
    else
        for cmd in "${_budget_validate_budget_commands[@]}"; do
            _budget_validate_check "commands/budget/$cmd.md" "$structure_dir/commands/budget/$cmd.md"
        done
        for cmd in "${_budget_validate_opsx_commands[@]}"; do
            _budget_validate_check "commands/opsx/$cmd.md" "$structure_dir/commands/opsx/$cmd.md"
        done
    fi

    # skills（6；codebuddy/claudecode skills/ 复数，opencode skill/ 单数）
    local skills_root="skills"
    if [[ "$kind" == "opencode" ]]; then
        skills_root="skill"
    fi
    local skill
    for skill in "${_budget_validate_skills[@]}"; do
        _budget_validate_check "$skills_root/$skill/SKILL.md" "$structure_dir/$skills_root/$skill/SKILL.md"
    done

    # rules（12；codebuddy 逐文件 .mdc / opencode+claudecode fragment 12 区块 /
    # codex skill 内全文副本 .md + AGENTS.md 轻量区块 12 条索引标记）
    local rule
    if [[ "$kind" == "opencode" || "$kind" == "claudecode" ]]; then
        local fragment=""
        local candidate
        # 合并目标文件名（opencode AGENTS.md / claudecode CLAUDE.md）
        local merged="AGENTS.md"
        if [[ "$kind" == "claudecode" ]]; then
            merged="CLAUDE.md"
        fi
        # 候选: 结构根 fragment（源形态）> 合并目标（安装器合并形态，design.md
        # §10——claudecode 项目级 CLAUDE.md 在项目根而非 .claude/ 下）> 管理面 fragment
        for candidate in "$structure_dir/${merged%.md}.fragment.md" \
                          "$structure_dir/$merged" \
                          "$BUDGET_SETUP_DIR/${merged%.md}.fragment.md"; do
            if [[ -f "$candidate" ]]; then
                fragment="$candidate"
                break
            fi
        done
        if [[ "$kind" == "claudecode" && -z "$fragment" \
              && "${BUDGET_PLATFORM_SCOPE:-}" == "project" && -n "${BUDGET_PLATFORM_ROOT:-}" ]] \
            && [[ -f "$BUDGET_PLATFORM_ROOT/CLAUDE.md" ]]; then
            fragment="$BUDGET_PLATFORM_ROOT/CLAUDE.md"
        fi
        if [[ -z "$fragment" ]]; then
            _budget_validate_total=$((_budget_validate_total + 1))
            budget_print_error "${merged%.md}.fragment.md（缺失: $structure_dir/${merged%.md}.fragment.md）"
            _budget_validate_failed+=("${merged%.md}.fragment.md")
        else
            for rule in "${_budget_validate_rules[@]}"; do
                _budget_validate_total=$((_budget_validate_total + 1))
                if grep -qF "<!-- budget-$rule:begin -->" "$fragment"; then
                    budget_print_success "$merged 区块 budget-$rule"
                else
                    budget_print_error "$merged 区块 budget-${rule}（缺失标记）"
                    _budget_validate_failed+=("$merged 区块 budget-$rule")
                fi
            done
        fi
    elif [[ "$kind" == "codex" ]]; then
        # 规则全文副本（skills/budget-workflow/rules/budget-<name>.md，构建期
        # 从 core/rules/ 单真值源复制，design D3）
        for rule in "${_budget_validate_rules[@]}"; do
            _budget_validate_check "skills/budget-workflow/rules/budget-$rule.md" \
                "$structure_dir/skills/budget-workflow/rules/budget-$rule.md"
        done
        # AGENTS.md 轻量区块 12 条索引标记（合并目标：项目根 AGENTS.md 或
        # ~/.codex/AGENTS.md；候选链同 claudecode 先例——结构根 fragment
        # （源形态）> 结构根 AGENTS.md（全局合并形态）> 项目根 AGENTS.md
        # （项目合并形态）> 管理面 fragment）
        local cx_fragment=""
        local cx_candidate
        for cx_candidate in "$structure_dir/AGENTS.fragment.md" \
                              "$structure_dir/AGENTS.md" \
                              "$BUDGET_SETUP_DIR/AGENTS.fragment.md"; do
            if [[ -f "$cx_candidate" ]]; then
                cx_fragment="$cx_candidate"
                break
            fi
        done
        if [[ -z "$cx_fragment" && "${BUDGET_PLATFORM_SCOPE:-}" == "project" \
              && -n "${BUDGET_PLATFORM_ROOT:-}" ]] \
            && [[ -f "$BUDGET_PLATFORM_ROOT/AGENTS.md" ]]; then
            cx_fragment="$BUDGET_PLATFORM_ROOT/AGENTS.md"
        fi
        if [[ -z "$cx_fragment" ]]; then
            _budget_validate_total=$((_budget_validate_total + 1))
            budget_print_error "AGENTS.md 轻量区块（缺失: $structure_dir/AGENTS.fragment.md）"
            _budget_validate_failed+=("AGENTS.md 轻量区块")
        else
            for rule in "${_budget_validate_rules[@]}"; do
                _budget_validate_total=$((_budget_validate_total + 1))
                if grep -qF "budget-$rule.md" "$cx_fragment"; then
                    budget_print_success "AGENTS.md 索引 budget-$rule"
                else
                    budget_print_error "AGENTS.md 索引 budget-${rule}（缺失标记）"
                    _budget_validate_failed+=("AGENTS.md 索引 budget-$rule")
                fi
            done
        fi
        # 派工契约（codex-runtime.md，design D6）
        _budget_validate_check "skills/budget-workflow/codex-runtime.md" \
            "$structure_dir/skills/budget-workflow/codex-runtime.md"
        # config.toml multi_agent 启用（spawn 工具前提，add-codex-platform D4）
        _budget_validate_total=$((_budget_validate_total + 1))
        if _budget_validate_codex_multi_agent "$structure_dir/config.toml"; then
            budget_print_success "config.toml multi_agent = true（spawn 工具已启用）"
        else
            budget_print_error "config.toml multi_agent 未启用（缺失或未注入: $structure_dir/config.toml）"
            _budget_validate_failed+=("config.toml multi_agent")
        fi
    else
        # codebuddy：逐文件 .mdc（rules/budget-<name>.mdc）
        for rule in "${_budget_validate_rules[@]}"; do
            _budget_validate_check "rules/budget-$rule.mdc" "$structure_dir/rules/budget-$rule.mdc"
        done
    fi

    # hooks（codebuddy/claudecode 形态；opencode/codex 无 hooks 机制，design.md §9）
    if [[ "$kind" == "codebuddy" || "$kind" == "claudecode" ]]; then
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
    if [[ "$kind" == "codex" ]]; then
        budget_print_info "Codex 平台无 hooks 机制（实验态不分发），跳过注入状态查询"
    elif declare -f budget_check_hooks &>/dev/null; then
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
