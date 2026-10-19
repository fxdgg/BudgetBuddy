#!/bin/bash
# BudgetBuddy preset management（design.md §3.2/§8.1/§8.3）
#
# 职责：
#   - budget setup agent <preset|inherit|custom>：预设切换与 agent 产物
#     frontmatter model 字段批量重写（重写目标按 platform.sh 探测定位）
#   - do_diff（T9c update.sh）所需查询函数：budget_get_current_models /
#     budget_preset_table（输出契约见函数注释）
# frontmatter 解析与写回统一由 lib/model_resolver.py 承担（YAML 安全），
# shell 仅做编排与结果呈现。
# 依赖调用方（setup.sh）提供：$BUDGET_PYTHON、$BUDGET_LIB_DIR、
# $BUDGET_MODELS_FILE、detect_platform（platform.sh）、budget_print_*（colors.sh）。

# model_resolver.py 统一调用入口（拼装公共参数）
_budget_resolver() {
    "$BUDGET_PYTHON" "$BUDGET_LIB_DIR/model_resolver.py" --models "$BUDGET_MODELS_FILE" "$@"
}

# setup_agent：agent 命令入口（setup.sh 分发：agent → preset.sh）
# 用法: setup_agent [preset <name>|inherit|custom <model>]
setup_agent() {
    local mode="${1:-}"

    # 平台探测：当前 shell 直接调用（变量副作用生效；stdout 丢弃）
    detect_platform >/dev/null || true
    if [[ "${BUDGET_PLATFORM_KIND:-unknown}" == "unknown" ]]; then
        budget_print_error "未检测到已安装的 BudgetBuddy 平台形态，无法定位 agent 目录"
        budget_print_info "提示：可设置 BUDGET_PLATFORM=codebuddy|opencode 显式指定平台"
        return 1
    fi
    if [[ -z "${BUDGET_AGENTS_DIR:-}" || ! -d "${BUDGET_AGENTS_DIR}" ]]; then
        budget_print_error "agent 目录不存在: ${BUDGET_AGENTS_DIR:-（空）}"
        return 1
    fi

    case "$mode" in
        preset)
            shift
            setup_agent_preset "${1:-}"
            ;;
        inherit)
            setup_agent_inherit
            ;;
        custom)
            shift
            setup_agent_custom "${1:-}"
            ;;
        "")
            budget_print_info "当前平台: ${BUDGET_PLATFORM_KIND}:${BUDGET_PLATFORM_SCOPE}（agent 目录: ${BUDGET_AGENTS_DIR}）"
            echo ""
            setup_agent_usage
            ;;
        *)
            budget_print_error "未知模式: $mode"
            echo ""
            setup_agent_usage
            return 1
            ;;
    esac
}

# agent 子命令用法说明
setup_agent_usage() {
    cat << 'EOF'
用法: budget setup agent <preset|inherit|custom> [参数]

  preset <economic|balanced|quality>   应用预设档位（无参数列出各档明细）
  inherit                              全部 agent 跟随主会话模型（删除 model 字段）
  custom <model>                       统一覆写为指定模型（支持别名/ID/provider-model）
EOF
}

# 模式：preset（应用预设档位；无参数列出当前平台各档明细）
setup_agent_preset() {
    local preset_name="${1:-}"

    if [[ -z "$preset_name" ]]; then
        budget_print_info "当前平台: ${BUDGET_PLATFORM_KIND}（agent 目录: ${BUDGET_AGENTS_DIR}）"
        echo ""
        local rc=0
        _budget_resolver list-presets --platform "$BUDGET_PLATFORM_KIND" || rc=$?
        if [[ "$rc" -ne 0 ]]; then
            return 1
        fi
        echo ""
        budget_print_info "用法: budget setup agent preset <预设名>"
        return 0
    fi

    budget_print_info "应用预设: ${preset_name}（平台: ${BUDGET_PLATFORM_KIND}，目录: ${BUDGET_AGENTS_DIR}）"
    local rc=0
    _budget_resolver rewrite --agents-dir "$BUDGET_AGENTS_DIR" \
        --platform "$BUDGET_PLATFORM_KIND" --mode preset --preset "$preset_name" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        budget_print_error "预设应用失败: $preset_name"
        return 1
    fi
    budget_print_success "已应用预设: $preset_name"
}

# 模式：inherit（全部 agent 跟随主会话模型；双平台均删除 model 字段，design.md §3.2）
setup_agent_inherit() {
    budget_print_info "全部 agent 跟随主会话模型（平台: ${BUDGET_PLATFORM_KIND}，目录: ${BUDGET_AGENTS_DIR}）"
    local rc=0
    _budget_resolver rewrite --agents-dir "$BUDGET_AGENTS_DIR" \
        --platform "$BUDGET_PLATFORM_KIND" --mode inherit || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        budget_print_error "inherit 设置失败"
        return 1
    fi
    budget_print_success "全部 agent 已设置为跟随主会话模型（model 字段已删除）"
}

# 模式：custom（统一覆写为指定模型；别名/ID 解析按平台输出最终值）
setup_agent_custom() {
    local input="${1:-}"

    if [[ -z "$input" ]]; then
        budget_print_error "请指定模型: budget setup agent custom <model>"
        budget_print_info "支持标准 ID（glm-5.2）、别名（kimi/opus/sonnet 等）或 provider/model 形态（opencode）"
        return 1
    fi

    # 别名/ID 解析（平台感知：opencode 经 provider_map 输出 provider/model 形态；
    # --custom 信任用户已配置的第三方模型，方舟/Presence/讯飞/doubao 等原样返回）
    local resolved rc=0
    resolved=$(_budget_resolver resolve --input "$input" --platform "$BUDGET_PLATFORM_KIND" --custom 2>&1) || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        budget_print_error "模型解析失败:"
        echo "$resolved" >&2
        return 1
    fi
    if [[ "$resolved" != "$input" ]]; then
        budget_print_info "别名解析: $input → $resolved"
    fi

    budget_print_info "统一覆写全部 agent（平台: ${BUDGET_PLATFORM_KIND}，目录: ${BUDGET_AGENTS_DIR}）"
    rc=0
    _budget_resolver rewrite --agents-dir "$BUDGET_AGENTS_DIR" \
        --platform "$BUDGET_PLATFORM_KIND" --mode custom --model "$resolved" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        budget_print_error "custom 覆写失败: $resolved"
        return 1
    fi
    budget_print_success "全部 agent 已设置为: $resolved"
}

# ─── do_diff 查询函数（供 T9c update.sh 的 do_diff 调用）─────────────────
# 输出契约（两函数一致，可逐行 join 对比）：
#   stdout 每行 "<agent 文件名>=<model 值>"
#   - agent 文件名：连字符形态（coder-lite），仅本套件 10 agent（roles 映射命中）
#   - model 值：frontmatter 顶层 model 字段当前值（引号剥离）；字段缺失时为空串
#   - 失败（未探测到平台/目录缺失/预设名非法）时 stderr 报错并返回非零

# 当前全部 agent 的 model 值（按 platform.sh 探测定位 agent 目录）
budget_get_current_models() {
    detect_platform >/dev/null || true
    if [[ "${BUDGET_PLATFORM_KIND:-unknown}" == "unknown" || -z "${BUDGET_AGENTS_DIR:-}" ]]; then
        echo "budget_get_current_models: 未检测到平台形态，无法定位 agent 目录" >&2
        return 1
    fi
    _budget_resolver current --agents-dir "$BUDGET_AGENTS_DIR"
}

# 指定预设的 agent→模型表（platform 缺省按探测结果，探测失败回退 codebuddy）
budget_preset_table() {
    local preset_name="${1:-balanced}"
    local platform="${2:-}"
    if [[ -z "$platform" ]]; then
        detect_platform >/dev/null || true
        platform="${BUDGET_PLATFORM_KIND:-codebuddy}"
        if [[ "$platform" == "unknown" ]]; then
            platform="codebuddy"
        fi
    fi
    _budget_resolver preset --name "$preset_name" --platform "$platform"
}
