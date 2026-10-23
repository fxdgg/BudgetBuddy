# agent-roster Delta Spec

## ADDED Requirements

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
