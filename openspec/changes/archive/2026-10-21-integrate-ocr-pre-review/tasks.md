## 1. Agent 定义：OCR 机器预审集成

- [x] 1.1 修改 `core/agents/reviewer.md`：frontmatter `permissions.bash_allow` 扩展为 `["git *", "command -v ocr", "ocr review *"]`；正文新增「OCR 机器预审（可选）」章节——环境探测（`command -v ocr`）、降级语义（CLI 缺失零感知 / 执行失败、退出码非零或宿主超时截断时在「代码质量」段尾部记一行、不重试且不消费输出 / exit 0 时消费 JSON / 规则未装回落内置规则）、执行方式（`ocr review --format json --output /tmp/ocr-review-reviewer.json`，**不带 `--rule`**，规则靠 OCR 四层优先级解析；命令返回后用 read 工具读取临时 JSON 文件消费，不依赖 jq，临时文件不清理）、预审 diff 范围对齐（默认评审当前未提交工作区 diff；被审变更已 commit 时按 git 状态选 `--from <基线分支> --to HEAD` 分支区间或 `--commit <sha>`，均在 `ocr review *` 白名单覆盖内）、逐条验证三态（采纳/驳回/存疑）、severity 三档映射（critical|high→严重、medium→重要、low→建议，落入「代码质量」段对应档位）、非门禁声明（结论与 A/B/C/D 评分仍由本角色裁决）、报告结构不变约束、凭据纪律（不读取 OCR 凭据配置、不回显 token 类环境变量值，探测仅判断存在性）【config_edit】
- [x] 1.2 修改 `core/agents/reviewer-b.md`：frontmatter 同步扩展 `permissions.bash_allow`；正文新增「OCR 机器预审（可选）」章节——探测与降级语义与主审一致，唯失败提示落点适配辅审报告结构（在审查结论行之后、问题清单之前记一行，不改其「通过/不通过 + 问题清单」结构）；执行方式同主审（临时文件路径用 `/tmp/ocr-review-reviewer-b.json`）；category 分工侧重（security 深度验证、test 按测试逻辑独立验证职责处理，bug/performance/maintainability/style 不重复审查，documentation/other 知悉）；三态验证（采纳条目并入问题清单并逐条注明「来源：OCR 预审 + 已验证；档位：严重/重要/建议」）；非门禁声明；凭据纪律同主审（不读取 OCR 凭据配置、不回显 token 类环境变量值）【config_edit】

## 2. 规则集：budget-*-style 沉淀为 ocr-rule.json

- [x] 2.1 新建 `core/lib/ocr-rule.json`（与 `ocr-setup.py` 同目录，随 `_build_lib` 字节平移分发，**不放 `core/rules/`**——该目录仅允许 .md）：7 条语言规范各一条规则条目（go / python / typescript 含 js/vue / java / cpp / css / sql），每条含 `path` 单字符串 glob——多后缀按 brace 展开合并对应规范头部 globs（typescript `**/*.{ts,tsx,js,jsx,vue}`、cpp `**/*.{cpp,h,hpp,c,cc,cxx}`）；css/sql 头部 globs 无 `**/` 前缀属规范源历史写法，提炼层统一补前缀；css 条目为 `**/*.{css,scss,less}`（与 reviewer.md 人工对照表的 `.css/.scss/.less` 映射对齐）——规范源文件零改动；每条含 `merge_system_rule: true`、`rule` 指令文本（从对应规范提炼机器预审关注点，rule 文本内注明「按 budget-xx-style 检查」）、`source` 字段（规范文件主名，与语言规范主名集合双向一一对应）；`budget-trpc-style` 排除（服务调用场景规范，path glob 不可表达，人工审查继续覆盖）；`core/rules/budget-*-style.md` 本身零改动。**分派建议 coder-standard**（config_edit 标签默认 lite，但规则文本需逐条对照 7 份规范提炼，内容质量敏感，提级执行）【config_edit】
- [x] 2.2 修改 `scripts/build.py`：`--check` 新增 `core/lib/ocr-rule.json` 结构校验（JSON 可解析、全部 `merge_system_rule: true`、`source` 值集合与期望集合双向一一对应——期望集合 = 枚举 `core/rules/budget-*-style.md` 文件主名后显式排除 `budget-trpc-style`，不硬编码七元组，后续新增语言规范文件时校验自动跟进）；分发链**不改**（`_build_lib` 既有字节平移已覆盖四平台 dist 的 `lib/`，`core/platform/*.yaml` DSL 与 `_build_rules` 均零改动）【cross_module】

## 3. 管理面：budget setup ocr 子命令

- [x] 3.1 新建 `core/lib/ocr-setup.py`（Python stdlib only，形态同 `autorun.py`）：CLI 检测（`command -v ocr`，缺失输出安装指引不阻断）；模型配置检测（环境变量 `OCR_LLM_URL`/`OCR_LLM_TOKEN`/`OCR_LLM_MODEL` 或 `~/.opencodereview/` 配置文件任一命中即视为已配置，未命中输出「delegate 模式可忽略」提示、不阻断退出码 0）；规则模板安装——模板定位优先 `ocr-setup.py` `__file__` 同目录的 `ocr-rule.json`（`BUDGET_LIB_DIR` 可显式覆盖，正常安装态两者等价），目标 `~/.opencodereview/rule.json`：目录不存在时 `os.makedirs` 创建（权限失败非零退出提示手动创建）、不存在写入 / 相同幂等 / 不同先备份（默认 `rule.json.bak`，`.bak` 已存在时改用时间戳后缀 `rule.json.bak.<YYYYMMDDHHMMSS>`，不覆盖既有文件）+ 差异展示 + 确认后覆盖，stdin 非 TTY 默认跳过覆盖退出码 0；写文件用同目录临时文件原子写（参照 `core/lib/autorun.py` `_atomic_write` 的 `tempfile.mkstemp` + `os.replace` 先例）；降级语义输出；模板源缺失（旧安装，`__file__` 同目录与 `BUDGET_LIB_DIR` 均无）非零退出指引 `budget setup update`【cross_module】
- [x] 3.2 修改 `core/setup.sh`：注册 `ocr` 子命令到 setup 分发层（case 分支 + 直调 python，先例同 autorun/quickstart），help 文案补充【config_edit】

## 4. README 双语文档

- [x] 4.1 `README.md` 新增 `## Optional: OCR Pre-Review Integration` 章节（插入点统一：`### Setup subcommands` 子章节之后、`## Architecture` 之前）：定位（机器预审 detector + reviewer 裁决 judge，非门禁）、安装（`npm i -g @alibaba-group/open-code-review`）、配置二选一（`ocr config provider && ocr config model` 或 `ocr delegate` 免 key）、**规范规则集**（`budget setup ocr` 安装说明 + 项目级 `.opencodereview/rule.json` 优先级说明）、Claude Code 用户可选加速提示（settings.json `permissions.allow` 自行追加预审命令白名单，属用户域）、降级语义（未安装/未配置/未装规则全流程照常）、官方文档链接 `https://open-codereview.ai`；不含任何内网地址与私有基建信息【docs_only】
- [x] 4.2 `README_CN.md` 新增对等中文章节 `## 可选：OCR 代码预审集成`（插入点与英文版对齐：setup 子命令章节之后、架构章节之前），信息点与英文版一一对应【docs_only】

## 5. 测试与门禁验证

> 5.1–5.3 由 **tester 角色**执行（测试与验证职责，标签按 router.md 15 标签集合标注）；5.4 由 **reviewer 角色**人工审计执行（非 coder 分派任务——router 15 标签集合无 review 类标签，不路由 coder）。

- [x] 5.1 `tests/` 新增 ocr-rule.json 结构校验用例（7 语言 source 双向一一对应 / merge_system_rule 全 true / trpc 不出现）与 `core/lib/ocr-setup.py` 单测（幂等 / 备份不静默覆盖与 `.bak` 时间戳后缀 / 非交互默认跳过 / CLI 缺失退出码 0 / 模型配置未检出不阻断 / 模板缺失非零退出 / 目录自动创建与原子写）；确认交互分支的自动化测试以可注入函数（confirm 抽为参数、unittest.mock 替换输入）或 pty 模拟实现，不挂起、不跳过覆盖语义用例【test_only】
- [x] 5.2 运行 `python3 scripts/build.py --check`，按四平台权限落地形态核对产物：`dist/opencode/agent/reviewer.md` 与 `dist/opencode/agent/reviewer-b.md` 的 `permission.bash` 在既有 `"git *": "allow"` 之上新增 `"command -v ocr": "allow"`、`"ocr review *": "allow"` 两条（`"*": "ask"` 不变）；`dist/codebuddy/agents/reviewer*.md`、`dist/claudecode/agents/reviewer*.md` 的 frontmatter 与集成前逐字节一致（permissions drop 行为不变，`permissionMode` 仍为 plan；正文新增章节属预期变更）；`dist/codex/skills/budget-workflow/agents/reviewer*.md` frontmatter 字段集与集成前一致（permissions 丢弃不变）；四平台 dist 的 `lib/ocr-rule.json` 与 `core/lib/ocr-rule.json` 逐字节一致；构建无告警【test_only】
- [x] 5.3 运行 `python3 scripts/scan-brand.py`（新增 README 与 ocr-rule.json 文案零命中）与 `python3 -m unittest discover -s tests`（全量通过）【test_only】
- [x] 5.4 人工审计（由 reviewer 角色执行）：对照四份 delta spec 全部 **10 条 requirement** 逐条核验（`specs/ocr-pre-review/spec.md` 6 条：权限边界源定义与平台落地、降级语义与失败落点双报告区分、三态验证与档位映射含辅审呈现、输出格式兼容、规则集内容与一致性、分发与安装；`specs/workflow-orchestration/spec.md` 1 条；`specs/repo-docs/spec.md` 1 条；`specs/setup-cli/spec.md` 2 条：子命令全集含 ocr + ocr 子命令行为细节）——含全部 scenario 逐项核验；对「不设自动化用例」豁免项（workflow-orchestration delta 的提示词行为约束、报告结构类约束）以人工审计为验收方式；并核对 `core/rules/budget-*-style.md` 与变更前逐字节一致
