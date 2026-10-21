# workflow-orchestration Delta Spec

## ADDED Requirements

<!-- 采 ADDED 而非 MODIFIED 的理由：主 spec「Review Gate 与 Director 终裁」requirement 描述的是交叉复核/驳回/终裁语义（非枚举式清单），本变更是其上叠加可选步骤、不改既有语义；新增独立 requirement 以「MUST NOT 影响」约束表达兼容性，避免重写既有 requirement 全文引入归档合并歧义（对照 setup-cli delta 的子命令全集 requirement 属枚举式，须 MODIFIED 纳入新子命令——两类结构处理方式不同）。 -->

### Requirement: Review Gate 可选 OCR 机器预审

Review Gate（reviewer + reviewer-b 交叉复核）阶段 SHALL 支持可选的 OpenCodeReview（开源 `ocr` CLI）机器预审：双 reviewer 在启动审查时按 ocr-pre-review capability 的探测与降级语义尝试获取结构化预审结果，作为各自审查维度的辅助输入（detector），最终裁决权保留在 reviewer agent（judge）；预审缺失或失败 MUST NOT 影响 Review Gate 的既有语义——3 轮驳回应急、Director 六类裁决、通知节点 N1-N11 联动均不变。本条属提示词行为约束，验收方式为人工审计 + 构建产物一致性校验，不设自动化用例（人工审计为该豁免项的验收方式）。【MUST】

#### Scenario: 预审缺失不影响应急语义

- **WHEN** 同一任务累计 3 轮审查驳回且环境中无 `ocr` CLI
- **THEN** 3 轮驳回应急路径（升级 coder 级别/Director 介入）与对应通知行为与集成前完全一致

#### Scenario: 预审结果进入双审分工

- **WHEN** 预审返回 security 与 test 类 finding
- **THEN** security 类由 reviewer-b 深度验证、test 类由 reviewer-b 按测试逻辑独立验证职责处理，主审不重复审查
