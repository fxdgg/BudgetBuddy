# Design — integrate-ocr-pre-review

## Context

- BudgetBuddy 审查阶段由 `core/agents/reviewer.md`（主审：规格合规 + 代码质量 + 语言规范逐项对照）与 `core/agents/reviewer-b.md`（辅审：技术合理性 + 需求完整性 + 安全/容错深检 + 测试逻辑独立验证）构成双审，均为只读角色（`edit_allow: []`，`bash_allow: ["git *"]`）。
- 阿里开源 OpenCodeReview（`@alibaba-group/open-code-review`，Apache-2.0）提供 `ocr review` CLI：对本地 diff（工作区/分支区间/单 commit）输出结构化结果——severity（critical/high/medium/low）、category（bug/security/performance/maintainability/test/style/documentation/other）、file:line 定位；支持 `--format json`、`rule.json` 规则引擎、`ocr delegate` 委托模式（评审用宿主额度、无需额外 key）。
- 约束：`core/` 是唯一中立源，agent 定义改动必须经 `scripts/build.py` 同步四平台（codebuddy/opencode/claudecode/codex）产物；README 在品牌门禁扫描范围内；本仓库为通用套件，**不得携带任何私有基建内容与规则文件**。

## Goals / Non-Goals

**Goals:**

- reviewer / reviewer-b 审查前获得机器预审结构化清单，作为审查输入的一部分，提高检出率
- 预审**自带项目规范检出能力**：`budget-*-style` 语言规范沉淀为 `ocr-rule.json` 机器规则，预审不只依赖 OCR 内置通用规则
- 无 `ocr` 环境的用户零感知：探测失败 → 静默降级，流程、输出格式与现状一致
- OCR 结果作为 detector 输入，最终裁决权保留在 reviewer agent
- README 双语增加可选集成说明，用户可自行安装配置

**Non-Goals:**

- 不把 OCR 结果作为门禁（severity 命中不直接决定通过/不通过）
- 不修改 `core/rules/budget-*-style.md` 规范正文（人类可读权威源不动，ocr-rule.json 是其机器预审提炼层）
- 不做 CI/MR 层 GitLab 集成（行级评论、飞书通知——与 agent 流程正交，另行提案）
- 不修改 coder-* / tester / guard / notify / goal-loop 的任何行为
- 不新增仓库代码依赖（不 vendor `ocr` 二进制，不写安装脚本去装它）

## Decisions

### D1：集成载体 = 直接修改两个 agent 定义，不新建 skill

**选择**：修改 `core/agents/reviewer.md` 与 `core/agents/reviewer-b.md` 正文（新增「OCR 机器预审（可选）」章节）+ frontmatter 权限。
**理由**：预审是审查流程内嵌步骤，agent 定义本身就是 `core/` 的分发单元（随构建进入四平台 `dist/`），无需引入新的 skill 分发结构。
**备选**：新建 `core/skills/ocr-pre-review/`—— rejected：skill 面向「可独立调用的操作指南」，而这里是角色流程变更；且 skill 无法表达 frontmatter 权限扩展。

### D2：权限扩展 = 源定义层白名单精确到只读子命令

```yaml
permissions:
  bash_allow: ["git *", "command -v ocr", "ocr review *"]
```

- `command -v ocr`：环境探测（不执行）
- `ocr review *`：只读评审（覆盖 `--format json --output ...`、`--from/--to`、`--commit` 等参数形式）
- **显式不放开** `ocr config`（写配置）、`ocr rules`（可写自定义层）等子命令，保持 reviewer 只读角色语义；模型/凭据配置由用户在 agent 会话外自行完成（`ocr config provider/model` 或环境变量），agent 上下文不接触 token 明文——**两个 agent 正文章节明示凭据纪律：不读取 OCR 凭据配置文件、不回显 `OCR_LLM_TOKEN` 等 token 类环境变量的值**（探测仅判断存在性，如 `command -v ocr`，不打印凭据内容）
- **平台落地差异**：上述白名单是源定义层（`core/agents/*.md` frontmatter）约束；各平台产物的落地形态见 D6「四平台权限落地形态表」（opencode 经 permission map 精确生效；codebuddy/claudecode/codex 落地为粗粒度/丢弃，预审命令经宿主人工审批仍可执行——源定义层 MUST NOT 放行写配置类子命令的约束不变）
**备选**：放开 `ocr *`——rejected：违反只读角色权限最小化原则。

### D3：降级语义 = 三级探测、失败静默

1. **CLI 缺失**：`command -v ocr` 失败 → 跳过预审，审查报告不出现任何 OCR 相关内容（零感知）
2. **执行失败**（未配置模型 / key 失效 / 超时 / 宿主侧超时或信号截断 / 网络错误 / **退出码非零**）：记一行 `（OCR 预审不可用：跳过）`，**落点按报告结构区分**——主审（reviewer，报告含「代码质量」段）在「代码质量」段尾部记一行；辅审（reviewer-b，「通过/不通过 + 问题清单」结构）在审查结论行之后、问题清单（如有）之前记一行——不影响结论、不重试；**退出码非零或命令被截断时不消费任何已产出的输出**（不解析部分 JSON，保持处置确定性）
3. **部分失败**：OCR 自身按组隔离失败、部分结果照发（`exit 0`），reviewer 直接消费返回的 JSON，不感知内部失败语义

**判级规则简化**：以退出码为准——`exit 0` → 消费 JSON（第 3 级）；非零或截断 → 第 2 级（记一行、不消费）。避免「非零但有部分 stdout」的模糊态。宿主侧超时/信号截断（命令被平台超时机制中断、进程被 kill 无退出码）按第 2 级执行失败处理。

**执行方式（临时文件落盘 + read 消费）**：`ocr review --format json --output <临时文件>`，临时文件用 agent 名隔离的固定路径（主审 `/tmp/ocr-review-reviewer.json`、辅审 `/tmp/ocr-review-reviewer-b.json`，避免双审并行互写覆盖）；命令返回后 agent 用 **read 工具读取该 JSON 文件**消费结果——reviewer tools 为 read/bash/grep/glob、无 jq，读文件消费不引入额外依赖；临时文件留在系统临时目录不做清理（`rm` 不在 bash 白名单内，不为此扩权，`/tmp` 由系统清理）。

**预审 diff 范围对齐**：默认评审**当前未提交工作区 diff**（`ocr review` 工作区模式 = staged + unstaged + untracked，与 reviewer 人工审查的 `git diff` 视角一致）；被审变更已 commit 时，reviewer 按 git 状态选择分支区间参数（`ocr review --from <基线分支> --to HEAD`，merge-base 语义）或单 commit 参数（`ocr review --commit <sha>`）——参数写法进 agent 章节，全部形式均在 `ocr review *` 白名单覆盖内，无需额外放行。

**超时**：预审单次预算纳入 reviewer `max_turns: 40` 现有约束；OCR 侧单请求超时由用户环境变量 `OCR_LLM_TIMEOUT` 控制，agent 定义中不写死数值，只写「等待命令返回，不因慢而中断流程」。

### D4：结果合并 = 验证后采纳 + 三档映射

```
OCR severity        →  reviewer 报告档位
─────────────────────────────────────
critical / high     →  严重问题（必须修复）
medium              →  重要问题（建议修复）
low                 →  建议改进
```

**关键规则：逐条验证，不盲信。** reviewer 对每条 OCR finding 先自行读代码确认，标注三态之一：
- ✅ 采纳（确认成立，纳入报告，注明「来源：OCR 预审 + 已验证」）
- ❌ 驳回（误报，不进报告——LLM 非确定性是官方明示特性）
- ⚠️ 存疑（证据不足，可列为「待澄清」或直接丢弃）

**category → 双审分工映射**（写入两个 agent 定义，避免重复审查）：

| OCR category | 主审 reviewer | 辅审 reviewer-b |
|---|---|---|
| bug / performance / maintainability / style | 主要验证 | 不重复 |
| security | 基础确认 | 深度验证（与既有分工一致） |
| test | 知悉 | 主要验证（对应「测试逻辑独立验证」职责） |
| documentation / other | 知悉 | 知悉 |

**三档映射的双报告呈现**：主审报告「代码质量」段含三档分节，采纳条目落入对应档位；辅审报告为「通过/不通过 + 问题清单」结构（无三档分节），采纳条目**并入其问题清单**并逐条行内注明「来源：OCR 预审 + 已验证；档位：严重/重要/建议」——不改造辅审报告结构（与「审查输出格式兼容」约束一致），severity 信息以行内标注承载。

### D5：README 文档 = 双语对等的「可选集成」章节

`README.md` / `README_CN.md` 新增 `## Optional: OCR Pre-Review Integration` / `## 可选：OCR 代码预审集成`，**插入点统一为一个**：`### Setup subcommands` 子章节之后、`## Architecture` 之前（与 `budget setup ocr` 子命令语义相邻，避免 Features 与 Setup 两处二选一的歧义）：
- 一段定位说明（机器预审 detector + reviewer 裁决 judge，非门禁）
- 安装：`npm i -g @alibaba-group/open-code-review`
- 配置二选一：`ocr config provider && ocr config model`（独立 LLM key）或 `ocr delegate` 委托模式（免 key）
- Claude Code 平台用户可选加速提示一句：可在 settings.json `permissions.allow` 自行追加预审命令白名单（属用户域配置，非 BudgetBuddy 分发内容）
- 降级语义一句话：未安装/未配置时 BudgetBuddy 全流程照常
- 不包含任何内网地址、实例变量名、私有 runner 信息（引用开源官方文档链接 `https://open-codereview.ai`）

**品牌门禁自查**：`OpenCodeReview` / `ocr` / `open-codereview.ai` 均非参照项目品牌词；新增文案过 `scripts/scan-brand.py` 验证。

### D6：构建影响 = frontmatter 按平台 DSL 重写 + `core/lib/` 落位，无 DSL 改动

**agent frontmatter 非整文件原样映射**：`scripts/build.py` 的 `rewrite_agent`（903-937 行）按各平台 `core/platform/*.yaml` 的 `agent_frontmatter.emit/drop` 表选择性重写——`permissions` 字段在四平台均被 drop，bash 白名单由平台特定表达式重新表达，落地形态各异：

**四平台权限落地形态表**（`bash_allow` 三项白名单扩展后的实际效果）：

| 平台 | frontmatter 重写（permissions 处理） | bash 白名单落地形态 | 预审命令执行方式 |
|---|---|---|---|
| opencode | drop `permissions`，`{permission_map}` 经 `compute_permission_map`（build.py 883-900 行）将 `bash_allow` 逐项映射为 `permission.bash` 的 allow 条目 | **精确生效**：`command -v ocr`、`ocr review *` 逐条进入 allow（`*` 保持 ask） | 白名单内命令免审批执行 |
| codebuddy | drop `permissions`，emit `permissionMode`（`edit_restricted → plan`，compute_permission_mode 874-880 行） | **不落地**（粗粒度 plan 模式，bash 白名单不进产物） | 预审命令经宿主人工审批后仍可执行（plan 模式 ≠ 不可用） |
| claudecode | drop `permissions`，emit `permissionMode: plan`（同 codebuddy 映射，camelCase 键） | **不落地**（同 codebuddy） | 经宿主人工审批执行；用户可在 settings.json `permissions.allow` 自行追加白名单（用户域，README 提示一句） |
| codex | drop `permissions`（emit 仅 name/description，skill 素材形态） | **完全丢弃** | 经运行时人工审批执行（spawn 派工契约场景） |

**决策：接受落地差异，不改 DSL。** bash_allow 精确白名单只在 opencode 平台逐条生效；codebuddy/claudecode/codex 平台预审命令退化为「宿主人工审批执行」——**预审在该平台并非不可用，而是无白名单加速、多一次审批交互**，全流程语义（探测 → 执行 → 降级）在四平台等价。不为此修改四份 platform yaml 或 `rewrite_agent`：收益仅是粗粒度平台的审批加速，代价是 DSL/构建器变更面 + 四平台回归验证，不成比例。源定义层三项白名单约束保持不变（MUST NOT 放行写配置类子命令的边界在 `core/agents/*.md` 源头成立，与平台落地无关）。

验收链照旧：`build.py --check` → `scan-brand.py` → 全量 unittest；产物核对按上表（opencode 逐条 allow；其余三平台产物 frontmatter 与集成前逐字节一致——permissions drop 行为不变，正文新增章节属预期变更）。

**`ocr-rule.json` 落位决策（修订）**：放 `core/lib/`（与 `ocr-setup.py` 同目录），随 `_build_lib` **字节平移**至四平台 dist 的 `lib/`（该函数不过滤扩展名）。原方案 `core/rules/` 已否决——`_build_rules` 的两条路径互斥（`build.py:1549-1550` fragment 平台提前 return）：codebuddy（唯一逐文件落位平台）走 1554-1556 行的 `.md` 硬校验，非 .md 直接 BuildError；fragment 类平台（opencode/claudecode/codex）rules 全量走 `_build_extra_outputs` 管线，按 `suffix='.md'` 过滤采集（`build.py:1658`），`.json` 被静默排除——两条路径都不分发 `.json`，但语义不同（前者报错、后者静默）。`core/lib/` 是唯一零改动即四平台全量分发的通道，且安装形态下 `setup.sh` 的 `BUDGET_LIB_DIR`（= setup.sh 同目录 `lib/`）使 `ocr-setup.py` 与 `ocr-rule.json` 天然同目录、模板定位与 autorun/quickstart 的模块定位机制一致。

**备选**：①`core/rules/` + 修改 `_build_rules` 放行 .json——rejected：触碰既有构建硬约束（codebuddy 路径的 rules 目录 .md 语义 + fragment 管线采集过滤两处都要改）且 fragment 管线仍需另行改造；②新建 `core/ocr/` 目录 + 四平台 DSL 新增 routing——rejected：DSL 变更影响面大（4 份 yaml + manifest），收益仅是目录语义更「纯」。

### D7：规范沉淀 = budget-*-style 为权威源，ocr-rule.json 为机器提炼层

**选择**：新增 `core/lib/ocr-rule.json`，每条语言规范提炼一条规则条目：

```json
{
  "rules": [
    { "path": "**/*.go", "merge_system_rule": true,
      "rule": "按 budget-go-style 检查：……（提炼的机器预审关注点）",
      "source": "budget-go-style" },
    ...
  ]
}
```

- **每语言一条**（glob 以对应规范文件头部 globs 为准，7 条语言规范：go/python/typescript(含 js/vue)/java/cpp/css/sql）；**`budget-trpc-style` 排除**——它是 RPC/API 服务调用场景规范，约束点按调用形态而非文件后缀，path glob 无法表达，不纳入机器规则集（reviewer 人工审查维度继续覆盖）。OCR 的 `rules` 按声明顺序取第一条匹配 → 语言级粒度即止，不做目录细分（细规则留给用户项目级 rule.json）
- **path glob 落地语法（多后缀合并）**：`path` 为单字符串 glob，多后缀按 **brace 展开单字符串**合并——typescript `**/*.{ts,tsx,js,jsx,vue}`（对应头部 5 globs）、cpp `**/*.{cpp,h,hpp,c,cc,cxx}`（对应头部 6 globs）。保守选择理由：brace 展开是 glob 标准能力且有可用先例（社区 rule.json 实例 `**/*.{ts,tsx,js,jsx}`、`**/*.{yaml,yml}` 实跑形态）；不依赖未证实的多值数组语法（官方文档未明示 path 支持数组），实施时 tester 实跑一条多后缀规则验证命中，若 brace 不被支持则降级为「该语言按首要后缀单 glob + 正文注明其余后缀由人工审查覆盖」，不影响 source 一一对应校验
- **sql/css 头部 glob 前缀修正**：`budget-css-style` 头部 globs 为 `["*.css"]`、`budget-sql-style` 为 `["*.sql"]`（无 `**/` 前缀，属规范源历史写法）；ocr-rule.json 提炼层统一补 `**/` 前缀（OCR path 按文件全路径匹配，`*.css` 不保证命中子目录文件；其余五规范头部均已带 `**/` 前缀）。规范源文件零改动
- **css 是否补 `.scss/.less`：补**。裁决理由：`core/agents/reviewer.md` 68 行人工审查对照表把 `.css/.scss/.less` 都映射到 budget-css-style（规范内容为 CSS 编码/格式/选择器/属性规范，对预处理器通用部分适用），机器预审层与人工维度对齐——否则 `.scss/.less` 变更只被人工覆盖、机器规则留盲区。最终 css 条目 `**/*.{css,scss,less}`；规范头部 globs 不改（CodeBuddy rule 生成范围维持现状，`core/rules/` 零改动铁律）
- **`merge_system_rule: true`（全部条目）**：在 OCR 内置语言规则之上叠加——默认 false 会整体替换内置规则导致漏检（官方文档明示的坑）
- **`source` 标注字段**：每条注明来源规范名，作为一致性审计锚点（`budget-*-style.md` 改动时按 source 定位需同步的条目）
- **双源一致性策略**：md 是自然语言、无法自动 diff 语义 → 分两层：①结构层自动化——`build.py --check` 校验（校验对象 `core/lib/ocr-rule.json`）：JSON 可解析、全部 `merge_system_rule: true`、`source` 值集合与语言规范文件主名集合**双向一一对应**——期望集合的判定方式为**枚举 `core/rules/budget-*-style.md` 文件主名后显式排除 `budget-trpc-style`**（glob 枚举而非硬编码七元组，后续新增语言规范文件时校验自动跟进；glob 内容属人工提炼自由度不参与比对）；②语义层人工——审查报告审计 + tasks 固化「改 budget-*-style 必须同步 ocr-rule.json」的维护纪律

**备选**：①以 md 为源自动派生 rule.json——rejected：自然语言到指令文本的抽取不可靠，生成质量不可控；②只给文档示例不维护规则文件——rejected：失去「预审自带项目规范」的核心价值，每用户重复劳动。

### D8：规则分发 = 管理面模板 + `budget setup ocr` 安装，不用 `--rule`

**选择**：分发链 `core/lib/ocr-rule.json` →（`_build_lib` 字节平移）四平台 dist `lib/` → 安装后由 `budget setup ocr`（新子命令，实现为 `core/lib/ocr-setup.py`，Python stdlib only，形态同 `autorun.py`/`quickstart`）安装到 OCR **全局层** `~/.opencodereview/rule.json`。

- **不用 `ocr review --rule <path>`**：`--rule` 是单次最高优先级，会压掉用户项目级 `.opencodereview/rule.json` 定制；走 OCR 原生四层优先级（`--rule` > 项目 > 全局 > 内置），BudgetBuddy 只占全局层，项目定制始终优先
- **模板定位**：优先 `ocr-setup.py` 自身 `__file__` 同目录的 `ocr-rule.json`（`Path(__file__).with_name('ocr-rule.json')`——dist lib 内两者天然同目录，脚本被单独复制时仍能找到模板）；环境变量 `BUDGET_LIB_DIR` 显式覆盖（setup.sh 注入形态，与 `__file__` 定位在正常安装态等价）
- **`setup ocr` 行为**：① 检测 `ocr` CLI（`command -v ocr`，缺失则提示安装命令但退出码 0——不强制）；② 检测模型配置可用性（存在 `ocr` 时）：检查环境变量 `OCR_LLM_URL`/`OCR_LLM_TOKEN`/`OCR_LLM_MODEL` 或 `~/.opencodereview/` 配置文件任一命中即视为已配置；检测不到时仅输出「未检测到模型配置——若使用 delegate 模式可忽略」提示、**不阻断**（退出码 0，后续步骤照常——delegate 模式无需配置，不能据此断定不可用）；③ 安装规则（目标已存在且内容不同 → 备份 + 明示 diff 提示，**不静默覆盖**；相同则幂等 no-op；**非交互环境（stdin 非 TTY）检测到内容差异时默认不覆盖**、输出跳过提示与手动路径，退出码 0）；④ 输出降级语义说明。全平台可用（不依赖 codebuddy 安装态）
- **安装容错细节**：`~/.opencodereview/` 目录不存在时 `os.makedirs(..., exist_ok=True)` 创建，权限失败（OSError）非零退出并提示手动创建；写文件用**同目录临时文件原子写**（参照 `core/lib/autorun.py` `_atomic_write` 192-209 行先例：`tempfile.mkstemp` + `os.replace`，写失败不留半截文件）；备份默认名 `rule.json.bak`，**`.bak` 已存在时改用时间戳后缀** `rule.json.bak.<YYYYMMDDHHMMSS>`（不覆盖任何既有备份/用户文件，语义确定可追溯）
- **降级链完整化**：CLI 缺失 → 跳过预审（D3 一级）；CLI 在、全局规则未装 → OCR 用内置规则照跑（预审可用，规范检出降级）；全链路任何一层缺失都不阻断

**备选**：①安装器（install.sh）直接写 `~/.opencodereview/rule.json`——rejected：静默触碰用户 OCR 全局配置且升级重装时无提示，setup 子命令给用户知情权与控制权；②agent 会话内传 `--rule` 指向管理面路径——rejected：见上，破坏项目级优先级。

## Risks / Trade-offs

- [OCR 误报污染报告] → D4 逐条验证 + 三态标注，未验证条目不进结论段
- [预审拉长审查周期（单次 3~9 分钟，波动 ±40%）] → D3 降级语义保证失败不阻断；用户可用 `OCR_EFFORT=low` 等环境变量自行调优（README 提示一句）；agent 侧不做耗时自适应（保持流程确定性）
- [reviewer 上下文 token 膨胀（大 diff 的 JSON 结果）] → 已升格为 D3 执行方式：结果落临时文件（`--output`，agent 名隔离路径），agent 用 read 工具读文件、只摘取 severity/category/file:line 与描述字段；JSON 过大时 OCR 自身的分组机制已按文件分片；同机跨项目并发会话存在固定临时路径互写可能（agent 名隔离仅区分双审角色、不区分项目），逐条验证三态可兜底——污染条目在逐条对照实际 diff 验证时被驳回，不直接进入报告
- [四平台权限落地差异（`bash_allow` 各平台解释不同）] → D6 落地形态表如实描述并已成正式决策：opencode 经 permission map 精确生效；codebuddy/claudecode 落地为 permissionMode 粗粒度（plan 模式下预审命令经宿主人工审批**仍可执行，非不可用**）；codex 丢弃 permissions（同走运行时人工审批）——预审在四平台可用性等价，差异仅为审批交互摩擦；`build.py --check` + 5.2 产物核对兜底；Claude Code 用户侧可选 settings.json 加白（README 提示，用户域）
- [用户误把 OCR 当门禁] → README 与 agent 定义双处写明「非门禁」；审查结论格式不变（A/B/C/D 评分 + 通过/需修改/升级人工），OCR 来源仅以行内标注出现
- [开源 CLI 演进（参数变更）] → agent 定义只依赖最稳定的核心面：`ocr review --format json`；其余参数不写入定义
- [双源漂移：budget-*-style 改了但 ocr-rule.json 未同步] → D7 source 标注锚点 + 构建结构校验兜底语言覆盖完整性（source 与规范文件名双向一一对应）；语义漂移靠审查阶段审计（reviewer 审 `core/rules/budget-*-style.md` 变更时必查两源同步）；md 与 rule.json 职责分层（权威源 vs 提炼层）降低完全一致的心理预期
- [`setup ocr` 覆盖用户已有全局规则] → D8 备份 `.bak` + diff 提示，不静默覆盖（非交互环境默认跳过）；用户项目级 `.opencodereview/rule.json` 优先级天然更高，可逐项目覆盖
- [规则文件敏感/品牌合规] → ocr-rule.json 内容全部来自 `core/rules/budget-*-style.md` 既有内容（已在门禁扫描范围，`scan-brand.py` 全量遍历不过滤扩展名）；新增文件位于 `core/lib/` 同样在扫描范围（`SCAN_DIRS` 含 core）

## Migration Plan

1. 实施顺序：agent 定义（reviewer → reviewer-b）→ `core/lib/ocr-rule.json`（规范提炼）→ `scripts/build.py`（`--check` 结构校验，分发走既有 `_build_lib` 无需改动分发函数）→ `core/lib/ocr-setup.py` + `core/setup.sh`（`setup ocr` 子命令）→ README 双语 → 单测补充 → 门禁与全量测试
2. 回滚：`git revert` 整个变更即可；产物随下次构建自动回退。`setup ocr` 已安装的 `~/.opencodereview/rule.json` 属用户环境文件，回滚仓库不回收（安装时已有 `.bak` 备份链，README 说明手动移除路径），无数据/状态迁移负担
3. **归档顺序依赖（在途变更 add-codex-platform）**：本变更 **repo-docs 与 setup-cli 两份 delta 的 MODIFIED 均已预置归档后终态口径**——repo-docs 的 README requirement 为**四平台口径**（与 add-codex-platform 归档后的口径一致，叠加 OCR 段与 codex preset 降级/gpt-5.6 部署别名三档细节括注）；setup-cli 的「setup.sh 子命令体系」requirement 为**标准标题下的完整终态**（子命令枚举全集含 `ocr`，并入其 codex preset 降级语义与 show 三档映射表——其 delta 标题带非标准后缀「（preset codex 降级语义）」，本 delta 已统一回标准标题预置完整正文，两处均非 last-writer-wins 失真）。建议 **add-codex-platform 先归档**、本变更后归档（两份 delta 已按其归档后口径预置，直接替换即得「四平台 + OCR + codex 降级」终态）；若顺序颠倒（本变更先归档），add-codex-platform 归档前必须把其 repo-docs 与 setup-cli 两份 delta 重新基线化以保留 OCR 段与 ocr 子命令语义；**归档时对两份 delta 的合并终态逐条人工核对**（尤其 setup-cli：确认 codex 降级语义合并后无重复 requirement 条目、枚举全集与 ocr 子命令完整保留）

## Open Questions

- `OCR_INCREMENTAL`（跨轮增量去重）是否值得在 agent 定义中提示用户开启？→ 倾向不提（环境变量属用户调优域，README 已链接官方文档），实施时由 reviewer 双审裁决
- ~~Claude Code 平台对 subagent bash 白名单的精确支持度~~ → **已处置**（D6 落地形态表）：claudecode 产物 drop `permissions`、落地 `permissionMode: plan`，预审命令经宿主人工审批执行（plan 模式 ≠ 不可用，白名单不落地不阻断预审）；用户侧可选在 settings.json `permissions.allow` 自行追加预审命令白名单获得免审批体验（README 提示一句，属用户域配置）；实施时 tester 验证 **opencode** 产物映射（permission.bash 新增两条 allow）即可闭环
- `ocr-rule.json` 是否随 `budget setup update` 升级链自动刷新全局层副本？→ 初版不做（`setup ocr` 手动重装幂等即可），观察使用频率后再议
