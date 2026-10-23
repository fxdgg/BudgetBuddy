# setup-cli Delta Spec

## MODIFIED Requirements

### Requirement: lib 24 文件模块化

`core/lib/` 代码模块按六组组织（design.md §8.2）：基础层（colors/utils/platform/shell，4）、生命周期（init/update/uninstall，3）、模型与护栏（models/preset/model_resolver/guard/guard_metrics/rtk/ocr-setup，7）、persona 与校验（persona/persona_expand/validate/budget-state/display，5）、交互与汇总（interactive/quickstart/run_summary/banner/autorun/metrics，6）、通知与 hooks（notify/hooks/hooks_inject，3）——共 **28 个代码模块**（16 .sh + 12 .py）另含 1 个数据模板（ocr-rule.json，非模块，经 `_build_lib` 分发的规则模板；标题「24」为归档合并锚点保留的历史计数，正文计数已修正）。状态机 `budget-state.py` 全仓单份（A4），skill 文档经 `$HOME/.budgetbuddy/lib/budget-state.py` 引用。lib 不随产物分发内嵌测试，测试统一在仓库根 `tests/`。【MUST】

#### Scenario: guard_metrics 归组

- **WHEN** 检查 core/lib/ 目录
- **THEN** guard_metrics.py 存在且与 guard.sh、ocr-setup.py 同属「模型与护栏」组，autorun.py 归「交互与汇总」组；模块计数为 28（.sh/.py）+ ocr-rule.json 数据模板，六组枚举与目录文件一一对应无缺漏

#### Scenario: dist 同步

- **WHEN** 构建完成后核对四平台 dist 的 lib/
- **THEN** guard_metrics.py 与 metrics.py 均经 `_build_lib` 字节平移分发，display.py/run_summary.py 与其同目录（import 路径成立）
