# agent-roster Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
### Requirement: 10 个 agent 中立定义齐全

`core/agents/` 恰好包含 10 个中立 agent：architect、coder-lite、coder-standard、coder-senior、reviewer、reviewer-b、tester、recorder、director、goal-evaluator；name/model_role/edit_allow/bash_allow/max_turns 按 design.md §6 角色表逐项一致；正文为中立措辞（含职责、触发时机、协作约定），含模板变量处遵守 §3.3 白名单（design.md §6）。【MUST】

#### Scenario: 构建校验角色清单
- **WHEN** build 执行 §3.1 校验
- **THEN** 10 个文件的 name 恰为角色清单全集（无缺失、无多余）

#### Scenario: 只读 agent 权限落位
- **WHEN** 构建 reviewer/reviewer-b/tester/recorder/director/goal-evaluator
- **THEN** 其编辑权限按 §6 表映射（reviewer/director/goal-evaluator 只读；recorder 可写 openspec/docs；tester 只读但 bash 全放开；director/goal-evaluator bash 禁止）

#### Scenario: 角色表逐项一致
- **WHEN** reviewer 审计 10 个文件的 frontmatter
- **THEN** model_role、max_turns 与 §6 表逐行一致（如 director max_turns=15、goal-evaluator=8、architect=80）

### Requirement: 正文职责与协作语义中立化

每个 agent 正文描述职责、触发时机与上下游协作（如 coder 三级差异、reviewer A/B 交叉复核、director 六类裁决、goal-evaluator 判定输出），全部使用平台中立措辞；子代理调用语法用 `{{TASK_TOOL}}` 变量；不出现任何平台专有 API 名称或参照项目品牌（design.md §3.3/§6）。【MUST】

#### Scenario: 双平台产物正文等价
- **WHEN** 构建后对比 dist/codebuddy 与 dist/opencode 的同一 agent
- **THEN** 除六个模板变量的平台取值与 frontmatter 结构外，正文内容一致

#### Scenario: 品牌零残留
- **WHEN** scan-brand.py 扫描 core/agents/
- **THEN** 零违禁词命中

