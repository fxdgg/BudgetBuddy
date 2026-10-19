# neutral-source-format Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
### Requirement: Agent 中立 frontmatter schema

`core/agents/*.md` 必须使用统一中立 frontmatter：`name`（必填，kebab-case 且与文件主名一致）、`description`（必填，一句话职责含触发时机）、`model_role`（必填，取值 ∈ budget-models.json roles）、`tools`（必填，中立小写白名单 read/write/edit/bash/grep/glob/webfetch/websearch 的子集，且与权限语义一致）、`permissions`（可选，`edit_allow` glob 列表 + `bash_allow` 命令模式列表，各键值为三态之一：`["*"]` 全放开 / 非空条目列表受限 / `[]` 显式全禁止，缺省 `["*"]`）、`max_turns`（可选正整数）；frontmatter 之后必须有非空正文（design.md §3.1/§6）。【MUST】

#### Scenario: name 与文件主名不一致
- **WHEN** 构建时发现某 agent 文件 frontmatter 的 name 与文件主名不同
- **THEN** build.py 校验失败退出非零，输出该文件路径与原因

#### Scenario: model_role 非法
- **WHEN** 某文件的 model_role 不在 budget-models.json 的 roles 键中
- **THEN** build 失败并指出非法角色键

#### Scenario: tools 含白名单外工具
- **WHEN** tools 列表出现白名单之外的任何工具名
- **THEN** build 失败并列出非法工具名

#### Scenario: tools 与权限语义矛盾
- **WHEN** 某 agent `bash_allow: []` 但 tools 含 bash，或 `edit_allow: []` 但 tools 含 write/edit
- **THEN** build 失败并指出 tools 与 permissions 语义不一致

#### Scenario: permissions 值形态非法
- **WHEN** `edit_allow` 或 `bash_allow` 的值为 `["*"]` 与具体条目的混合，或为非列表形态
- **THEN** build 失败并说明合法三态（`["*"]` 全放开 / 非空条目列表 / `[]` 显式全禁止，不允许混合）

#### Scenario: 空列表为合法显式禁止形态
- **WHEN** 某 agent 的 `edit_allow: []`（如 reviewer/director）或 `bash_allow: []`（如 director/goal-evaluator）
- **THEN** 通过构建期校验，语义为显式全禁止（edit 只读 / bash 禁止），不判非法

#### Scenario: 合法文件通过校验
- **WHEN** 某文件满足全部 schema 约束且正文非空
- **THEN** 该文件通过构建期校验并进入双平台产物生成

### Requirement: 命令中立 frontmatter schema

`core/commands/{budget,opsx}/*.md` 使用命令中立 frontmatter：`name`（必填，显示名，形如 `<组>: <标题>`，组 ∈ {Budget, Opsx}，品牌无关命名）、`description`（必填，一句话用途）、`argument-hint`（可选，参数提示）；命令调用名由 routing 规则从文件名与组名派生，不依赖 name 字段；构建期按平台映射输出（design.md §3.1/§3.2）。【MUST】

#### Scenario: 命令缺必填字段
- **WHEN** 某命令模板缺 name 或 description
- **THEN** build 失败并指出缺失字段与文件路径

#### Scenario: 命令名品牌残留
- **WHEN** 命令 name 或文件名包含参照项目品牌词
- **THEN** 品牌门禁命中（scan-brand exit 1），构建门禁失败

#### Scenario: 双平台命令 frontmatter 映射
- **WHEN** 构建任一命令模板
- **THEN** CodeBuddy 产物直出 name/description/argument-hint 三字段；OpenCode 产物仅输出 description（name 与 argument-hint 丢弃，命令名由产物文件名承载）

### Requirement: 正文模板变量白名单替换

agent/skill/command 正文中只允许出现六个模板变量：`{{TASK_TOOL}}`、`{{SKILL_NS}}`、`{{PROJECT_DOC}}`、`{{AGENT_DIR}}`、`{{GUARD_PATH}}`、`{{RULES_DIR}}`；构建时按 platform/*.yaml 的 `body_variables` 精确匹配替换；能用中立措辞表达的差异不得引入新变量（design.md §3.3）。【MUST】

#### Scenario: 已知变量替换
- **WHEN** 构建含 `{{TASK_TOOL}}` 的正文且平台为 codebuddy
- **THEN** 该变量被替换为 yaml 声明的平台取值（`Agent`），产物中不再出现 `{{TASK_TOOL}}`

#### Scenario: 未知名保留并告警
- **WHEN** 正文出现 `{{UNKNOWN_VAR}}` 等白名单之外的模板变量
- **THEN** 构建不失败，该变量原样保留在产物中，并在 stderr 输出告警（文件+变量名）

### Requirement: platform/*.yaml 映射 DSL schema

`core/platform/{codebuddy,opencode}.yaml` 必须符合 §3.5 字段表 schema：顶层 `platform`/`output`/`routing`/`agent_frontmatter`/`command_frontmatter`/`command`/`body_variables`，opencode 额外 `extra_outputs`；routing 必须覆盖 agent/command/skill/rule/models/personas/lib/setup 八类路径规则 + `docs` 显式 map（每个 core/docs 源文件 → 目标路径或 null，null 表示该平台不分发）；`extra_outputs` 为块式 list 项为 map 形态；DSL 仅声明数据无编程逻辑，由 build.py 作为唯一消费者解释执行；映射到 `*.template.md` 源的条目经 A6 渲染管线输出，模板文件本身不平移进产物（design.md §3.5 / 调整点 A5/A6）。【MUST】

#### Scenario: DSL 缺 routing 键
- **WHEN** 某平台 yaml 缺少 routing.agent 声明
- **THEN** build 失败并指出缺失字段

#### Scenario: routing.docs 显式映射
- **WHEN** 构建时处理 core/docs/ 下文件
- **THEN** 每个文件的目标路径由 routing.docs 显式条目决定（值为 null 则该平台不产出），build.py 无任何文件名特判；MODEL_SELECTION.template.md 经渲染管线产出 MODEL_SELECTION.md，模板文件不出现在产物中

#### Scenario: extra_outputs 块式 list-of-map 解析
- **WHEN** 解析 opencode.yaml 的 extra_outputs（`- kind: agents_fragment` + 缩进续行 source/dest/markers）
- **THEN** 正确加载为 list[map]，构建生成 AGENTS.fragment.md 合并声明产物

#### Scenario: DSL 被非 build 工具消费
- **WHEN** 任何脚本以 build.py 之外的方式解析或改写 platform/*.yaml
- **THEN** 视为违规（reviewer 审计项），DSL 不得引入 build.py 无法解释的逻辑

### Requirement: 权限语义双平台映射

构建期按平台执行权限映射（design.md §3.2）：CodeBuddy 依据 `edit_allow` 输出粗粒度 `permissionMode`（`["*"]` 或缺省 → `acceptEdits`；受限或 `[]` → `plan`），`bash_allow` 不映射但中立字段保留（`[]` 禁止语义由正文约束措辞承担）；OpenCode 逐键构造细粒度 `permission` map——edit：`["*"]` 或缺省 → `"*": "allow"`，否则先 `"*": "deny"` 再逐 glob `allow`；bash 三分支：`["*"]` 或缺省 → `"*": "allow"`，非空受限 → 先 `"*": "ask"` 再逐模式 `allow`，`[]` → 仅 `"*": "deny"`（显式禁止）；tools 在 CodeBuddy 输出 PascalCase，在 OpenCode 省略。【MUST】

#### Scenario: edit 全放开的 agent
- **WHEN** 构建某 `edit_allow` 缺省或为 `["*"]` 的 agent（如 coder-lite）
- **THEN** dist/codebuddy 产物含 `permissionMode: acceptEdits`；dist/opencode 产物 permission.edit 为 `{"*": "allow"}`

#### Scenario: 只读 agent
- **WHEN** 构建 `edit_allow: []` 的只读 agent（如 reviewer、director）
- **THEN** dist/codebuddy 产物 `permissionMode: plan`；dist/opencode 产物 permission.edit 仅含 `"*": "deny"`

#### Scenario: 禁 bash agent
- **WHEN** 构建 `bash_allow: []` 的 agent（如 director、goal-evaluator）
- **THEN** dist/opencode 产物 permission.bash 仅含 `"*": "deny"`（显式禁止，不落入 ask 分支）；dist/codebuddy 产物不受影响（bash_allow 不映射，语义由正文措辞承担）

#### Scenario: 受限编辑 agent
- **WHEN** 构建 `edit_allow: ["openspec/**", "docs/**"]` 的 architect
- **THEN** dist/codebuddy 产物 `permissionMode: plan`；dist/opencode 产物 permission.edit 含 `"*": "deny"` 与两个 glob 的 `allow` 条目

#### Scenario: model_role 烘焙
- **WHEN** 构建任一 agent 且 budget-models.json 就位
- **THEN** 产物 frontmatter 的 model 字段为 budget-models.json 中 `platforms.<platform>.presets.balanced.<model_role>` 解析出的具体模型 ID

