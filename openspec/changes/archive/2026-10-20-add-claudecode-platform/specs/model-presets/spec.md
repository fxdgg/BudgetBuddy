# model-presets Delta

## MODIFIED Requirements

### Requirement: budget-models.json 目录结构

`core/models/budget-models.json` 结构（design.md §7）：`_meta`（description/updated_at/update_command=`budget setup models`）；`aliases`（简写→标准 ID 映射）；`roles`（与 agent 清单一致的 10 个 model_role 键）；`models.paid` 与 `models.free`（按 claude/gemini/gpt/kimi/glm/minimax/deepseek 分组，条目含 id/tier/cost/tags/platform/note，无内部渠道引用；platform 数组取值 = platforms 键集，数据内自洽）；`platforms.<p>.presets.{economic,balanced,quality}`（角色→该平台模型 ID 映射，p ∈ codebuddy/opencode/claudecode）与 `platforms.<p>` 可选键 `note`（平台说明字符串数组）与 `unconfirmed_ids`（待确认 ID 字符串数组，opencode 旧 `_meta.unconfirmed_opencode_ids` 读侧兼容一个版本）。配套 `core/models/budget-models.schema.json` 描述该结构（platform 枚举与可选键同步扩展），validate 子命令依据其校验。【MUST】

#### Scenario: 结构校验

- **WHEN** budget-models.json 缺 roles 键或某 agent 的 model_role 不在 roles 中

- **THEN** validate 失败并指出缺失/非法键

#### Scenario: 三平台预设齐全

- **WHEN** 检查 platforms 下全部平台各三档预设

- **THEN** 每档预设覆盖全部 10 个角色键，值为该平台合法模型 ID（claudecode 值 ∈ models.paid.claude 目录且该条目 platform 含 claudecode）

#### Scenario: platform 数组自洽

- **WHEN** 某 claude 组条目 platform 数组含 platforms 键集外的值
- **THEN** 构建与 validate 均失败并指出该条目

### Requirement: 预设切换与角色覆写

`budget setup agent preset <n>` 将 agent 产物 frontmatter 的 model 批量重写为指定预设；`budget setup agent custom <model>` 以 aliases 解析后统一覆写；`budget setup agent inherit` 将全部 agent 的 model 置为跟随主会话（inherit）。重写目标按 platform.sh 探测结果定位 agent 目录（design.md §8.1/§8.3）；claudecode 探测形态下 frontmatter 读写按 Claude Code camelCase 键结构操作（model 键名一致，无 model_role/permissions 中立键）。【MUST】

#### Scenario: preset 切换

- **WHEN** `budget setup agent preset economic` 在 codebuddy 项目级安装上执行
- **THEN** 全部 agent 产物的 model 字段被重写为 economic 预设对应 ID

#### Scenario: custom 别名解析

- **WHEN** `budget setup agent custom <alias>` 传入 aliases 表中的简写
- **THEN** 解析为标准 ID 后覆写，未知名报错并列出可用别名

#### Scenario: claudecode preset 切换

- **WHEN** `budget setup agent preset quality` 在 claudecode 项目级安装上执行
- **THEN** .claude/agents/ 全部产物 frontmatter 的 model 被重写为 quality 预设对应 ID，其余 camelCase 键不受影响

## MODIFIED Requirements

### Requirement: OpenCode 预设 provider/model 格式

`platforms.opencode.presets` 的值为 `provider/model` 格式（anthropic/openai/google/zhipu/deepseek/moonshotai 系）；实现时经本机 `opencode models` 或官方 catalog 核对存在性，无法确认的 ID 在 `platforms.opencode.unconfirmed_ids` 显式标注「待确认」（旧 `_meta.unconfirmed_opencode_ids` 位置读侧兼容一个版本；读取点含 core/lib/models.sh 与 build.py 渲染），阻塞上线前清零（design.md §15-Q2）。【MUST】

#### Scenario: 待确认标注

- **WHEN** 某预设 ID 未能核对
- **THEN** budget-models.json `platforms.opencode.unconfirmed_ids` 含该 ID，README 不将其宣传为已验证（README 宣传口径为人工审计项，T13 核查）

#### Scenario: 旧键兼容读取

- **WHEN** 读取仍使用 `_meta.unconfirmed_opencode_ids` 旧位置的 budget-models.json
- **THEN** 兼容读取生效（渲染与 models.sh 提示不静默丢失），迁移后新位置优先

## ADDED Requirements

### Requirement: Claude Code 预设三档梯度

`platforms.claudecode.presets` 三档值为 models.paid.claude 目录完整 ID（复用 catalog 校验策略，不用 sonnet/opus/haiku 别名）：economic → haiku 系（免费/低成本优先）、balanced → sonnet 系（构建期烘焙默认档）、quality → opus 系（质量优先）；未在本机 Claude Code 环境核对的 ID 记入 `platforms.claudecode.unconfirmed_ids`，MODEL_SELECTION.md 渲染「待确认」清单，上线前清零（纪律同 opencode 先例）。【MUST】

#### Scenario: 构建烘焙

- **WHEN** build.py 生成 claudecode 平台 agent 产物
- **THEN** 每个 agent frontmatter 的 model 为 balanced 预设中其 model_role 对应的 claude 系 ID

#### Scenario: 待确认标注

- **WHEN** 某 claudecode 预设 ID 未能核对
- **THEN** budget-models.json `platforms.claudecode.unconfirmed_ids` 含该 ID，产物 MODEL_SELECTION.md 渲染对应「待确认」提示
