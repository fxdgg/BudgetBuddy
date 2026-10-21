# ocr-pre-review Delta Spec

## ADDED Requirements

### Requirement: OCR 预审环境探测与静默降级

reviewer / reviewer-b 在审查启动时 SHALL 先探测 OpenCodeReview CLI（`ocr`）是否可用（`command -v ocr`）；CLI 缺失时 MUST 跳过机器预审且审查报告不出现任何 OCR 相关内容（零感知降级）；预审执行失败（未配置模型 / 凭据失效 / 超时 / 宿主侧超时或信号截断 / 网络错误 / **退出码非零**）时 MUST 仅记一行「OCR 预审不可用：跳过」，**落点按报告结构区分**——主审（reviewer，报告含「代码质量」段）在「代码质量」段尾部记一行，辅审（reviewer-b，「通过/不通过 + 问题清单」结构）在审查结论行之后、问题清单（如有）之前记一行——不重试、不阻断、不影响审查结论，且退出码非零或命令被截断时 MUST NOT 解析或消费任何已产出的输出（判级以退出码为准：`exit 0` 消费 JSON，非零/截断即跳过）。预审执行方式 SHALL 为 `ocr review --format json --output <临时文件>`（主审/辅审各用独立固定路径 `/tmp/ocr-review-reviewer.json`、`/tmp/ocr-review-reviewer-b.json`，避免双审并行互写），命令返回后 agent MUST 用 read 工具读取该文件消费结果（不依赖 jq；临时文件留在系统临时目录不做清理——删除命令不在权限白名单内）。预审 diff 范围 SHALL 与被审变更对齐：默认评审当前未提交工作区 diff；被审变更已 commit 时由 reviewer 按 git 状态选择分支区间（`--from <基线分支> --to HEAD`）或单 commit（`--commit <sha>`）参数，全部形式在 `ocr review *` 白名单覆盖内。【MUST】

#### Scenario: CLI 未安装

- **WHEN** 执行环境未安装 `ocr` CLI（`command -v ocr` 失败）
- **THEN** 审查流程与输出格式与无 OCR 集成时完全一致，报告中无 OCR 字样

#### Scenario: 预审执行失败

- **WHEN** `ocr review` 因模型未配置或超时返回失败
- **THEN** 主审报告在「代码质量」段尾部、辅审报告在审查结论行之后问题清单之前各记一行不可用说明，审查继续，结论与评分不受影响

#### Scenario: 非零退出不消费输出

- **WHEN** `ocr review` 退出码非零但已产出临时 JSON 文件（含部分结果）
- **THEN** 不解析该输出，按执行失败处理（记一行跳过），预审结果为空

#### Scenario: 宿主超时截断

- **WHEN** `ocr review` 被平台超时机制或信号中断（无退出码产出）
- **THEN** 按执行失败处理（记一行跳过），不消费已产出的临时文件内容

#### Scenario: 预审部分失败

- **WHEN** OCR 按组隔离失败、返回部分结果（exit 0）
- **THEN** reviewer 消费返回的部分结果，不感知 OCR 内部失败语义

#### Scenario: 预审 diff 范围对齐

- **WHEN** 被审变更已全部 commit（工作区无未提交 diff）
- **THEN** reviewer 按 git 状态以分支区间或单 commit 参数运行预审，预审范围与被审变更一致

### Requirement: 预审权限边界

**源定义层**：reviewer / reviewer-b 的 frontmatter `permissions.bash_allow` SHALL 在 `git *` 之上精确放行 `command -v ocr` 与 `ocr review *`（只读评审命令）；MUST NOT 放行 `ocr config`、`ocr rules` 等写配置类子命令，保持只读角色语义（该约束作用于 `core/agents/*.md` 源定义，四平台产物均继承，差异仅在落地形态）；模型与凭据配置 MUST 由用户在 agent 会话外自行完成（`ocr config provider/model`、环境变量或 delegate 模式），agent 上下文 MUST NOT 接触 token 明文（agent 正文章节 SHALL 明示：不读取 OCR 凭据配置、不回显 token 类环境变量值，探测仅判断存在性）。**平台落地层（如实描述，非源定义约束）**：opencode 产物经 permission map 精确生效（`bash_allow` 逐条映射为 `permission.bash` 的 allow 条目）；codebuddy / claudecode 产物落地为 `permissionMode` 粗粒度（bash 白名单不进产物，预审命令经宿主人工审批后执行——plan 模式下仍可执行，非不可用）；codex 产物丢弃 permissions（预审命令经运行时人工审批执行）。【MUST】

#### Scenario: 权限白名单最小化

- **WHEN** 审查源定义 `core/agents/reviewer.md`、`core/agents/reviewer-b.md` 的 frontmatter `permissions.bash_allow`
- **THEN** 白名单仅含 `git *`、`command -v ocr`、`ocr review *` 三项，不含任何写配置类 ocr 子命令

#### Scenario: 平台落地形态差异如实

- **WHEN** 核对四平台 dist 产物的 reviewer / reviewer-b frontmatter
- **THEN** opencode 产物 `permission.bash` 含 `command -v ocr` 与 `ocr review *` 两条 allow；codebuddy / claudecode 产物 `permissionMode` 与集成前一致（permissions drop 行为不变）；codex 产物 frontmatter 字段集与集成前一致（permissions 丢弃不变）

#### Scenario: 只读语义保持

- **WHEN** reviewer 会话中执行预审
- **THEN** 不发生任何文件写入或 ocr 配置变更（预审结果临时文件除外，属工具输出落盘），审查报告仍以回复文本返回，agent 不回显任何 token 类环境变量值

### Requirement: OCR 结果验证后采纳与档位映射

reviewer MUST 对每条 OCR finding 先自行读代码验证，标注三态（✅ 采纳 / ❌ 驳回 / ⚠️ 存疑）后才可纳入报告；severity SHALL 映射为：critical/high → 严重问题（必须修复）、medium → 重要问题（建议修复）、low → 建议改进；category 分工 SHALL 为：bug/performance/maintainability/style 归主审验证、security 辅审深度验证、test 归辅审（测试逻辑独立验证职责）、documentation/other 双审均知悉（不作为主要验证职责，避免重复审查）；三档呈现 SHALL 适配双报告结构——主审采纳条目落入「代码质量」段对应档位，辅审采纳条目并入其问题清单并逐条注明来源与对应档位（如「来源：OCR 预审 + 已验证；档位：严重」，不改造辅审报告结构）；OCR 结果 MUST NOT 直接决定审查结论（通过/需修改/升级人工与 A/B/C/D 评分仍由 reviewer agent 裁决）。【MUST】

#### Scenario: 逐条验证三态标注

- **WHEN** OCR 预审返回包含若干 finding 的 JSON 结果
- **THEN** 报告中仅出现经 reviewer 验证标注的条目，每条注明来源（OCR 预审 + 已验证）；未验证条目不进结论段

#### Scenario: 辅审条目档位行内标注

- **WHEN** 辅审（reviewer-b）采纳一条 severity 为 high 的 OCR finding
- **THEN** 该条目并入问题清单，行内注明「来源：OCR 预审 + 已验证；档位：严重」，问题清单结构不变

#### Scenario: 误报驳回

- **WHEN** 某 OCR finding 经 reviewer 读代码确认为误报
- **THEN** 该条目不进入审查报告问题清单

#### Scenario: 非门禁语义

- **WHEN** OCR 结果中出现 critical 级 finding
- **THEN** 审查结论仍由 reviewer 验证后裁决，不因 severity 档位自动判不通过

### Requirement: 审查输出格式兼容

启用预审后，reviewer / reviewer-b 的审查报告结构（主审：审查结论/规格合规/代码规范合规/代码质量/评分；辅审：通过或不通过+问题清单）MUST 保持不变；OCR 来源信息仅以行内标注形式出现在既有段落/清单内，预审失败的一行说明亦为既有结构内的行级插入（落点见「OCR 预审环境探测与静默降级」），不改章节结构。【MUST】

#### Scenario: 报告结构不变

- **WHEN** 预审成功且条目被采纳
- **THEN** 条目落入既有「严重问题/重要问题/建议改进」三档，报告章节结构与无预审时一致

### Requirement: OCR 规则集（ocr-rule.json）内容与一致性

`core/lib/ocr-rule.json` SHALL 按语言提炼 `budget-*-style` 语言规范为机器预审规则：7 条语言规范（go/python/typescript/java/cpp/css/sql）各一条条目；`path` 为单字符串 glob 且多后缀 MUST 以 brace 展开合并（typescript `**/*.{ts,tsx,js,jsx,vue}`、cpp `**/*.{cpp,h,hpp,c,cc,cxx}`——以对应规范文件头部 globs 为基准）；`budget-css-style`/`budget-sql-style` 头部 globs 缺 `**/` 前缀（规范源历史写法），提炼层 MUST 统一补 `**/` 前缀；css 条目 MUST 扩展为 `**/*.{css,scss,less}`（与 reviewer 人工审查对照表的 `.css/.scss/.less` 映射对齐）；全部 `merge_system_rule: true`（叠加 OCR 内置规则，MUST NOT 替换）、每条含 `source` 字段标注来源规范文件主名；`budget-trpc-style` 属服务调用场景规范（非 path glob 可表达）MUST 排除在机器规则集之外（reviewer 人工审查维度继续覆盖）；`core/rules/budget-*-style.md` 规范正文 MUST NOT 被本能力修改（人类可读权威源与机器提炼层分离）。结构一致性 SHALL 由 `build.py --check` 自动校验（校验对象 `core/lib/ocr-rule.json`）：JSON 可解析、全部 `merge_system_rule: true`、`source` 值集合与语言规范文件主名集合**双向一一对应**（期望集合 = 枚举 `core/rules/budget-*-style.md` 文件主名后显式排除 `budget-trpc-style`，glob 枚举而非硬编码清单；glob 内容属人工提炼自由度不参与比对）；语义一致性（规范条目变更后规则同步）MUST 由审查阶段人工审计承担。【MUST】

#### Scenario: 语言覆盖完整

- **WHEN** `build.py --check` 校验 `core/lib/ocr-rule.json`
- **THEN** 7 条语言规范各对应一条条目，JSON 可解析，`source` 值与规范文件主名双向一一对应（无缺无多），全部 `merge_system_rule: true`

#### Scenario: trpc 不纳入

- **WHEN** 检查 ocr-rule.json 条目集合
- **THEN** 不存在 `source: budget-trpc-style` 的条目（服务调用场景规范由人工审查覆盖）

#### Scenario: 规范正文不动

- **WHEN** 本变更实施完成
- **THEN** `core/rules/budget-*.md` 文件与变更前逐字节一致

#### Scenario: 规范变更触发同步审计

- **WHEN** 后续变更修改任一 `budget-*-style.md`
- **THEN** reviewer 审查该变更时必查 ocr-rule.json 对应 `source` 条目是否需同步（纪律写入 tasks 与审查关注点，非自动阻断）

### Requirement: 规则集分发与安装

`core/lib/ocr-rule.json` SHALL 经 `_build_lib` 字节平移随四平台（codebuddy/opencode/claudecode/codex）dist 的 `lib/` 分发（`core/platform/*.yaml` DSL 无改动）；`budget setup ocr` 子命令（实现为 `core/lib/ocr-setup.py`，Python stdlib only）SHALL 将规则模板安装到 OCR 全局层 `~/.opencodereview/rule.json`——模板定位 MUST 优先 `ocr-setup.py` 自身 `__file__` 同目录的 `ocr-rule.json`（环境变量 `BUDGET_LIB_DIR` 可显式覆盖，正常安装态两者等价）；目标目录 `~/.opencodereview/` 不存在时 MUST 自动创建（权限失败非零退出并提示手动创建）；写文件 MUST 采用同目录临时文件原子写（参照 `core/lib/autorun.py` `_atomic_write` 的 `tempfile.mkstemp` + `os.replace` 先例，写失败不留半截文件）；目标不存在则安装；已存在且内容相同则幂等 no-op；已存在且内容不同则 MUST 先备份并明示差异后经用户确认再覆盖（不静默覆盖；备份默认名 `rule.json.bak`，`.bak` 已存在时 MUST 改用时间戳后缀 `rule.json.bak.<YYYYMMDDHHMMSS>`，不覆盖任何既有文件；stdin 非 TTY 的非交互环境 MUST 默认跳过覆盖并输出提示与手动路径，退出码 0）；`ocr` CLI 缺失时 MUST 输出安装指引且退出码 0（不强制安装）；模型配置检测 SHALL 不阻断（检测环境变量 `OCR_LLM_URL`/`OCR_LLM_TOKEN`/`OCR_LLM_MODEL` 或 `~/.opencodereview/` 配置文件，未命中仅输出「delegate 模式可忽略」提示）；子命令不依赖特定平台安装态，任何平台可用。agent 侧预审命令 MUST NOT 使用 `--rule` 参数（保持 OCR 四层规则优先级，用户项目级 `.opencodereview/rule.json` 始终优先于 BudgetBuddy 全局层）。规则未安装时 OCR SHALL 静默回落内置规则，预审照常。【MUST】

#### Scenario: 安装到全局层

- **WHEN** 用户执行 `budget setup ocr` 且 `~/.opencodereview/rule.json` 不存在
- **THEN** 规则模板安装到该路径，`ocr review` 预审自动叠加 budget 语言规范关注点（merge_system_rule 叠加内置）

#### Scenario: 已有规则不静默覆盖

- **WHEN** `~/.opencodereview/rule.json` 已存在且与模板内容不同
- **THEN** 先生成 `.bak` 备份并展示差异，用户确认后才覆盖，取消则原文件保持不变

#### Scenario: 备份名冲突用时间戳后缀

- **WHEN** 覆盖前发现 `~/.opencodereview/rule.json.bak` 已存在
- **THEN** 本次备份改用 `rule.json.bak.<YYYYMMDDHHMMSS>` 时间戳后缀路径，既有 `.bak` 文件不被覆盖

#### Scenario: 目标目录不存在自动创建

- **WHEN** 执行 `budget setup ocr` 时 `~/.opencodereview/` 目录不存在
- **THEN** 目录被自动创建后规则照常安装；目录创建因权限失败时报错非零退出并提示手动创建，不留半截文件

#### Scenario: 模型配置未检出不阻断

- **WHEN** CLI 已安装但环境变量与 `~/.opencodereview/` 配置文件均未检出模型配置
- **THEN** 输出「未检测到模型配置——若使用 delegate 模式可忽略」提示，安装步骤照常完成，退出码 0

#### Scenario: 非交互环境默认跳过

- **WHEN** 在 stdin 非 TTY 的环境（CI/管道）执行 `budget setup ocr` 且目标与模板内容不同
- **THEN** 不覆盖、不交互挂起，输出跳过说明与手动覆盖路径，退出码 0

#### Scenario: CLI 缺失不强制

- **WHEN** 环境未安装 `ocr` CLI 时执行 `budget setup ocr`
- **THEN** 输出 `npm i -g @alibaba-group/open-code-review` 指引，退出码 0，无文件写入

#### Scenario: 项目级规则优先

- **WHEN** 用户项目存在 `.opencodereview/rule.json` 且已安装 BudgetBuddy 全局规则
- **THEN** 该项目内预审按 OCR 原生优先级使用项目级规则，BudgetBuddy 全局规则不干扰

#### Scenario: 规则未装降级到内置

- **WHEN** CLI 可用但用户未执行 `setup ocr`（全局层无规则文件）
- **THEN** 预审按 OCR 内置规则照常执行，无报错、无阻断
