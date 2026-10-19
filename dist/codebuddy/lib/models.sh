#!/bin/bash
# BudgetBuddy model catalog（design.md §7 / §8.1 models 子命令）
#
# 职责：budget setup models 完整实现——模型目录表格（paid/free 分组 + 倍率 +
# 档位 + 适用角色推荐 + 平台可用性 + 别名速查 + 双平台预设概览）。
# 依赖调用方（setup.sh）提供：$BUDGET_PYTHON、$BUDGET_MODELS_FILE、
# budget_print_*（colors.sh）。
# 分发约定：lib/models.sh 就位时 setup.sh 调用 do_models（本文件）；未就位时
# 降级为 setup.sh 内置概要实现（budget_cmd_models），保证部分安装下可用。

# do_models：模型目录完整表格（setup.sh models 分发入口）
do_models() {
    budget_print_header
    if [[ ! -f "$BUDGET_MODELS_FILE" ]]; then
        budget_print_error "模型目录文件不存在: $BUDGET_MODELS_FILE"
        budget_print_info "请先完成安装或更新：budget setup update"
        return 1
    fi
    budget_print_info "模型目录: $BUDGET_MODELS_FILE"
    echo ""
    BUDGET_MODELS_FILE="$BUDGET_MODELS_FILE" "$BUDGET_PYTHON" << 'PYEOF'
import json
import os

try:
    with open(os.environ['BUDGET_MODELS_FILE'], encoding='utf-8') as handle:
        data = json.load(handle)
except (OSError, ValueError) as exc:
    print(f'模型目录解析失败: {exc}')
    raise SystemExit(1)

meta = data.get('_meta', {})
unconfirmed = meta.get('unconfirmed_opencode_ids', [])
print(f"更新于: {meta.get('updated_at', '-')}（更新命令: {meta.get('update_command', '-')}）")
if unconfirmed:
    print(f'注意: {len(unconfirmed)} 个 opencode 预设 ID 待官方清单核对'
          '（详见 _meta.unconfirmed_opencode_ids）')
print('')


def platform_mark(platforms):
    """平台可用性短标：双平台 / cb / oc。"""
    if len(platforms) >= 2:
        return '双平台'
    if platforms:
        return {'codebuddy': 'cb', 'opencode': 'oc'}.get(platforms[0], platforms[0])
    return '-'


models = data.get('models', {})
for section, title in (('paid', '付费模型'), ('free', '免费模型')):
    groups = models.get(section, {})
    rows = []
    for vendor in sorted(groups):
        for entry in groups[vendor]:
            roles = ', '.join(entry.get('recommended_for', [])) or '-'
            rows.append((entry.get('id', '-'), vendor, entry.get('cost', '-'),
                         entry.get('tier', '-'), platform_mark(entry.get('platform', [])), roles))
    print(f'{title}（{len(rows)} 个）:')
    if rows:
        print('  %-26s %-9s %-6s %-7s %-6s %s' % ('模型ID', '厂商', '倍率', '档位', '平台', '适用角色'))
        for row in sorted(rows):
            print('  %-26s %-9s %-6s %-7s %-6s %s' % row)
    print('')

aliases = data.get('aliases', {})
if aliases:
    items = [f'{key}→{value}' for key, value in sorted(aliases.items())]
    print(f'别名（{len(items)} 个）:')
    wrapped = []
    current = []
    width = 2
    for item in items:
        if current and width + len(item) + 2 > 78:
            wrapped.append('  ' + '  '.join(current))
            current = []
            width = 2
        current.append(item)
        width += len(item) + 2
    if current:
        wrapped.append('  ' + '  '.join(current))
    print('\n'.join(wrapped))
    print('')

platforms = data.get('platforms', {})
for platform in sorted(platforms):
    presets = platforms[platform].get('presets', {})
    names = ', '.join(sorted(presets))
    role_count = len(next(iter(presets.values()), {}))
    print(f'预设: {platform} × {names}（{role_count} 角色/档）')
print('')
print('预设切换: budget setup agent preset <economic|balanced|quality>')
print('预设明细: budget setup agent preset（无参数列出）')
print('统一覆写: budget setup agent custom <model>（支持别名/第三方模型 ID）')

# 外部自定义模型（来自 CodeBuddy 客户端配置：方舟/Presence/讯飞/doubao 等）
budget_ids = {e.get('id', '').lower() for sec in ('paid', 'free')
              for v, es in data.get('models', {}).get(sec, {}).items() for e in es}
ext_paths = [os.path.expanduser('~/.codebuddy/models.json'),
             os.path.join(os.getcwd(), '.codebuddy/models.json')]
ext_models = []
ext_seen = set()
for ep in ext_paths:
    if os.path.isfile(ep):
        try:
            ed = json.load(open(ep, encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for m in ed.get('models', []):
            if not isinstance(m, dict):
                continue
            mid = m.get('id')
            if not mid or mid.lower() in ext_seen or mid.lower() in budget_ids:
                continue
            ext_seen.add(mid.lower())
            ext_models.append((mid, m.get('vendor', '-'), m.get('name', mid)))
print('')
if ext_models:
    print('外部自定义模型 · CodeBuddy（来自客户端 models.json，可直接 budget setup agent custom <id> 使用）:')
    by_v = {}
    for mid, vendor, name in ext_models:
        by_v.setdefault(vendor, []).append(mid)
    for vendor in sorted(by_v):
        print('  [%s] %s' % (vendor, ', '.join(by_v[vendor])))

# 外部自定义模型 · opencode（~/.config/opencode/opencode.jsonc|json 的 provider.<name>.models）
import re as _re
def _load_jsonc(_p):
    try:
        _raw = open(_p, encoding='utf-8').read()
    except OSError:
        return None
    _raw = _re.sub(r'/\*.*?\*/', '', _raw, flags=_re.S)
    _raw = _re.sub(r'(?m)(?<![:"])//.*$', '', _raw)
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
    _ocd = _load_jsonc(_ocp)
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
    print('外部自定义模型 · opencode（来自 ~/.config/opencode/opencode.jsonc，可直接 budget setup agent custom <provider/model> 使用）:')
    _by_p = {}
    for _prov, _ref in _oc:
        _by_p.setdefault(_prov, []).append(_ref)
    for _prov in sorted(_by_p):
        print('  [%s] %s' % (_prov, ', '.join(sorted(_by_p[_prov]))))
if not ext_models and not _oc:
    print('外部自定义模型: 无（CodeBuddy / opencode 配置均未检出额外模型）')
PYEOF
}
