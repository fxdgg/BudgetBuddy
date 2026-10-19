#!/bin/bash
# BudgetBuddy 管理入口：budget setup <子命令>（design.md §8.1/A11）
# 用法: setup.sh [init|show|agent|persona|validate|diff|stats|update|reinstall|uninstall|guard|quickstart|models|notify|status|help]

set -euo pipefail

# ---- Python 命令检测（Windows 兼容：Windows 上通常为 python 而非 python3）----
export BUDGET_PYTHON="${BUDGET_PYTHON:-}"
if [[ -z "$BUDGET_PYTHON" ]]; then
    if command -v python3 &>/dev/null; then
        export BUDGET_PYTHON="python3"
    elif command -v python &>/dev/null; then
        export BUDGET_PYTHON="python"
    else
        export BUDGET_PYTHON="python3"
    fi
fi

# ---- 安装根定位（脚本所在目录；兼容 core 源形态与安装产物形态）----
BUDGET_SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUDGET_LIB_DIR="${BUDGET_LIB_DIR:-$BUDGET_SETUP_DIR/lib}"

# 模型目录定位：安装形态（setup.sh 同目录）优先，core 源形态（models/ 子目录）兜底
BUDGET_MODELS_FILE="${BUDGET_MODELS_FILE:-}"
if [[ -z "$BUDGET_MODELS_FILE" ]]; then
    if [[ -f "$BUDGET_SETUP_DIR/budget-models.json" ]]; then
        BUDGET_MODELS_FILE="$BUDGET_SETUP_DIR/budget-models.json"
    elif [[ -f "$BUDGET_SETUP_DIR/models/budget-models.json" ]]; then
        BUDGET_MODELS_FILE="$BUDGET_SETUP_DIR/models/budget-models.json"
    else
        BUDGET_MODELS_FILE="$BUDGET_SETUP_DIR/budget-models.json"
    fi
fi

BUDGET_GLOBAL="${BUDGET_GLOBAL:-0}"
export BUDGET_SETUP_DIR BUDGET_LIB_DIR BUDGET_MODELS_FILE BUDGET_GLOBAL

# ---- lib 模块加载 ----
# 基础层 4 文件为硬依赖（缺失即无法工作）；后续任务模块（init/update/
# uninstall/models/preset/rtk/notify/hooks/persona/validate/guard）存在才
# 加载——未就位时分发到对应子命令时由 budget_require_module 报
# 「模块未安装」错误（source 时检查文件存在性自然实现）。
budget_source_module() {
    local name="$1"
    local file="$BUDGET_LIB_DIR/$name"
    if [[ -f "$file" ]]; then
        # shellcheck disable=SC1090  # 动态路径 source
        source "$file"
        return 0
    fi
    return 1
}

for _budget_base_module in colors.sh utils.sh platform.sh shell.sh; do
    if ! budget_source_module "$_budget_base_module"; then
        echo "ERROR: 基础模块缺失: $BUDGET_LIB_DIR/$_budget_base_module" >&2
        exit 1
    fi
done

for _budget_optional_module in init.sh update.sh uninstall.sh models.sh preset.sh rtk.sh notify.sh hooks.sh persona.sh validate.sh guard.sh; do
    budget_source_module "$_budget_optional_module" || true
done
unset _budget_base_module _budget_optional_module

# ---- 模块就位检查（分发到未就位模块时显式报错，exit 1）----
budget_require_module() {
    local cmd="$1"
    local func="$2"
    local module="$3"
    if ! declare -f "$func" &>/dev/null; then
        budget_print_error "子命令 '$cmd' 的实现模块尚未安装（lib/${module}）"
        budget_print_info "请先完成安装或更新：budget setup update"
        return 1
    fi
    return 0
}

# ---- 内置子命令：show / status ----
# show 固定走内置概览；status 在 notify.sh 就位（提供 do_status 状态查询：
# guard 汇总 + 状态机活跃变更 + agent 配置概览）时优先分发，否则降级 show。
budget_cmd_show() {
    budget_print_header

    # 当前 shell 直接调用（变量副作用生效；stdout 结果丢弃，stderr 诊断保留）
    detect_platform >/dev/null || true
    if [[ "${BUDGET_PLATFORM_KIND:-unknown}" == "unknown" ]]; then
        budget_print_warning "未检测到已安装的 BudgetBuddy 平台形态，仅展示模型目录信息"
    else
        budget_print_info "运行平台: $BUDGET_PLATFORM_KIND:$BUDGET_PLATFORM_SCOPE${BUDGET_PLATFORM_ROOT:+ (root: $BUDGET_PLATFORM_ROOT)}"
        budget_print_info "Agent 目录: ${BUDGET_AGENTS_DIR:-}"
    fi
    budget_print_info "模型目录: $BUDGET_MODELS_FILE"
    echo ""

    BUDGET_SHOW_AGENTS_DIR="${BUDGET_AGENTS_DIR:-}" \
    BUDGET_SHOW_MODELS_FILE="$BUDGET_MODELS_FILE" \
        "$BUDGET_PYTHON" << 'PYEOF'
import glob
import json
import os

agents_dir = os.environ.get('BUDGET_SHOW_AGENTS_DIR', '')
models_file = os.environ.get('BUDGET_SHOW_MODELS_FILE', '')

# balanced 预设反查表：model → model_role（双平台合并）
role_by_model = {}
models_meta = {}
if models_file and os.path.isfile(models_file):
    try:
        with open(models_file, encoding='utf-8') as f:
            data = json.load(f)
        models_meta = data.get('_meta', {})
        for platform in ('codebuddy', 'opencode'):
            presets = (data.get('platforms', {}).get(platform, {})
                       .get('presets', {}).get('balanced', {}))
            for role, model in presets.items():
                role_by_model.setdefault(model, role)
    except (OSError, ValueError):
        print('（警告: budget-models.json 解析失败）')
else:
    print('（警告: 未找到 budget-models.json）')

rows = []
if agents_dir and os.path.isdir(agents_dir):
    for path in sorted(glob.glob(os.path.join(agents_dir, '*.md'))):
        name = os.path.basename(path)[:-3]
        model = '(未设置)'
        try:
            with open(path, encoding='utf-8') as f:
                lines = f.read().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        if lines and lines[0].strip() == '---':
            for line in lines[1:]:
                if line.strip() == '---':
                    break
                if line.startswith('model:'):
                    model = line.split(':', 1)[1].strip().strip('\'"')
                    break
        rows.append((name, model, role_by_model.get(model, '-')))
else:
    print('（未检测到 agent 目录，跳过 agent 清单）')

if rows:
    print('Agent 模型配置（%s）：' % agents_dir)
    print('  %-16s %-28s %s' % ('Agent', 'Model', 'Model Role'))
    for name, model, role in rows:
        print('  %-16s %-28s %s' % (name, model, role))
    print('共 %d 个 agent。' % len(rows))
# 外部自定义模型（来自 CodeBuddy 客户端配置：方舟/Presence/讯飞/doubao 等）
_bm = data.get('models', {})
budget_ids = {e.get('id', '').lower() for sec in ('paid', 'free')
              for v, es in _bm.get(sec, {}).items() for e in es}
_ext_paths = [os.path.expanduser('~/.codebuddy/models.json'),
              os.path.join(os.getcwd(), '.codebuddy/models.json')]
_ext = []
_ext_seen = set()
for _ep in _ext_paths:
    if os.path.isfile(_ep):
        try:
            _ed = json.load(open(_ep, encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for _m in _ed.get('models', []):
            if not isinstance(_m, dict):
                continue
            _mid = _m.get('id')
            if not _mid or _mid.lower() in _ext_seen or _mid.lower() in budget_ids:
                continue
            _ext_seen.add(_mid.lower())
            _ext.append((_mid, _m.get('vendor', '-'), _m.get('name', _mid)))
if _ext:
    print('')
    print('外部自定义模型 · CodeBuddy（来自客户端 models.json）:')
    _by_v = {}
    for _mid, _v, _n in _ext:
        _by_v.setdefault(_v, []).append(_mid)
    for _v in sorted(_by_v):
        print('  [%s] %s' % (_v, ', '.join(_by_v[_v])))
    print('  → 可分配: budget setup agent custom <id>')

# 外部自定义模型 · opencode（~/.config/opencode/opencode.jsonc|json 的 provider.<name>.models）
import re as _ore
def _oload(_p):
    try:
        _raw = open(_p, encoding='utf-8').read()
    except OSError:
        return None
    _raw = _ore.sub(r'/\*.*?\*/', '', _raw, flags=_ore.S)
    _raw = _ore.sub(r'(?m)(?<![:"])//.*$', '', _raw)
    try:
        return json.loads(_raw)
    except ValueError:
        return None

_oc = []
_oc_seen = set()
for _ocp in [os.path.expanduser('~/.config/opencode/opencode.jsonc'),
             os.path.expanduser('~/.config/opencode/opencode.json'),
             os.path.join(os.getcwd(), 'opencode.jsonc'),
             os.path.join(os.getcwd(), 'opencode.json')]:
    _ocd = _oload(_ocp)
    if isinstance(_ocd, dict):
        for _prov, _pcfg in (_ocd.get('provider') or {}).items():
            if not isinstance(_pcfg, dict):
                continue
            for _mid in (_pcfg.get('models') or {}):
                _ref = '%s/%s' % (_prov, _mid)
                if _ref.lower() not in _oc_seen:
                    _oc_seen.add(_ref.lower())
                    _oc.append((_prov, _ref))
if _oc:
    print('')
    print('外部自定义模型 · opencode（来自 ~/.config/opencode/opencode.jsonc）:')
    _by_p = {}
    for _prov, _ref in _oc:
        _by_p.setdefault(_prov, []).append(_ref)
    for _prov in sorted(_by_p):
        print('  [%s] %s' % (_prov, ', '.join(sorted(_by_p[_prov]))))
    print('  → opencode 可分配: budget setup agent custom <provider/model>')

if models_meta:
    print('模型目录更新于 %s（更新命令: %s）' % (
        models_meta.get('updated_at', '-'),
        models_meta.get('update_command', '-')))
PYEOF
}

# ---- 内置子命令：models（降级概要；完整表格归 lib/models.sh do_models，就位时优先分发）----
budget_cmd_models() {
    budget_print_header
    if [[ ! -f "$BUDGET_MODELS_FILE" ]]; then
        budget_print_error "模型目录文件不存在: $BUDGET_MODELS_FILE"
        budget_print_info "请先完成安装或更新：budget setup update"
        return 1
    fi
    budget_print_info "模型目录: $BUDGET_MODELS_FILE"
    echo ""
    BUDGET_SHOW_MODELS_FILE="$BUDGET_MODELS_FILE" "$BUDGET_PYTHON" << 'PYEOF'
import json
import os

try:
    with open(os.environ['BUDGET_SHOW_MODELS_FILE'], encoding='utf-8') as f:
        data = json.load(f)
except (OSError, ValueError) as exc:
    print('模型目录解析失败: %s' % exc)
    raise SystemExit(1)

meta = data.get('_meta', {})
models = data.get('models', {})
for section, title in (('paid', '付费模型'), ('free', '免费模型')):
    groups = models.get(section, {})
    count = sum(len(entries) for entries in groups.values())
    vendors = ', '.join(sorted(groups))
    print('%s: %d 个（厂商: %s）' % (title, count, vendors or '-'))
aliases = data.get('aliases', {})
print('别名: %d 个' % len(aliases))
platforms = data.get('platforms', {})
for platform in sorted(platforms):
    presets = platforms[platform].get('presets', {})
    preset_names = ', '.join(sorted(presets))
    role_count = len(next(iter(presets.values()), {}))
    print('预设: %s × %s（%d 角色/档）' % (platform, preset_names, role_count))
print('更新于: %s' % meta.get('updated_at', '-'))
print('更新命令: %s' % meta.get('update_command', '-'))

# 外部自定义模型（来自 CodeBuddy 客户端配置）
_bm = data.get('models', {})
budget_ids = {e.get('id', '').lower() for sec in ('paid', 'free')
              for v, es in _bm.get(sec, {}).items() for e in es}
_ext_paths = [os.path.expanduser('~/.codebuddy/models.json'),
              os.path.join(os.getcwd(), '.codebuddy/models.json')]
_ext = []
_ext_seen = set()
for _ep in _ext_paths:
    if os.path.isfile(_ep):
        try:
            _ed = json.load(open(_ep, encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for _m in _ed.get('models', []):
            if not isinstance(_m, dict):
                continue
            _mid = _m.get('id')
            if not _mid or _mid.lower() in _ext_seen or _mid.lower() in budget_ids:
                continue
            _ext_seen.add(_mid.lower())
            _ext.append((_mid, _m.get('vendor', '-'), _m.get('name', _mid)))
if _ext:
    print('外部自定义模型 · CodeBuddy（来自客户端 models.json）:')
    _by_v = {}
    for _mid, _v, _n in _ext:
        _by_v.setdefault(_v, []).append(_mid)
    for _v in sorted(_by_v):
        print('  [%s] %s' % (_v, ', '.join(_by_v[_v])))

# 外部自定义模型 · opencode（~/.config/opencode/opencode.jsonc|json 的 provider.<name>.models）
import re as _ore
def _oload(_p):
    try:
        _raw = open(_p, encoding='utf-8').read()
    except OSError:
        return None
    _raw = _ore.sub(r'/\*.*?\*/', '', _raw, flags=_ore.S)
    _raw = _ore.sub(r'(?m)(?<![:"])//.*$', '', _raw)
    try:
        return json.loads(_raw)
    except ValueError:
        return None

_oc = []
_oc_seen = set()
for _ocp in [os.path.expanduser('~/.config/opencode/opencode.jsonc'),
             os.path.expanduser('~/.config/opencode/opencode.json'),
             os.path.join(os.getcwd(), 'opencode.jsonc'),
             os.path.join(os.getcwd(), 'opencode.json')]:
    _ocd = _oload(_ocp)
    if isinstance(_ocd, dict):
        for _prov, _pcfg in (_ocd.get('provider') or {}).items():
            if not isinstance(_pcfg, dict):
                continue
            for _mid in (_pcfg.get('models') or {}):
                _ref = '%s/%s' % (_prov, _mid)
                if _ref.lower() not in _oc_seen:
                    _oc_seen.add(_ref.lower())
                    _oc.append((_prov, _ref))
if _oc:
    print('外部自定义模型 · opencode（来自 ~/.config/opencode/opencode.jsonc）:')
    _by_p = {}
    for _prov, _ref in _oc:
        _by_p.setdefault(_prov, []).append(_ref)
    for _prov in sorted(_by_p):
        print('  [%s] %s' % (_prov, ', '.join(sorted(_by_p[_prov]))))
if not _ext and not _oc:
    print('外部自定义模型: 无（CodeBuddy / opencode 配置均未检出额外模型）')
PYEOF
}

# ---- 内置子命令：help（子命令全集，design.md §8.1/A11）----
budget_cmd_help() {
    budget_print_header
    cat << 'EOF'
用法: budget setup <子命令> [参数]（或直接 budget <子命令>）

子命令全集:
  init [shell]   初始化安装（init shell 注入 CodeBuddy CLI shell 别名）
  show           展示当前 agent 模型配置
  status         状态查询（独立入口 budget status，同 show）
  agent ...      模型预设切换/覆写（preset|inherit|custom）
  persona ...    persona 主题管理（list|set|expand|show）
  validate       安装完整性校验
  diff [preset]  当前配置 vs 预设对比（默认 balanced）
  stats          工作流统计
  update         增量更新（budget update 为顶层快捷别名）
  reinstall      uninstall + init 组合重装
  uninstall      卸载
  guard ...      Coder Guard 查询/重置
  quickstart     快速上手引导（别名 tour / wizard）
  models         模型目录查看
  notify <消息> <事件名>  发送通知（独立入口 budget notify）
  help           显示本帮助

环境变量（BUDGET_* 前缀）:
  BUDGET_GLOBAL   全局模式标志（1=全局）
  BUDGET_DIR      运行时数据目录覆盖（默认 .budget/ > ~/.budgetbuddy/）
  BUDGET_PLATFORM 显式指定平台（codebuddy|opencode，跳过运行时探测）
EOF
}

# ---- 入口分发（子命令全集对齐参照项目 setup.sh 实际分发，A11）----
# 分发纪律：子命令参数一律 shift 后透传 do_xxx "$@"（do_* 内部已实现
# 参数解析：--yes/--purge/--non-interactive 等；无参子命令透传多余参数
# 由 do_* 侧 warning 忽略，不阻断分发）。
budget_main() {
    # 「budget setup <子命令>」前缀形式：剥离 setup 后重新分发；
    # 裸 budget setup（无后续参数）显示帮助（避免意外触发 init）。
    if [[ "${1:-}" == "setup" ]]; then
        shift
        if [[ $# -eq 0 ]]; then
            budget_cmd_help
            return 0
        fi
        budget_main "$@"
        return
    fi
    case "${1:-help}" in
        init)
            if [[ "${2:-}" == "shell" ]]; then
                budget_setup_shell_alias
            else
                shift
                budget_require_module "init" "do_init" "init.sh"
                do_init "$@"
            fi
            ;;
        show|status)
            if [[ "${1:-}" == "status" ]] && declare -f do_status &>/dev/null; then
                shift
                do_status "$@"
            else
                budget_cmd_show
            fi
            ;;
        agent)
            shift
            budget_require_module "agent" "setup_agent" "preset.sh"
            setup_agent "$@"
            ;;
        persona)
            shift
            budget_require_module "persona" "do_persona" "persona.sh"
            do_persona "$@"
            ;;
        validate|check)
            shift
            budget_require_module "validate" "do_validate" "validate.sh"
            do_validate "$@"
            ;;
        diff)
            shift
            budget_require_module "diff" "do_diff" "update.sh"
            do_diff "${1:-balanced}"
            ;;
        stats)
            if [[ -f "$BUDGET_LIB_DIR/display.py" ]]; then
                # 平台探测注入形态变量（display.py 项目形态概览数据源；
                # detect_platform 的变量副作用需 export 后才能传入子进程）
                shift
                detect_platform >/dev/null || true
                export BUDGET_PLATFORM_KIND BUDGET_PLATFORM_SCOPE BUDGET_PLATFORM_ROOT BUDGET_AGENTS_DIR
                exec "$BUDGET_PYTHON" "$BUDGET_LIB_DIR/display.py" "$@"
            fi
            budget_print_error "子命令 'stats' 的实现模块尚未安装（lib/display.py）"
            budget_print_info "请先完成安装或更新：budget setup update"
            return 1
            ;;
        update|upgrade)
            shift
            budget_require_module "update" "do_update" "update.sh"
            do_update "$@"
            ;;
        reinstall)
            shift
            budget_require_module "reinstall" "do_reinstall" "update.sh"
            do_reinstall "$@"
            ;;
        uninstall|remove)
            shift
            budget_require_module "uninstall" "do_uninstall" "uninstall.sh"
            do_uninstall "$@"
            ;;
        guard)
            shift
            budget_require_module "guard" "setup_guard" "guard.sh"
            setup_guard "$@"
            ;;
        notify)
            shift
            budget_require_module "notify" "_dispatch_notify" "notify.sh"
            _dispatch_notify "$@"
            ;;
        quickstart|tour|wizard)
            if [[ -f "$BUDGET_LIB_DIR/quickstart.py" ]]; then
                shift
                exec "$BUDGET_PYTHON" "$BUDGET_LIB_DIR/quickstart.py" "$@"
            fi
            budget_print_error "子命令 'quickstart' 的实现模块尚未安装（lib/quickstart.py）"
            budget_print_info "请先完成安装或更新：budget setup update"
            return 1
            ;;
        models)
            if declare -f do_models &>/dev/null; then
                shift
                do_models "$@"
            else
                budget_cmd_models
            fi
            ;;
        help|--help|-h)
            budget_cmd_help
            ;;
        *)
            budget_print_error "未知子命令: ${1:-}"
            budget_cmd_help
            return 1
            ;;
    esac
}

budget_main "$@"
