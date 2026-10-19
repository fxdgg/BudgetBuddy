# Reviewer-B 辅审报告：openspec 变更 `foundation`（v0.1.0 全量首版）

- 审查人：Reviewer-B（辅审，视角：技术合理性 / 需求完整性 / 安全性 / 稳定性）
- 审查对象：`openspec/changes/foundation/{proposal.md, design.md, specs/*, tasks.md}`
- 对照基准：参照项目发行目录（dist/）、已确认架构设计（docs/plans/2026-10-16-*.md）
- 审查方式：逐文件通读 + 与参照项目逐组件比对 + 交叉一致性核对

## 结论：【驳回】—— 5 个 P1 阻塞问题 + 15 个 P2 重要问题

方案整体架构方向正确（单一源+构建转换、manifest 幂等、三层 P0 落位、A1-A10 调整点均有依据），任务拆分与依赖图合理。但存在规范内部硬矛盾（权限空列表）、功能对等实际缺口（通知点 N11、personas 角色集、superpowers 插件启用）、品牌合规自违反（tasks.md 写入参照项目根路径）等阻塞问题，必须修正后方可进入实现。

---

## 一、P1 阻塞问题（5 条）

### P1-1 权限空列表：§3.1 校验规则与 §6 角色表直接矛盾
- 位置：design.md §3.1（构建期校验④）vs design.md §6 角色表 vs specs/neutral-source-format/spec.md「permissions 值形态非法」Scenario
- 问题：§3.1 规定 permissions 各键值只能为 `["*"]` 或**非空**列表；spec Scenario 明确「空列表 → build 失败」。但 §6 表中 reviewer/reviewer-b/tester/recorder/director/goal-evaluator 的 edit_allow 均为 `[]`（只读），director/goal-evaluator 的 bash_allow 也为 `[]`（禁止），且 §6 表下注释明确认可 `edit_allow: []` 为合法输入。按 §3.1 字面，6 个 agent 无法通过构建——实现自相矛盾。
- 建议：§3.1 合法形态改为「`["*"]` / 非空条目列表 / `[]`（=显式全禁止）」三态，specs/neutral-source-format 对应 Scenario 同步修改（仅「混合形态」与「非列表」判非法）。

### P1-2 bash_allow=[] 的 OpenCode 映射缺失，禁止语义退化为「询问」
- 位置：design.md §3.2 vs specs/neutral-source-format/spec.md「权限语义双平台映射」Requirement
- 问题：§3.2 仅定义两种 bash 映射（受限：先 `"*": "ask"` 再逐模式 allow；缺省：`"*": "allow"`）。bash_allow=`[]`（director/goal-evaluator 禁 bash）落入「受限」分支会得到 `{"*": "ask"}`——询问后可执行，与「禁止」语义相反。spec 的四个 Scenario 也未覆盖 bash_allow=[]。
- 建议：§3.2 与 spec 补充第三种映射：bash_allow=`[]` → `"*": "deny"`；并补 Scenario「禁 bash agent（director）在 OpenCode 产物 permission.bash 仅含 "*": "deny"」。

### P1-3 通知点实际为 N1-N11，N11（Goal 达成）被遗漏
- 位置：design.md §9「通知点 N1-N10」、specs/notify/spec.md「通知点 N1-N10 嵌入工作流」、proposal.md（notify capability 描述）、tasks.md 2.2（T3）
- 问题：参照项目工作流文档实际通知点编号到 N11（N11-markdown = Goal Loop 达成通知，见参照项目 dist/skills/*-workflow/goal.md 第 622 行；N10 = 全流程完成，phases.md 第 433 行）。design/spec 均写 N1-N10 且声称「保留参照项目**全部**节点」——「全部」与 N1-N10 自相矛盾，Goal 达成通知将丢失，违背已定决策③全量功能对等。另：参照项目通知分 voice/markdown 两种形式，本项目统一 webhook markdown（决策④的自然结果），但该形式降级未声明。
- 建议：design §9 / specs/notify / tasks T3 全部改为 N1-N11，并在 design 中列全 11 个节点定义表（编号、触发条件、消息模板要点）；注明 voice 形式统一降级为 markdown。

### P1-4 personas 角色集合矛盾：删除 leader 将破坏 greeting 称呼机制
- 位置：design.md §8.5 vs design.md §6 vs specs/setup-cli/spec.md「personas 五主题」Requirement
- 问题：参照项目 personas.json 的 roles 为 leader + 9 个 subagent（含 reviewer-a、无 goal-evaluator）；design §8.5 与 spec 要求「角色键对齐 §6 十角色」= 10 个 subagent（无 leader、reviewer 而非 reviewer-a、含 goal-evaluator）。两个「10 角色」集合不同。严格执行将：① 删除 leader 角色——参照项目 phases.md Step 0 与全部 agent 正文依赖 roles.leader + greeting 实现主会话称呼与角色化调度，删除后该核心机制失效；② goal-evaluator 无参照角色名，5 个主题均需新造（T8 未提此工作量）；③ reviewer-a→reviewer 改名需同步 T2 全部 agent 正文的 persona 引用（参照项目 agent 正文写死「roles.reviewer-a」）。
- 建议：明确 personas roles 键集为 leader + §6 十角色（共 11 键）；design §8.5、specs/setup-cli、tasks T2/T8 同步说明改名（reviewer-a→reviewer）与新增（goal-evaluator 角色名创作）的系统性影响。

### P1-5 tasks.md 写入参照项目根路径，违反品牌合规 P0 约束
- 位置：tasks.md 通用约束第 3 条（第 6 行）
- 问题：该行以明文写出参照项目根目录绝对路径（含内部域名与项目名，均属违禁词表），而 design.md 头部明确「参照项目根目录绝对路径不得写入任何仓库文件，根路径由 Leader 派发任务时注入」，specs/brand-compliance「全部 openspec 与设计产物合规」Requirement 也禁止出现参照项目根路径。tasks.md 本身是提交进 git 的仓库文件，直接违规。
- 建议：删除该行，改为「REF: 指针的基准路径由 Leader 派发任务时注入，禁止写入任何产出」。

---

## 二、P2 重要问题（15 条）

### P2-1 superpowers 插件启用环节整体遗漏
- 位置：design.md §9（hooks 仅三事件）、§10；specs/notify「CodeBuddy hooks 三事件通知」；tasks.md 3.2（T10）
- 问题：参照项目 init.sh/hooks.sh/hooks_inject.py 将 superpowers 插件写入 settings.json 的 enabledPlugins 作为安装初始化核心步骤（含检测/注入/移除/提示重启）。本项目 §3.5 的 SKILL_NS="superpowers:"（skill 引用带该前缀）依赖此插件启用；design/spec/tasks 均未提。新用户安装后 superpowers: 前缀的 skill 引用可能失效。
- 建议：design §9/§10 与 specs（notify 或 setup-cli）增加「superpowers 插件启用」Requirement（hooks_inject 注入或安装完成后指引），T10 任务说明同步。

### P2-2 brand-compliance spec 的 docs/plans 审计 Scenario 不可满足
- 位置：specs/brand-compliance/spec.md「全部 openspec 与设计产物合规」Requirement 的 Scenario vs design.md §5
- 问题：spec Scenario 要求审计 docs/plans/** 时「硬性词表词汇零出现」，但 docs/plans/ 已确认设计文档含大量品牌词（组件对等清单必须引用参照项目组件名），且该文档属不可重开的已确认输入；design §5 又明确 docs/ 不在扫描范围。两处直接矛盾，验收无法同时满足。
- 建议：spec Scenario 范围收窄为「本变更新增产物（proposal/design/specs/tasks）」，docs/plans/ 已确认文档豁免（design §5 已给出豁免理由）。

### P2-3 违禁词表定义载体豁免不完整
- 位置：design.md §12-A10 vs design.md §5 词表行 vs specs/brand-compliance/spec.md 词表行
- 问题：A10 仅豁免 scan-brand.py 自身；design §5 与 brand-compliance spec 的词表定义行以字面量包含违禁词，而 spec 第三个 Requirement 要求 proposal/design/specs/tasks「零品牌词」——按字面 design 与 spec 自身即违规。
- 建议：A10 豁免范围扩展为「违禁词表定义载体」（scan-brand.py + design §5 词表行 + brand-compliance spec 词表行），并在 spec 中明确。

### P2-4 tasks.md 的 REF: 指针未按约定通配品牌词
- 位置：tasks.md 2.2（T3）、2.3（T4）、2.5（T6）、2.7（T8）等多处
- 问题：多处 REF: 指针直接引用参照项目品牌文件名（如 REF:dist/skills/<品牌>-workflow/、REF:dist/<品牌>-models.json、REF:dist/commands/<品牌>/*.md、REF:dist/hooks/<品牌>-notify-hook.py），违反 design 头部「品牌词以 * 通配」约定。
- 建议：全部改为通配形式（REF:dist/skills/*-workflow/、REF:dist/*-models.json 等）。

### P2-5 design §9「双级合并读配置」与 specs/notify「不合并」矛盾
- 位置：design.md §9 vs specs/notify/spec.md「notify.json 配置与双级读取」Scenario
- 问题：design 写「双级**合并**读配置」，spec 写「仅项目级生效，全局配置**不被读取合并**」。参照项目实际行为为降级 fallback（项目级存在则用项目级，否则降级全局），与 spec 一致、与 design 措辞冲突。
- 建议：design §9 改为「双级降级读取（项目级存在即生效，否则用全局级；不合并）」。

### P2-6 load-env Requirement 字段与 notify.json schema 脱节
- 位置：specs/notify/spec.md「load-env.sh 环境导出」Requirement vs design.md §9 schema
- 问题：spec 要求导出「token/sendto 等发送所需字段」——token/sendto 是参照项目内部通知的字段概念，本项目 notify.json schema（enabled/channels/events）中不存在顶层 token/sendTo；且 notify.py 直接读配置文件时，BUDGET_NOTIFY_* 环境变量的角色（覆盖/补充/仅遗留兼容）未定义，load-env.sh 的存在意义模糊。
- 建议：重写该 Requirement：明确导出字段集合（如 BUDGET_NOTIFY_ENABLED / 渠道 webhook 与 secret 的引用方式）及其与 notify.py 文件读取的优先级；或声明环境变量仅为兼容旧用法。

### P2-7 install.sh 下载完整性校验缺失（供应链安全）
- 位置：design.md §10、specs/installer/spec.md（无对应 Requirement）
- 问题：参照项目安装器下载产物后执行 SHA256 校验；本项目 A9 移除 latest.json 后，design §10 与 specs/installer 均未定义下载 zip 的完整性校验机制。curl|bash + 无校验下载构成供应链安全缺口。
- 建议：specs/installer 增加「下载包完整性校验」Requirement（如 release 附带 .sha256 文件、install.sh 下载后强制校验、失败即中止），design §10 同步。

### P2-8 已安装清单持久化机制缺失（升级清理与卸载完整性）
- 位置：design.md §10「卸载仅删清单内文件」、specs/installer「manifest 增量同步」Requirement
- 问题：manifest 是构建产物清单，非安装侧记录。未定义安装清单的持久化位置，导致升级时旧版文件无法清理、卸载漏删旧版本文件。
- 建议：定义安装时持久化已装清单（如 <安装目录>/.budget-manifest.json）；升级按「本地旧清单 − 新 manifest」差集清理；卸载按本地清单删除；specs/installer 补两个 Scenario。

### P2-9 命令 frontmatter 中立 schema 与转换规则缺失
- 位置：design.md §3.1（仅 agent schema）、§3.5（DSL 无 command frontmatter 字段）
- 问题：core/commands/*.md 的中立 frontmatter 格式、双平台转换规则均未定义；品牌词命令名必须改名但改名规则缺失。
- 建议：§3.1 扩展命令 schema（name/description/argument-hint 中立格式与品牌无关命名规则），§3.5 DSL 增加 command_frontmatter 映射或 build.py 明确转换规则。

### P2-10 setup 子命令缺口：reinstall / quickstart 入口
- 位置：design.md §8.1 vs 参照项目 setup.sh 实际子命令集 vs design.md §8.2
- 问题：参照项目实际子命令还含 reinstall、quickstart|tour|wizard、guard、init shell。design §8.1 未纳入 reinstall 与 quickstart 入口，而 §8.2 lib 清单又包含 quickstart.py——模块在、入口无，成为死代码。
- 建议：§8.1 增补 quickstart 入口；reinstall/guard/init shell 增补或在 A 系列调整点声明放弃理由。

### P2-11 install.sh 版本定位机制不完整
- 位置：design.md §10、§12-A9、§15-Q1
- 问题：A9 排除 latest.json 但未给出替代方案：下载 zip 的 URL 构造规则未定义；「budget setup update 重跑安装流程」如何发现新版本未定义。
- 建议：design §10/Q1 明确版本定位策略（如约定 $BUDGET_REPO_URL/releases/latest 固定别名），并写明 update 的版本发现路径。

### P2-12 §16 合计数字与明细不符
- 位置：design.md §16.1 合计行
- 问题：明细共 76 个 src 文件（skills 12 行 + hooks 1 行），合计行声称「src 80（…… skills 17 ……）」。
- 建议：合计改为 76（skills 12 + hooks 1 单列），或补齐明细使数字一致。

### P2-13 tasks 3.2「业务层 16 文件」实列 17 个
- 位置：tasks.md 3.2（T10）
- 问题：T10 声称「业务层 16 文件」但实际列出 17 个（24 − 基础层 7 = 17）。
- 建议：改为 17 文件。

### P2-14 T13 验收基准引用旧口径
- 位置：tasks.md 5.1（T13）vs docs/plans §11 vs design A1/A2/§5
- 问题：P §11-3/4 的数量口径（commands×3、rules×11）是 A1/A2 调整前的旧口径（本项目为 commands×7、rules×12）；P §11-2「全仓 0 违禁词」与 design §5 固定扫描范围不一致。另「三渠道」vs 四渠道口径不一。
- 建议：T13 注明「P §11 按 design 修正口径核验：commands×7、rules×12、扫描范围按 design §5、渠道按四渠道」。

### P2-15 构建失败留下半成品 dist
- 位置：design.md §4（先清空后构建）vs specs/build-pipeline「校验失败即阻断」Scenario
- 问题：流程为「清空 dist/<platform>/ → 转换 → 校验」，校验失败时 dist 已被清空；dist 提交进 git，失败会污染工作区。
- 建议：改为「构建到临时目录，全部成功后原子替换 dist/<platform>/」；spec Scenario 收紧为「失败时 dist/<platform>/ 保持构建前原样」。

---

## 三、P3 建议项（19 条，不阻塞，实现期注意）

1. §6 角色表缺 tools 列——10 个角色各自的白名单子集无规格值。
2. §8.3 opencode 探测「.opencode/agent/ 或 ~/.config/opencode/agent/」未定优先序。
3. §8.4 项目级 .budget/memory/ 用途未定义（guard 固定用全局）。
4. MODEL_SELECTION 模板渲染与 routing DSL 平移语义的特例协调未声明。
5. specs/build-pipeline 与 specs/installer 产物列举均漏 docs/。
6. specs/notify「chmod 600」责任主体未定义。
7. specs/model-presets「agent inherit」双平台表达未定义。
8. specs/setup-cli 缺「平台探测失败」Scenario。
9. specs/installer 缺「安装中断恢复」Scenario。
10. .budget/ 的 gitignore 写入责任方未指定。
11. P0 三层一致性 diff「告警不阻断」——建议 CI 提供 --strict。
12. hooks 注入建议补幂等与原子写要求；Notification matcher 细节建议写入 design。
13. 「业务自定义 skill 仅缺失时安装」vs「哈希不一致即覆盖」行为差异建议在 design 声明。
14. 参照项目 scripts/lint.sh 无对应物；建议 tests/ 纳入 bash -n / shellcheck 冒烟。
15. BUDGET_DIR 安装目录自定义未纳入 design §10/specs/installer。
16. PERSONAS.md 与架构图在 opencode 侧的分发未定义。
17. RTK hooks 注入去留未声明。
18. `budget update` 与 `budget setup update` 层级关系未定义。
19. curl|bash 信任边界：README 建议增加安全提示。

---

## 四、维度评估小结

| 维度 | 评估 | 依据 |
|------|------|------|
| 需求完整性 | **不足** | P1-3（N11 遗漏）、P1-4（personas 角色集）、P2-1（superpowers 插件）、P2-10（reinstall/quickstart）；其余组件与参照项目 dist/ 逐项对齐无缺 |
| 技术合理性 | **总体合理，局部矛盾** | P1-1/P1-2（权限映射不完备）、P2-5/P2-6（通知配置语义冲突）、P2-9（命令 schema 空白）、P2-15（构建原子性） |
| 安全性 | **有缺口** | P2-7（下载完整性校验缺失）、P2-8（卸载/升级清单）、P3-12（hooks 注入幂等/原子性） |
| 稳定性 | **基本达标，边界场景不足** | P2-15（构建失败半成品）、P3-8/9（探测失败/安装中断场景缺失） |
| 品牌合规 | **自违反** | P1-5（tasks.md 根路径）、P2-2/3/4（spec 范围矛盾、词表载体豁免、REF 通配） |

## 五、处置建议

P1 五条作为合并闸门（必须修订）；P2 十五条在 T1 开工前修订 design/specs/tasks 一并解决（均为文档修订）；P3 由实现任务消化并在 T13 验收时抽查。
