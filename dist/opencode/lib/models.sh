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
print('统一覆写: budget setup agent custom <model>（支持别名）')
PYEOF
}
