# Tasks: foundation — BudgetBuddy 全量首版（v0.1.0）

> 通用约束（每个任务都适用）：
> - **品牌合规 P0**：产出不得含 D §5 违禁词表中的任何词汇（大小写不敏感，含大写与前后缀变体；词表定义见 D §5，不在本文件复制字面量）。参照项目一律称「参照项目」，引用其组件/文件名时一律以 `*` 通配。
> - **构建门禁**：每任务完成后跑 `python3 scripts/build.py --check`，违禁词或结构错误一律不过。
> - **参照项目指针**：`REF:` 一律为相对路径 + 通配形式；基准路径由 Leader 派发任务时注入（含 2.1 涉及的「用户本机 opencode 迁移版 agent 集」样本说明，派发时另行提供），禁止写入任何产出。
> - **设计依据**：D = `openspec/changes/foundation/design.md`，P = `docs/plans/2026-10-16-budgetbuddy-architecture-design.md`（P §11 验收标准按 D §14 修正口径核验）。
> - **任务口径**：13 任务 / 24 执行单元（T1/T3/T9 各拆 3、T8 拆 2、T10 拆 4 + quickstart 单列），每执行单元 ≤2h。

## 1. 构建系统与门禁（先行）

- [x] 1.1 **T1a 构建系统核心**【cross_module, api_endpoint → coder-senior】
  - 创建 `scripts/build.py`：手写最小 YAML 子集解析器（D §12-A5，~150 行，语法清单含块式 list 项为 map）、DSL schema 校验（D §3.5）、core→dist 双平台转换（frontmatter 重写 D §3.1/3.2、变量替换 D §3.3、routing 落位 D §3.5）、manifest 生成（D §12-A7：按键排序、无时间戳）、原子构建流程（D §4：构建到 `dist/<platform>.new/` 临时目录、全部成功后原子替换、失败保持原样）、空 core / 数据未就位降级规则（D §4）。CLI：`--platform codebuddy|opencode`、`--check`、`--strict`。
  - 创建 `core/platform/codebuddy.yaml` 与 `core/platform/opencode.yaml`：按 D §3.5 字段表完整声明（含 opencode 的 extra_outputs 块式 list-of-map 形态）。
  - 创建空 core 骨架目录（agents/skills/commands/rules/models/personas/lib/docs/hooks）。
  - 创建 `tests/test_build.py`，固定用例清单：① 引号内冒号（值形如 `"/{group}:{name}"`）；② 值后行内注释；③ 空字符串 `""`；④ 块式 list 项为 map（extra_outputs 形态）；⑤ 锚点/多行字符串/YAML tag 报不支持错误；⑥ 两次构建 manifest diff 为空（按键排序 + 遍历顺序确定性）；⑦ 校验失败 dist 保持构建前原样（原子性）；⑧ 空 core 冒烟 exit 0（降级规则）；⑨ agents 存在但 models 缺失 → 产物无 model 字段并告警。
  - MODEL_SELECTION 渲染管线本任务仅在 build.py 预留挂接点（routing.docs 模板条目数据缺失时按 D §4 跳过），具体实现与真实验证在 2.9（T8a）。
  - 验收：`python3 scripts/build.py` exit 0 且双平台 .manifest.json 生成；schema 校验失败用例（缺 routing 键）正确报错；test_build.py 全部用例通过。
  - 依赖：无（首个任务）。

- [x] 1.2 **T1b 违禁词门禁**【api_endpoint, test_only → coder-standard】
  - 创建 `scripts/scan-brand.py`：按 D §5/D §12-A10 实现（扫描范围 core/ dist/ scripts/ install.sh README.md README_CN.md CHANGELOG.md；词表大小写不敏感；跳过自身；命中输出 文件:行号:摘要 exit 1；非文本文件跳过告警）。
  - 创建 `tests/test_scan_brand.py`：临时目录构造命中/干净/大小写变体/大写前缀变体/二进制文件样本，验证 exit code 与输出格式（违禁词样本仅在测试内构造，tests/ 在扫描范围外）。
  - 验收：门禁对当前仓库 exit 0（此时仓库尚无违禁内容）；对构造样本 exit 1 且输出定位准确。
  - 依赖：无（可与 1.1 并行）。

- [x] 1.3 **T1c release 打包与 VERSION**【config_edit → coder-lite】
  - 创建 `VERSION`（内容 `0.1.0`，提前创建以解除 build-release.sh 前向依赖）与 `scripts/build-release.sh`：`build.py --check` → 读取 `VERSION` → `zip -r budgetbuddy-<version>.zip dist/ VERSION` → 生成同名 `.sha256` 校验文件（D §10/A12；门禁失败不产 zip）。
  - 参照：REF:scripts/build-release.sh（结构思路，内容按本项目重写）。
  - 验收：check 失败注入时无 zip 产生；正常时 zip 名含 0.1.0 且 .sha256 生成。
  - 依赖：1.1、1.2。

## 2. 中立源内容（T2-T8，部分可并行）

- [x] 2.1 **T2 十个中立 agent**【copy_pattern, cross_module → coder-standard】
  - 创建 `core/agents/{architect,coder-lite,coder-standard,coder-senior,reviewer,reviewer-b,tester,recorder,director,goal-evaluator}.md`：按 D §3.1 frontmatter schema 与 §6 角色权限表（permissions 三态语义，含 `[]` 显式全禁止角色）；正文从参照项目双版本（REF:dist/agents/*.md 与用户本机 opencode 迁移版 agent 集——后者在参照根之外，路径与样本清单由 Leader 派发任务时另行提供；该实例仅 9 个 agent、无 goal-evaluator，goal-evaluator 只取参照项目 codebuddy 版改写）融合改写：保留职责/工作流程/输出规范语义，去品牌词（参照项目角色名与称呼一律不出现），平台差异用 D §3.3 模板变量（正文不硬编码 Agent/task 工具名）。
  - **persona 引用对齐（D §8.5）**：参照项目正文写死旧 reviewer 键名，本项目统一改写为 reviewer 键；10 个文件的 `roles.<name>` 引用须与 11 键集（leader + 十角色）全部可解析。
  - 验收：10 文件全部通过 build.py 构建期校验（name 一致/model_role 合法/tools 白名单/permissions 三态/正文非空）；双平台产物 frontmatter 符合 D §3.2 映射（人工核对 architect/reviewer/coder-lite 三例，另加 director 例验证 bash `"*": "deny"`）。
  - 依赖：1.1。

- [x] 2.2 **T3a 工作流主文档（SKILL + router）**【copy_pattern, cross_module → coder-senior】
  - 创建 `core/skills/budget-workflow/{SKILL.md,router.md}`：从 REF:dist/skills/*-workflow/ 对应文件迁移改写；SKILL.md 含 5 阶段总览、P0 三规则（D §3.4：leader-no-code / coder-guard / 流程强制）、Superpowers 集成、循环兜底 +「强制执行规则（P0）」内联章节（与 core/rules 对应文件语义一致，D §3.4）+ 通知机制总览（指向 D §9 N1-N11 节点表）；router.md 含任务分级路由（lite/standard/senior）与 Coder Guard 联动阈值；所有工作流系斜杠命令 → 模板变量化 budget 系命令、通知调用 → `budget notify`、消息前缀 → `[budget]`、guard 路径 → `{{GUARD_PATH}}`、persona 路径 → `.budget/` 与 `~/.budgetbuddy/`、状态脚本引用 → `$HOME/.budgetbuddy/lib/budget-state.py`（A4 单份）。
  - 验收：两文档对照参照项目能力清单（D §16.1 T3 行）无缺失；构建后双平台产物模板变量全部替换（无 `{{...}}` 残留）；P0 内联章节与 core/rules 侧一致性 diff 通过（2.8 完成后一并验证，D §3.4 判定规则）。
  - 依赖：1.1（内容可先行起草，构建验证需 1.1）。

- [x] 2.3 **T3b phases 阶段细则**【copy_pattern, docs_only → coder-senior】
  - 创建 `core/skills/budget-workflow/phases.md`：从 REF:dist/skills/*-workflow/phases.md 迁移改写（5 阶段入口/出口条件与细则、Phase 2 评审门、Phase 3 验证、3 轮驳回应急、Director 六类裁决、通知节点 **N1-N10** 嵌入与消息模板按 D §9 节点表逐条落位）。
  - 验收：5 阶段入口/出口条件齐全；通知节点 N1-N10 每个均有对应调用示例与消息模板（前缀 `[budget]`）。
  - 依赖：2.2（术语与变量约定随 SKILL/router）。

- [x] 2.4 **T3c goal 与 reference**【copy_pattern, docs_only → coder-standard】
  - 创建 `core/skills/budget-workflow/goal.md` 与 `core/skills/budget-workflow/reference.md`：goal.md 迁移 REF:dist/skills/*-workflow/goal.md（goal loop 规则、goal-evaluator 判定标准、循环超限终止、**N11 目标达成通知**）；reference.md 迁移参照速查文件（组件速查：agent 清单/命令/模型预设/personas/状态机）。
  - 验收：goal loop 与 N11 通知节点齐全（调用示例 + 消息模板）；reference 速查表组件名与本套件命名完全一致（无参照项目组件名）。
  - 依赖：2.2。

- [x] 2.5 **T4 budget-notify skill 与 hooks**【api_endpoint, cross_module → coder-standard】
  - 创建 `core/skills/budget-notify/{SKILL.md,notify.py,load-env.sh}` 与 `core/hooks/budget-notify-hook.py`：按 D §9 与 specs/notify 全部 Requirement（四渠道格式化、钉钉 HMAC-SHA256 签名、飞书卡片、双级降级读配置不合并、5s 超时、任一成功即停、静默失败、load-env 仅导出非敏感 BUDGET_NOTIFY_* 变量、hooks 三事件、stdin JSON 安全解析、注入前备份 + 原子写）；参照 REF:dist/skills/*-notify/ 与 REF:dist/hooks/*-notify-hook.py 的结构（实现按通用 webhook 重写，不保留内部通知渠道）。
  - 创建 `tests/test_notify.py`：四渠道格式化与签名固定向量单测、双级配置优先级、load-env 导出集与短路语义、事件开关、mock 发送不外呼。
  - 验收：单测全部通过；notify.py 在无配置环境 exit 0 静默；hook 对空 stdin exit 0；webhook/secret 不出现在环境变量、命令行参数与日志。
  - 依赖：1.1（可并行 2.1/2.2）。

- [x] 2.6 **T5 openspec 四 skill 迁移**【copy_pattern, docs_only → coder-lite】
  - 创建 `core/skills/openspec-{apply-change,archive-change,explore,propose}/SKILL.md`：从 REF:dist/skills/openspec-*/ 迁移，触发词改 budget/opsx 系命令，去品牌词与内部路径；功能语义对等（specs/entry-points 第三个 Requirement）。
  - 验收：四文件与参照项目逐能力对照无缺失；构建产物落位 `skills/openspec-*/`（双平台）。
  - 依赖：1.1。

- [x] 2.7 **T6 命令模板七件**【copy_pattern → coder-lite】
  - 创建 `core/commands/budget/{start,status,goal}.md` 与 `core/commands/opsx/{apply,archive,explore,propose}.md`：frontmatter 按 D §3.1 命令 schema（name 为「<组>: <标题>」显示名，组 ∈ {Budget, Opsx}）；参照 REF:dist/commands/*/*.md（工作流组为参照项目品牌命名组，opsx 组同名）；命令正文平台中立（引用 `{{TASK_TOOL}}`、skill 名 budget-workflow 等）；status 命令引用 budget-state.py 状态查询；产物命名按 routing（/budget:start、/opsx:apply；opencode /budget-start 等，D §3.5）。
  - 验收：双平台产物命令数 3+4；start 正文含「Leader 只编排不编码 + 必须指定 subagent_type」两条约束。
  - 依赖：1.1、2.2（引用 skill 名）。

- [x] 2.8 **T7 rules 十二条**【copy_pattern, docs_only → coder-standard】
  - 创建 `core/rules/`：3 条 P0（budget-leader-no-code、budget-coder-guard、budget-workflow-enforcement，参照 REF:dist/rules/ 对应 3 条，路径改 `.budget/`/`~/.budgetbuddy/`、命令改 budget 系）+ 8 条代码规范（cpp/css/go/java/python/sql/typescript/trpc，参照 REF:dist/rules/ 同名规范；trpc 条目按 D §15-Q5 中立化为通用服务调用规范）+ budget-rtk（保留 RTK 通用说明，去内部 hook 命令引用，改 budget hooks 路径）。
  - 验收：12 文件均通过构建；codebuddy 产物落 `rules/budget-*.mdc`，opencode 产物合并为 AGENTS.fragment.md（含 12 个二级标记区块，D §3.5）；P0 三条与 budget-workflow SKILL.md 内联章节按 D §3.4 可执行判定规则通过一致性 diff（构建无告警，或告警逐条说明）。
  - 依赖：1.1、2.2（P0 一致性）。

- [x] 2.9 **T8a 模型目录与 MODEL_SELECTION 渲染**【config_edit, cross_module → coder-standard】
  - 创建 `core/models/budget-models.json` + `core/models/budget-models.schema.json`：按 D §7 与 specs/model-presets（aliases/roles/models.paid+free/platforms.codebuddy+opencode 各三档预设）；codebuddy 预设沿用 REF:dist/*-models.json 的 ID 体系（去内部渠道注记），balanced 角色映射对齐参照项目；opencode 预设用 provider/model 格式（anthropic/openai/google/zhipu/deepseek/moonshotai 系），不确定 ID 逐一核对并在 _meta 标「待确认」（D §15-Q2）。
  - 实现 **MODEL_SELECTION 渲染管线**（D §4/A6；挂接点已在 T1a 预留）：`core/docs/MODEL_SELECTION.template.md` + budget-models.json 按平台生成 `dist/<platform>/docs/MODEL_SELECTION.md`（三个占位符 `{{models_table}}`/`{{preset_table}}`/`{{platform_note}}`，白名单独立于正文六变量）。
  - 创建 `core/docs/MODEL_SELECTION.template.md`。
  - 验收：`python3 -c json.load` 校验通过；schema 校验通过；构建后双平台产物含 budget-models.json 且 MODEL_SELECTION.md 渲染无残留占位符；agent 产物 model_role 烘焙生效（frontmatter 含 model 字段）。
  - 依赖：1.1、2.1（roles 与 agent model_role 对齐）。

- [x] 2.10 **T8b personas 五主题**【copy_pattern, docs_only → coder-standard】
  - 创建 `core/personas/personas.json`：5 主题（default/tech-legends/sanguo/shuihu/genshin），从 REF:dist/personas.json 迁移对应主题（剔除品牌主题）；**roles 键集 = leader + 十角色（共 11 键，D §8.5）**：保留 leader 键（各主题 greeting 称呼随主题创作）；reviewer 键按 D §8.5 改名（与 T2 正文引用对齐）；**goal-evaluator 为新增键，5 个主题均需新造角色名**。
  - 创建 `core/docs/PERSONAS.md`（persona 主题使用说明）。
  - 验收：各主题 11 键齐全；agent 正文 `roles.<name>` 引用全部可解析（无旧键名残留、无缺失键）；json 格式校验通过。
  - 依赖：1.1、2.1（persona 引用对齐）。

## 3. 管理面（T9-T10）

- [x] 3.1 **T9a setup 入口与 lib 基础层**【cross_module → coder-senior】
  - 创建 `core/setup.sh`（子命令分发骨架，D §8.1/A11 子命令全集）与 `core/lib/` 基础层 4 文件：colors.sh、utils.sh、platform.sh（运行时平台探测 D §8.3：codebuddy 项目级 → codebuddy 全局 → opencode（项目级优先）→ 显式报错并列出已检测位置）、shell.sh（参照 REF:dist/setup.sh 与 REF:dist/lib/ 同名文件结构重写；BUDGET_* 前缀；数据目录 `.budget/` 与 `~/.budgetbuddy/`）。
  - 创建 `tests/test_platform.py`：三分支探测单测（临时目录构造三种安装形态）+ 探测失败显式报错用例。
  - 验收：`core/setup.sh help` 与子命令分发骨架在临时目录冒烟通过（未知子命令友好报错）；test_platform.py 全分支通过。
  - 依赖：1.1、2.9（models 数据就位；各子命令实现由 3.2-3.8 陆续接入）。

- [x] 3.2 **T9b init 初始化流程**【cross_module → coder-senior】
  - 创建 `core/lib/init.sh`：setup init 子命令（参照 REF:dist/lib/init.sh 结构重写）：数据目录初始化（.budget/ / ~/.budgetbuddy/）、`init shell` 别名注入、.gitignore `# BudgetBuddy:begin/end` 标记区块幂等追加（D §8.4）；hooks 注入与 superpowers 启用的编排调用点写入 init.sh（模块在 3.7 落地后联调验证，T13 全流程复验）。
  - 验收：临时目录 init 演练：目录创建幂等、gitignore 区块幂等追加且区块外内容不变、重跑无重复副作用。
  - 依赖：3.1。

- [x] 3.3 **T9c update 与 uninstall**【cross_module → coder-senior】
  - 创建 `core/lib/update.sh` 与 `core/lib/uninstall.sh`：update 按 D §10/A9 约定发现版本（$BUDGET_REPO_URL/releases/latest + BUDGET_VERSION，重新下载 release zip 并强制 SHA256 校验）后重跑安装流程；uninstall 按本地 `<安装根>/.budget-manifest.json` 清单删除（离线可用，清单外一律保留）并清理 hooks/AGENTS.md 标记区块；参照 REF:dist/lib/ 同名文件结构重写。
  - 验收：临时目录构造本地清单模拟卸载（仅删清单内、清单外保留）；update 版本定位与校验逻辑以 mock 单测验证。
  - 依赖：3.1。

- [x] 3.4 **T10a 模型与预设**【cross_module → coder-senior】
  - 创建 `core/lib/{models.sh,preset.sh,model_resolver.py,rtk.sh}`（4 文件）：模型目录加载/列出、预设切换与 agent 产物重写（`agent preset|custom|inherit`，按 platform.sh 探测定位 agent 目录）、角色→模型 ID 解析、RTK 工具适配（保留通用说明，去内部 hook 引用）；参照 REF:dist/lib/ 同名文件结构重写。
  - 创建 `tests/test_preset.py`：预设解析、别名解析、agent frontmatter model 重写单测。
  - 验收：单测通过；临时安装中 `budget setup show`（输出 agent 清单与模型）与 `agent preset|custom|inherit` 冒烟通过。
  - 依赖：3.1、2.9（models 数据）、2.1（agent 产物就位）。

- [x] 3.5 **T10b 状态机与 Coder Guard**【cross_module → coder-senior】
  - 创建 `core/lib/{budget-state.py,guard.sh}`（2 文件）：单份状态机（A4：工作流状态读写/更新、openspec change 与任务进度）；Coder Guard 查询/追加/汇总（固定路径 `$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json`，最近 5 次窗口、失败 ≥2 降级阈值语义对齐 router 定义）；参照 REF:dist/lib/*_state.py 与同名 guard 文件结构重写。
  - 创建 `tests/test_state.py`（状态机流转与幂等）与 `tests/test_guard.py`（记录追加、窗口滚动、降级判定，含边界：最近 5 次恰 2 次失败）。
  - 验收：单测全部通过。
  - 依赖：3.1。

- [x] 3.6 **T10c persona、校验与展示**【cross_module → coder-senior】
  - 创建 `core/lib/{persona.sh,persona_expand.py,validate.sh,display.py,interactive.sh,run_summary.py,banner.py}`（7 文件）：persona 主题管理与展开（11 键集对齐 personas.json）、安装完整性校验（manifest 比对）、展示/表格输出、交互式向导、运行汇总、启动横幅。
  - 验收：临时安装中 `budget setup persona list|set` 与 `validate` 冒烟通过；persona set 写入的 roles 映射覆盖 11 键。
  - 依赖：3.1、2.10（personas 数据）。

- [x] 3.7 **T10d 通知与 hooks 注入**【cross_module, security_related → coder-senior】
  - 创建 `core/lib/{notify.sh,hooks.sh,hooks_inject.py}`（3 文件）：notify.sh 转发 core/skills/budget-notify/notify.py；hooks.sh 编排 CodeBuddy settings.json 注入（Notification/PreToolUse/SubagentStop 三事件）与 **superpowers 插件启用**（检测 enabledPlugins，未启用注入并提示重启或手动执行，D §9/A11）；hooks_inject.py 实现 settings.json 读改写（注入幂等、注入前备份、临时文件 + 原子 rename 写入）；全局/项目定位按 platform.sh 探测（BUDGET_GLOBAL 语义）。
  - 验收：临时目录模拟 settings.json 注入：三事件 + superpowers 条目生效、重跑幂等无重复注入、备份文件生成、文件其余字段不变。
  - 依赖：3.1、2.5（notify 引擎就位）。

- [x] 3.8 **T10e quickstart 快速上手**【docs_only, api_endpoint → coder-standard】
  - 创建 `core/lib/quickstart.py`：快速上手交互引导（参照 REF:dist/lib/ 同名文件结构重写；独立大文件单列任务）；`budget setup quickstart`（别名 tour/wizard）入口已在 setup.sh 分发表声明。
  - 验收：临时安装中 `budget setup quickstart` 启动引导并走通主流程、无外部调用。
  - 依赖：3.1、3.6（交互/展示模块复用）。

## 4. 安装器与文档（T11-T12）

- [x] 4.1 **T11 install.sh 双平台安装器**【cross_module, security_related → coder-senior】
  - 创建 `install.sh`：按 D §10 与 specs/installer 全部 Requirement（交互 /dev/tty + --global + BUDGET_PLATFORM/BUDGET_GLOBAL 非交互、双平台落点、**版本定位 $BUDGET_REPO_URL/releases/latest + BUDGET_VERSION**、**下载 zip 强制 SHA256 校验失败即中止**、AGENTS.md 标记区块幂等合并、manifest 增量同步、**安装清单持久化 <安装根>/.budget-manifest.json（升级差集清理、卸载按本地清单）**、清单外保留、依赖检查（含 sha256 工具）、Windows Git Bash/WSL 提示、BUDGET_REPO_URL 可配置占位、hooks 注入 + superpowers 插件启用）。参照 REF:install.sh 的整体结构与 SHA256 校验思路（下载源与内部镜像逻辑全部重写）。
  - 创建 `tests/test_installer.py`：AGENTS.md 幂等合并、manifest 增量同步（哈希跳过/覆盖）、升级差集清理、卸载按本地清单单测（临时目录模拟）。
  - 验收：单测通过；临时目录双平台安装演练（项目级+全局级×2 平台）；幂等重装 AGENTS.md 无重复；manifest 外自定义文件保留；安装中断重跑恢复。
  - 依赖：1.1（manifest 格式）、2.1-2.10 与 3.1-3.8 全部完成（dist 全量就绪，3.8 为末单元）。

- [x] 4.2 **T12 仓库文档**【docs_only → coder-standard】
  - 创建 README.md、README_CN.md（双语对等，内容清单见 specs/repo-docs，含 curl|bash 信任提示）、CHANGELOG.md（v0.1.0 首条）、LICENSE（MIT）、CODEBUDDY.md、AGENTS.md（自举说明双入口，内容一致）、`core/docs/architecture.md`（Mermaid 架构图）、`core/docs/opencode-setup-notes.md`（opencode 安装说明与 hooks 插件扩展点）。
  - 验收：门禁覆盖 README/README_CN/CHANGELOG 通过；Mermaid 语法校验；CODEBUDDY.md 与 AGENTS.md 内容一致。
  - 依赖：4.1（功能面与安装器定稿）。

## 5. 全量验收（T13）

- [x] 5.1 **T13 全量构建 + 双平台安装演练 + 门禁**【test_only → coder-standard】
  - 依次执行并记录：`python3 scripts/build.py --check`（干净，并以 `--strict` 复跑一次）；两次构建幂等比对（manifest diff 为空）；临时目录 codebuddy 项目级安装（agents×10 / commands×7（budget 3 + opsx 4）/ skills×6 / rules×12 / hooks / lib / setup.sh / docs，`budget setup show` + `validate` 冒烟、superpowers 插件启用与 hooks 注入验证）；opencode 全局安装（agent/command/skill + AGENTS.md 合并 + ~/.budgetbuddy/ 管理面）；`tests/` 全量单测；notify 四渠道 mock 演练（含 N11 目标达成消息模板）；**全部 shell 脚本（core/lib/*.sh、core/setup.sh、install.sh、scripts/build-release.sh）`bash -n` 语法冒烟**；**通知点 N1-N11 审计**（人工审计项：每节点均有调用示例与模板）；**P0 三条规则人工逐条抽查**（机器 diff 按 D §3.4 规则 + 人工语义兜底）；对照 P §11 验收标准 7 条**按 D §14 修正口径核验（commands×7、rules×12、门禁扫描范围按 D §5、通知渠道按四渠道）**并在 openspec 变更下写验收报告。
  - 行为类 Scenario（router 分级评估、DSL 单一消费者、README 宣传口径）为人工审计项，不作为自动化用例（specs 已标注）。
  - 验收：P §11 的 7 条验收标准（按 D 修正口径）全部通过。
  - 依赖：全部任务。

## 依赖图

```
高层主线：1.1 → 内容（2.x）→ 管理面（3.x）→ 4.1 → 4.2 → 5.1

1.1（T1a）→ {2.1, 2.2, 2.5, 2.6}（内容任务可并行）
1.1 + 1.2 → 1.3（T1c）
2.1（T2）→ {2.9（T8a）, 2.10（T8b）}
2.2（T3a）→ {2.3（T3b）, 2.4（T3c）, 2.7（T6）, 2.8（T7）}
2.9（T8a）→ 3.1（T9a）
3.1（T9a）→ {3.2（T9b）, 3.3（T9c）, 3.4（T10a）, 3.5（T10b）}
2.10（T8b）+ 3.1 → 3.6（T10c）；3.6 → 3.8（T10e）
2.5（T4）+ 3.1 → 3.7（T10d）
{2.x 全部, 3.x 全部} + 1.1（manifest 格式）→ 4.1（T11）→ 4.2（T12）→ 5.1（T13）
```
