# Task 4.2 Open Questions 端到端验证记录（Tester）

> 对应 tasks.md 4.2（O3 修订显式跟踪项）与 design.md「Open Questions」前三项。
> 验证人：Tester。验证环境：macOS (darwin) / 仓库工作区，无真实 CodeBuddy IDE 会话。
> 证据原则：每项结论附实际命令、退出码、原始输出摘要；不可验项明确标注 ⚠️未执行 + 依赖条件。
> 验证日期：以 git 提交记录为准（本文件随 4.2 完成落位）。

## OQ1：IDE 设置页 Agent Tab 的 Auto Run 开关与 frontmatter `enabledAutoRun` 的优先级关系

### 已验证部分：产物字段形态与官方文档一致 ✅

命令与结果：

1. 提取 dist/codebuddy/agents 全部 10 个 agent 产物 frontmatter 关键字段
   （`for f in *.md; do awk ... | grep -E '^(name|permissionMode|enabledAutoRun|max_turns):'`，退出码 0）：

   | agent | permissionMode | enabledAutoRun |
   |---|---|---|
   | coder-lite | acceptEdits | `enabledAutoRun: true` |
   | coder-standard | acceptEdits | `enabledAutoRun: true` |
   | coder-senior | acceptEdits | `enabledAutoRun: true` |
   | tester | plan | `enabledAutoRun: true` |
   | architect / director / goal-evaluator / recorder / reviewer / reviewer-b | plan | （不含该键） |

   字段位置确认：`enabledAutoRun: true` 位于 frontmatter 内 `max_turns` 之后一行（样例 `dist/codebuddy/agents/coder-lite.md` L1-9：name/description/model/tools/permissionMode/max_turns/enabledAutoRun），布尔值无引号（`true` 非 `"true"`）。

2. 官方文档核对（web_fetch https://www.codebuddy.cn/docs/ide/Features/Subagents 「Subagents 使用指南」，抓取成功）：
   - 配置说明表格：**Auto Run** = 「Subagents 调用工具时是否需要用户的同意」，agentic/manual 两模式均为 Optional。
   - 文档两个 frontmatter 示例（agentic 模式 `timezone-introducer`、manual 模式 `weather-expert`）均含 `enabledAutoRun: true`。
   - 文档原文：「Subagents 在本地存储为 Markdown 文件，也可以在对应路径下创建文件来配置 Subagents，不过在 IDE 中推荐使用设置页 Agent Tab 下的 Create Agent 按钮创建不同模式的 Subagents。点击按钮时选中的是 User Agent Tab 则会创建 user 级别的 Subagents，反之则为 project 级别。」

   **结论（已验证部分）**：字段名（camelCase `enabledAutoRun`）、位置（YAML frontmatter）、值形态（布尔 `true`）与官方文档示例逐字一致；官方文档表明设置页 Agent Tab 创建/管理的 Subagent 即本地 Markdown 文件，两入口指向同一份 Subagent 配置（同一数据源的强旁证，但文档未明示「设置页开关回写 frontmatter 的具体行为」）。

### ⚠️ 未执行：IDE 实际行为优先级（依赖条件）

- 官方文档未说明设置页开关与 frontmatter 的优先级关系，本环境无真实 CodeBuddy IDE 会话，无法实证。
- **依赖条件**：需用户在真实 CodeBuddy IDE 会话中验证——① 在设置页 Agent Tab 关闭某 project 级 subagent 的 Auto Run，观察 `.codebuddy/agents/<name>.md` 是否被回写（写入形态见 OQ2）；② 仅改文件 frontmatter 不动设置页（或反之），重启会话后确认哪侧生效。

### 文档口径建议

在真实 IDE 验证定稿前，建议 README 双语 AutoRun 段增补（不承诺优先级、引导单一入口）：

> Auto Run 可在 IDE 设置页 Agent Tab 与 agent 文件 frontmatter（`enabledAutoRun`）两处管理，两者指向同一 Subagent 配置。为避免多入口状态漂移，推荐统一通过 `budget setup autorun list|on|off` 管理；若曾在 IDE 设置页手动调整过 Auto Run，请以 IDE 设置页当前显示为准——两者出现分歧时，`budget setup autorun list` 的双栏输出会暴露差异。

（若后续真实 IDE 验证确认「IDE 侧优先」，将上述「请以 IDE 设置页当前显示为准」升级为显式口径「以 IDE 设置为准」并去除条件语气。）

## OQ2：IDE 关闭时的写入形态（删行 vs `enabledAutoRun: false`）

### 已验证部分：两种形态下种子化按值判定均安全 ✅

沙盒实证（构造双形态 + 无状态文件执行 `on` 另一 agent）：

- 命令：`python3 /tmp/oq2_seed_sandbox.py`（tmp 目录伪造 agents 目录 + 隔离 HOME；coder-lite 持 `enabledAutoRun: false` 行、reviewer 无 enabledAutoRun 行（删行态）、architect 无行；注入 `BUDGET_PLATFORM_KIND=codebuddy`/`BUDGET_PLATFORM_SCOPE=project`/`BUDGET_PLATFORM_ROOT`/`BUDGET_AGENTS_DIR`；子进程直调 `core/lib/autorun.py on architect`）。
- 退出码：0。
- 原始输出摘要：
  - `[i] 状态文件缺失，已按安装态种子化基线（仅 enabledAutoRun: true 进基线）: （无）`
  - `[✓] architect 已开启 AutoRun（.../architect.md: inserted）`
  - `[✓] 状态文件已更新: .../auto-run.json（1 个 agent: architect）`
  - 状态文件内容：`{"agents": ["architect"]}`
  - 终态文件：coder-lite 仍为 `enabledAutoRun: false`（行数 1，未被翻转、未被删除）；reviewer 仍无 enabledAutoRun 行（字节零改动）；architect 插入 `enabledAutoRun: true`（行数 1）。
- 断言核验 7/7 PASS：false 行不被翻转 / false 行不进基线 / 删行 agent 不进基线 / 删行 agent 文件零改动 / on 目标进基线 / on 目标插入 true / 退出码 0。
- 附带证据：`on` 输出触发 D7 降级路径（「未找到 .bash-patterns.json … 暂无法列出具体 bash 模式…开启照常完成」），与设计一致。

回归套件佐证：

- 命令：`python3 -m unittest tests.test_autorun -v`，退出码 0，`Ran 27 tests ... OK`。
- 相关用例：`SeedBaselineTests.test_seed_only_true_enters_baseline`（false 行不翻转不进基线）、`PatchOnOffTests.test_on_replaces_existing_false_value`、`SeedBaselineTests.test_seed_reads_crlf_true_value` 等均 ok。

**结论**：无论 IDE 关闭态采用删行还是 `enabledAutoRun: false`，D4 种子化「仅值 true 进基线」口径均安全——false 行 agent 不被 install 重放静默翻转，删行态 agent 不进基线。**design.md D4 种子化口径无需因 OQ2 改动**（实证结论记入本变更记录）。

### ⚠️ 未执行：IDE 实际写入形态（依赖条件）

- 本环境无真实 CodeBuddy IDE 会话，无法实证设置页关闭 Auto Run 时 IDE 写回文件的形态。
- **依赖条件**：需用户在真实 IDE 中对某 project 级 subagent 在设置页 Agent Tab 关闭 Auto Run，随后查看 `.codebuddy/agents/<name>.md` frontmatter：删行态或 `enabledAutoRun: false` 行态。

## OQ3：`enabledAutoRun` 与 `permissionMode`（plan/acceptEdits）的层级关系

### 已验证部分：产物中二者并存形态确认 ✅

- 命令：同上 frontmatter 全量提取（退出码 0）。
- 结果：4 个执行类 agent 均呈「permissionMode 与 enabledAutoRun 并存」形态——coder-lite/coder-standard/coder-senior 为 `permissionMode: acceptEdits` + `enabledAutoRun: true`；tester 为 `permissionMode: plan` + `enabledAutoRun: true`。即产物层二者为独立字段、可同时成立（tester 提供了 plan + AutoRun 并存的实物样本）。
- 官方文档核对（web_fetch https://www.codebuddy.cn/docs/cli/permission-modes 「权限模式」，抓取成功）：
  - 文档给出子代理 permissionMode 七级解析链（显式传入 mode → frontmatter/product config permissionMode → CLI `--subagent-permission-mode` → 环境变量 `CODEBUDDY_SUBAGENT_PERMISSION_MODE` → settings `permissions.subagentPermissionMode` → 代码内继承映射 → 继承主会话），**该链条中不包含 Auto Run / enabledAutoRun**；通篇未出现 `enabledAutoRun`/`Auto Run` 关键词，未描述二者交互。
  - plan 语义：「plan 真正额外放行的只有当前 session 的计划文件写入」，普通 Edit/Bash 委托给进入 plan 前的模式（即 plan 下非计划文件的工具调用仍会 ask）。

**结论（已验证部分）**：官方文档将 permissionMode 的解析链完整文档化且不含 Auto Run 项，两字段在文档层无记载的层级关系；产物层并存形态确认。**Auto Run 是否压制 plan 模式审批无官方文档依据**。

### ⚠️ 未执行：Auto Run 对 plan 模式审批的压制行为（依赖条件）

- **依赖条件**：需用户在真实 CodeBuddy IDE 会话中验证——对 `permissionMode: plan` 的 agent（本套件中为 tester 及 5 个 plan 类 agent）开启 Auto Run 后，触发一次非计划文件的工具调用（如 Bash/Edit），观察是否仍弹审批框。

### 文档口径建议

按 design.md「验证前文档不承诺二者语义正交」，建议 README 双语 AutoRun/安全知情段增补：

> Auto Run 与 `permissionMode`（plan/acceptEdits）的交互行为尚未经官方文档确认；对 plan 模式 agent 开启 Auto Run 前，请在真实 IDE 会话中确认审批行为符合预期（本口径待端到端验证后更新）。

## 附注

- design.md 第 4 个 Open Question（`enabledAutoRun` 是否为 CodeBuddy 稳定 frontmatter 键）不在 tasks.md 4.2 跟踪范围（tasks.md 4.2 仅列前三项）；本记录顺带留证：官方 Subagents 文档示例使用该键，design.md 已声明「若版本间更名，构建映射单点可改」，无需额外动作。
- 本文件为验证记录（docs-only），供 task 4.3 recorder 归档落位；不涉及 core/ 或 dist/ 改动。
