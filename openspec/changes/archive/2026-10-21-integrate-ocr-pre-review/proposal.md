## Why

BudgetBuddy 的代码审查（reviewer / reviewer-b 双审）目前完全依赖 LLM 通读 diff 与源码，缺少机器可执行的结构化预审输入：问题发现没有 severity/category 分级、没有按语言/路径的规则引擎沉淀、跨轮审查无法增量去重。阿里官方开源的 OpenCodeReview（`@alibaba-group/open-code-review`，Apache-2.0，GitHub `alibaba/open-code-review`）提供 `ocr review` CLI——对 diff 输出结构化评审结果（severity: critical/high/medium/low；category: bug/security/performance/maintainability/test/style）、`rule.json` 规则引擎、`ocr delegate` 委托模式（无需额外 LLM key）。将其作为审查阶段的**可选机器预审（detector）**，与 reviewer 的人工判断（judge）互补，可提高 coder 编码完成后的 review 检出率与确定性。

**为什么是开源 CLI 而不是现成 skill**：直接集成开源 `ocr` CLI，不引入任何私有基建内容（内网 runner、实例级变量、飞书通知服务均不进入本仓库），零耦合风险、零敏感信息。

## What Changes

- reviewer / reviewer-b 的审查流程增加**可选 OCR 预审步骤**：审查前运行 `ocr review --format json` 获取结构化问题清单，叠加进各自审查维度后合并输出（severity 映射到现有「严重/重要/建议」三档）
- **环境探测与静默降级**：`ocr` CLI 未安装或未配置（`OCR_LLM_URL/TOKEN/MODEL` 缺失、且不使用 delegate 模式）时，跳过预审、不阻断、不告警污染审查报告，reviewer 流程与现状完全一致
- reviewer / reviewer-b 的 `bash_allow` 权限扩展（源定义层）：在 `git *` 之上允许 `ocr review`（只读评审命令，含 `command -v ocr` 探测，不含 `ocr config` 写配置类子命令）；平台落地差异：opencode 产物经 permission map 精确生效（逐条 allow），codebuddy/claudecode 落地为 `permissionMode` 粗粒度（预审命令经宿主人工审批仍可执行，非不可用），codex 丢弃 permissions（同走运行时人工审批）——源定义只读约束四平台不变
- 定位约束：OCR 结果仅作辅助输入（detector），**最终审查结论仍由 reviewer agent 裁决（judge）**，不作为门禁（与 OCR 官方「LLM 非确定性、勿当门禁」建议一致）
- **规范沉淀为机器规则集**：新增 `core/lib/ocr-rule.json`（与 `ocr-setup.py` 同目录，经 `_build_lib` 字节平移分发），把 7 条 `budget-*-style` **语言规范**（go/python/typescript/java/cpp/css/sql）各提炼一条机器预审关注点（per-language path glob + 指令文本），全部 `merge_system_rule: true`（叠加 OCR 内置语言规则之上，不替换防漏检）；`budget-trpc-style` 属服务调用场景规范（非 path glob 可表达），不纳入机器规则集；预审不再只依赖 OCR 内置通用规则，自带项目规范检出能力
- **规则集分发与安装**：`ocr-rule.json` 随四平台 dist（codebuddy/opencode/claudecode/codex）分发（`_build_lib` 字节平移，无需改 `core/platform/*.yaml` DSL），`build.py --check` 增加 JSON 结构校验（可解析、语言覆盖集完整、来源标注齐全）；新增 `budget setup ocr` 子命令将其安装到 OCR 全局层 `~/.opencodereview/rule.json`（幂等、已存在且内容不同时备份提示、不静默覆盖）；项目级 `.opencodereview/rule.json` 优先级天然高于全局层，用户项目定制不受影响
- **降级语义扩展**：规则文件未安装时，`ocr review` 静默回落 OCR 内置规则，预审照常执行（降级链：项目规则 > 全局规则 > 内置规则）
- `README.md` / `README_CN.md` 增加「Optional: OCR Pre-Review Integration」章节：开源 CLI 安装、模型配置（含 delegate 免 key 模式）、规则集安装（`budget setup ocr`）、降级语义说明

## Capabilities

### New Capabilities
- `ocr-pre-review`: 审查阶段可选机器预审能力——环境探测与降级、预审执行与结果合并、权限边界、与双审分工的映射关系、OCR 规则集（ocr-rule.json）的内容与一致性维护

### Modified Capabilities
- `workflow-orchestration`: Review Gate（reviewer + reviewer-b 交叉复核）阶段新增可选机器预审步骤；预审缺失不影响 3 轮驳回 / Director 终裁等既有语义
- `repo-docs`: README 双语文档章节清单新增「OCR Pre-Review Integration（可选）」，要求双语对等
- `setup-cli`: `budget setup` 子命令全集新增 `ocr` 子命令（规则集安装与 CLI/配置状态检测）

## Impact

- **Agent 定义**：`core/agents/reviewer.md`、`core/agents/reviewer-b.md`（流程章节 + frontmatter `permissions.bash_allow`）——改后必须跑 `python3 scripts/build.py --check` 同步平台产物
- **规则文件（新增）**：`core/lib/ocr-rule.json`（7 条 per-language 规则，来源标注 `budget-*-style`，与 `ocr-setup.py` 同目录）；`core/rules/budget-*-style.md` 本身不改（规范正文保持人类可读权威源，ocr-rule.json 为机器预审提炼层，按语言映射关系人工同步）
- **构建**：`scripts/build.py` 沿用 `_build_lib` 字节平移分发 `core/lib/ocr-rule.json` 至四平台 dist（零 DSL 改动，`core/rules/` 的仅 .md 约束不受触碰）+ `--check` 新增 JSON 结构校验（可解析、语言覆盖集完整、来源标注齐全）
- **管理面**：`core/lib/ocr-setup.py`（新增，Python stdlib only）实现 `budget setup ocr`，模板源即同目录 `ocr-rule.json`（`$BUDGET_LIB_DIR/ocr-rule.json`，与 autorun/quickstart 的分发定位机制一致）；`core/setup.sh` 子命令注册（setup-cli capability 范围内扩展）
- **文档**：`README.md`、`README_CN.md`（品牌门禁扫描范围内，措辞需过 `python3 scripts/scan-brand.py`）
- **依赖**：无新增仓库代码依赖；`ocr` CLI 为**用户环境可选依赖**（`npm i -g @alibaba-group/open-code-review`），缺失时全流程照常
- **不受影响**：coder-* / tester / director / guard / notify / goal-loop 均不变；用户项目级 `.opencodereview/rule.json` 优先级天然高于全局层，定制不受影响
