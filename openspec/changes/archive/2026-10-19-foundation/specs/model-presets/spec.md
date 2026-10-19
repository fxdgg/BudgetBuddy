## ADDED Requirements

### Requirement: budget-models.json 目录结构

`core/models/budget-models.json` 结构（design.md §7）：`_meta`（description/updated_at/update_command=`budget setup models`）；`aliases`（简写→标准 ID 映射）；`roles`（与 agent 清单一致的 10 个 model_role 键）；`models.paid` 与 `models.free`（按 claude/gemini/gpt/kimi/glm/minimax/deepseek 分组，条目含 id/tier/cost/tags/platform/note，无内部渠道引用）；`platforms.codebuddy.presets.{economic,balanced,quality}` 与 `platforms.opencode.presets.{...}`（角色→该平台模型 ID 映射）。配套 `core/models/budget-models.schema.json` 描述该结构，validate 子命令依据其校验。【MUST】

#### Scenario: 结构校验
- **WHEN** budget-models.json 缺 roles 键或某 agent 的 model_role 不在 roles 中
- **THEN** validate 失败并指出缺失/非法键

#### Scenario: 双平台预设齐全
- **WHEN** 检查 platforms 下两平台各三档预设
- **THEN** 每档预设覆盖全部 10 个角色键，值为该平台合法模型 ID

### Requirement: CodeBuddy 预设对齐参照项目

`platforms.codebuddy.presets.balanced` 的角色→模型映射对齐参照项目 balanced 预设（架构/审查用强推理模型、coder 分级三档、廉价模型承担低优先角色）；economic 与 quality 两档体现「免费优先 / 质量优先」梯度（design.md §7）。【MUST】

#### Scenario: 构建烘焙
- **WHEN** build.py 生成 codebuddy 平台 agent 产物
- **THEN** 每个 agent frontmatter 的 model 为 balanced 预设中其 model_role 对应的 ID

### Requirement: OpenCode 预设 provider/model 格式

`platforms.opencode.presets` 的值为 `provider/model` 格式（anthropic/openai/google/zhipu/deepseek/moonshotai 系）；实现时经本机 `opencode models` 或官方 catalog 核对存在性，无法确认的 ID 在 `_meta` 显式标注「待确认」（design.md §15-Q2，阻塞上线前清零）。【MUST】

#### Scenario: 待确认标注
- **WHEN** 某预设 ID 未能核对
- **THEN** budget-models.json `_meta` 中存在对应「待确认」标注，README 不将其宣传为已验证（README 宣传口径为人工审计项，T13 核查）

### Requirement: 预设切换与角色覆写

`budget setup agent preset <n>` 将 agent 产物 frontmatter 的 model 批量重写为指定预设；`budget setup agent custom <model>` 以 aliases 解析后统一覆写；`budget setup agent inherit` 将全部 agent 的 model 置为跟随主会话（inherit）。重写目标按 platform.sh 探测结果定位 agent 目录（design.md §8.1/§8.3）。【MUST】

#### Scenario: preset 切换
- **WHEN** `budget setup agent preset economic` 在 codebuddy 项目级安装上执行
- **THEN** 全部 agent 产物的 model 字段被重写为 economic 预设对应 ID

#### Scenario: custom 别名解析
- **WHEN** `budget setup agent custom <alias>` 传入 aliases 表中的简写
- **THEN** 解析为标准 ID 后覆写，未知名报错并列出可用别名

### Requirement: MODEL_SELECTION.md 模板化生成

`dist/<platform>/docs/MODEL_SELECTION.md` 由 `core/docs/MODEL_SELECTION.template.md`（占位符模板）+ budget-models.json 数据在构建期按平台生成（design.md §12-A6）：双平台均经 routing.docs 模板条目走 A6 渲染管线独立产出（模板本身不平移进产物，design.md §3.5），保证模型目录与文档单一数据源。【MUST】

#### Scenario: 数据驱动
- **WHEN** budget-models.json 中某模型 cost 修改后重新构建
- **THEN** 产物 MODEL_SELECTION.md 中该模型条目同步更新，无需手改文档
