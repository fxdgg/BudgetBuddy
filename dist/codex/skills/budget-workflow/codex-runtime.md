# Codex 平台派工契约

> **本文件为 Codex 平台的派工规范，优先级高于 SKILL.md / goal.md 中的 Task 调用格式块。**
> Codex 端没有结构化 Task 工具（spawn 调用无 subagent_type 参数、无同步阻塞返回），
> 以 `spawn_agent` + `wait_agent` + `close_agent` 三工具组装等价能力。SKILL.md
> 规则 1-8 的流程语义（分级派工、tester/reviewer 不可跳过、委派追踪等）在 Codex
> 端全部保持不变，仅调用形态按本文件执行。

## 前置条件

- `config.toml` 的 `[features]` 段含 `multi_agent = true`（安装器已幂等注入；
  未注入时 spawn_agent 系工具不可用，需手动补齐后重启会话）。
- 角色素材位于 `.codex/skills/budget-workflow/agents/`（项目级安装）或
  `~/.codex/skills/budget-workflow/agents/`（全局安装）；派工 prompt 中需指明
  素材文件路径，供子 agent 对号入座。
- 规则全文位于 `skills/budget-workflow/rules/`（按需读取；AGENTS.md 仅含轻量
  索引，受 32KiB 截断上限约束）。

## 调用模板（三步）

### 第一步：spawn_agent

```
spawn_agent(
  message: "<按七要素组装的派工 prompt，见下节>",
  model: "<查表值，见「三档模型查表」>",
  fork_context: false
)
```

- `fork_context: false` 为固定值：子 agent 不继承主会话上下文，任务输入全部
  写入 message（防上下文漂移与 token 浪费）。
- 返回子 agent 标识（agent id），Leader 记录标识与派工内容后进入等待。

### 第二步：wait_agent

```
wait_agent(
  targets: ["<agent id>", ...],
  timeout_ms: <超时毫秒数>
)
```

- 可同时等待多个已 spawn 的子 agent（并行派工场景，见「并发与深度约束」）。
- 超时未完成不等于失败：先读取已有产出，按 SKILL.md 的续作唤起流程处理，
  禁止盲目销毁重派。

### 第三步：close_agent

```
close_agent("<agent id>")
```

- 结果验收并追加 dispatch log 后关闭，释放会话资源。

## message 七要素组装

派工 prompt（message 参数）必须按以下七要素组装，缺一不可：

| # | 要素 | 说明 |
|---|------|------|
| 1 | 角色职责 | 指明角色名与素材文件路径（如 coder-standard 及其 agents/ 路径），概述该角色的职责边界 |
| 2 | 唯一目标 | 本次派工要完成的唯一明确目标（一次 spawn 只做一件事，不合并任务） |
| 3 | 可信输入 | 任务所需的全部上下文：需求/设计文档路径、相关源文件路径、上游 agent 的结论摘要（子 agent 无共享上下文） |
| 4 | 读写范围 | 允许读写的文件/目录白名单（见「权限边界」） |
| 5 | 验证命令 | 完成后必须运行的自验命令（编译/测试，按角色级别要求） |
| 6 | 结构化输出 | 要求的回报格式（实现报告/审查报告模板，含修改文件清单与自测结果） |
| 7 | 禁止事项 | 明确禁止的行为（越权修改、跳过验证、吞错误等） |

## 三档模型查表

`model` 参数取自 `budget-models.json` 的 `platforms.codex.presets`（部署别名，
需在部署环境将别名映射到实际模型后方可调用）：

| 任务分派 | 档位 | 模型（查表值） |
|---------|------|----------------|
| coder-lite | economic | gpt-5.6-luna |
| coder-standard | balanced | gpt-5.6-terra |
| coder-senior | quality | gpt-5.6-sol |
| 其余角色（architect/reviewer/tester 等） | balanced（默认） | gpt-5.6-terra |

- 档位语义与 router.md 分级派工一致：任务标签路由决定 coder 级别，级别决定
  查表档位；档位查询可用 `budget setup models` / `budget setup show`。
- 模型不可用的逃生门：编辑 `budget-models.json` 的 `platforms.codex.presets`
  （`budget setup models` 指引），或在 spawn_agent 调用中显式传其他 model 值。
  注意 `budget setup agent custom` 在 codex 形态已降级（agent 素材无 frontmatter
  model 可写），不要用它切换模型。

## 并发与深度约束

- **max_depth = 1**：子 agent 不得再派生子 agent（禁止嵌套派工；子 agent 需要
  协作时回报 Leader，由 Leader 编排）。
- **max_threads = 6**：同时在途的子 agent 不超过 6 个。
- **并行规则**：仅当多个任务的**写入范围互不相交**时才可并行 spawn（如两个
  独立模块的实现任务）；实现类任务满足该条件时可并行，**审查与合并必须串行**
  （reviewer / reviewer-b 不得与被审任务的 coder 并行，合并与归档动作串行执行）。
- 每次派工前后必须维护 `agent_dispatch.log`（委派追踪，同 SKILL.md 规则 6）。

## 权限边界（permissions 三态的 Codex 端表达）

Codex 无结构化权限字段，中立源 permissions 三态语义改在 message 第 4 要素中
显式声明：

| 中立源三态 | Codex 端 prompt 声明 |
|-----------|----------------------|
| `edit_allow: ["*"]` | 「允许读写仓库内任务相关文件」 |
| `edit_allow: [具体条目]` | 「仅允许修改以下路径：<条目清单>；其余文件只读」 |
| `edit_allow: []` | 「禁止修改任何文件，仅读取与分析」 |

bash 执行范围（bash_allow）同理在 prompt 中声明允许执行的命令类别（如「仅允许
运行 git status/diff 与构建测试命令」）。子 agent 越界时按流程异常处理：记录
Coder Guard、必要时升级派工（lite→standard→senior）。
