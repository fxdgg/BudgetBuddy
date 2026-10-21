# model-presets Delta

## ADDED Requirements

### Requirement: Codex 预设三档部署别名

`platforms.codex.presets` 三档值为 gpt 组部署别名（用户环境需将别名映射到实际模型）：economic→`gpt-5.6-luna`（低成本档）、balanced→`gpt-5.6-terra`（平衡默认档）、quality→`gpt-5.6-sol`（高质量档）；档内十角色统一模型。catalog `models.paid.gpt` 组新增三别名条目（platform 仅 ["codex"]，note 注明部署映射前提）；三别名记入 `platforms.codex.unconfirmed_ids`（部署别名无法集中核对，**永久标注不适用上线前清零纪律**——note 声明该偏离，映射就绪后手动移除）；`platforms.codex.note` 说明三档定位、映射前提；**模型不可用时的逃生门为编辑 budget-models.json `platforms.codex.presets`（`budget setup models` 指引）或 spawn 时显式传 model——非 `budget setup agent custom`（codex 形态该子命令降级）**。模型选择语义：codex 端 Leader 按 budget-models.json 查表后经 spawn_agent 的 model 参数传递（非 frontmatter 烘焙）。【MUST】

#### Scenario: 三档预设齐全

- **WHEN** 检查 platforms.codex 三档预设
- **THEN** 每档覆盖十角色，值为三别名之一且 ∈ gpt 组目录（platform 含 codex）

#### Scenario: 别名待确认标注

- **WHEN** 产物 MODEL_SELECTION.md 渲染
- **THEN** codex 待确认清单含三别名与部署映射说明

## MODIFIED Requirements

### Requirement: 预设切换与角色覆写

`budget setup agent preset <n>` 将 agent 产物 frontmatter 的 model 批量重写为指定预设；`budget setup agent custom <model>` 以 aliases 解析后统一覆写；`budget setup agent inherit` 将全部 agent 的 model 置为跟随主会话。重写目标按 platform.sh 探测结果定位 agent 目录；claudecode 形态 camelCase 键读写兼容；**codex 形态降级**：无 frontmatter model 可写，preset/custom/inherit 输出降级提示（模型档位由 Leader spawn 时查 budget-models.json，详见 specs/setup-cli）。【MUST】

#### Scenario: preset 切换

- **WHEN** `budget setup agent preset economic` 在 codebuddy 项目级安装上执行
- **THEN** 全部 agent 产物的 model 字段被重写为 economic 预设对应 ID

#### Scenario: custom 别名解析

- **WHEN** `budget setup agent custom <alias>` 传入 aliases 表中的简写
- **THEN** 解析为标准 ID 后覆写，未知名报错并列出可用别名

#### Scenario: claudecode preset 切换

- **WHEN** `budget setup agent preset quality` 在 claudecode 项目级安装上执行
- **THEN** .claude/agents/ 全部产物 frontmatter 的 model 被重写为 quality 预设对应 ID，其余 camelCase 键不受影响

#### Scenario: codex 形态降级

- **WHEN** codex 形态执行 agent preset/custom/inherit 任一
- **THEN** 输出降级提示并 exit 0，无文件被修改
