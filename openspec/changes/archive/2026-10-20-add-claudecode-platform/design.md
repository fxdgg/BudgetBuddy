# 设计：新增 Claude Code 平台支持

> 承接 proposal.md；沿用 foundation 变更确立的「单一中立源 + 构建期平台适配」架构与 DSL 语义（§3.5）。本文档中的行号引用基于当前 `scripts/build.py`。

## Context

现状为双平台（codebuddy/opencode）产物，平台差异全部收敛在 `core/platform/*.yaml` DSL 与 build.py 转换器两层。调研确认 Claude Code 为「近亲平台」：子代理 frontmatter、分组斜杠命令（`commands/{group}/{name}.md` → `/budget:start`）、skills 目录结构、`permissionMode` 枚举（含 `acceptEdits`/`plan`）、PascalCase 工具名（Read/Write/Edit/Bash/Grep/Glob/WebFetch/WebSearch 与 `_TOOL_PASCAL` 完全一致）均与 CodeBuddy 同构。差异仅三处：frontmatter 键名 camelCase（`permissionMode`/`maxTurns`）、派发工具名为 `Task`（非 `Agent`）、规则承载于 CLAUDE.md（合并机制同 opencode AGENTS.md 先例）。

约束：Python3 stdlib only（不引 PyYAML）；YAML 子集不支持多行字符串；无法识别的 frontmatter 字段在 Claude Code 端静默忽略（碎片风险低）。

## Goals / Non-Goals

**Goals:**
- `dist/claudecode/` 完整产物：agents×10（camelCase frontmatter）、commands×7（`/budget:start` 形态）、skills×6、CLAUDE.fragment.md 规则合并、models/personas/lib/setup/docs
- build.py 平台清单数据驱动——后续新增平台（如 Codex）不再改转换器代码
- 安装器/运行时管理面完整支持 claudecode（项目/全局、CLAUDE.md 合并、preset 切换）

**Non-Goals:**
- Claude Code hooks 注入与通知适配（v2 独立变更）
- Codex 平台（后续独立提案）
- 插件 marketplace 分发形态、superpowers 命名空间等价物

## Decisions

### D1 平台清单数据驱动（泛化 5 处硬编码）

| # | 现状（build.py） | 泛化后 |
|---|---|---|
| 1 | `_MODEL_PLATFORMS = ('codebuddy','opencode')`（模型条目 platform 枚举） | 由 `models.json platforms` 键集推导：条目 platform 值必须 ∈ `data['platforms']` 键集（数据内自洽校验） |
| 2 | `validate_models_data` 中 `for platform in ('codebuddy','opencode')` | `for platform in data['platforms']`（对每个键做 presets 三档校验） |
| 3 | `_PLATFORM_NOTE_LINES` 常量字典（平台说明文案） | `models.json platforms.<p>` 增可选键 `note`（字符串数组）与 `unconfirmed_ids`（字符串数组）；`_render_platform_note` 数据驱动渲染，**阶段 1 实现「数据驱动 + 常量回退」**（`note` 缺失时沿用现有常量文案，保证任务 1.5 的 hash 回归可满足）；现有两平台文案作为 `note` 初值的**数据迁移统一在任务 2.2 落地**（与 models 数据扩展同批，models.json 变更前回归标准成立）；`_meta.unconfirmed_opencode_ids` 迁移至 `platforms.opencode.unconfirmed_ids`（读侧兼容旧键一个版本，兼容读取点含 core/lib/models.sh） |
| 4 | `_render_preset_table` 双平台表头循环 | `for platform in data['platforms']` 键序（JSON 插入序，确定性由源文件保证） |
| 5 | `parse_args` choices 元组 + `main` 硬编码平台列表 | 构建期 glob `core/platform/*.yaml` 枚举平台清单；choices 与默认构建范围动态生成；未知 `--platform` 值显式报错 |

- **备选被否**：直接在枚举里加第三个字符串——每新增平台仍要改 5 处转换器代码，泛化本身是本次变更的技术债清理收益，也为 Codex 后续提案铺路。
- **预设值校验策略**：`_validate_preset_value` 改为「**默认 catalog_id、opencode 特判 provider/model**」——除 opencode 外的平台（claudecode 及后续如 Codex）零代码走默认策略，`provider/model` 特判收敛为 opencode 单平台分支（策略集合稳定，保留在 build.py 可接受）。
- **双清单一致性校验**（双审共同发现）：构建期校验 `core/platform/*.yaml` 平台集合 == `models.json platforms` 键集（双向不一致 → 显式报错），消除 glob 与数据两真值源漂移。

### D2 `core/platform/claudecode.yaml` DSL 映射

```yaml
platform: claudecode
output: dist/claudecode
routing:
  agent:   "agents/{name}.md"
  command: "commands/{group}/{name}.md"     # 与 codebuddy 同构 → /budget:start
  skill:   "skills/{skill}/"
  rule:    "CLAUDE.fragment.md"             # 与 extra_outputs dest 一致（同 opencode 模式）
  hook:    ""                               # 首发降级不分发（同 opencode 先例）
  models:  "budget-models.json"
  personas: "personas.json"
  lib:     "lib/"
  setup:   "setup.sh"
  docs:
    MODEL_SELECTION.template.md: "docs/MODEL_SELECTION.md"
    PERSONAS.md: "docs/PERSONAS.md"
    architecture.md: "docs/architecture.md"
    opencode-setup-notes.md: null
agent_frontmatter:
  emit:
    name: "{name}"
    description: "{description}"
    model: "{resolved_model}"
    tools: "{tools|pascal}"
    permissionMode: "{permission_mode}"     # camelCase 键：emit 输出键名任意，零 schema 扩展
    maxTurns: "{max_turns}"
  permission_mode_rule: { edit_all: "acceptEdits", edit_restricted: "plan" }
  drop: [model_role, permissions]
command_frontmatter:
  emit: [description, argument-hint]        # 命令名由产物文件名承载；不输出 name（Claude Code 按文件名识别）
  drop: [name]
command:
  invoke: "/{group}:{name}"
body_variables:
  TASK_TOOL: "Task"                         # Claude Code 派发工具名（区别于 CodeBuddy 的 Agent）
  SKILL_NS: ""
  AGENT_DIR: ".claude/agents/（项目级；不存在则 ~/.claude/agents/）"
  GUARD_PATH: "$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json"
  RULES_DIR: "CLAUDE.md 标记区块（安装器合并）"
  PROJECT_DOC: "启动时读取项目根 CLAUDE.md（如保留 CODEBUDDY.md/AGENTS.md，一并参考）"
extra_outputs:
  - kind: agents_fragment
    source: "rules/**"
    dest: "CLAUDE.fragment.md"
    markers: ["<!-- BudgetBuddy:begin -->", "<!-- BudgetBuddy:end -->"]
```

- **emit 零扩展验证**：`EMIT_EXPRESSIONS` 七表达式（`{name}/{description}/{resolved_model}/{tools|pascal}/{permission_mode}/{permission_map}/{max_turns}`）已覆盖 claudecode 全部需要；camelCase 通过 emit **键名**实现（键名任意是既有语义）；`_TOOL_PASCAL` 映射与 Claude Code 工具名完全一致；`compute_permission_mode` 输出值由 DSL `permission_mode_rule` 配置（`acceptEdits`/`plan` 均为 Claude Code 合法枚举值），函数零改动。
- **tools 列表形态**：Claude Code 接受逗号分隔或 YAML 列表；沿用现有列表输出。
- **命令 frontmatter 不输出 `name`**：备选「与 codebuddy 一致三字段直出」被否——Claude Code 靠文件路径识别命令，name 属无效字段（虽静默忽略，但产物应干净）。

### D3 模型目录与三档预设

- `models.paid.claude` 组条目的 `platform` 数组扩展 `"claudecode"`（数据变更，无 schema 结构变化）。
- `platforms.claudecode` 新增三档十角色预设，值为 catalog 中 claude 系完整 ID（复用 catalog_id 校验策略）：
  - `economic` → haiku 系；`balanced` → sonnet 系；`quality` → opus 系
  - **备选被否**：用别名（`haiku`/`sonnet`/`opus`）——脱离 catalog 校验体系，与 codebuddy 预设形态不一致，且丢失成本倍率语义。
- 未在本机 Claude Code 环境核对的 ID 记入 `platforms.claudecode.unconfirmed_ids`（D1-3 泛化机制），MODEL_SELECTION 渲染「待确认」清单，上线前清零纪律同 opencode 先例。
- `budget-models.schema.json` 若硬编码 platform 枚举则同步扩展；`platforms.<p>.note/unconfirmed_ids` 为可选键，schema 增补。

### D4 install.sh claudecode 分支

- 落点：项目级 `.claude/`（agents/commands/skills）或全局 `~/.claude/`；管理面统一 `~/.budgetbuddy/`（A3 不变）。
- `CLAUDE.fragment.md` 幂等合并：项目级合并进项目根 `CLAUDE.md`，全局级合并进 `~/.claude/CLAUDE.md`——复用 opencode 的 `merge_agents_md`（标记区块 + 临时文件原子 rename，无备份步骤——与 opencode 先例一致），目标文件名参数化。
- 本地清单（辅审 M4）：opencode 与 claudecode 管理面同装 `~/.budgetbuddy/`（**非逐字节一致**：`docs/MODEL_SELECTION.md` 按平台渲染、opencode 独有 `docs/setup-notes.md`），`write_local_manifest` mode `claudecode` 采用**合并写**——`files` 段（管理面，保留其他平台仍存在于磁盘的条目 + 写入/更新本平台条目）+ `platform_files` 段**按平台命名空间合并**（opencode 保持历史无前缀平铺格式、claudecode 用 `claudecode:` 前缀条目；仅写入/更新本平台段，保留其他平台条目）；`is_struct` 结构判定区分 claudecode 复数目录前缀（`agents/commands/skills`，区别于 opencode 单数）；升级差集清理与卸载仅作用于本平台段与共享管理面（卸载其一不破坏另一平台记录）；共装时跳过管理面差集清理（防误删他平台独有文件，陈旧文件由 uninstall 兜底）。
- 平台选择：交互菜单四选项（CodeBuddy / OpenCode / Claude Code / 全部）；非交互 `BUDGET_PLATFORM` 增值 `claudecode` 与 `all`（三平台）；`both` 语义保持「codebude+opencode」历史兼容，帮助文本标注推荐用 `all`。
- `budget` 包装器、`~/.local/bin` 落位、SHA256 校验、增量同步逻辑平台无关，复用。

### D5 运行时管理面（platform.sh / preset）

- `platform.sh` 探测序（同时命中时前者优先）：① 向上 `.codebuddy/setup.sh` → codebuddy:project；② `~/.codebuddy/setup.sh` → codebuddy:global；③ 向上 `.claude/agents/` 含本套件 agent（`_budget_has_suite_agents` 复用）→ claudecode:project；④ `~/.claude/agents/` → claudecode:global；⑤ 现有 opencode 两分支。`BUDGET_PLATFORM=claudecode` 显式分支同现有模式。
- `preset.sh`/`agent preset|custom|inherit` 的 frontmatter 读写：按 `BUDGET_PLATFORM_KIND` 感知目标键（claudecode 产物无 `model_role`/`permissions` 中立键，`model` 键名一致）。改动面明示（辅审 M2/M3/m5/m6）：`model_resolver.py`（`--platform` choices 四处硬编码需动态化 + resolve 的 claudecode 走 catalog_id 默认策略）、`notify.sh`（`_budget_locate_notify_py` 的 case 补 claudecode:project/global 两分支——hooks 降级 ≠ notify CLI 降级）、`quickstart.py`（Python 侧探测补 claudecode 两级 + 「双平台」文案三平台化）、`models.sh`（unconfirmed 读取位置迁移兼容 + 双平台计数文案与短标 map 补 claudecode）。
- hooks：claudecode 不注入（`routing.hook: ""`）；`init.sh`/`hooks.sh` 的注入调用按平台 kind 跳过（同 opencode 分支先例）。

### D6 文档与门禁

- `MODEL_SELECTION.template.md` 平台说明与预设表随 D1-3 数据驱动自动扩展（渲染管线不改）。
- CODEBUDDY.md / AGENTS.md 双入口说明扩展为三平台（Claude Code 会话读取 CLAUDE.md 合并产物）；README 架构图与安装章节增 claudecode 支路；两份入口文件同步更新纪律不变。
- `scan-brand.py`：验证扫描范围对 `dist/claudecode/` 自动覆盖（若 glob 为 `dist/**` 则零改动；若枚举双平台目录则扩展）。
- `build-release.sh`：验证 zip 打包自动包含 `dist/claudecode/`（manifest 驱动应零改动，验证之）。

## Risks / Trade-offs

- [Claude Code frontmatter 字段演进（新版本增删字段）] → 无法识别字段静默忽略而非报错；产物仅使用稳定字段（name/description/model/tools/permissionMode/maxTurns）；以官方 subagents 文档为版本基线。
- [CLAUDE.md 标记区块被用户手工破坏] → 备份 + 标记区块重建语义（同 AGENTS.md 合并先例）；uninstall 兜底。
- [Claude 系模型 ID 未经本机核对] → `platforms.claudecode.unconfirmed_ids` 标注 + 上线前清零纪律；`budget setup agent custom` 提供用户侧覆写逃生门。
- [任务工具名漂移（Task/Agent 历史上曾变更）] → `{{TASK_TOOL}}` 单点变量替换，漂移时改一个 DSL 值即可。
- [`both`/`all` 语义并存造成用户困惑] → 帮助文本与 README 明确 `all` 为推荐三平台值；`both` 仅历史兼容。
- [多平台共装 `~/.budgetbuddy/` 本地清单覆盖冲突] → `platform_files` 按平台命名空间合并写 + 卸载/升级仅作用于本平台段（D4，辅审 M4）。
- [preset 管理面对 camelCase 键的读写回归] → 实施任务中为 preset 切换增加 claudecode 专项测试用例（三平台产物 frontmatter 快照比对）。

## Migration Plan

1. 先落 D1 泛化（纯重构，双平台产物字节级不变——以现有 dist 清单 hash 校验回归）
2. 再加 claudecode.yaml + models 数据扩展 + install/lib 分支
3. 全量门禁：`build.py --check`、`scan-brand.py`、`unittest discover`；新增三平台快照测试
4. 发布：`build-release.sh` 产物含 dist/claudecode/，install.sh 向后兼容（现有双平台用户升级零感知，无 BREAKING）
5. 回滚：本变更为纯增量（新增目录/分支/数据段），revert 提交即回滚；对已安装 claudecode 用户 `budget setup uninstall` 清理

## Open Questions

- claude 系 catalog 条目中哪些 ID 未在本机 Claude Code 环境核对（决定 `unconfirmed_claudecode_ids` 初始清单）——实施任务 T-a 中盘点
- `~/.claude/CLAUDE.md` 全局合并与用户已有全局 CLAUDE.md 内容共存的实际表现（标记区块机制理论覆盖，实施时以真实环境验证）
