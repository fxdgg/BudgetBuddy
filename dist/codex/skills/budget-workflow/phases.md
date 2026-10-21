## 研发阶段流程

整体流程：用户需求 → Phase 1 方案设计 → Phase 2 方案评审 → Phase 3 代码开发 → Phase 4 最终审查 → Phase 5 归档沉淀

> **Goal Loop 模式**：`/budget:goal` 在标准流程外层包一个目标驱动宏循环，新增 Phase 0（目标定义）和 Phase 6（目标验证）。首轮走完整 Phase 1-5，后续迭代走精简版。完整执行规范见 `goal.md`。

| Phase | Agent | 动作 | 产物 | 流转 |
|-------|-------|------|------|------|
| **Phase 0: 目标定义**（仅 Goal Loop） | Leader | 澄清目标 → 生成 goal.md + goal-state.json | goal.md + goal-state.json | → Phase 1（首轮）|
| **Phase 1: 方案设计** | architect | `/opsx:propose` | proposal.md + design.md + specs/ + tasks.md | → Phase 2 |
| **Phase 2: 方案评审**（多轮闭环） | reviewer + reviewer-b（并行） | 审查 proposal + design + specs | gate-review.md（通过/驳回+具体修改要求） | 通过 → Phase 3；驳回 → 退回 Phase 1 修正后重新评审（最多 3 轮） |
| **Phase 3: 代码开发**（分级分派） | coder-lite/standard/senior + tester + reviewer | Per Task：coder 实现 → tester 验证 → reviewer 审查 | 代码变更 + tasks.md 标记完成 | Review Gate 不通过 → 升级 coder 重做 |
| **Phase 4: 最终审查** | reviewer | 全量 diff 审查 | 审查报告 | 通过 → Phase 5；不通过 → 退回修改 |
| **Phase 5: 归档沉淀** | recorder | `openspec archive` + 经验记录 | 归档完成 + memory 更新 | 单次模式 → 结束；Goal Loop → Phase 6 |
| **Phase 6: 目标验证**（仅 Goal Loop） | tester + reviewer + Leader | 验收标准检查 + 完整性审查 | 验证报告 (iterations/iter-N.md) | 达标 → 归档完成；未达标 → 差距分析 → Phase 3 |

**Phase 2 双 reviewer 模式**：2 个 reviewer 并行评审（不同模型/视角），两者都通过才算通过。

**Phase 3 Per Task 链路**：Leader 判断复杂度 → 分派对应 coder → coder 实现+自测 → tester 编译+测试验证 → reviewer spec 合规+代码质量审查。

## 防重复调用机制（completed_steps 状态锁）

> ⚠️ **Goal Loop 模式注意**：当通过 `/budget:goal` 启动时，本节所有对 `start-state.json` 的引用均应替换为 `goal-state.json`，路径为 `openspec/changes/goal-<slug>/goal-state.json`。`completed_steps` 命名规则也有差异（见本节末尾「Goal Loop 命名规则」）。

> ⚠️ **核心规则**：Leader 调用任何 Agent 前，必须先检查 `start-state.json` 中 `completed_steps` 数组是否包含该步骤标识。如果已存在，**跳过调用**，直接使用已有产物。调用完成后（Agent 返回结果），Leader 必须将步骤标识追加到 `completed_steps` 数组、递增 `agent_calls_used`、向 `agent_dispatch.log` 追加记录，写回 `start-state.json`。
>
> **步骤标识命名规则**：
> - Step 2 architect → `2-architect`
> - Step 3 reviewer-A（按轮次）→ `3-reviewer-a-r<round>`（如 `3-reviewer-a-r1`、`3-reviewer-a-r2`）
> - Step 3 reviewer-B（按轮次）→ `3-reviewer-b-r<round>`
> - Step 4.1 coder（按级别+任务）→ `4.1-coder-<level>-task<N>`（如 `4.1-coder-lite-task1`）
> - Step 4.2 tester（按任务）→ `4.2-tester-task<N>`
> - Step 4.3 reviewer（按任务）→ `4.3-reviewer-task<N>`
> - Step 5 reviewer → `5-reviewer`
> - Step 6 recorder → `6-recorder`
>
> **续作唤起例外**：max_turns 超限后的续作唤起不受 `completed_steps` 限制（因为上一次调用未正常返回），但续作唤起前必须先执行产物检查。
>
> **路径**：`openspec/changes/<change-id>/start-state.json`；状态读写统一经单份状态机脚本 `python3 ${HOME}/.budgetbuddy/lib/budget-state.py`（post-call / step / find / get 子命令）。

> ⚠️ **Goal Loop 命名规则**：当通过 `/budget:goal` 启动时，`completed_steps` 的步骤标识前缀需加上迭代号，格式为 `<iteration>-<step>-<agent>`（如 `0-2-architect`、`1-4.1-coder-lite-task1`）。详见 goal.md「completed_steps 防重复调用」章节。状态文件路径为 `openspec/changes/goal-<slug>/goal-state.json`。

## Superpowers Skills 集成

| 阶段 | 引用的 Superpowers Skill | 用途 |
|------|------------------------|------|
| Step 1 | `brainstorming` | 需求不清晰时先头脑风暴 |
| Step 2 | `writing-plans` | 方案设计的结构化方法 |
| Step 3 | `subagent-driven-development` | Per-task 的实现+审查循环 |
| Step 3 | `test-driven-development` | coder 编码时遵循 TDD |
| Step 3 (bug) | `systematic-debugging` | 修复 bug 时先定位根因 |
| Step 4 | `requesting-code-review` | 最终审查的模板和标准 |
| Step 4 | `verification-before-completion` | 审查前必须运行验证 |
| Step 5 | `finishing-a-development-branch` | 归档前的分支集成决策 |

## Superpowers 与多 Agent 的关系

**Superpowers** 提供研发质量实践（TDD、系统调试、代码审查等），**多 Agent 系统**提供执行架构（谁来执行、用什么模型）。两者是互补关系：

- Superpowers 回答"怎么做才对"（方法论）
- 多 Agent 系统回答"谁来做最省"（成本优化）

当使用 `/budget:start` 时，Leader 会自动在适当时机调用 Superpowers skills 注入质量实践，同时通过分级 coder 控制成本。

### Superpowers 安装检查

在执行工作流前，检查 Superpowers 是否已安装：

```bash
# 检查是否已安装（CodeBuddy 平台）
ls $HOME/.codebuddy/plugins/marketplaces/codebuddy-plugins-official/external_plugins/superpowers/skills/ 2>/dev/null

# 如未安装，提示用户
# "Superpowers 插件未安装，建议安装以获得完整的质量实践支持：
#  在 CodeBuddy Code 中执行 /plugin superpowers"
# OpenCode 平台无原生插件机制，质量实践 skill 的接入方式见安装说明文档
```

## 通知调度（可选，基于 budget-notify）

如果 notify.json 存在且 `enabled: true`，Leader 在关键节点发送通知。

**优先级**：项目 `.budget/notify.json` > 全局 `~/.budgetbuddy/notify.json`。
如果项目中有配置则用项目的，没有则自动降级到全局配置。两者都没有则跳过通知。

### 初始化（Step 1）

Leader 启动时读取 notify.json（`.budget/notify.json` → fallback `~/.budgetbuddy/notify.json`）:
- 不存在或 enabled=false → 跳过所有通知
- enabled=true → 侧加载 channels + events 配置

### 调度规则

1. 检查 events.Nx.enabled 开关
2. 确定渠道列表: events.Nx.channels（按事件声明的渠道列表发送）
3. 调用: `budget notify "<message>" <Nx>`（Nx 为事件名 N1-N11，notify 命令按事件渠道列表投递）
4. 任一成功 (exit 0) 停止，全部失败 `|| true` 静默忽略

### 渠道映射

| 渠道 | 说明 |
|------|------|
| wecom_bot | 企业微信机器人，markdown 消息 |
| dingtalk_bot | 钉钉机器人，markdown + HMAC-SHA256 加签 |
| feishu_bot | 飞书机器人，interactive 卡片 |
| custom | 自定义 webhook，原样 POST |

### 变量来源表

Leader 构造消息模板变量时，从以下位置获取值：

| 变量 | 来源 | 示例 |
|------|------|------|
| `{change_id}` | openspec changes/ 目录名 | `foundation` |
| `{task_id}` | tasks.md 当前 task 编号 | `Task 3` |
| `{round_count}` | 循环计数器 | `3` (升级轮次3) |
| `{done}` / `{total}` | tasks.md [x] 和 [ ] 计数 | `4/6` |
| `{count}` | 阻塞项计数器 (N9) | `3` (3个问题需裁决) |
| `{duration}` | Phase 开始/结束时间差 | `12m` |

## 执行步骤

### Step 0: 加载角色 Persona（每次流程启动时必做）

**Leader 必须在流程开始时读取角色配置，后续所有 Agent 调用都使用角色名。**

```
读取 .budget/persona-active.json（项目级，不存在则读 $HOME/.budgetbuddy/persona-active.json），获取：
- greeting: 对主会话 Leader 的称呼（各主题不同，子 agent 以此称呼汇报）
- roles: 各 agent 的角色名映射（11 键：leader + 十个 agent 角色键，
  其中 roles.leader 为主会话 Leader 的角色名，如 {roles.architect} / {roles.coder-senior}）
- report_templates: 汇报模板

如果两个文件都不存在，使用默认专业名称（architect/coder-senior/...）。
**禁止**：未读取 persona-active.json 就编造角色名（如根据项目名联想无关角色）。
如需切换主题：budget setup persona <name>（name 见 personas.json 主题清单）。
```

### 角色化调度用语

当已启用角色主题（persona-active.json 存在且非 default 主题）时，Leader 在调度 Agent 时应使用**自然的角色化语言**，避免生硬的"调用 XX"句式：

| 生硬写法 ❌ | 自然写法 ✅ |
|------------|-----------|
| "我来调用{roles.architect}" | "让{roles.architect}先看看这个需求" |
| "调动{roles.coder-senior}去实现" | "{roles.coder-senior}，你去把这事儿办了" |
| "启动{roles.director}审查" | "请{roles.director}过目一下代码" |
| "让{roles.reviewer-b}一起看看" | "{roles.reviewer-b}你也看看，有没有疏漏" |
| "调用{roles.coder-standard}来写" | "{roles.coder-standard}，这段代码你来写" |
| "使用{roles.tester}验证" | "{roles.tester}，去试试能不能跑通" |

**核心原则**：
1. **用对话语气**，别用命令/调用口吻。想象你是在跟同事/下属说话，不是在操作机器。
2. **融入角色关系**：读取 `persona-active.json` 中的 `roles` 映射，用实际角色名代入（如 `{roles.architect}` → 三国主题下的军师角色名，或 Tech Legends 主题下的对应人物名）。
3. **description 也要自然**：不要写"{roles.coder-senior} 实现 Task 1"，写"{roles.coder-senior} 去实现批量删除"、"{roles.architect} 出个方案"、"{roles.director} 审一下代码"

**Agent prompt 中的角色注入也保持一致**：
```
// 生硬 ❌
spawn_agent({
  // 没有 subagent_type，会用 Leader 的模型运行！
  prompt: "你是「{roles.coder-senior}」(coder-senior agent)。{motto}。完成后直接输出结果。"
})

// 自然 ✅
spawn_agent({
  subagent_type: "coder-senior",  // 强制使用 coder-senior 绑定的模型与权限
  prompt: "{roles.coder-senior}听令！{motto}。{greeting}让你去搞定这件事：...",
  description: "{roles.coder-senior} 去查日志"
})
```

### Step 1: 初始化

1. **加载 Persona**（读取 `.budget/persona-active.json`，项目级优先，不存在则读 `~/.budgetbuddy/persona-active.json`）

2. **需求澄清**（调用 Superpowers brainstorming）
   - 如果需求模糊、边界不清、用户只说"做个 xxx 功能"：
     - **已安装 Superpowers**：调用 `brainstorming` skill 进行需求探索
     - **未安装 Superpowers**：Leader 自行通过对话澄清需求（一问一答方式）
   - 输出：清晰的需求描述 + 验收标准

3. 检查当前模型预设（`budget setup show`）

   注意：全局安装模式下，所有项目默认共用全局配置。如需某个项目使用自定义配置，可在项目中放置同名文件覆盖全局配置：
   - **Agent 定义**：在 .codex/skills/budget-workflow/agents/（项目级；全局 ~/.codex/skills/…） 下放同名 `.md` 文件，平台自动优先使用项目级
   - **通知配置**：在项目 `.budget/notify.json` 中配置，覆盖全局通知设置
   - **角色主题**：在项目 `.budget/persona-active.json` 中选择不同主题
   - **优先级规则**：项目级 > 全局

4. 加载通知配置（如存在且启用，则导出环境变量供后续通知使用）
   ```bash
   eval "$(bash <budget-notify skill 安装目录>/load-env.sh 2>/dev/null)" || true
   ```
   - `<budget-notify skill 安装目录>` 为本套件安装后的 budget-notify skill 所在位置（项目级优先）；直接调用 `budget notify` 亦可，其内部自动完成双级降级定位
   - 加载后 `$BUDGET_NOTIFY_ENABLED`（"1"/"0"）和 `$BUDGET_NOTIFY_CONFIG` 可用
   - 通知调用：`budget notify "<message>" <Nx> || true`（Nx 为事件名 N1-N11）
   - **消息格式规范**：所有通知统一使用 markdown，包含项目名（当前目录 basename）
     ```
     ### [budget] <emoji> <标题>
     
     > **项目**：`<project>`
     > **详情**：<描述>
     
     <行动指引>
     ```
     示例：
     ```bash
     PROJECT=$(basename "$PWD")
     MSG="### [budget] ✅ Phase 2 评审通过\n\n> **项目**：\`$PROJECT\`\n> **详情**：评审通过，进入代码开发阶段\n\n请回到对话查看"
     budget notify "$MSG" N7 || true
     ```

5. 创建 openspec change

### Step 2: 方案设计（architect agent）

> ⚠️ **防重复调用（状态锁）**：调用前先检查 `start-state.json` 中 `completed_steps` 是否已包含 `2-architect`。如果已存在，**跳过本步**，直接使用已有方案产物。
>
> **调用后置位**：Agent 返回后，执行 `python3 ${HOME}/.budgetbuddy/lib/budget-state.py post-call --step "2" --agent "architect" --step-id "2-architect" --task "方案设计"`（自动递增 agent_calls_used、追加 completed_steps、追加 dispatch log）。

**前置**：调用 `writing-plans` 获取计划编写方法论。

**⚡ 必须通过 spawn_agent 工具派发子代理调用 architect（角色化语言）：**
```
spawn_agent({
  subagent_type: "architect",
  prompt: "{roles.architect}，{motto}。{greeting}让你为以下需求出个方案。\n\n完成后直接输出结果。\n\n---\n\n<需求描述>\n\n请执行 /opsx:propose 生成完整的 openspec artifacts（proposal.md + design.md + specs/ + tasks.md）。",
  description: "{roles.architect} 出个方案",
  max_turns: 80
})
```

Leader 收到 architect 返回的方案后，确认产物存在再进入下一步。

> 🔄 **architect max_turns 超限恢复**：适用 SKILL.md 通用恢复流程。检查 `openspec/changes/<change-id>/` 下已产出文件（proposal.md / design.md / specs/ / tasks.md），续作唤起时注入已有产物列表。

### Step 3: 方案评审（双 reviewer 并行 — 闭环验证）

> ⚠️ **防重复调用（状态锁）**：调用前先检查 `start-state.json` 中 `completed_steps` 是否已包含当前轮次的 `3-reviewer-a-r<round>` 和 `3-reviewer-b-r<round>`。如果已存在，**跳过本步**，直接使用已有评审结论。每轮评审的 round 编号递增（第 1 轮 r1，被驳回后第 2 轮 r2，最多 r3）。
>
> **调用后置位**：每个 reviewer 返回后，执行 `python3 ${HOME}/.budgetbuddy/lib/budget-state.py post-call --step "3" --agent "<reviewer或reviewer-b>" --step-id "3-reviewer-<a|b>-r<round>" --task "方案评审"`（自动递增 agent_calls_used、追加 completed_steps、追加 dispatch log）。

**⚠️ 核心规则：architect 修正后必须重新评审，直到两个 reviewer 都通过才能进入开发。**

**所有预设都使用双 reviewer 并行评审：**

Leader 必须同时发起 2 个 reviewer agent，分别从不同视角审查：

```
// reviewer-A：实现可行性视角（并行发起）
spawn_agent({
  subagent_type: "reviewer",
  prompt: "{roles.reviewer}，请帮忙审一下这份方案，重点看能不能落地。\n\n完成后直接输出结果。\n\n---\n\n评审以下变更的设计方案：\n- 变更目录: openspec/changes/<change-id>/\n- 你的审查视角：【实现可行性】\n- 重点关注：代码能否写对、边界情况是否覆盖、复杂度估算是否合理、是否可测试\n- 按以下维度评估：落地可行性、可测试性、复杂度、边界情况\n- 输出评审意见\n- 必须给出明确结论：【通过】或【驳回 + 具体问题列表】",
  description: "{roles.reviewer} 审一下方案",
  max_turns: 40
})

// reviewer-B：技术合理性视角（并行发起，跨配置交叉辅审）
spawn_agent({
  subagent_type: "reviewer-b",
  prompt: "{roles.reviewer-b}，你也来审审，从不同角度看看有没有遗漏。\n\n完成后直接输出结果。\n\n---\n\n评审以下变更的设计方案：\n- 变更目录: openspec/changes/<change-id>/\n- 你的审查视角：【技术合理性】\n- 重点关注：需求是否完整、逻辑是否自洽、安全性是否有保障、是否有遗漏场景\n- 按以下维度评估：需求完整性、技术合理性、安全性、稳定性\n- 输出评审意见\n- 必须给出明确结论：【通过】或【驳回 + 具体问题列表】",
  description: "{roles.reviewer-b} 也审一下方案",
  max_turns: 40
})
```

**双 reviewer 的模型配置**：主审（reviewer）与辅审（reviewer-b）分别绑定不同模型，形成跨视角交叉验证；具体模型由当前预设决定，可用 `budget setup show` 查看。

**双 reviewer 通过规则：**
- 两者都通过 → 进入 Step 4
- 任一驳回 → 合并两者意见，退回 architect 修正
- 两者意见冲突 → Leader 仲裁（取更严格的那个）

**评审闭环流程（不论单/双 reviewer，最多 3 轮）：**

1. **第 1 轮**：architect 提交方案 → reviewer(s) 评审
   - 通过 → **直接进入 Phase 3（Step 4 代码开发），不需要向用户确认**
   - 驳回 → 退回 architect 修正，进入第 2 轮
2. **第 2 轮**：architect 修正方案（基于 reviewer 具体意见）→ reviewer(s) 重新评审（⚠️ 不可跳过此步）
   - 通过 → **直接进入 Phase 3，不需要向用户确认**
   - 驳回 → 退回 architect 再次修正，进入第 3 轮
3. **第 3 轮**：architect 再次修正 → reviewer(s) 三审
   - 通过 → **直接进入 Phase 3，不需要向用户确认**
   - 驳回 → 暂停，向用户报告分歧点

**通知规则：**
- **通过时（N7）**：如 notify 启用，执行：
  ```bash
  PROJECT=$(basename "$PWD")
  MSG="### [budget] ✅ Phase 2 评审通过\n\n> **项目**：\`$PROJECT\`\n> **详情**：设计方案评审通过，进入开发阶段\n\n请回到对话查看"
  budget notify "$MSG" N7 || true
  ```
- **第 3 次驳回时（N1）**：如 notify 启用，执行：
  ```bash
  PROJECT=$(basename "$PWD")
  MSG="### [budget] ⚠️ Phase 2 第3次驳回\n\n> **项目**：\`$PROJECT\`\n> **详情**：Phase 2 第3次被驳回，需用户裁决\n\n请回到对话查看"
  budget notify "$MSG" N1 || true
  ```

**⚠️ 关键约束：architect 修正后绝不能直接进入开发，必须经 reviewer 重新确认通过。**

这与代码开发阶段的 Review Gate 逻辑一致——任何修改都需要重新审查才能流转到下一阶段。

### Step 4: 代码开发（分级 coder 分派）

**前置**：调用 `subagent-driven-development` 获取 per-task 编排模式。

按 tasks.md 逐任务执行。**每个任务必须严格走完 coder → tester → reviewer 三步，不可跳过任何一步。**

**Per Task Loop（强制完整执行）:**

#### 4.1 分派 coder（通过 spawn_agent 工具派发子代理）

> ⚠️ **防重复调用（状态锁）**：调用前先检查 `start-state.json` 中 `completed_steps` 是否已包含 `4.1-coder-<level>-task<N>`。如果已存在，**跳过本步**，直接使用已有代码产物。Review Gate 升级时，新的级别标识不同（如 `4.1-coder-standard-task1`），不触发跳过。
>
> **调用后置位**：Agent 返回后，执行 `python3 ${HOME}/.budgetbuddy/lib/budget-state.py post-call --step "4.1" --agent "coder-<level>" --step-id "4.1-coder-<level>-task<N>" --task "代码实现 Task<N>"`（自动递增 agent_calls_used、追加 completed_steps、追加 dispatch log）。

Leader 判断复杂度后，**必须通过 spawn_agent 工具派发子代理** spawn 对应 coder（分级路由规则见 router.md）：

> ⚠️ **max_turns 按级别调整**：以下模板默认 `max_turns: 35`（coder-lite 级别），实际分派时按下表替换：
> | coder 级别 | max_turns |
> |-----------|-----------|
> | coder-lite | 35 |
> | coder-standard | 50 |
> | coder-senior | 70 |

```
spawn_agent({
  subagent_type: "coder-<level>",
  prompt: "{roles.coder-<level>}，{greeting}让你去把这事办了。\n\n---\n\n## 任务描述\n<明确的任务描述>\n\n## 任务标签\n<标签列表>\n\n## 相关文件\n- <file_path:line>\n\n## 参照代码\n- <file_path:line — 类似实现位置>\n\n## 设计要求\n<从 design.md 摘取>\n\n## 代码规范\n读取 skills/budget-workflow/rules/（按需读取；AGENTS.md 仅含轻量索引） 下对应语言的规范条目，严格遵循。不要尝试搜索确认路径存在性，直接读取。\n\n完成后输出实现报告。",
  description: "{roles.coder-<level>} 去实现批量删除",
  max_turns: <按级别替换: coder-lite=35 / coder-standard=50 / coder-senior=70>
})
```

#### 4.2 tester 验证（不可跳过 ⚠️）

> ⚠️ **防重复调用（状态锁）**：调用前先检查 `start-state.json` 中 `completed_steps` 是否已包含 `4.2-tester-task<N>`。如果已存在，**跳过本步**，直接使用已有测试结果。coder 自修复重试时使用后缀区分（如 `4.2-tester-task1-retry1`）。
>
> **调用后置位**：Agent 返回后，执行 `python3 ${HOME}/.budgetbuddy/lib/budget-state.py post-call --step "4.2" --agent "tester" --step-id "4.2-tester-task<N>" --task "测试验证 Task<N>"`（自动递增 agent_calls_used、追加 completed_steps、追加 dispatch log）。

**coder 返回结果后，Leader 必须立即调用 tester agent 验证。**

```
spawn_agent({
  subagent_type: "tester",
  prompt: "{roles.tester}，去试试刚才写的代码能不能跑通。\n\n完成后直接输出结果。\n\n---\n\n验证刚完成的代码修改：\n\n## 修改文件\n<从 coder 报告中提取>\n\n## 验证要求\n1. 编译是否通过\n2. 相关测试是否通过\n3. 如有新功能，是否有对应测试覆盖\n\n## 证据强制（不可跳过）\n每项结论必须附带：实际执行命令、退出码、原始输出摘要（PASS/FAIL 统计行）。禁止只给结论不给证据，禁止编造通过结论。未实际执行的验证标注⚠️未执行。\n\n跑完给个结果，别漏了什么。",
  description: "{roles.tester} 跑一遍测试",
  max_turns: 40
})
```

**tester 结果处理：**
- ✅ 通过 → 进入 4.3 reviewer 审查
- ❌ 失败 → coder 自修复（同级重试最多 2 次），超过则升级

#### 4.3 reviewer 审查（不可跳过 ⚠️）

> ⚠️ **防重复调用（状态锁）**：调用前先检查 `start-state.json` 中 `completed_steps` 是否已包含 `4.3-reviewer-task<N>`。如果已存在，**跳过本步**，直接使用已有审查结论。Review Gate 升级时使用后缀区分（如 `4.3-reviewer-task1-gate2`）。
>
> **调用后置位**：Agent 返回后，执行 `python3 ${HOME}/.budgetbuddy/lib/budget-state.py post-call --step "4.3" --agent "reviewer" --step-id "4.3-reviewer-task<N>" --task "代码审查 Task<N>"`（自动递增 agent_calls_used、追加 completed_steps、追加 dispatch log）。

**tester 通过后，Leader 必须立即调用 reviewer agent 审查。**

```
spawn_agent({
  subagent_type: "reviewer",
  prompt: "{roles.reviewer}，代码写完了，请过目。\n\n完成后直接输出结果。\n\n---\n\n审查 Task N 的代码实现：\n\n## 修改文件\n<从 coder 报告中提取>\n\n## 设计规格\n<从 design.md 摘取对应部分>\n\n## 审查要求\n0. 【文件范围审计 — 最先执行】执行 git diff --name-only 获取实际变更文件，与 design.md 文件范围章节比对。超出范围的文件变更直接判定不通过，列出超出范围文件。\n1. 代码是否符合 design.md 设计要求\n2. 错误处理是否完备\n3. 命名和代码风格是否符合项目规范\n4. 是否引入潜在 bug 或安全问题\n5. 是否有遗漏的边界情况\n\n给个明确结论：【通过】或【不通过 + 具体问题列表】",
  description: "{roles.reviewer} 审一下代码",
  max_turns: 40
})
```

**reviewer 结果处理（任务完成标准）：**
- ✅ 通过 → 任务完成，标记 tasks.md 对应条目（[x]）；任务完成标准 = tester 验证通过 **且** reviewer 审查通过，两者缺一不可
- ❌ 不通过 → 触发 Review Gate 升级（见下方升级机制）

#### 4.4 Review Gate 升级处理

不通过时，Leader 必须：
1. 记录本轮失败信息
2. 升级到更高级 coder（lite→standard→senior）
3. 重新走 4.1→4.2→4.3 完整流程
4. 升级后的 coder prompt 中必须包含前一轮 reviewer 的具体意见

**独立任务并行**：当 3+ 个任务互相独立时，可并行发起多个 Agent 调用。但每个任务内部的 coder→tester→reviewer 链路仍必须串行。

> ⚠️ **委派日志**：每个 task 的 coder/tester/reviewer 调用完成后，执行 `python3 ${HOME}/.budgetbuddy/lib/budget-state.py post-call --step "4.x" --agent "<agent_type>" --task "<简述>"`（自动追加 agent_dispatch.log 并递增 agent_calls_used）。**所有 Agent 调用**（不限于此处）均需追加记录。这用于委派门禁检查（见 SKILL.md 委派门禁章节）。

**通知(N8)**: 如 notify 启用, PROJECT=$(basename "$PWD"); MSG="### [budget] ✅ Phase 3 代码开发完成\n\n> **项目**：\`$PROJECT\`\n> **详情**：{total}个任务全部通过\n\n请回到对话查看"; budget notify "$MSG" N8 || true

> ⚠️ **自动衔接（强制）**：Phase 3 全部任务通过后，Leader **直接进入 Step 5 最终审查**，不需要向用户确认。禁止在 Phase 3→4 衔接时暂停等待用户回复或询问"是否继续"。同理，Phase 3 内部每个 task 的 coder→tester→reviewer 链路全部自动执行，task 之间不暂停。

#### 4.5 循环兜底与驳回应急

**目标**：避免 agent 间无限互相驳回，保证流程在有限次数内收敛。

**「轮」的计算方式**：每次 coder→tester→reviewer 完整链路记为一轮。

**循环上限（6 次）**：单任务自动恢复机会总数上限 6 次——3 轮分级 review（lite→standard→senior 各一轮）+ 2 次同级 tester 自修复 + 1 次 Director 终裁兜底。当任务循环超过 5 轮时即触发强制暂停（N3）；6 次机会全部耗尽后必须请用户裁决（N4/N9），禁止继续自动重试。

**Phase 3 Per-Task 循环（含升级机制）**：

| 情况 | 动作 |
|------|------|
| 编译/测试失败 (1-2次) | 同级 coder 自修复 |
| 编译/测试失败 (3次) | 升级到更高级 coder |
| review 不通过 (升级轮次1) | 升级到 coder-standard（或当前级别+1） |
| review 不通过 (升级轮次2) | 升级到 coder-senior |
| review 不通过 (升级轮次3) | **暂停任务**，进入 3 轮驳回应急 |

**通知(N2)**: 如 notify 启用, PROJECT=$(basename "$PWD"); MSG="### [budget] ⚠️ Task 3轮审查未通过\n\n> **项目**：\`$PROJECT\`\n> **详情**：lite→standard→senior 均未通过\n\n请回到对话查看"; budget notify "$MSG" N2 || true

**通知(N3)**: 如 notify 启用, PROJECT=$(basename "$PWD"); MSG="### [budget] ⚠️ Task 循环超5轮触发暂停\n\n> **项目**：\`$PROJECT\`\n> **详情**：任务循环超过5轮，已触发暂停\n\n请回到对话查看"; budget notify "$MSG" N3 || true

**3 轮驳回应急（升级路径）**：

lite(1轮) → standard(2轮) → senior(3轮) → Leader 根因分析 → Director 终裁 → 用户裁决

当 lite → standard → senior 都未能通过 review 时，Leader 必须执行根因分析流程（而不是直接抛给用户）：读取全部 3 轮实现报告 + reviewer 意见，判断失败根因并归入六类分型之一（A 设计缺陷 / B 任务过大 / C reviewer 误判 / D 需求不清 / E 能力天花板 / F 环境限制），按分型执行对应自救策略（architect 重评估 / 拆分任务 / Leader 仲裁换审 / 重新澄清需求 / 跳过环境阻塞）。详细分派细则与自救策略见 router.md「3轮失败应急处理」。

**Director 终裁（六类裁决）**：

当 Leader 的自救策略全部耗尽（或根因为能力天花板）时，Leader 召唤 director agent 做最终裁决（调用模板与激活条件见 router.md「Director 终裁」）。Director 只读不写，基于失败简报输出六类裁决之一：

| 分类 | 判定 | Director 动作 | 流程走向 |
|------|------|-------------|---------|
| A - 设计缺陷 | architect 方案本身有问题 | 标注 design.md 缺陷点与修改方向，交 architect 修订 | 回到 Phase 3（1 次机会） |
| B - 任务过大 | 需求应拆分为子任务 | 输出拆分建议（N 个任务 + 描述） | Leader 拆分后重新分派 |
| C - reviewer 误判 | 某轮实现其实可接受 | 标注被误判的轮次和理由 | Leader 接受该实现，task 完成 |
| D - 需求不清 | 原始需求有歧义/矛盾 | 列出需用户澄清的具体问题 | → 上升用户裁决，附带 Director 问题 |
| E - 能力天花板 | 当前模型组合确实做不到 | 建议切 quality 预设或手动接管 | → 上升用户裁决，附带 Director 分析 |
| F - 环境限制 | 缺少依赖/权限/配置 | 列出缺失项 | → 上升用户裁决，附带清单 |

**裁决后的流程**：
- A/B/C → 流程**自动恢复**，用户不被打断（继续修复 / 拆任务重派 / 接受实现）。
- D/E/F → 进入用户裁决，但用户收到的报告已附带 Director 的分析结论（不再是一堆原始失败日志）。

**通知(N4)**: 如 notify 启用, PROJECT=$(basename "$PWD"); MSG="### [budget] ⚠️ 自动恢复策略耗尽, 需最终裁决\n\n> **项目**：\`$PROJECT\`\n> **详情**：含 Director 在内的所有自动恢复策略已耗尽\n\n请回到对话查看"; budget notify "$MSG" N4 || true

**用户裁决（最终兜底）**：

当以上所有策略（含 Director）都无法解决问题时，向用户呈现完整上下文：

**通知(N9)**: 如 notify 启用, PROJECT=$(basename "$PWD"); MSG="### [budget] ⚠️ {count}个问题需您拍板\n\n> **项目**：\`$PROJECT\`\n> **详情**：{count}个问题需要您裁决\n\n请回到对话查看"; budget notify "$MSG" N9 || true

```markdown
## ⚠️ 任务阻塞 — 需要您裁决

**任务**: Task X (<描述>)
**已尝试**: lite → standard → senior + architect 重评估 + Director 终裁
**根因分析**: <Leader 判断的根因类型>

**3 轮实现概要**:
- lite: <实现思路> — 未通过原因: <...>
- standard: <实现思路> — 未通过原因: <...>
- senior: <实现思路> — 未通过原因: <...>

**可选方案**:
1. 【接受当前实现】有已知风险/限制，但可运行
2. 【手动修复】您提供具体修改方向，Leader 转述给 coder
3. 【降低验收标准】调整 reviewer 的通过标准（如跳过某些检查）
4. 【搁置任务】标记为 block，等外部条件成熟后再处理
5. 【其他】您有其他建议
```

**整体流程兜底**：

| 情况 | 动作 |
|------|------|
| 单次任务循环超过 5 轮 | 强制暂停，向用户汇报阻塞点（N3） |
| 同一阶段反复退回 ≥3 次 | 升级到主对话请用户裁决 |
| context 接近用满 | 主动建议 `/clear` 后用 openspec 状态恢复 |
| context 稀释后重复 spawn 同一 Agent | 读取 `start-state.json` 的 `completed_steps`，跳过已完成的步骤 |

### Step 5: 最终审查（reviewer agent）

> ⚠️ **防重复调用（状态锁）**：调用前先检查 `start-state.json` 中 `completed_steps` 是否已包含 `5-reviewer`。如果已存在，**跳过本步**，直接使用已有最终审查结论。最终审查不通过退回修复后，重新审查使用后缀区分（如 `5-reviewer-r2`）。
>
> **调用后置位**：Agent 返回后，执行 `python3 ${HOME}/.budgetbuddy/lib/budget-state.py post-call --step "5" --agent "reviewer" --step-id "5-reviewer" --task "最终审查"`（自动递增 agent_calls_used、追加 completed_steps、追加 dispatch log）。

**⚡ 全部 tasks 完成后，必须做最终全量审查。不可跳过。直接调用 reviewer agent 执行，不需要向用户确认是否继续。**

**前置**：调用 `verification-before-completion` 确保验证已执行。

```
spawn_agent({
  subagent_type: "reviewer",
  prompt: "{roles.reviewer}，全部改完了，最后再过一遍。\n\n完成后直接输出结果。\n\n---\n\n对本次完整变更做最终审查：\n\n## 审查范围\n- 【文件范围审计 — 最先执行】执行 git diff --name-only 获取全部变更文件，与 design.md 文件范围章节比对。超出范围的文件变更直接判定不通过。\n- 查看全量 git diff（使用 Bash 执行 git diff）\n- 检查跨任务一致性\n- 检查代码规范合规（读取 skills/budget-workflow/rules/（按需读取；AGENTS.md 仅含轻量索引） 对应规范）\n- 验证无遗留 TODO/FIXME\n- 检查是否有冲突或重复代码\n- 【测试逻辑验证】独立检查测试代码逻辑是否正确（claim key/参数名/断言期望值是否与实现一致），不信任 tester 报告的通过结论\n\n## 必须输出\n- 审查结论：【通过 / 不通过】\n- 如不通过：列出具体问题和建议修复方案",
  description: "{roles.reviewer} 最终再过一遍",
  max_turns: 40
})
```

**最终审查不通过** → 根据问题分派对应 coder 修复 → 修复后再次调用 tester + reviewer（最多 2 轮，超过则暂停向用户报告阻塞点）
**最终审查通过** → 进入 Step 6

### Step 6: 归档与 Coder Guard 更新（recorder agent）

> ⚠️ **防重复调用（状态锁）**：调用前先检查 `start-state.json` 中 `completed_steps` 是否已包含 `6-recorder`。如果已存在，**跳过本步**，直接使用已有归档结果。
>
> **调用后置位**：Agent 返回后，执行 `python3 ${HOME}/.budgetbuddy/lib/budget-state.py post-call --step "6" --agent "recorder" --step-id "6-recorder" --task "归档沉淀"`（自动递增 agent_calls_used、追加 completed_steps、追加 dispatch log）。

**前置**：调用 `finishing-a-development-branch` 决定分支集成策略（merge/PR/keep）。

```
spawn_agent({
  subagent_type: "recorder",
  prompt: "{roles.recorder}，活干完了，记一下档。\n\n完成后直接输出结果。\n\n---\n\n归档本次变更：\n\n1. 执行 openspec archive <change-id> -y\n2. 提取本次开发的关键经验和决策\n3. 更新 Coder Guard 记录（$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json，如有 review 升级/失败记录）\n4. 记录格式参照 agent 配置中的规范",
  description: "{roles.recorder} 记下档",
  max_turns: 30
})
```

**通知(N10)**: 如 notify 启用, PROJECT=$(basename "$PWD"); MSG="### [budget] ✅ 全流程完成\n\n> **项目**：\`$PROJECT\`\n> **详情**：{done}/{total}任务通过，已归档\n\n请回到对话查看"; budget notify "$MSG" N10 || true

**Coder Guard 记录格式**：
```json
{
  "history": [
    {
      "timestamp": "2026-06-02T12:00:00Z",
      "coder": "coder-lite",
      "tags": ["api_endpoint", "cross_module"],
      "result": "review_rejected",
      "escalated_to": "coder-standard"
    }
  ],
  "summary": {
    "coder-lite": {
      "api_endpoint": {"total": 5, "success": 2, "failure": 3}
    }
  }
}
```
