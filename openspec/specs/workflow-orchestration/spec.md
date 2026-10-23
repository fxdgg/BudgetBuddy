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

### Requirement: 归档质量指标采集与查询面趋势告警

Phase 5 归档（recorder）SHALL 在执行 openspec archive **之前**执行质量指标采集（archive 会将 change 目录移动至 `archive/<date>-<id>/`，之后扫描将落空——采集时扫描原 `openspec/changes/<id>/` 目录）：调用 `python3 $HOME/.budgetbuddy/lib/metrics.py record --change-id <id> --change-dir <change目录>`（递归扫描 change 目录 .md 提取全部 budget-verdict 标记，聚合 phase2_rating/phase2_rounds/reviewer_b_conclusion/final_rating，并快照 guard.json 的全量失败/降级计数），写入 `~/.budgetbuddy/projects/<project-name>/memory/metrics.json`（history 追加，同 change_id 重复 record 幂等覆盖；标记缺失字段可人工参数兜底，全缺失记 null 不阻断）。`budget setup stats`（display.py）与 run summary（run_summary.py）SHALL 以延迟导入容错模式（import 失败降级为不展示趋势段、其余照常 exit 0，同 guard_metrics 先例）展示「质量趋势」段：最近 N 次（默认 5）final 评分序列、phase2 一次通过率、guard 失败率，及告警行——R1 评分严格连续下降（最近 ≥3 条）、R2 一次通过率 < 50%、R3 guard 失败率 > 40%（**metrics.json 最新一条快照口径**：guard_failures / guard_history_total，样本 ≥5——分子分母同为 history 快照口径，不混实时值；R2 分母为 0 时不计算不告警）。告警 MUST 仅在查询面呈现（不推送通知、不触发降级、不影响任何流程判定——纯参考层）；N1-N11 通知事件、guard 写入端、降级硬规则 MUST NOT 改变。metrics 采集失败（脚本异常/标记全缺失且未兜底）MUST NOT 阻断归档流程本身。本条属提示词行为约束与查询面能力，验收方式为人工审计 + 单元测试 + 构建产物一致性校验。【MUST】

#### Scenario: 归档时自动采集

- **WHEN** recorder 归档一个含 budget-verdict 标记的变更（采集先于 openspec archive 执行）
- **THEN** metrics.json 的 history 追加该 change 记录（评分/轮数/双审结论/guard 快照四类字段齐备），归档流程正常完成

#### Scenario: 标记缺失人工兜底

- **WHEN** 变更产物缺 budget-verdict 标记且 recorder 以 `--phase2-rating` 等参数显式补录
- **THEN** 显式参数优先于扫描结果，指标记录完整；未兜底的缺失字段记 null，归档不被阻断

#### Scenario: 幂等重录

- **WHEN** 同一 change_id 重复执行 record
- **THEN** history 按 change_id 去重更新（覆盖非追加），recorded_count 不虚增

#### Scenario: 同轮多文件标记消歧

- **WHEN** reviews/reviewer-a.md 与 reviews/round2-verdict.md 均含 round=2 的 reviewer 标记
- **THEN** phase2_rating 取文件路径字典序最大者的标记（确定性 tie-breaker）

#### Scenario: final_rating 缺失不触发退化告警

- **WHEN** 某变更终审无评分（final_rating 为 null）且其后变更评分为 B、C
- **THEN** R1 连续下降序列在 null 处中断（A→null→B→C 不告警；A→B→C 无 null 才告警）

#### Scenario: 趋势段与告警呈现

- **WHEN** metrics.json 积累 ≥3 条记录且 final 评分序列为 A → B → C
- **THEN** `budget setup stats` 与 run summary 的「质量趋势」段显示评分序列并输出退化告警行

#### Scenario: 采集失败不阻断归档

- **WHEN** metrics.py 调用异常（脚本缺失/内部错误）
- **THEN** 归档流程照常完成（stderr 提示采集失败），指标记录缺失

#### Scenario: 容错降级

- **WHEN** display.py / run_summary.py import metrics 失败
- **THEN** 两命令其余段照常输出退出码 0，无「质量趋势」段

#### Scenario: 通知与降级零改动

- **WHEN** 告警规则命中
- **THEN** 仅查询面输出告警行——无 N1-N11 事件触发、guard 记录不写入、降级判定不参与
