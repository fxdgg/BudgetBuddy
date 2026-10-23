# agent-roster Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
### Requirement: 10 个 agent 中立定义齐全

`core/agents/` 恰好包含 10 个中立 agent：architect、coder-lite、coder-standard、coder-senior、reviewer、reviewer-b、tester、recorder、director、goal-evaluator；name/model_role/edit_allow/bash_allow/max_turns 按 design.md §6 角色表逐项一致；`auto_run` 按角色表对应列：coder-lite/coder-senior/coder-standard/tester 四个执行类 agent 为 `true`，其余 6 个（architect/reviewer/reviewer-b/recorder/director/goal-evaluator）不声明；正文为中立措辞（含职责、触发时机、协作约定），含模板变量处遵守 §3.3 白名单（design.md §6）。【MUST】

#### Scenario: 构建校验角色清单

- **WHEN** build 执行 §3.1 校验
- **THEN** 10 个文件的 name 恰为角色清单全集（无缺失、无多余）

#### Scenario: 只读 agent 权限落位

- **WHEN** 构建 reviewer/reviewer-b/tester/recorder/director/goal-evaluator
- **THEN** 其编辑权限按 §6 表映射（reviewer/director/goal-evaluator 只读；recorder 可写 openspec/docs；tester 只读但 bash 全放开；director/goal-evaluator bash 禁止）

#### Scenario: 角色表逐项一致

- **WHEN** reviewer 审计 10 个文件的 frontmatter
- **THEN** model_role、max_turns 与 §6 表逐行一致（如 director max_turns=15、goal-evaluator=8、architect=80）

#### Scenario: auto_run 默认开启清单

- **WHEN** 审计 10 个文件的 `auto_run` 声明
- **THEN** 恰为 coder-lite/coder-senior/coder-standard/tester 四个执行类 agent 声明 `true`，其余 6 个不声明（保留逐条人工确认）

#### Scenario: 执行类 agent 产物免审批

- **WHEN** 构建 CodeBuddy 平台后检查 4 个执行类 agent 产物
- **THEN** 四个产物含 `enabledAutoRun: true`，6 个保留确认 agent 产物不含该键

### Requirement: 正文职责与协作语义中立化

每个 agent 正文描述职责、触发时机与上下游协作（如 coder 三级差异、reviewer A/B 交叉复核、director 六类裁决、goal-evaluator 判定输出），全部使用平台中立措辞；子代理调用语法用 `{{TASK_TOOL}}` 变量；不出现任何平台专有 API 名称或参照项目品牌（design.md §3.3/§6）。【MUST】

#### Scenario: 双平台产物正文等价
- **WHEN** 构建后对比 dist/codebuddy 与 dist/opencode 的同一 agent
- **THEN** 除六个模板变量的平台取值与 frontmatter 结构外，正文内容一致

#### Scenario: 品牌零残留
- **WHEN** scan-brand.py 扫描 core/agents/
- **THEN** 零违禁词命中

### Requirement: reviewer 结论结构化标记

`core/agents/reviewer.md` 与 `reviewer-b.md` 的输出格式章节 SHALL 约定报告末尾追加一行机器可解析的结构化标记：`<!-- budget-verdict: {...} -->`（单行 JSON，HTML 注释形态，markdown 渲染零干扰）。reviewer 标记含 `rating`（A/B/C/D）、`conclusion`（pass/revise/escalate）、`round`（Phase 2 评审轮次 1-3；Phase 4 终审固定填 0）三键；reviewer-b 标记含 `conclusion`（pass/fail）、`round`（1-3，仅 Phase 2 输出故无 0 值）两键。标记为输出格式 MUST 级约定（缺失时 metrics 采集退化为人工兜底，不阻断审查流程本身）；标记行 MUST NOT 改变报告既有结构（行内追加，不新增章节）。标记 MUST 仅在 Phase 2（方案评审）与 Phase 4（终审）输出——Phase 3 per-task 审查 MUST NOT 输出 budget-verdict（防 round 污染聚合）；标记行位于报告正文末尾、任何 code fence 之外。【MUST】

#### Scenario: reviewer 标记形态

- **WHEN** reviewer 完成一次 Phase 2 第 2 轮评审（评分 B、结论需修改）
- **THEN** 报告末行输出 `<!-- budget-verdict: {"rating":"B","conclusion":"revise","round":2} -->`，报告其余结构不变

#### Scenario: 终审标记 round 为 0

- **WHEN** reviewer 完成 Phase 4 最终审查（评分 A、通过）
- **THEN** 标记为 `round: 0`（区分终审与 Phase 2 轮次）

#### Scenario: reviewer-b 标记无评分

- **WHEN** reviewer-b 完成评审（不通过）
- **THEN** 标记仅含 conclusion 与 round 两键（辅审报告本无评分结构）

#### Scenario: Phase 3 不输出标记

- **WHEN** reviewer 执行 Phase 3 per-task 代码审查
- **THEN** 报告不含 budget-verdict 标记（仅 Phase 2 / Phase 4 输出）

#### Scenario: 四平台产物同步

- **WHEN** 构建后核对 dist 四平台 reviewer 产物
- **THEN** 标记约定章节随 agent 定义整文件分发，四平台一致
