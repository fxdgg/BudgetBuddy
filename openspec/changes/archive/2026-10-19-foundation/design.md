# Design: foundation — BudgetBuddy 全量首版实现设计

> 权威输入：`docs/plans/2026-10-16-budgetbuddy-architecture-design.md`（已确认，下称「设计文档」）。本文将其形式化并补足实现级细节；与设计文档冲突以本文为准（调整点见 §12，均不触碰四项已定决策）。
> 参照项目根目录绝对路径**不得写入任何仓库文件**（品牌合规）；参照文件指针统一用 `REF:` 前缀 + 相对路径（glob 形式，品牌词以 `*` 通配），根路径由 Leader 派发任务时注入。

## 1. Context

BudgetBuddy 是功能对等参照项目的多 Agent 省钱研发工作流套件（10 agents / 5 阶段工作流 / Coder Guard / Review Gate / Director 终裁 / 模型分级 / personas / 通知 / hooks / openspec 集成），双平台（CodeBuddy + OpenCode），单一中立源 `core/` 经 `scripts/build.py` 生成 `dist/codebuddy/` 与 `dist/opencode/`。仓库全新（git main 已初始化，无存量代码）。

已定决策（不可重开）：① 单一源+构建转换；② `budget` 前缀；③ 全量功能对等；④ 通用 webhook 通知。

## 2. Goals / Non-Goals

**Goals**：G1 双平台产物完整可用；G2 改 `core/` 一处双平台生效；G3 全量功能对等（设计文档 §8+§11-7，通知点以参照项目实际全集 N1-N11 为准）；G4 品牌零违禁词（构建门禁强制）；G5 构建/安装幂等可重复。

**Non-Goals**：不做第三平台适配（仅架构可扩展）；不保留任何参照项目品牌/内部域名/内部镜像兼容；不做 npm/pypi 发包（仅 git + install.sh + zip）；不实现 OpenCode 原生 hooks（无此机制，以文档说明插件扩展点替代）；不做升级探测服务端（版本发现仅依赖 release 托管方的 latest 固定别名，见 §10）。

## 3. 中立源格式细化

### 3.1 Agent 与命令中立 frontmatter 精确 schema

**Agent（core/agents/*.md）**：

```yaml
---
name: <kebab-case，与文件主名一致>          # 必填
description: <一句话职责，含触发时机>        # 必填
model_role: <角色键>                        # 必填，取值见 §7 roles
tools: [read, write, edit, bash, grep, glob, webfetch, websearch]  # 必填，中立小写白名单，取值见 §6 表
permissions:                                # 可选；整体缺省 = 全放开
  edit_allow: ["openspec/**", "docs/**"]    # glob 列表；三态：["*"]（全放开）/ 非空条目列表（受限）/ []（显式全禁止）；缺省 ["*"]
  bash_allow: ["git *", "openspec *"]       # 命令模式列表；三态同上；缺省 ["*"]
max_turns: <正整数>                         # 可选
---
<正文：中立措辞 + §3.3 模板变量>
```

构建期校验（违规即 build 失败；空 core / 数据未就位的降级规则见 §4）：① name == 文件主名，且 agents 目录非空时 10 个 name 恰为 §6 角色清单；② model_role ∈ roles（budget-models.json 就位时）；③ tools ⊆ 白名单；④ permissions 各键值为三态之一——`["*"]`（全放开）、非空条目列表（受限）、`[]`（显式全禁止）；仅「`["*"]` 与具体条目混合」与「非列表形态」判非法；⑤ frontmatter 后必须有非空正文；⑥ tools 与 permissions 语义一致：`bash_allow: []` ⇒ tools 不含 bash，`edit_allow: []` ⇒ tools 不含 write/edit。

**命令（core/commands/{budget,opsx}/*.md）**：

```yaml
---
name: "Budget: Start"                       # 必填，显示名，形如 "<组>: <标题>"，组 ∈ {Budget, Opsx}，品牌无关
description: <一句话用途>                    # 必填
argument-hint: "<参数提示>"                  # 可选
---
<正文：中立措辞 + §3.3 模板变量>
```

命令名即文件主名（start/status/goal/apply/archive/explore/propose），中立命名不引入品牌词；`name` 仅是展示用标题，命令调用名由 routing 规则从文件名与组名派生。

### 3.2 权限与 frontmatter 双平台映射（build.py 按平台执行）

**Agent 权限**：

- **CodeBuddy**（仅粗粒度 permissionMode）：`edit_allow==["*"]`（或缺省）→ `acceptEdits`；受限或 `[]` → `plan`。`bash_allow` 不映射（平台无对应字段），语义由正文约束措辞承担，中立字段保留供 OpenCode 与审计（`bash_allow: []` 的禁止语义在 CodeBuddy 侧同样由正文措辞承担）。
- **OpenCode**（细粒度 map，逐键构造）：`permission.edit` 先写 `"*": "deny"`，再为每个 edit_allow glob 写 `"<glob>": "allow"`（`edit_allow==["*"]` 或缺省时直接 `"*": "allow"`）；`permission.bash` 三分支——`["*"]` 或缺省 → `"*": "allow"`；非空受限 → 先 `"*": "ask"` 再逐模式 `allow`；**`[]` → 仅 `"*": "deny"`（显式禁止）**。
- **tools**：CodeBuddy 输出 PascalCase 列表；OpenCode 省略 tools 字段（继承全部工具，由 permission 控制）。
- **model_role → model**：经 `budget-models.json` 的 `platforms.<platform>.presets.balanced.<role>` 解析（构建期以 balanced 烘焙默认；安装后 `budget setup agent preset|custom` 重写）；`budget setup agent inherit` 时 CodeBuddy 产物删除 model 字段、OpenCode 产物省略 model 字段（均跟随主会话模型）。

**命令 frontmatter**：CodeBuddy 产物直出 name/description/argument-hint 三字段；OpenCode 产物仅输出 description（name 与 argument-hint 丢弃，命令名由产物文件名承载）。

### 3.3 正文模板变量

仅六个：`{{TASK_TOOL}}` `{{SKILL_NS}}` `{{PROJECT_DOC}}` `{{AGENT_DIR}}` `{{GUARD_PATH}}` `{{RULES_DIR}}`（agent/skill/command 正文共用该变量集）。能用中立表述的（「使用内置读取/搜索工具」、persona 路径 `.budget/persona-active.json` > `~/.budgetbuddy/persona-active.json`）不设变量。变量替换为白名单精确匹配，未知名保留原样并告警。

### 3.4 P0 规则纵深防御

leader-no-code / coder-guard / 流程强制 3 条 P0 规则三层落位：① CodeBuddy `rules/budget-*.mdc`；② 内联进 `core/skills/budget-workflow/SKILL.md`「强制执行规则（P0）」章节（双平台一致）；③ OpenCode AGENTS.fragment.md 标记区块。①③由 `core/rules/` 派生，②在 core 中手工维护，构建时 diff 校验一致性（不一致仅告警不阻断）。

**一致性 diff 可执行判定规则**（机器可执行，作为人工审计前的下界保障）：

1. 提取两处 P0 条目集合：`core/rules/budget-{leader-no-code,coder-guard,workflow-enforcement}.md`（①③同源）与 SKILL.md 内联章节条目，按条目出现顺序配对；
2. 规范化：strip 首尾空白、小写化、折叠连续空白、剔除 Markdown 标记字符（`` ` `` `*` `#` `-` `>`）；
3. 判定一致 = ①两侧条目数相等；②逐对条目分词（去停用词与标点）后关键词集合双向包含率均 ≥ 80%；
4. 不一致 → stderr 输出告警（文件路径 + 差异摘要：条目数或失配对索引），构建 exit 0 不阻断；CI 可用 `--strict` 将该告警升级为失败；
5. T13 验收时对三条 P0 规则做人工逐条抽查兜底（机器比对覆盖措辞漂移，人工覆盖语义漂移）。

### 3.5 platform/*.yaml 映射 DSL（精确 schema）

build.py 是唯一消费者；无编程逻辑。字段表：

| 字段 | 类型 | 说明 |
|------|------|------|
| `platform` / `output` | string | 平台标识 / 产物根 |
| `routing` | map | 类别→路径规则；`{name}`=主名、`{skill}`=skill 目录名、`{group}`=命令组(budget/opsx)、`{path}`=相对路径；**`routing.docs` 为显式 map**：`<core/docs 源文件名>: <目标路径或 null>`（null = 该平台不分发），模板类源（`*.template.md`）的目标经 A6 渲染管线输出，模板本身不平移 |
| `agent_frontmatter.emit` | map | 中立字段→平台取值表达式（`{name}/{description}/{resolved_model}/{tools\|pascal}/{permission_mode}/{permission_map}/{max_turns}`，max_turns 仅源存在时输出） |
| `agent_frontmatter.permission_mode_rule` | map | `edit_all:acceptEdits`、`edit_restricted:plan`（opencode 忽略） |
| `agent_frontmatter.drop` | list | 不输出的中立字段 |
| `command_frontmatter.emit` / `command_frontmatter.drop` | list / list | 命令 frontmatter 输出/丢弃的中立字段（§3.2 命令映射） |
| `command.invoke` | string | 文档调用语法模板 |
| `body_variables` | map | §3.3 变量→平台取值 |
| `extra_outputs` | list | 平台附加产物（opencode 的 AGENTS.fragment 合并声明），**块式 list 项为 map**（`- kind: ...` + 缩进续行） |

**core/platform/codebuddy.yaml**：

```yaml
platform: codebuddy
output: dist/codebuddy
routing:
  agent:   "agents/{name}.md"
  command: "commands/{group}/{name}.md"      # budget | opsx
  skill:   "skills/{skill}/"
  rule:    "rules/budget-{name}.mdc"
  hook:    "hooks/budget-notify-hook.py"
  models:  "budget-models.json"
  personas: "personas.json"
  lib:     "lib/"
  setup:   "setup.sh"
  docs:                                      # 显式映射：源文件 → 目标路径；null = 不分发
    MODEL_SELECTION.template.md: "docs/MODEL_SELECTION.md"   # 经 A6 渲染管线输出
    PERSONAS.md: "docs/PERSONAS.md"
    architecture.md: "docs/architecture.md"
    opencode-setup-notes.md: null            # opencode 专属说明，本平台不分发
agent_frontmatter:
  emit:
    name: "{name}"
    description: "{description}"
    model: "{resolved_model}"
    tools: "{tools|pascal}"
    permissionMode: "{permission_mode}"
    max_turns: "{max_turns}"
  permission_mode_rule: { edit_all: "acceptEdits", edit_restricted: "plan" }
  drop: [model_role, permissions]
command_frontmatter:
  emit: [name, description, argument-hint]   # 三字段直出
  drop: []
command:
  invoke: "/{group}:{name}"                  # /budget:start、/opsx:apply
body_variables:
  TASK_TOOL: "Agent"
  SKILL_NS: "superpowers:"
  AGENT_DIR: ".codebuddy/agents/（项目级；不存在则 $HOME/.codebuddy/agents/）"
  GUARD_PATH: "$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json"
  RULES_DIR: ".codebuddy/rules/（不存在则 $HOME/.codebuddy/rules/）"
  PROJECT_DOC: ""
```

**core/platform/opencode.yaml**：

```yaml
platform: opencode
output: dist/opencode
routing:
  agent:   "agent/{name}.md"
  command: "command/{group}-{name}.md"        # budget-start.md、opsx-apply.md
  skill:   "skill/{skill}/"                   # 单数目录名
  rule:    "AGENTS.fragment.md"               # 全部 rule 合并单文件
  hook:    ""                                 # 无 hooks 机制
  models:  "budget-models.json"
  personas: "personas.json"
  lib:     "lib/"
  setup:   "setup.sh"
  docs:
    MODEL_SELECTION.template.md: "docs/MODEL_SELECTION.md"   # 经 A6 渲染管线输出
    PERSONAS.md: "docs/PERSONAS.md"
    architecture.md: "docs/architecture.md"
    opencode-setup-notes.md: "docs/setup-notes.md"
agent_frontmatter:
  emit:
    description: "{description}"
    mode: "subagent"
    model: "{resolved_model}"
    permission: "{permission_map}"
    max_turns: "{max_turns}"
  drop: [name, model_role, permissions, tools]
command_frontmatter:
  emit: [description]                         # 命令名由产物文件名承载
  drop: [name, argument-hint]
command:
  invoke: "/{group}-{name}"
body_variables:
  TASK_TOOL: "task"
  SKILL_NS: ""
  AGENT_DIR: "~/.config/opencode/agent/（全局；项目级 .opencode/agent/ 覆盖）"
  GUARD_PATH: "$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json"
  RULES_DIR: "AGENTS.md 标记区块（安装器合并）"
  PROJECT_DOC: "启动时读取项目根目录 AGENTS.md（如保留 CODEBUDDY.md，一并参考）"
extra_outputs:
  - kind: agents_fragment
    source: "rules/**"
    dest: "AGENTS.fragment.md"
    markers: ["<!-- BudgetBuddy:begin -->", "<!-- BudgetBuddy:end -->"]
```

rules 合并格式：整体包裹外层 begin/end 标记，每条 rule 一个二级标记区块 `<!-- budget-<rule-name>:begin/end -->`，安装器据此幂等更新。

**docs 分发语义**（消除特判）：`routing.docs` 显式列出每个 core/docs 源文件的目标（或 null），build.py 严格按映射执行、无任何文件名特判；`*.template.md` 扩展名是模板约定——映射到该类源的目标一律经 A6 渲染管线生成，模板文件本身永不平移进产物。

## 4. 构建系统（scripts/build.py）

- 输入 `core/**` + `core/platform/*.yaml`；**手写最小 YAML 子集解析器**（~150 行，语法清单见 §12-A5）+ DSL schema 校验。
- **原子构建流程**：构建写入临时目录 `dist/<platform>.new/` → 逐类别转换（agent/命令 frontmatter 重写、变量替换、routing 落位改名）→ lib/models/personas/docs 处理（平移或渲染）→ rules 合并（opencode）→ 校验（§3.1）→ 写 `.manifest.json` → 全部成功后将旧 `dist/<platform>/` 原子替换为 `.new`（旧目录先改名 `.old`，替换完成后删除）；任一步失败即清理 `.new` 并以非零退出，`dist/<platform>/` **保持构建前原样**（不产生半成品，不污染已提交的产物）。
- **幂等确定性输出**：`.manifest.json` 与一切生成 JSON 一律按键排序输出（`sort_keys=True`）；目录遍历一律按名称排序；文件写入统一 UTF-8 无 BOM、LF 行尾——「两次构建 manifest diff 为空」确定成立，不受 os.walk 遍历顺序影响。
- `.manifest.json`（A7）：`{"files": {"<相对路径>": "<sha256>"}}`，**不含任何时间戳**；该文件自身不列入清单；作为安装器增量同步与升级差集清理的构建侧依据。
- **空 core / 数据未就位降级规则**（保证 T1 空骨架冒烟与 T2-T7 增量构建可执行，全量校验在 T8 数据就位后自动恢复生效）：① `core/agents/` 无文件时跳过「10 个 name 恰为 §6 角色清单」集合完备性校验（已存在的文件仍执行单文件 schema 校验）；② `core/models/budget-models.json` 缺失时跳过 MODEL_SELECTION.md 渲染（不产出该文件）与 model_role→model 烘焙（agent 产物不输出 model 字段并输出告警，不失败）；③ `core/personas/personas.json` 缺失时跳过 personas 平移。
- CLI：`python3 scripts/build.py [--platform codebuddy|opencode] [--check] [--strict]`；`--check` 构建后自动跑 scan-brand.py，违禁 exit 1；`--strict` 将 §3.4 P0 一致性告警升级为失败（CI 用）。
- `MODEL_SELECTION.md` 渲染管线：budget-models.json + `core/docs/MODEL_SELECTION.template.md` 按平台生成（模型表 + 平台说明段，占位符语法见 §12-A6）；**实现排期在 T8a**（模型数据就位后实现并真实验证），T1a 仅在 build.py 中预留渲染挂接点（routing.docs 模板条目在数据缺失时按 §4 降级跳过）。

## 5. 品牌合规门禁（scripts/scan-brand.py）

- 扫描范围（与设计文档 §7 一致，不扩到 docs/ 与 openspec/——设计文档本身含参照路径引用）：`core/`、`dist/`、`scripts/`、`install.sh`、`README.md`、`README_CN.md`、`CHANGELOG.md`。
- 违禁词表（大小写不敏感；词类涵盖参照项目名、归属组织与公司标识、内部渠道域名、中文角色系称呼、旧环境变量前缀及其前后缀变体）以转义编码存储于 scripts/scan-brand.py 唯一权威载体，文档不出现字面量。
- **词表定义载体豁免（A10 扩围）**：违禁词表必须以字面量定义的载体——`scan-brand.py` 自身、`design.md` §5 词表行、`specs/brand-compliance` 词表行——不因词表字面量本身判违规；机器扫描层面 scan-brand.py 跳过自身文件，openspec 产物合规审计（brand-compliance spec）明确豁免上述词表定义行；载体文件的其余内容仍正常扫描/审计。
- 命中输出 `文件:行号:摘要` 并 exit 1；非文本/解码失败文件跳过并告警。

## 6. Agent 角色清单（10 个）

| name | model_role | tools | edit_allow | bash_allow | max_turns | 职责 |
|------|-----------|-------|-----------|-----------|-----------|------|
| architect | architect | read,write,edit,bash,grep,glob,webfetch,websearch | openspec/**,docs/** | git *,openspec * | 80 | 方案/闸门/架构决策 |
| coder-lite | coder_lite | read,write,edit,bash,grep,glob | ["*"] | ["*"] | 35 | 简单 CRUD/配置 |
| coder-standard | coder_standard | read,write,edit,bash,grep,glob | ["*"] | ["*"] | 50 | 中等任务 |
| coder-senior | coder_senior | read,write,edit,bash,grep,glob,webfetch,websearch | ["*"] | ["*"] | 70 | 架构/安全/并发 |
| reviewer | reviewer | read,bash,grep,glob | [] 只读 | git * | 40 | 审查 A |
| reviewer-b | reviewer_b | read,bash,grep,glob | [] 只读 | git * | 40 | 审查 B（交叉复核） |
| tester | tester | read,bash,grep,glob | [] 只读 | ["*"] | 40 | 验证执行 |
| recorder | recorder | read,write,edit,bash,grep,glob | openspec/**,docs/** | git * | 30 | 归档/经验提取 |
| director | director | read,grep,glob | [] 只读 | [] 禁止 | 15 | 终裁 |
| goal-evaluator | goal_evaluator | read,grep,glob | [] 只读 | [] 禁止 | 8 | 目标达成判定 |

（`edit_allow: []` 在 CodeBuddy 映射 `permissionMode: plan`；OpenCode edit 仅 `"*": "deny"`。`bash_allow: []` 在 OpenCode 映射 bash 仅 `"*": "deny"`（§3.2）；CodeBuddy 侧由正文约束措辞承担。tools 与权限语义一致性由 §3.1 校验⑥强制。）

## 7. 模型目录（core/models/budget-models.json）

结构：`_meta`（description/updated_at/update_command=`budget setup models`）+ `aliases`（opus/kimi/glm 等简写→ID）+ `roles`（§6 的 10 个 model_role 数组）+ `models.paid/free`（按 claude/gemini/gpt/kimi/glm/minimax/deepseek 分组，条目含 id/tier/cost/tags/platform/note，去除内部引用）+ `platforms.codebuddy.presets.{economic,balanced,quality}`（角色→CodeBuddy 模型 ID；balanced 对齐参照项目角色映射）+ `platforms.opencode.presets.{...}`（provider/model 格式，anthropic/openai/google/zhipu/deepseek/moonshotai 系；ID 经本机 `opencode models` 或官方 catalog 核对，不确定者在 `_meta` 标注）。另生成 `budget-models.schema.json` 供 validate。

## 8. 管理面（core/setup.sh + core/lib/ + budget CLI）

### 8.1 子命令

`budget setup [init|show|agent|persona|validate|diff|stats|update|reinstall|uninstall|guard|quickstart|models|help]`，其中：`init shell` 注入 shell 别名；`quickstart`（别名 `tour`/`wizard`）启动快速上手引导（lib 已含 quickstart.py，入口对齐避免死代码）；`guard` 查询/重置 Coder Guard 记录；`reinstall` = uninstall + init 组合重装；`agent [preset|inherit|custom]`、`persona [list|set|expand|show]` 同前。独立子命令 `budget notify "<消息>" <事件名>`、`budget status`；**`budget update` 为 `budget setup update` 的顶层快捷别名**。子命令全集对齐参照项目 setup.sh 实际分发（A11）。环境变量前缀统一 `BUDGET_*`（BUDGET_GLOBAL/BUDGET_DIR/BUDGET_PLATFORM）。

### 8.2 lib 模块全清单（core/lib/，双平台产物同名平移）

- 基础层：`colors.sh` `utils.sh` `platform.sh` `shell.sh`
- 生命周期：`init.sh` `update.sh` `uninstall.sh`
- 模型与护栏：`models.sh` `preset.sh` `model_resolver.py` `guard.sh` `rtk.sh`
- persona 与校验：`persona.sh` `persona_expand.py` `validate.sh` `budget_state.py` `display.py`
- 交互与汇总：`interactive.sh` `quickstart.py` `run_summary.py` `banner.py`
- 通知与 hooks：`notify.sh` `hooks.sh` `hooks_inject.py`

（`budget_state.py` 参照 `REF:dist/lib/*_state.py`，统一单份放 lib，skill 内相对路径引用——调整点 A4。）

### 8.3 平台自适应（运行时）

lib 双平台共用同一份产物；`platform.sh` 运行时探测：① 向上找到 `.codebuddy/setup.sh` → codebuddy 项目级；② `~/.codebuddy/setup.sh` → codebuddy 全局；③ `.opencode/agent/`（项目级，**优先**）或 `~/.config/opencode/agent/`（全局）存在本套件 agent → opencode；三级均未命中 → 报错并列出已检测位置（探测失败显式报错，不静默猜默认）。`agent preset/custom` 与 hooks 注入（仅 codebuddy）按探测结果定位 agent 目录。环境变量前缀统一 `BUDGET_*`（BUDGET_GLOBAL/BUDGET_DIR/BUDGET_PLATFORM；BUDGET_DIR 仅作运行时数据目录覆盖，安装落点见 §10）。

### 8.4 数据目录

项目级 `.budget/`（persona-active.json、notify.json、memory/——项目内运行数据如 goal-state 等项目态，gitignore）；全局 `~/.budgetbuddy/`（同名 + `projects/<project-name>/memory/coder-guard.json`、`bin/budget`、`lib/`、`budget-models.json`、`personas.json`、`docs/`）。读取优先级项目级 > 全局级，皆无 → 通知跳过 / persona 用 default。**Coder Guard 固定用全局路径**（跨会话汇总降级判定），项目级 memory/ 仅存项目态数据。**`.gitignore` 写入责任**：install.sh（项目级安装）与 `setup init` 检测项目 `.gitignore`，无 `# BudgetBuddy:begin/end` 标记区块则追加 `.budget/` 忽略项（幂等，区块外内容不触碰）。

### 8.5 personas.json

5 主题：default、tech-legends、sanguo、shuihu、genshin（**剔除参照项目品牌主题**）；结构沿用参照项目（`_meta` + `themes.<name>.{greeting,roles.*,report_templates}`）。**roles 键集 = leader + §6 十角色（共 11 键）**——保留 `leader` 键：参照项目 phases Step 0 与全部 agent 正文依赖 `roles.leader` + `greeting` 实现主会话称呼与角色化调度，删除即破坏该核心机制。与参照项目（leader + 9 subagent，含 reviewer-a、无 goal-evaluator）的系统性差异：① **reviewer-a → reviewer 改名**：T2 迁移 agent 正文时全部 persona 引用同步（参照项目正文写死 `roles.reviewer-a`）；② **goal-evaluator 为新增键**：5 个主题均需新造角色名（T8b 工作量）；③ 各主题 `leader` 键值（对主会话的称呼）随主题创作。

## 9. 通知（core/skills/budget-notify/）

- **notify.json schema**（`.budget/notify.json` > `~/.budgetbuddy/notify.json`，**双级降级读取：项目级存在即生效、否则降级用全局级，不合并**）：顶层 `enabled:bool` + `channels`（每渠道 `type: wecom_bot|dingtalk_bot|feishu_bot|custom` + `webhook` + 可选 `secret` + custom 的 `format:raw`）+ `events`（N1..N11，各 `{enabled, channels[]}`）。配置文件由生成方（setup init 模板 / notify.py 首次写入）默认 `chmod 600`。
- **notify.py 行为**：双级降级读配置（同上，不合并）→ 校验 enabled 与事件开关 → 渠道格式化（企微 bot markdown；钉钉 markdown+HMAC-SHA256 签名 timestamp+"\n"+secret base64 urlenc；飞书 interactive 卡片；custom 原样 POST）→ `urllib` 发送 5s 超时 → 任一成功即停，全失败静默 exit 0 → **webhook/secret 仅存于 chmod 600 的配置文件，不经环境变量传递，不落命令行与日志**。
- **load-env.sh 环境导出**：定位生效配置文件（项目级 > 全局级，不合并），仅导出**非敏感**环境变量：`BUDGET_NOTIFY_ENABLED`（生效配置的 enabled 值，"1"/"0"；无配置时 "0"）与 `BUDGET_NOTIFY_CONFIG`（生效配置文件绝对路径）。存在意义：Leader 在通知节点 `eval` 后以 `$BUDGET_NOTIFY_ENABLED` 快速短路（无配置时不空跑 notify.py）、并把定位结果传给后续子进程。notify.py 读取优先级：`$BUDGET_NOTIFY_CONFIG`（已设置时）> 自行按同一降级规则定位；enabled 最终判定以文件内容为准。敏感字段（webhook/secret）不经环境变量。
- **通知点 N1-N11**（保留参照项目**全部**节点；参照项目分 voice/markdown 两种形式，本项目统一 webhook markdown——决策④的自然结果，voice 形式降级为 markdown 投递，消息内容不变）：

| 节点 | 触发条件 | 参照形式 | 消息模板要点 |
|------|---------|---------|-------------|
| N1 | Phase 2 设计评审第 3 次驳回 | voice | ⚠️ Phase 2 第3次驳回，需用户裁决 |
| N2 | Task 3 轮审查全败（lite→standard→senior 均未通过） | voice | ⚠️ 3轮审查未通过 |
| N3 | Task 循环超 5 轮触发暂停 | voice | ⚠️ 循环超5轮，已触发暂停 |
| N4 | 自动恢复策略耗尽（含 Director），需最终裁决 | voice | ⚠️ 所有自动恢复策略已耗尽 |
| N5 | reviewer 疑似误判，Leader 介入仲裁 | voice | ⚠️ reviewer 疑似误判，Leader 已介入 |
| N6 | Director 介入（含 goal loop 连续驳回场景） | voice | 🎯 Director 介入 + 裁决分类/结论/状态 |
| N7 | Phase 2 评审通过 | markdown | ✅ 设计评审通过，进入开发阶段 |
| N8 | Phase 3 代码开发完成 | markdown | ✅ {total}个任务全部通过 |
| N9 | 需用户拍板（含 goal 循环超限/预算耗尽/轮次与时间上限） | voice | ⚠️ {count}个问题需您拍板 |
| N10 | 全流程完成（归档） | markdown | ✅ {done}/{total}任务通过，已归档 |
| N11 | Goal Loop 达成并归档 | markdown | 🎯 经过 {N} 轮迭代，目标已达成 |

消息前缀统一 `[budget]`，模板含项目名（`$(basename "$PWD")`）与详情字段，变量来源表不变；各节点调用形如 `budget notify "<msg>" || true`。

- **hooks 与 superpowers 插件启用**：CodeBuddy `dist/codebuddy/hooks/budget-notify-hook.py`（stdin JSON → 构建消息 → 调 notify）+ lib/hooks*.sh 注入 settings.json（Notification/PreToolUse/SubagentStop 三事件；注入前备份 `settings.json.bak-budget`；注入幂等，settings.json 写入采用临时文件 + 原子 rename）。lib/hooks.sh 同时负责 **superpowers 插件启用**：检测 settings.json 的 `enabledPlugins`，未启用则注入 `"superpowers@codebuddy-plugins-official": true` 并提示重启或手动执行 `/plugin superpowers`——`SKILL_NS="superpowers:"` 前缀的 skill 引用依赖该插件；`setup init` 与安装器 codebuddy 路径均调用该启用流程（A11）。OpenCode 无此机制，以 setup-notes.md 说明插件扩展点。

## 10. 安装器（install.sh）

`curl -fsSL $BUDGET_REPO_URL/install.sh | bash`；顶部 BUDGET_REPO_URL 可配置（默认 GitHub raw 占位，推送后修正——Q1）。**版本定位**：默认经 `$BUDGET_REPO_URL/releases/latest`（release 托管方 latest 固定别名）解析最新版本 zip 下载 URL；`BUDGET_VERSION` 可指定具体 tag；`budget setup update` 沿同一约定重新发现版本（A9 补充）。**下载包完整性校验**：release 附 `budgetbuddy-<version>.zip.sha256`；install.sh 下载 zip 后强制校验（sha256sum / shasum -a 256 自动探测），**校验失败即中止、不进入安装**（A12，供应链安全）。交互选择平台（codebuddy/opencode/both）与作用域（项目/全局）；`--global` 跳过交互；`BUDGET_PLATFORM`/`BUDGET_GLOBAL` 支持非交互。codebuddy：结构文件 → `.codebuddy/`（项目）或 `~/.codebuddy/`（全局），写 `~/.local/bin/budget`，hooks 注入 settings.json（含 superpowers 插件启用）。opencode：`dist/opencode/{agent,command,skill}` → `~/.config/opencode/` 或 `.opencode/`，AGENTS.fragment.md 幂等合并进 AGENTS.md（`<!-- BudgetBuddy:begin/end -->`）；管理面（setup.sh/lib/models/personas/docs）统一装 `~/.budgetbuddy/`（A3，docs → `~/.budgetbuddy/docs/`）。**安装清单持久化**（A12）：安装/升级成功后写 `<安装根>/.budget-manifest.json`（本套件已装文件与哈希）；**升级** = 按「本地旧清单 − 新 manifest」差集清理旧版文件 + manifest 内哈希不一致覆盖（清单内文件的用户本地修改会被升级覆盖，清单外用户自建文件一律保留）；**卸载** 按本地清单删除（离线可用，不依赖 dist manifest）。增量同步以 `dist/<platform>/.manifest.json` 为准：哈希一致跳过、不一致覆盖、清单外文件一律保留。安装各步骤幂等（哈希跳过 / AGENTS.md 合并幂等 / 清单最后原子写），**中断后重跑安装即恢复**。依赖检查 curl/tar/python3/sha256 工具；Windows 提示 Git Bash/WSL。v0.1.0 安装落点固定（`~/.budgetbuddy/` 等），不支持自定义安装根。README 安装节提示 curl|bash 信任边界（建议先审查脚本再执行）。`scripts/build-release.sh`：`build.py --check && zip -r budgetbuddy-<version>.zip dist/ VERSION` 并生成同名 `.sha256`。

## 11. OpenSpec 与命令入口

`core/commands/`：budget 组 `start.md`/`status.md`/`goal.md` + opsx 组 `apply.md`/`archive.md`/`explore.md`/`propose.md`（frontmatter 按 §3.1 命令 schema）。产物：CodeBuddy `/budget:start` `/opsx:apply` 等；OpenCode `/budget-start` `/opsx-apply` 等。`core/skills/openspec-{apply-change,archive-change,explore,propose}/`：沿用参照项目内容，中立化措辞 + 触发词改 budget 系。

## 12. 对设计文档的细化/调整点（A1-A14）

以下调整均**不触碰四项已定决策**，只补实现级细节或纠偏；coder 实现以本文为准。

- **A1 workflow skill 文件集合扩大**：设计文档 §2 仅列 budget-workflow 的 SKILL.md + router.md + phases.md；参照项目该 skill 实际还含 goal.md、reference.md 及一份状态脚本。调整：core/skills/budget-workflow/ 迁移全部 5 个 markdown（SKILL/router/phases/goal/reference），状态脚本更名 budget-state.py 并单份化（见 A4）。
- **A2 commands 增加 opsx 组 4 命令**：设计文档 §2/§8 只列 start/status/goal 3 个命令；参照项目 commands 下实为两组（工作流组 + opsx 组 apply/archive/explore/propose，对应 openspec 4 skill 的命令入口）。调整：core/commands/ 分 budget/ 与 opsx/ 两组共 7 个命令，产物为 `/budget:*`、`/opsx:*`（opencode 为 `/budget-*`、`/opsx-*`），§11 已按此表述。
- **A3 opencode 管理面产物落点明确为 ~/.budgetbuddy/**：设计文档 §9 未说明 opencode 安装时 lib/、setup.sh、budget-models.json、personas.json 的落点。调整：管理面（上述四类 + docs/）统一装 `~/.budgetbuddy/`（与 codebuddy 全局一致），平台结构目录（`~/.config/opencode/` 或 `.opencode/`）只装 agent/command/skill/AGENTS.fragment 等结构性文件——保证「安装器增量同步永不碰用户数据」（设计文档 §4）对双平台同样成立。
- **A4 状态机单份化**：参照项目存在两份状态脚本（lib/ 下一份、workflow skill 目录下一份），存在漂移风险。调整：本项目仅保留 `core/lib/budget-state.py` 一份，skill 文档中以固定相对路径 `$HOME/.budgetbuddy/lib/budget-state.py` 引用（运行时），构建平移到 `dist/<platform>/lib/`；skill 目录不再放状态脚本。
- **A5 手写 YAML 子集解析器**：设计文档未指定 platform/*.yaml 的解析方式。为满足「Python3 stdlib only」（proposal Impact），build.py 内置约 150 行最小 YAML 子集解析器，仅支持本 DSL 用到的语法：两空格缩进嵌套 map、块式 list（`- item`）、**块式 list 项为 map（`- key: value` + 两空格缩进续行——opencode.yaml 的 `extra_outputs` 即此形态）**、行内流式 `{}`/`[]`、单/双引号与裸标量（含引号内冒号如 `"/{group}:{name}"` 与值后行内注释）、空字符串 `""`、`#` 注释；不支持锚点/多行字符串/tag。DSL schema 校验失败即 build 失败。全部语法形态以 `tests/test_build.py` 固定用例锁定。
- **A6 MODEL_SELECTION.md 模板化生成**：设计文档 §8 将 MODEL_SELECTION.md 当静态文档；调整：由 `core/docs/MODEL_SELECTION.template.md`（模板）+ `core/models/budget-models.json`（数据）在构建期按平台生成 `dist/<platform>/docs/MODEL_SELECTION.md`。**模板占位符语法**：`{{models_table}}`（模型目录表）、`{{preset_table}}`（双平台三档预设表）、`{{platform_note}}`（平台说明段）三个；占位符替换与 §3.3 六变量共用同一替换器实现（白名单精确匹配、未知名保留原样并告警），但白名单独立（模板占位符集与 §3.3 变量集互不混用）。routing.docs 映射到 `*.template.md` 源的条目自动走本渲染管线（模板不平移，§3.5）。
- **A7 .manifest.json SHA256 清单**：设计文档 §9 提到「SHA256 清单增量同步」但未定义清单来源。调整：build.py 在每次构建后写 `dist/<platform>/.manifest.json`（`{"files": {"<相对路径>": "<sha256>"}}`，**不含任何时间戳，按键排序**），作为安装器增量同步与升级差集清理的**构建侧**依据；两平台各一份。该文件本身不列入自身清单。
- **A8 补全 lib 文件清单**：设计文档 §8 称「lib/（20+ 文件）」未列明细。调整：§8.2 给出全量 24 文件清单（六组）。与参照项目的差异：① 状态脚本更名 budget-state.py 单份（A4）；② 剔除 `__pycache__`/*.pyc；③ 参照项目随 dist 分发的 lib 内嵌测试目录**不随产物分发**，本项目测试统一放仓库根 `tests/`（位于品牌扫描范围之外，避免用例中构造违禁词样本误触发门禁）。
- **A9 latest.json 不纳入 + 版本定位约定**：参照项目 dist 含 latest.json（升级探测元数据）。v0.1.0 不做在线版本协商（不迁移该文件、不做升级探测服务端），版本发现依赖 release 托管方的 `$BUDGET_REPO_URL/releases/latest` 固定别名（§10）；`budget setup update` 按该约定重新下载 release zip 并重跑安装流程。
- **A10 词表定义载体豁免（扩围）**：违禁词表必须以字面量定义的载体（scan-brand.py 自身、design.md §5 词表行、specs/brand-compliance 词表行）不因词表字面量判违规。机器扫描层面 scan-brand.py 执行时跳过自身文件（其位于扫描范围 `scripts/` 内），其余 scripts/ 文件正常扫描；openspec 产物合规审计（brand-compliance spec）明确豁免上述三处词表定义行。`tests/` 已在扫描范围之外（A8），用例内构造的违禁词样本不受影响。
- **A11 setup 子命令全集对齐 + superpowers 插件启用**：设计文档 §8 未列全子命令、未提 superpowers 插件启用。调整：① 子命令对齐参照项目 setup.sh 实际分发——增补 `quickstart`（别名 tour/wizard；lib 已含 quickstart.py，避免「模块在、入口无」死代码）、`init shell`（shell 别名注入）、`guard`（Coder Guard 查询/重置）、`reinstall`（uninstall+init 组合）；`budget update` 为 `budget setup update` 顶层快捷别名（§8.1）；② lib/hooks.sh 承担 superpowers 插件检测与启用注入（参照项目 init/hooks 链路核心步骤，`SKILL_NS="superpowers:"` 前缀依赖），`setup init` 与安装器 codebuddy 路径均调用（§9）。
- **A12 下载完整性校验与安装清单持久化**：设计文档 §9 未定义下载校验与安装侧清单。调整：① release 附 `budgetbuddy-<version>.zip.sha256`，install.sh 下载后强制校验、失败即中止（供应链安全）；② 安装/升级成功后写 `<安装根>/.budget-manifest.json` 本地清单，升级按「本地旧清单 − 新 manifest」差集清理、卸载按本地清单删除（离线可用）；清单外用户文件一律保留（§10）。
- **A13 agent description 恢复 MUST BE USED 调度前缀**：T2 初版 10 个 agent 的 description 丢弃了参照项目双版本均携带的 `MUST BE USED —` 强制调度前缀（9/10 agent 有该前缀，goal-evaluator 参照版本无）。该前缀是 CodeBuddy/OpenCode 主会话按 description 决定派发的调度可靠性约定（ad-hoc 场景下降低漏派发概率）。决策：**恢复前缀**（语义对等要求 + 调度可靠性，成本为零）；goal-evaluator 参照版无前缀，保持无前缀。双审意见：主审 P3/P 辅审 P2-3（2026-10-17 复审记录）。
- **A14 Coder Guard 语义口径统一**：spec workflow-orchestration 初版将 guard 描述为承载「任务范围、修改文件清单、边界声明」的护栏，与 §8.4（跨会话汇总降级判定）及参照项目实际语义（失败率记录）漂移。裁决：guard 仅承担**失败记录与分级降级**（history + summary，5 次窗口失败 ≥2 降级）；任务范围审计（修改文件清单 vs §16 文件范围）由 reviewer 在 Phase 3 与 phases.md 4.3 步骤承担。spec 措辞已同步修订（辅审 P1-1，2026-10-17）。

## 13. Risks / Trade-offs

| # | 风险/取舍 | 影响 | 缓解 |
|---|-----------|------|------|
| R1 | 手写 YAML 子集解析器（A5）语法覆盖不足 | platform DSL 表达受限，构建失败 | DSL schema 严格校验、失败即阻断；解析器仅服务两份 yaml，语法面可控；tests/test_build.py 固定用例覆盖全部 DSL 实际用到的语法形态（含块式 list-of-map、引号内冒号、行内注释、空串） |
| R2 | 状态机单份化（A4）跨目录引用在双平台落位后需均成立 | opencode 项目级安装时 skill 与 lib 分离两地 | skill 引用统一指向 `$HOME/.budgetbuddy/lib/budget-state.py`（管理面恒为全局单点，A3），不依赖相对路径 |
| R3 | CodeBuddy 粗粒度 permissionMode 表达不了 bash_allow 细粒度（含 `[]` 禁止语义） | CodeBuddy 侧 bash 约束弱于 OpenCode 侧 | 正文约束措辞承担语义（§3.2 已定）；中立字段保留供审计与构建校验 |
| R4 | OpenCode 无原生 rules/hooks 机制 | 强制力弱于 CodeBuddy 侧 | 三层落位（§3.4：AGENTS.fragment 合并 + SKILL 内联 P0 + setup-notes 说明）；diff 校验一致性（可执行判定规则 + --strict + T13 人工抽查） |
| R5 | dist 提交进 git，源/产物漂移 | 用户装到过期产物 | `build.py --check` 本地+CI 门禁；release 打包强制 --check 先行；原子构建保证失败不污染已提交产物 |
| R6 | 模型 ID 目录漂移（尤其 opencode provider/model ID 待核对） | 预设解析失败或指向不存在模型 | `_meta` 标注不确定项；`budget setup models` 可更新；Open Questions 跟踪 |
| R7 | 增量同步误删用户自定义文件 | 用户数据损失 | 清单外文件一律保留（§10）；卸载按本地清单删清单内；hooks 注入前备份 settings.json |
| R8 | 单次变更体量大（13 任务 / 24 执行单元、76 个 src 文件） | 集成风险 | 任务依赖线性化（T1 门禁先行）；每执行单元 ≤2h；每任务验收含构建冒烟；T13 全量演练兜底 |
| R9 | 钉钉/飞书加签算法与官方文档不一致 | 通知发送 4xx | 单测以固定向量验证 HMAC/签名实现（mock 发送不外呼）；实现时对照官方文档 |
| R10 | curl|bash 供应链信任 | 用户盲执行远程脚本 | release zip 强制 SHA256 校验（A12）；README 提示先审查 install.sh |

**关键取舍**：① 不引 PyYAML 换 stdlib-only（R1 承担代价）；② dist 进 git 换「安装器零构建依赖、离线可装」（R5 承担代价）；③ 功能全量对等一次落地（不做分期），换取 v0.1.0 基线完整可审计；④ P0 一致性 diff 用「规范化关键词比对」近似语义一致（80% 双向包含率），换取机器可执行，语义漂移由 T13 人工抽查兜底。

## 14. Migration Plan

全新仓库，**无存量代码迁移**。落地顺序即任务依赖（tasks.md，13 任务 / 24 执行单元）：

1. **T1 先行**（3 执行单元）：构建系统核心（解析器+校验+转换+manifest+原子构建+空 core 降级）、违禁词门禁、release 打包 + VERSION——门禁与转换链路就位后，后续所有内容任务都能即时构建验证。
2. **T2-T8 内容填充**（agents / workflow skill / notify / openspec skill / commands / rules / models / personas），可部分并行，各自完成后立即构建 + 门禁；MODEL_SELECTION 渲染在 T8a 数据就位后实现。
3. **T9-T10 管理面**（setup.sh + lib 基础层/业务层），依赖 T8 的 models/personas 数据。
4. **T11 安装器**，依赖 .manifest.json 格式（T1a）与 dist 结构定型。
5. **T12 仓库文档**，依赖功能面定稿（版本号、组件清单）。
6. **T13 全量验收**：双平台安装演练、幂等验证、违禁词门禁、通知单测、setup 冒烟、P0 人工抽查（设计文档 §11 全部 7 条，口径按本文修正）。

每任务合并前必须 `python3 scripts/build.py --check` 通过。v0.1.0 全量合入后打 tag `v0.1.0`，跑 `scripts/build-release.sh` 产出 zip + .sha256。

**用户侧迁移**：参照项目用户以 install.sh 全新安装本套件即可；不提供从参照项目的自动迁移（Non-Goal）。数据目录（`.budget/`、`~/.budgetbuddy/`）为全新路径，与参照项目目录互不冲突，可共存。

## 15. Open Questions

| # | 问题 | 影响 | 状态 |
|---|------|------|------|
| Q1 | `BUDGET_REPO_URL` 默认值当前为 GitHub raw **占位地址**（仓库尚未推送远端） | install.sh 在线安装在真实地址确定前不可用 | 不阻塞开发/提测；**阻塞上线发布**——推送远端后修正 install.sh 顶部变量并复跑门禁。版本定位约定已定：`$BUDGET_REPO_URL/releases/latest` 固定别名 + `BUDGET_VERSION` 指定 tag（§10/A9） |
| Q2 | OpenCode 三档预设的 provider/model ID 待核对（anthropic/openai/google/zhipu/deepseek/moonshotai 系） | 预设解析出的模型 ID 可能在用户 opencode.jsonc 中不存在 | 不阻塞开发；实现 T8a 时经本机 `opencode models` 或官方 catalog 核对；不确定者在 budget-models.json `_meta` 显式标注「待确认」，**阻塞上线**前必须清零 |
| Q3 | CodeBuddy 模型 ID 目录（balanced 烘焙用）在 v0.1.0 后的增删 | 烘焙默认过期 | `budget setup models` / `budget setup agent preset\|custom` 重写机制缓解；非阻塞 |
| Q4 | 钉钉/飞书 webhook 加签细节（timestamp 单位、编码方式）以官方文档为准 | 通知渠道发送失败 | T4 实现时对照官方文档；单测固定向量验证；非阻塞 |
| Q5 | 参照项目 rules 的 8 条代码规范含平台内部框架细节（如内部 RPC 框架规范） | 直接迁移可能残留内部专有名词或对开源用户无意义 | T7 中逐条审查：去除内部引用、保留通用规范本体；无法中立化的条目在规范正文降级为通用写法。非阻塞，但纳入品牌门禁覆盖 |

## 16. 文件范围全量清单（coder 修改边界 / reviewer 审计基准）

> 本清单为 v0.1.0 全量文件范围。coder 只允许创建/修改本清单内文件（`openspec/`、`tests/` 的自举产物除外）；reviewer 逐文件对照审计。`dist/**` 为构建产物，**禁止手改**，一律经 `python3 scripts/build.py` 生成。「类型」：src=中立源、gen=构建生成、infra=仓库基础设施、doc=文档、test=测试。

### 16.1 中立源 core/（src）

| 路径 | 类型 | 说明 | 任务 |
|------|------|------|------|
| `core/agents/architect.md` | src | 架构师：方案/闸门/架构决策，权限 §6 | T2 |
| `core/agents/coder-lite.md` | src | 轻量 coder | T2 |
| `core/agents/coder-standard.md` | src | 标准 coder | T2 |
| `core/agents/coder-senior.md` | src | 高级 coder（架构/安全/并发） | T2 |
| `core/agents/reviewer.md` | src | 审查 A（只读） | T2 |
| `core/agents/reviewer-b.md` | src | 审查 B（交叉复核，只读） | T2 |
| `core/agents/tester.md` | src | 验证执行（只读+任意 bash） | T2 |
| `core/agents/recorder.md` | src | 归档/经验提取 | T2 |
| `core/agents/director.md` | src | 终裁（只读+禁 bash） | T2 |
| `core/agents/goal-evaluator.md` | src | 目标达成判定（只读+禁 bash） | T2 |
| `core/skills/budget-workflow/SKILL.md` | src | 工作流主文档（含 P0 内联章节） | T3a |
| `core/skills/budget-workflow/router.md` | src | 任务路由/分级派发 | T3a |
| `core/skills/budget-workflow/phases.md` | src | 5 阶段细则 | T3b |
| `core/skills/budget-workflow/goal.md` | src | goal loop 细则（A1，含 N11） | T3c |
| `core/skills/budget-workflow/reference.md` | src | 组件引用/速查（A1） | T3c |
| `core/skills/budget-notify/SKILL.md` | src | 通知 skill 文档 | T4 |
| `core/skills/budget-notify/notify.py` | src | 通用 webhook 发送（四渠道） | T4 |
| `core/skills/budget-notify/load-env.sh` | src | BUDGET_NOTIFY_* 环境加载 | T4 |
| `core/hooks/budget-notify-hook.py` | src | CodeBuddy hooks 通知引擎源（routing `hook` 的输入，仅 codebuddy 平台产物） | T4 |
| `core/skills/openspec-apply-change/SKILL.md` | src | openspec 实现 skill | T5 |
| `core/skills/openspec-archive-change/SKILL.md` | src | openspec 归档 skill | T5 |
| `core/skills/openspec-explore/SKILL.md` | src | openspec 探索 skill | T5 |
| `core/skills/openspec-propose/SKILL.md` | src | openspec 提案 skill | T5 |
| `core/commands/budget/start.md` | src | 工作流启动命令模板 | T6 |
| `core/commands/budget/status.md` | src | 状态查询命令模板 | T6 |
| `core/commands/budget/goal.md` | src | goal loop 命令模板 | T6 |
| `core/commands/opsx/apply.md` | src | openspec 实现命令（A2） | T6 |
| `core/commands/opsx/archive.md` | src | openspec 归档命令（A2） | T6 |
| `core/commands/opsx/explore.md` | src | openspec 探索命令（A2） | T6 |
| `core/commands/opsx/propose.md` | src | openspec 提案命令（A2） | T6 |
| `core/rules/budget-leader-no-code.md` | src | P0：Leader 禁写代码 | T7 |
| `core/rules/budget-coder-guard.md` | src | P0：Coder 护栏 | T7 |
| `core/rules/budget-workflow-enforcement.md` | src | P0：流程强制 | T7 |
| `core/rules/budget-cpp-style.md` | src | C++ 代码规范 | T7 |
| `core/rules/budget-css-style.md` | src | CSS 代码规范 | T7 |
| `core/rules/budget-go-style.md` | src | Go 代码规范 | T7 |
| `core/rules/budget-java-style.md` | src | Java 开发规范 | T7 |
| `core/rules/budget-python-style.md` | src | Python 代码规范 | T7 |
| `core/rules/budget-sql-style.md` | src | SQL 官方规范 | T7 |
| `core/rules/budget-typescript-style.md` | src | TypeScript 代码规范 | T7 |
| `core/rules/budget-trpc-style.md` | src | 内部 RPC 框架规范→通用服务调用规范（Q5） | T7 |
| `core/rules/budget-rtk.md` | src | 可选 RTK 工具规则 | T7 |
| `core/models/budget-models.json` | src | 模型目录+双平台三档预设（§7） | T8a |
| `core/models/budget-models.schema.json` | src | 模型目录 JSON Schema | T8a |
| `core/docs/MODEL_SELECTION.template.md` | src | 模型选择文档模板（A6） | T8a |
| `core/personas/personas.json` | src | 5 主题 persona（§8.5，roles 11 键） | T8b |
| `core/docs/PERSONAS.md` | src | persona 使用文档 | T8b |
| `core/platform/codebuddy.yaml` | src | CodeBuddy 平台 DSL（§3.5） | T1a |
| `core/platform/opencode.yaml` | src | OpenCode 平台 DSL（§3.5） | T1a |
| `core/lib/colors.sh` | src | 终端颜色/输出基础 | T9a |
| `core/lib/utils.sh` | src | 通用 shell 工具函数 | T9a |
| `core/lib/platform.sh` | src | 运行时平台探测（§8.3） | T9a |
| `core/lib/shell.sh` | src | shell 兼容/严格模式 | T9a |
| `core/setup.sh` | src | setup.sh 主入口（§8.1 子命令分发；routing `setup: "setup.sh"` 平移） | T9a |
| `core/lib/init.sh` | src | setup init 子命令（含 superpowers 插件启用/gitignore/hooks 编排调用） | T9b |
| `core/lib/update.sh` | src | setup update 子命令 | T9c |
| `core/lib/uninstall.sh` | src | setup uninstall 子命令 | T9c |
| `core/lib/models.sh` | src | 模型目录加载/列出 | T10a |
| `core/lib/preset.sh` | src | 预设切换/agent 重写 | T10a |
| `core/lib/model_resolver.py` | src | 角色→模型 ID 解析 | T10a |
| `core/lib/rtk.sh` | src | RTK 工具适配 | T10a |
| `core/lib/guard.sh` | src | Coder Guard 护栏 | T10b |
| `core/lib/budget-state.py` | src | 工作流状态机（单份，A4） | T10b |
| `core/lib/persona.sh` | src | persona 管理 | T10c |
| `core/lib/persona_expand.py` | src | persona 展开 | T10c |
| `core/lib/validate.sh` | src | 安装完整性校验 | T10c |
| `core/lib/display.py` | src | 展示/表格输出 | T10c |
| `core/lib/interactive.sh` | src | 交互式向导 | T10c |
| `core/lib/run_summary.py` | src | 运行汇总 | T10c |
| `core/lib/banner.py` | src | 启动横幅 | T10c |
| `core/lib/notify.sh` | src | notify 命令 shell 侧 | T10d |
| `core/lib/hooks.sh` | src | hooks 注入编排 + superpowers 插件启用 | T10d |
| `core/lib/hooks_inject.py` | src | settings.json 注入实现（幂等+原子写） | T10d |
| `core/lib/quickstart.py` | src | 快速上手引导 | T10e |
| `core/docs/architecture.md` | src | 架构说明（Mermaid 图） | T12 |
| `core/docs/opencode-setup-notes.md` | src | opencode 平台安装/扩展点说明 | T12 |

### 16.2 构建与基础设施（infra/gen）

| 路径 | 类型 | 说明 | 任务 |
|------|------|------|------|
| `scripts/build.py` | infra | core→dist 双平台转换（§4） | T1a |
| `scripts/scan-brand.py` | infra | 违禁词门禁（§5） | T1b |
| `scripts/build-release.sh` | infra | release zip 打包 + .sha256 生成 | T1c |
| `install.sh` | infra | 双平台安装器（§10） | T11 |
| `dist/codebuddy/**` | gen | 构建产物（含 agents/commands/skills/rules/hooks/lib/setup.sh/docs/.manifest.json），禁手改 | T1-T13 |
| `dist/opencode/**` | gen | 构建产物（含 agent/command/skill/AGENTS.fragment.md/docs/lib/.manifest.json），禁手改 | T1-T13 |

### 16.3 测试与仓库文档（test/doc）

| 路径 | 类型 | 说明 | 任务 |
|------|------|------|------|
| `tests/test_build.py` | test | 构建转换/幂等/manifest/解析器边界单测（A5 全语法形态 + 原子构建 + 空 core 降级） | T1a |
| `tests/test_scan_brand.py` | test | 门禁扫描单测（违禁词样本在测试内构造） | T1b |
| `tests/test_notify.py` | test | 四渠道格式化+签名单测（mock 发送） | T4 |
| `tests/test_platform.py` | test | platform.sh 三分支探测单测 | T9a |
| `tests/test_preset.py` | test | 预设解析/agent 重写单测 | T10a |
| `tests/test_state.py` | test | 状态机单测 | T10b |
| `tests/test_guard.py` | test | Coder Guard 记录/降级窗口单测 | T10b |
| `tests/test_installer.py` | test | AGENTS.md 幂等合并/manifest 增量同步/卸载差集单测 | T11 |
| `README.md` | doc | 英文 README（含 curl|bash 信任提示） | T12 |
| `README_CN.md` | doc | 中文 README（含 curl|bash 信任提示） | T12 |
| `CHANGELOG.md` | doc | 变更日志（v0.1.0 首条） | T12 |
| `VERSION` | doc | 版本号 `0.1.0`（T1c 提前创建，解除 build-release.sh 前向依赖） | T1c |
| `LICENSE` | doc | MIT | T12 |
| `CODEBUDDY.md` | doc | 自举开发说明（CodeBuddy 读） | T12 |
| `AGENTS.md` | doc | 自举开发说明（OpenCode 读，与 CODEBUDDY.md 内容一致） | T12 |
| `openspec/changes/foundation/**` | doc | 本变更产物（proposal/design/specs/tasks） | 已完成 |

**合计**：src 76（agents 10 + skills 12 + hooks 1 + commands 7 + rules 12 + models 2 + personas 1 + platform 2 + setup.sh 1 + lib 24 + docs 4）/ infra 4 / gen 2 顶层 / test 8 / doc 8。
