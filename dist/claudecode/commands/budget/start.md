---
description: 启动多 Agent 研发工作流。按 设计→评审→开发→测试→审查→归档 阶段编排不同 agent 完成开发任务
argument-hint: <需求描述>
---

启动多 Agent 研发工作流。

**触发**：用户输入 `/budget:start <需求描述>`（OpenCode 平台调用形式为 `/budget-start <需求描述>`），例如：
- `/budget:start 给用户管理页面增加批量删除功能`
- `/budget:start 修复登录后跳转空白页的 bug`

**两条硬约束（P0，贯穿全流程）**：
1. **主会话是 Leader，只编排不编码**：Leader 负责需求澄清、任务拆分、派发、汇总与仲裁，禁止直接编写业务代码；所有代码产出必须由子代理完成。
2. **派发子代理必须指定 subagent_type**：所有角色必须通过 Task 工具调度，且每次调用必须显式指定 subagent_type（architect / coder-lite / coder-standard / coder-senior / tester / reviewer / reviewer-b / recorder / director / goal-evaluator），禁止不带类型的模糊派发。

**步骤**：

0. **加载角色配置（硬门禁 — 必须在输出任何文字前执行）**
   ```bash
   cat .budget/persona-active.json 2>/dev/null || cat ~/.budgetbuddy/persona-active.json 2>/dev/null
   ```
   - 读取成功 → 使用该主题的 greeting 和 roles 映射
   - 文件不存在 → 使用 default 专业主题，不得编造角色名

1. **澄清需求（无参数时必须先执行）**
   `$ARGUMENTS` 为空或需求模糊时，先与用户澄清目标、范围与验收标准，澄清完成后再进入流程；需求明确时跳过本步。

2. **加载 budget-workflow skill**
   立即加载 budget-workflow skill，按其中定义的阶段流程执行，并将以下需求描述作为输入传递：

   > $ARGUMENTS

3. **遵循阶段门禁**
   - Phase 1（设计）→ 派发 architect
   - Phase 2（评审）→ 派发 reviewer 与 reviewer-b 并行（实现可行性 + 技术合理性）
   - Phase 3（开发）→ 派发分级 coder（coder-lite / coder-standard / coder-senior）+ tester + reviewer 循环
   - Phase 4（最终审查）→ 派发 reviewer
   - Phase 5（归档）→ 派发 recorder

   每个阶段必须有产物才能进入下一阶段，不允许跳过。

4. **状态防护（防 context 稀释脱轨）**
   需求确认完成、openspec change 创建后，立即写入 `start-state.json`：
   ```json
   {
     "current_step": "pipeline-running",
     "change_id": "<change-id>",
     "created_at": "<ISO8601>",
     "completed_steps": [],
     "agent_calls_used": 0,
     "max_agent_calls": 60,
     "updated_at": "<ISO8601>"
   }
   ```
   路径：`openspec/changes/<change-id>/start-state.json`

   **防重复调用**：Leader 调用任何子代理前，必须先检查 `completed_steps` 数组是否包含该步骤标识。如果已存在，跳过调用，直接使用已有产物。调用完成后，将步骤标识追加到 `completed_steps` 并写回文件。步骤标识命名规则详见 budget-workflow skill 的 phases.md「防重复调用机制」章节。

5. **使用当前模型预设**
   不切换预设；如需调整可先运行 `budget setup agent preset <name>`。

---

**注意**：
- 需求模糊时，先加载 brainstorming skill 探索
- 简单 hotfix（一行级修改、文档修改、配置修改）可直接执行，不需走流程
- 用户明确说"不走流程/直接改"时，跳过本流程
