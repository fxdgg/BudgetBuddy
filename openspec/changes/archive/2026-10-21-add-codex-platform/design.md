# 设计：新增 Codex 平台支持

> 承接 proposal 与调研结论（参照项目（Codex 形态）实证 + 官方机制核实）。核心策略：**机制上复用现有 DSL/fragment/安装器全套，语义上以「Leader 组装 spawn prompt」替代「结构化 Task 工具」**。

## Context

Codex 关键机制（官方核实）：`spawn_agent`/`wait_agent`/`close_agent` 三工具（需 `config.toml [features] multi_agent = true`）；skills 原生加载（`~/.codex/skills/` 与 `.codex/skills/`，SKILL.md frontmatter name/description）；AGENTS.md 指令链（项目根 + ~/.codex/，**默认 32KiB 截断上限** `project_doc_max_bytes`）；custom prompts 已弃用。本机 codex-cli 0.163.0 可验证。

关键约束推论：① 12 条规则全文（约 40KiB+）不能进 AGENTS.md（会被截断）→ 轻量索引 + skill 内按需读取（参照项目同款决策）；② 无 agent 定义文件机制 → 角色素材平移 + 派工契约文档；③ spawn 靠显式调用（无自动委派）→ 契约必须写明调用模板与权限边界。

## Goals / Non-Goals

**Goals:** dist/codex/ 完整产物（skill 形态 + 轻量 AGENTS 索引 + 管理面）；安装/卸载/探测/管理面闭环；本机 codex 端到端派工验证
**Non-Goals:** TOML 子代理定义、插件 marketplace、hooks、风险分级自动路由

## Decisions

### D1 产物形态（codex.yaml）

```yaml
platform: codex
output: dist/codex
routing:
  agent:   "skills/budget-workflow/agents/{name}.md"     # 角色素材平移（非子代理定义）
  command: "skills/budget-workflow/commands/{group}-{name}.md"  # 命令并入 skill 参考文档
  skill:   "skills/{skill}/"
  rule:    "AGENTS.fragment.md"                          # 轻量索引（extra_outputs rules_index）
  hook:    ""                                            # Codex hooks 实验态，不分发
  models:  "budget-models.json"
  personas: "personas.json"
  lib:     "lib/"
  setup:   "setup.sh"
  docs:
    MODEL_SELECTION.template.md: "docs/MODEL_SELECTION.md"
    PERSONAS.md: "docs/PERSONAS.md"
    architecture.md: "docs/architecture.md"
    codex-runtime.md: "skills/budget-workflow/codex-runtime.md"   # 派工契约（静态文件经 docs 分发）
    opencode-setup-notes.md: null
agent_frontmatter:
  emit: { name: "{name}", description: "{description}" }  # 仅元数据（skill 素材形态）
  drop: [model_role, tools, permissions, max_turns]        # 无 model 烘焙（spawn 时查表）
command_frontmatter:
  emit: [description]
  drop: [name, argument-hint]
command:
  invoke: "/budget-start（触发 budget-workflow skill 的自然语言指令）"
body_variables:
  TASK_TOOL: "spawn_agent"
  SKILL_NS: ""
  AGENT_DIR: ".codex/skills/budget-workflow/agents/（项目级；全局 ~/.codex/skills/…）"
  GUARD_PATH: "$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json"
  RULES_DIR: "skills/budget-workflow/rules/（按需读取）与 AGENTS.md 轻量索引"
  PROJECT_DOC: "启动时读取项目根 AGENTS.md（BudgetBuddy 轻量区块）"
extra_outputs:
  - kind: rules_index                                    # 新 kind：轻量索引
    source: "rules/**"
    dest: "AGENTS.fragment.md"
    markers: ["<!-- BudgetBuddy:begin -->", "<!-- BudgetBuddy:end -->"]
```

- **agent emit 仅 name/description**：素材文档元数据（与 SKILL.md frontmatter 同构）；模型不烘焙——Codex 端模型选择发生在 spawn 调用参数（Leader 查 budget-models.json codex 预设），与结构化 Task 平台的「frontmatter 烘焙」路径不同。备选被否：emit 保留 model 键误导素材文档读者。
- **commands 并入 skill**：Codex prompts 已弃用；命令正文（入口指令）平移为 skill 内参考文档，SKILL.md 触发词涵盖自然语言入口（「budget:start」「开始 budget 工作流」等）。

### D2 rules_index 新 kind（build.py）

`extra_outputs` 新 kind `rules_index`：从 `source`（rules/**）文件名生成轻量 fragment——外层 markers + 标题 + 「按需读取」指引段 + 规则清单（`- budget-<name> → <skill 内相对路径>`，一行一条 + description 一句话）。**全文不进 fragment**（32KiB 约束）。校验：dest 与 routing.rule 一致性（同 agents_fragment 先例）；kind 枚举扩展 + schema 对齐。实现约 40 行（复用 `_iter_files`/`replace_variables`/`merge_rules_fragment` 的骨架，内容生成改为索引）。

**两项必须联动**（双审 B-5/辅 B-2）：
- **`_build_rules` 抑制扩展**：现 `_has_agents_fragment`（仅 agents_fragment kind 时跳过逐文件落位）必须扩展为「fragment 类 kind（agents_fragment | rules_index）均抑制」——否则 codex 的 12 条规则全文会逐个写入同一 `AGENTS.fragment.md` 路径相互覆盖，正确性押在管线副作用顺序上。任务 1.1 含此改造 + 三平台回归断言。
- **routing.docs 全平台声明**：新增 `core/docs/codex-runtime.md` 后，codebuddy/claudecode/opencode 三份 YAML 必须同步加 `codex-runtime.md: null`（`_build_docs` 要求全部源文件在全部平台声明，否则 BuildError）——任务 1.2 同批落地。

### D3 规则双通道落位（最终决策）

rules 全文经 rules_index kind 的 `copy_dest`（`skills/budget-workflow/rules/`）在构建期从 core/rules/ 单真值源复制；AGENTS.fragment.md 仅承载轻量索引。routing.rule = fragment dest（§3.5 一致性校验）。索引内路径写 skill 相对路径并注明项目级/全局两种安装形态的读取根（全局安装时 `.codex/skills/...` 换 `~/.codex/skills/...`）。

### D4 install.sh install_codex

- 落点：项目 `.codex/skills/budget-workflow/` 或全局 `~/.codex/skills/budget-workflow/`；管理面 `~/.budgetbuddy/`
- AGENTS.md 轻量区块合并：项目根 / `~/.codex/AGENTS.md`（复用 `merge_agents_md`，目标参数化；~/.codex 不存在时创建目录）；**异形态区块告警**：合并前检测既有区块为 opencode 全文形态（区块行数 > 阈值，如 100 行）时输出告警「检测到 OpenCode 全文区块，同项目混装两形态将相互替换」——轻量机制，防静默覆盖
- **config.toml 注入**：`~/.codex/config.toml` 或项目 `.codex/config.toml`——`[features]` 段 `multi_agent = true` 幂等注入（文本级四态：段头**行首精确匹配**（防 `[features.xxx]` 子串误判）含 `multi_agent = true`（容忍 `=` 两侧空格差异）→ 跳过；段含 `multi_agent = false`（用户显式关闭）→ **尊重用户配置，仅告警提示 spawn 工具不可用**；段存在缺键 → 段内追加；无段 → 文末追加段；原子写 + 注入前备份 `.bak-budget`；用户其他配置零触碰）。lib 新增 `config_codex.sh` 承载。卸载反向：段内仅删本键，段空则删段。
- 本地清单：mode `codex`（`codex:` 前缀 platform_files 段，结构同 claudecode 合并写）；结构前缀 `skills/`
- 卸载：AGENTS.md 区块清理 + config.toml multi_agent 键清理（`[features]` 段内仅删本键，段空则删段）+ skill 目录删除 + 共装 guard

### D5 管理面兼容（platform.sh / preset / 其他）

- platform.sh 探测：⑥ 向上 `.codex/skills/budget-workflow/` 存在 → codex:project；⑦ `~/.codex/skills/budget-workflow/` → codex:global；探测特征校验 `SKILL.md` 套件签名（目录名限定 + SKILL.md 存在双条件，防同名目录误判）；`BUDGET_PLATFORM=codex` 显式分支；探测序 codebuddy > claudecode > **codex** > opencode
- preset 降级语义：codex 形态 `agent preset/custom/inherit` → 提示「codex 平台模型档位由 Leader spawn 时按 budget-models.json 查询，无 frontmatter 可切换；档位查询用 `budget setup models` / `budget setup show`」；`show` 显示三档映射表
- notify/quickstart/models/uninstall/validate：codex 形态分支（同 claudecode 模式平移——notify 落 `.codex/skills/budget-notify/`、quickstart 文案四平台、validate 校验 skill 结构 + AGENTS 区块 + config multi_agent）
- guard：路径不变（~/.budgetbuddy 共享）

### D6 派工契约（core/docs/codex-runtime.md，经 docs 分发进 skill）

原创撰写（参照项目 MIT 思路、不抄文本；品牌词零出现——撰写后经 scan-brand 自检）：spawn_agent 调用模板（message=角色+唯一目标+可信输入+读写范围+验证命令+结构化输出、model=查表值、fork_context=false）→ wait_agent(targets, timeout) → close_agent；prompt 组装七要素（职责/目标/输入/权限边界/验证/输出格式/禁止事项）；三档模型查表指引（budget-models.json platforms.codex presets balanced 默认，经济/质量档由任务标签路由——与 router.md 既有分级派工语义对齐：coder-lite→economic、coder-standard→balanced、coder-senior→quality 对应 luna/terra/sol）；max_depth=1 与 max_threads=6 约束声明；并行规则（写入范围不相交才并行）。

**与既有 skill 正文的语义衔接**（辅 B-3）：SKILL.md 规则 1 与 goal.md 的 `{{TASK_TOOL}}(subagent_type, prompt, ...)` 调用格式块在 Codex 端语义错位（spawn_agent 无 subagent_type、无同步阻塞）。契约文档开头显式声明「**本文件为 Codex 平台的派工规范，优先级高于 SKILL.md/goal.md 中的 Task 调用格式块**：Codex 端以 spawn_agent(message, model)+wait_agent 组装等价能力」；并在 SKILL.md 规则 1 调用格式块处追加一行平台注记（「Codex 平台的调用形态见 budget-workflow/codex-runtime.md」——注记行经 skill 正文修订进入中立源，对其他平台无影响）。

### D7 models 数据

`platforms.codex.presets`：三档 × 10 角色统一档内模型（economic→gpt-5.6-luna、balanced→gpt-5.6-terra、quality→gpt-5.6-sol，用户指定）；catalog `models.paid.gpt` 组新增三别名条目（platform 仅 ["codex"]，note 注明「部署别名：需在部署环境将别名映射到实际模型」）；`platforms.codex.unconfirmed_ids` = 三别名（本机 codex 无该别名映射可核对，如实标注；**别名类不适用上线前清零纪律**——部署别名无法集中核对，永久标注直到部署环境映射就绪，note 声明该偏离）；note 说明三档定位与映射前提。模型不可用时逃生门：编辑 budget-models.json `platforms.codex.presets`（`budget setup models` 指引）或 spawn 时显式传 model——**非** `budget setup agent custom`（codex 形态该子命令降级）。

## Risks / Trade-offs

- [spawn 编排可靠性弱于结构化 Task 工具] → 契约模板强约束 + 本机端到端验证（派发 coder-lite 实测）+ 失败时用户可 claudecode/codebuddy 平台兜底
- [config.toml 文本级注入的 TOML 语法风险] → 仅在 `[features]` 段存在性明确时操作；注入前备份 + 原子写 + 注入后 codex CLI 冒烟（`codex --help` 正常）
- [AGENTS.md 32KiB 截断] → 轻量索引实测 < 1KiB；全量规则走 skill 按需读取
- [别名模型不可核对] → unconfirmed 永久标注（部署别名偏离声明）+ 逃生门为编辑 budget-models.json platforms.codex 或 spawn 显式传 model + note 映射说明
- [routing.rule 与 skill 全文副本的机制复杂度] → rules_index kind 单次遍历双输出，构建期单真值源，避免 core/ 双副本
- [回归断言基线] → models.json 增 codex 平台段必然传导 MODEL_SELECTION.md/预算表渲染变化——四平台回归断言采用**预期变化白名单**（dist/{codebuddy,opencode,claudecode} 仅 budget-models.json、MODEL_SELECTION.md 与 SKILL.md（Codex 注记行传导）允许变化），而非逐字节一致

## Migration Plan

1. build.py rules_index kind（纯增量，双平台/三平台回归不变）→ codex.yaml + models 数据 + codex-runtime.md
2. install/uninstall/config.toml 注入 → 管理面兼容
3. 本机端到端：install_codex → config multi_agent 生效 → `codex exec`/交互派发 coder-lite（spawn_agent 实测）→ AGENTS.md 区块/索引核验
4. 门禁三命令 + 测试扩展 → 归档（版本 0.3.0 minor）

## Open Questions

- codex CLI 0.163.0 的 spawn_agent 工具在本机订阅/鉴权下的实际可用性（端到端验证时确认；不可用则文档明确前置条件）
- Notification 类噪音（不适用——Codex 无 hooks，无此项）
