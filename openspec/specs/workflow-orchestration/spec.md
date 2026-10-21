# workflow-orchestration Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
### Requirement: budget-workflow skill 完整文件集

`core/skills/budget-workflow/` 包含 SKILL.md、router.md、phases.md、goal.md、reference.md 五个文件（调整点 A1），功能对等参照项目：5 阶段工作流、任务分级路由（lite/standard/senior）、Coder Guard、Review Gate（A/B 审查）、3 轮驳回应急、Director 六类裁决、goal loop；通知调用统一改 `budget notify`、消息前缀 `[budget]`（design.md §1/§12-A1）。【MUST】

#### Scenario: 文件集完整
- **WHEN** reviewer 审计 core/skills/budget-workflow/
- **THEN** 五个 markdown 文件齐全，且状态脚本不在 skill 目录内（单份化于 core/lib/budget-state.py）

#### Scenario: 5 阶段结构齐全
- **WHEN** 阅读 phases.md
- **THEN** 覆盖全部 5 个阶段（含 Phase 2 审查、Phase 3 验证）及各阶段入口/出口条件

#### Scenario: 状态机引用单份化
- **WHEN** SKILL.md/router.md 等引用状态脚本
- **THEN** 统一指向 `$HOME/.budgetbuddy/lib/budget-state.py`，不出现 skill 目录内第二份状态脚本（调整点 A4）

### Requirement: 任务分级路由

router.md 定义任务复杂度评估与 coder 三级（lite/standard/senior）派发规则，与 agent 权限/模型分级联动；路由结果影响 guard 记录与通知节点变量（design.md §6/§1）。本条属提示词行为约束，验收方式为人工审计（T13），不设自动化用例。【MUST】

#### Scenario: 分级派发规则可执行
- **WHEN** Leader 按 router.md 评估一个「简单配置修改」任务
- **THEN** 路由结论为 coder-lite；「架构/安全/并发」类任务路由 coder-senior

### Requirement: Coder Guard 护栏

工作流含 Coder Guard：coder 任务被驳回（reviewer 判定失败）后，经 `core/lib/guard.sh` 读写 `$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json`，记录跨会话失败历史（history: timestamp/coder/tags/result/escalated_to + summary 计数），以最近 5 次窗口内失败 ≥2 触发分级降级（standard→lite、senior→standard，参照项目语义）；guard 路径在正文中以 `{{GUARD_PATH}}` 变量表达（design.md §3.3/§8.2/§8.4）。任务范围审计（修改文件清单 vs design.md §16 文件范围）由 reviewer 在 Phase 3 审查与 4.3 文件范围审计步骤承担，非 guard 职责（A14）。【MUST】

#### Scenario: guard 记录读写
- **WHEN** coder 任务被 reviewer 驳回后触发记录
- **THEN** coder-guard.json 的 history 追加条目（时间戳/分级/标签/结果）且 summary 计数同步更新

#### Scenario: 越界驳回
- **WHEN** reviewer 发现实际修改超出 design.md §16 文件范围清单
- **THEN** 按 4.3 文件范围审计流程驳回并计入 3 轮驳回应急计数

### Requirement: Review Gate 与 Director 终裁

工作流定义 Review Gate（reviewer A + reviewer-b 交叉复核）、3 轮驳回应急（升级 coder 级别/Director 介入）、Director 六类裁决（实现分歧、驳回争议、优先级、范围变更、风险放行、终止）；通知点按 notify capability **N1-N11** 联动（节点定义表见 design.md §9，N11 = Goal Loop 达成通知）（design.md §1/§9）。【MUST】

#### Scenario: 3 轮驳回应急
- **WHEN** 同一任务累计 3 轮审查驳回
- **THEN** 工作流按应急路径升级处理（换更高级 coder 或 Director 介入），并发对应通知
#### Scenario: Director 只读终裁

- **WHEN** 分歧升级至 director agent
- **THEN** director 仅基于只读信息输出六类裁决之一，不执行任何写操作（对应 §6 权限）

### Requirement: Review Gate 可选 OCR 机器预审

Review Gate（reviewer + reviewer-b 交叉复核）阶段 SHALL 支持可选的 OpenCodeReview（开源 `ocr` CLI）机器预审：双 reviewer 在启动审查时按 ocr-pre-review capability 的探测与降级语义尝试获取结构化预审结果，作为各自审查维度的辅助输入（detector），最终裁决权保留在 reviewer agent（judge）；预审缺失或失败 MUST NOT 影响 Review Gate 的既有语义——3 轮驳回应急、Director 六类裁决、通知节点 N1-N11 联动均不变。本条属提示词行为约束，验收方式为人工审计 + 构建产物一致性校验，不设自动化用例（人工审计为该豁免项的验收方式）。【MUST】

#### Scenario: 预审缺失不影响应急语义

- **WHEN** 同一任务累计 3 轮审查驳回且环境中无 `ocr` CLI
- **THEN** 3 轮驳回应急路径（升级 coder 级别/Director 介入）与对应通知行为与集成前完全一致

#### Scenario: 预审结果进入双审分工

- **WHEN** 预审返回 security 与 test 类 finding
- **THEN** security 类由 reviewer-b 深度验证、test 类由 reviewer-b 按测试逻辑独立验证职责处理，主审不重复审查

### Requirement: goal loop

工作流支持 goal 模式：goal-evaluator 基于只读信息判定目标达成情况，未达成时循环继续派发、超限时终止并通知（design.md §6/§1、goal.md）。【MUST】

#### Scenario: 目标判定循环
- **WHEN** 一轮实现验证后 goal-evaluator 判定目标未达成
- **THEN** 工作流按 goal.md 规则继续下一轮派发；循环超限时终止并发通知

### Requirement: P0 规则三层落位

leader-no-code、coder-guard、流程强制 3 条 P0 规则同时落位于：① CodeBuddy `rules/budget-*.mdc`；② SKILL.md「强制执行规则（P0）」内联章节（双平台一致）；③ OpenCode AGENTS.fragment.md 标记区块；①③由 core/rules/ 派生、②手工维护，构建时 diff 校验一致性（不一致告警不阻断）（design.md §3.4）。【MUST】

#### Scenario: 三层内容一致
- **WHEN** 构建时执行 P0 一致性 diff 校验
- **THEN** 三处 P0 规则语义一致；不一致时构建继续但输出告警（文件与差异摘要）

#### Scenario: OpenCode 侧同等约束
- **WHEN** 用户仅安装 opencode 产物
- **THEN** AGENTS.fragment 合并与 SKILL 内联两处均含 P0 规则全文，强制力不依赖平台原生 rules 机制

