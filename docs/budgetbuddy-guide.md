# BudgetBuddy 接入指南与落地实践：一支分工明确、门禁严格的多 Agent 编排的 AI 研发团队

> **一句话定位**：BudgetBuddy 是一套开源（MIT）的多 Agent 研发工作流——把研发拆成 **10 个职责明确的角色**，用**五阶段门禁**与**编排**，把 AI 从"随手 vibe"变成一支能交付的生产团队。省钱不是它的卖点，而是分工与门禁带来的自然结果。

**版本**：v0.4.0 ｜ **平台**：CodeBuddy / OpenCode / Claude Code / Codex（单一 `core/` 源头构建四平台产物）｜ **仓库**：github.com/fxdgg/BudgetBuddy

***

## 写在前面：单个 AI 很能写代码，但它不是一个"团队"

过去一年，几乎每个团队都经历了同一条曲线：先是惊叹 AI 能写代码，然后把所有需求一股脑丢给同一个"全能 AI"，最后发现交付并不可控——没人做方案、没人独立审查、没人跑验证、出了问题没人兜底。

问题不在于模型的智商，而在于**我们一直把 AI 当"一个人"用，而不是当"一支团队"用**。真实的研发从来不是"一个高手从头写到尾"，而是分工协作：

- 有人**做方案**；
- 有人**写实现**（并按难度分给不同水平的工程师）；
- 有人**独立审查**；
- 有人**跑验证**；
- 有人**兜底裁决**；
- 有人**沉淀经验**。

缺了这套结构，AI 就只能"边想边写、边写边改"——看似很快，实则没有门禁、没有退出条件、没有可复用的经验。

我们在 AI 落地实践里反复看到一个共识：

- **"阶段不可合、门禁不可省"**——决定交付质量的，是流程里的**退出条件**，而不是模型的智商；
- **"避免廉价习得感"**——一次生成几百行看着很爽，但没有审查、没有验证、没有沉淀，返工成本远高于省下的时间；
- **"Agent 完成 ≠ 业务完成"**——必须有独立角色对"是否真的达成目标"做判定。

BudgetBuddy 就是把这些"团队结构"显式地工程化：**10 个角色分工、五阶段门禁、一个只编排不写码的 Leader、一套会收敛的循环**。它不追求"更聪明的 prompt"，而是用**分工、门禁、编排**，把 AI 研发从"随手 vibe"变成可交付的生产线。

***

## 一、问题的本质：缺的不是模型，是"团队结构"

把一个"全能 AI"当成研发团队，会同时暴露四类**结构性问题**——它们都不是"换一个更强的模型"能解决的。

| 结构缺失 | 具体表现 | 后果 | BudgetBuddy 的补法 |
| --- | --- | --- | --- |
| **缺分工** | 方案、实现、审查、验证、兜底全压在同一个 agent 上 | 职责混乱、上下文膨胀、无法按难度分级 | **10 个专职 Agent + 三级 coder** |
| **缺门禁** | 写完就合并，没有独立审查与验证 | 缺陷流到下游，返工 | **五阶段闸门 + tester/reviewer 双门禁** |
| **缺编排** | 没有阶段、没有退出条件，AI 自我循环 | 不可收敛、不可预测 | **Leader 编排 + 有限循环 + Director 终裁** |
| **缺记忆** | 同一个坑反复踩，踩过就忘 | 重复浪费 | **Coder Guard + recorder 沉淀** |

> 一句话：**单 Agent 不是"能力不够"，而是"结构不对"。** 用错模型、撑爆上下文、反复返工这些"贵"的现象，都只是结构缺失的症状，而非病因。

***

## 二、三条不变式：分工、门禁、编排

BudgetBuddy 的所有机制，都能归到三条"不变式"上——它们分别对应**分工**、**门禁**、**编排**。理解了这三条，后面的功能都能自己推导出来。

### 2.1 不变式一：编排与执行分离——Leader 绝不写代码

`leader` 只做四件事：分析需求、组装 prompt、路由任务、汇总结果。**任何代码修改，哪怕一行 typo，都必须委派给分级 coder agent 执行。**

这条规则的收益是双重的：

- **可控**：执行被收敛到少数几个"有权限、有模型、有护栏"的角色上，审查与降级才有抓手；
- **成本（附带）**：Leader 的上下文不因读代码/写代码而膨胀——这是好处，但不是目的。

> 配套的可观测性：子 agent 调度会写入 `agent_dispatch.log`，用于事后自检"Leader 是否偷偷自己动手了"。

### 2.2 不变式二：按复杂度分级 + 按角色配模型

不是"全流程同一个模型"，而是"**同一流程内，不同角色用不同模型**"：

- 任务按复杂度分三级 coder：`coder-lite` → `coder-standard` → `coder-senior`；
- 角色按能力需求配模型：推理型（architect / reviewer）用 reasoning 模型，代码型（coder-\*）用 code 模型，执行型（tester）用 agent 模型，总结型（recorder）用廉价模型。

### 2.3 不变式三：有限循环 + 显式兜底

AI 最危险的不是写错，而是**在错误方向上无限自我循环**。所以每个环节都有明确的**上限与出口**：

- 同级自修复最多 2 次；
- 审查不通过逐级升档，最多 3 轮；
- 单任务循环上限 5 轮（3 轮升级 + 2 次自修复）；
- 3 轮全败 → `director` 六类根因分型，A/B/C 自动恢复，D/E/F 上报用户；
- Goal Loop 最多 8 轮 / 80 次 agent 调用 / 连续 3 轮无进展即停。

**不靠"更聪明的 prompt"收敛，靠状态机与上限收敛。**

***

## 三、整体架构：四层 + 单一中立源

### 3.1 四层结构

| 层 | 组成 | 解决的问题 |
| --- | --- | --- |
| **角色层** | 10 个 agent 定义（`core/agents/*.md`） | 谁来做、权限边界、职责隔离 |
| **流程层** | 五阶段工作流 + openspec 变更管理（`core/skills/`） | 什么时候做、退出条件、产物 |
| **模型层** | 三档预设 + 模型目录（`core/models/budget-models.json`） | 用什么模型、多少钱 |
| **数据层** | guard / state / notify 三个 JSON（`core/lib/`） | 记忆、护栏、通知落盘 |

一个可直接复用的抽象是：**每一层都有"上限 + 降级 + 落盘"三件套**。角色层有权限最小化与降级路由，流程层有循环上限与终裁，模型层有档位与倍率，数据层有状态文件与日志。缺任何一件，系统都会在长任务里失控。

### 3.2 单一中立源 → 四平台产物

```
core/  (单一中立源，只在这里改)
  │  scripts/build.py + core/platform/*.yaml (平台映射 DSL)
  ▼
dist/  (生成物，禁止手改)
  ├── codebuddy/    → .codebuddy/ 或 ~/.codebuddy/
  ├── opencode/     → .opencode/ 或 ~/.config/opencode/
  ├── claudecode/   → .claude/ 或 ~/.claude/
  └── codex/        → .codex/skills/ 或 ~/.codex/skills/
```

**为什么要单一源**：多平台最容易腐化的是"四份配置各改各的、行为逐渐分叉"。`core/` + 平台 YAML 让"角色、规则、流程、模型"只有一份真相，平台差异被收敛为**声明式映射**。

最典型的是**权限三态映射**——同一份 agent frontmatter（`edit_allow` / `bash_allow`）被编译成三种平台方言：

| 平台 | 权限表达 |
| --- | --- |
| CodeBuddy / Claude Code | \`permissionMode: acceptEdits |
| OpenCode | `permission` map（ask / allow / deny） |
| Codex | 无 frontmatter 模型/权限——丢弃，由 Leader 在 spawn prompt 中声明 |

### 3.3 安装契约：manifest + SHA256 增量同步

`scripts/build.py` 在构建期生成 `dist/<platform>/.manifest.json`；安装器 `install.sh` 下载 release 后**强制 SHA256 校验**，再按 manifest 做**增量同步**：

- 官方文件哈希变了才覆盖；
- **非官方文件（用户自建 agent、业务 skill）一律保留**；
- 安装根目录记录 manifest，供升级差集清理与离线卸载。

> 这条"声明式文件 + 内容哈希 + 唯一写入者"的契约，是团队能安全升级、又敢自定义的前提。**不要用 IDE 面板去编辑这些 agent 文件**——面板会把 `Read` 改写成 `read_file`、追加 `agentMode/enabled` 等非规范字段，直接破坏哈希一致性。

***

## 四、核心功能详解

### 4.1 十个专业 Agent：把一个"全能 AI"拆成一支"分工明确的团队"

BudgetBuddy 不依赖单个"超级 agent"，而是把研发链路拆成 10 个职责单一的 sub-agent。这不是为了好看，而是为了让**每个角色都能被单独配模型、单独限权限、单独度量**。

| Agent | 层级 | 职责 | 关键约束 |
| --- | --- | --- | --- |
| `leader` | 编排 | 分析需求、组装 prompt、路由任务 | **绝不写代码** |
| `architect` | 设计 | 方案设计、文档撰写、闸门评审 | 产出 `proposal.md` + `design.md` |
| `reviewer` | 审查 | 主审：质量、安全、规格一致性 | **只读**，不给 Write/Edit |
| `reviewer-b` | 审查 | 辅审：独立视角交叉复核 | 与主审并行，**不阻塞** |
| `coder-lite` | 实现 | CRUD、配置、样板、文案 | 最低成本档 |
| `coder-standard` | 实现 | 常规功能、bug 修复、API、单测 | 中档 |
| `coder-senior` | 实现 | 架构性代码、跨模块、安全、并发 | 最高成本档 |
| `tester` | 验证 | 跑测试、验证编译、检查构建 | **纯验证**，不写业务代码 |
| `director` | 兜底 | 3 轮全败时终裁（A–F 根因分型） | 默认只调一次 |
| `recorder` | 沉淀 | 记录经验、归档变更、更新文档 | 写入 guard 记录 |

**权限最小化的三个刻意设计**：

1. **reviewer 只读**：审查者的职责是"发现问题"，不是"顺手改掉"。不给 Write/Edit，从机制上杜绝"审查者越权改代码导致既当运动员又当裁判"。
2. **tester 纯验证**：只给 Read/Bash/Grep/Glob，不写代码；发现问题反馈给 coder 修复。
3. **子 agent 不给 `use_skill`**：Skill 的调用是 Leader 的职责。如果子 agent 能自行调用 Skill，就可能绕过 Leader 的编排，破坏工作流的控制模型。

### 4.2 五阶段工作流：每个阶段都有唯一产物和退出条件

```
① 方案设计        ② 方案双审           ③ 分级实现（逐任务）      ④ 复审与回归      ⑤ 归档
architect    →   reviewer +      →    coder-lite/std/senior  →  reviewer    →  recorder
                  reviewer-b           → tester → reviewer
产物:                  产物:                 产物:                    产物:            产物:
proposal.md          gate-review.md        代码 + 测试结果          最终审查报告      归档 + guard 更新
design.md            (双审通过才放行)       (每任务独立过闸)
```

**五个阶段不可跳过**，但真正重要的是每个阶段的**退出条件**：

| 阶段 | 退出条件 | 不满足时 |
| --- | --- | --- |
| 方案设计 | `proposal.md` + `design.md` 产出完整 | 回到 architect 补充 |
| 方案双审 | 主审 + 辅审通过，产出 `gate-review.md` | 第 3 次驳回 → 用户裁决 |
| 分级实现 | 每个任务：tester 验证通过 **且** reviewer 审查通过 | 同级自修复 2 次 → 升档 → 3 轮全败 → director |
| 复审回归 | 全量回归通过 | 回到对应任务重做 |
| 归档 | recorder 沉淀 + guard 更新 | — |

> 这里借用了大仓 Harness 实践里的一条硬经验：**"阶段不是越多越好，关键是每个阶段有唯一产物、唯一退出条件"**。BudgetBuddy 把阶段压到 5 个，但把"门禁"下沉到**每个任务**——tester 与 reviewer 一个都不能省，这才是它敢宣称"半自动可交付"的底气。

### 4.3 模型三档预设：一条命令切换成本等级

三个预设不是"三个开关"，而是三套**完整的「角色 → 模型」映射表**。

| 预设 | 定位 | Claude Code 典型模型 | CodeBuddy 典型模型 | 倍率（以 Opus 为 1 单位） |
| --- | --- | --- | --- | --- |
| `economic` | 极致省钱 | `claude-haiku-5-5` | `deepseek-v4-flash` | ≈ x0.67 |
| `balanced` | 日常推荐 | `claude-sonnet-5-5` | `deepseek-v4-flash` | ≈ x2.00 |
| `quality` | 关键项目 | `claude-opus-5-5` | `deepseek-v4-pro` | ≈ x3.50 |

> 表中为各档 `coder_standard` 角色的典型模型；完整四平台预设表在构建期生成到 `dist/<platform>/docs/MODEL_SELECTION.md`，也可用 `budget setup models` 查看。
>
> **economic → quality 的价差约 5.2 倍**。这意味着"选错预设"本身就是最大的单点浪费——比优化 prompt 重要得多。

**三档之外还有两个精细化手段**：

```bash
# 切换整档预设（重写各 agent frontmatter 的 model 字段）
budget setup agent preset economic

# 只覆写某个 agent 的模型（比如让 reviewer 单独用更强的模型）
budget setup agent custom reviewer deepseek-v4-pro

# 让某个 agent 继承主面板模型（IDE 场景常用）
budget setup agent inherit coder-lite

# 查看当前配置
budget setup show
```

**外部模型接入**：不改内置文件也能扩充目录——CodeBuddy 客户端配置 `~/.codebuddy/models.json` 会被自动读取；或用 `BUDGET_EXTERNAL_MODELS` 指向一个或多个 `models[]` 格式的 JSON 文件/目录（`:` 分隔，支持 `~` 展开）。外部模型 ID 用 `budget setup models` 列出后，可直接用于 `budget setup agent custom <id>`。

> **诚实的碎碎念**：预设只是"起点"。真实项目里最优组合往往要按团队的实际任务分布微调——比如文档型团队可以把 recorder 压到免费模型，而安全团队宁愿给 reviewer 单独升档。预设的价值是**给出一个可对比的基线**，不是终局。

### 4.4 Coder Guard：不要在已被证伪的组合上反复烧钱

这是 BudgetBuddy 里我个人最看重的机制之一。

AI 工作流最隐蔽的浪费，是**在同一个"模型 × 任务类型"的高失败率组合上反复重试**。比如某个廉价 coder 反复搞不定"并发改造"这类任务，如果每次都还派它去，预算就在"必然失败"上被蒸发。

**Coder Guard 的做法**：

- 按 **coder × 任务标签** 记录最近 5 次成败，落盘在 `$HOME/.budgetbuddy/projects/<project>/memory/coder-guard.json`（本地持久化，不提交 git）；
- 分派任务前，Leader 先查该 coder 在**该任务标签**上的记录；
- 若最近 5 次中失败 ≥ 2 次，**自动触发降级保护**：把任务改派到更高一档（`lite → standard → senior`），而不是继续赌。

```
任务打标签 [concurrency]
  → 查 guard.json: coder-lite 最近 5 次 [concurrency] 失败 3 次
  → 触发降级：直接改派 coder-standard（跳过 lite）
  → 任务完成，recorder 把本次结果写回 guard.json
```

**它解决的是"经验无法复用"的问题**：人不会在同一个坑里摔三次，但 AI 工作流会。Guard 把"踩坑经验"变成了可查询的数据，让系统具备**跨任务的记忆**。

> 配套命令：`budget setup guard` 查询 / 重置记录；`budget setup status` 可看 guard 汇总。

### 4.5 Review Gate 升级 + Director 六类终裁：给"死循环"装一个出口

审查不通过时，系统不是"让同一个 coder 再试一次"，而是**逐级升档**：

```
coder-lite 实现
   → tester 验证（失败先同级自修复，最多 2 次）
   → reviewer 审查
        ├─ 不通过 → 升 coder-standard 重写 → 二审
        │              └─ 不通过 → 升 coder-senior 重写 → 三审
        └─ 通过 → recorder 沉淀
```

**关键约束**：升级后**不退回原级**；最多 3 轮审查；3 个不同级别 coder 各一次机会。

3 轮全败怎么办？这是很多"多 Agent 系统"翻车的地方——要么无限循环，要么直接报错甩锅。BudgetBuddy 引入 `director` 做**根因分型**，把"失败"变成"可决策的结构化信息"：

| 分型 | 含义 | Director 动作 | 去向 |
| --- | --- | --- | --- |
| **A 设计缺陷** | architect 方案本身有漏洞 | 直接改 `design.md` 标注缺陷 | **自动恢复**（仅 1 次机会） |
| **B 任务过大** | 需求拆得太粗 | 输出 N 个子任务 | **自动恢复**（拆分后重派） |
| **C reviewer 误判** | 某轮实现其实可接受 | 标注误判轮次与理由 | **自动恢复**（直接标记完成） |
| **D 需求不清** | 原始需求歧义/矛盾 | 列出待澄清问题 | **上报用户** |
| **E 能力天花板** | 模型组合做不到 | 建议切 quality 或人工接管 | **上报用户** |
| **F 环境限制** | 缺依赖/权限/配置 | 列出缺失项 | **上报用户** |

**设计意图非常清晰**：A/B/C 用户**不被打断**（只发知会通知），D/E/F 才上升用户。这样既避免了"AI 自己打转"，也避免了"动不动就弹窗烦人"。

> Director 的成本也被克制：默认只调一次、最多两次，`max_turns: 15`，且禁止再派生 sub-agent。它的定位是"低频高价值的一次性裁决"，不是常驻角色。

### 4.6 Goal Loop：从"跑一次流程"到"跑到达成目标"

普通工作流是"一次性"的：需求进来，走完五阶段，结束。但真实研发里，很多目标是**验收式的**——"直到全部测试通过且覆盖率 ≥ 80%"。

Goal Loop 把工作流升级为**目标驱动的宏循环**：

```
Phase 0  目标定义：把目标拆成可验证的验收条件
Phase 1-5 五阶段 pipeline（同普通流程）
Phase 6  目标验证：goal-evaluator 只读报告，做独立的"达成/差距"判定
          ├─ 达成 → 结束（发 N11 通知）
          └─ 有差距 → 带差距清单回到 Phase 1，迭代
```

**三条安全边界**（缺一不可）：

- 最多 **8 轮**；
- 最多 **80 次** agent 调用；
- 连续 **3 轮无进展** 即停。

并且用户可以在目标里内嵌更紧的限制（`stop_after_turns` 取更小值）。`goal-evaluator` 是**只读判定者**——它不执行任何代码、不跑命令，只基于 tester/reviewer 的报告做判定，避免"运动员兼任裁判"。

> 这条机制直接回答了 AI 军团实践里的一个关键问题：**"Agent 完成 ≠ 业务完成"**。必须有独立的验收环节，否则"跑完"只是"跑完"。

### 4.7 通知系统：11 个事件开关，异常才打扰人

工作流跑在后台时，人最需要知道的是\*\*"哪里卡住了、需不需要我"**，而不是每一步流水。BudgetBuddy 因此只在**异常/里程碑\*\*发通知。

```json
{
  "enabled": true,
  "channels": {
    "wecom":    {"type": "wecom_bot",    "webhook": "https://qyapi.example.com/..."},
    "dingtalk": {"type": "dingtalk_bot", "webhook": "https://oapi.example.com/...", "secret": "SEC..."},
    "feishu":   {"type": "feishu_bot",   "webhook": "https://open.example.com/..."},
    "custom":   {"type": "custom",       "webhook": "https://hooks.example.com/...", "format": "raw"}
  },
  "events": {
    "N7":  {"enabled": true, "channels": ["wecom", "dingtalk"]},
    "N10": {"enabled": true, "channels": ["feishu"]}
  }
}
```

- **11 个事件（N1–N11）**：设计评审驳回、审查升级耗尽、循环超限、Director 介入、阶段流转、目标达成等；
- **渠道**：企微机器人 / 钉钉机器人（HMAC-SHA256 加签）/ 飞书机器人（卡片）/ 自定义 webhook；
- **投递语义**：markdown 消息体、每渠道 5 秒超时、**任一成功即停、全部失败静默**——通知**绝不阻断工作流**；
- **安全**：配置文件 `chmod 600`；webhook/secret 不经环境变量、命令行参数与日志传递；错误输出只含脱敏主机名。

> 一个容易忽略的细节：通知失败必须静默。通知是"辅助观测"，不是"主链路"，让通知拖垮工作流是本末倒置。

### 4.8 openspec 变更管理：让"改什么"也有规格

工作流解决"怎么改"，openspec 解决"改什么、为什么改、改完怎么归档"。

| 命令 | 作用 |
| --- | --- |
| `/opsx:propose` | 发起一个新变更（提案 + 规格增量） |
| `/opsx:apply` | 实施变更中的任务 |
| `/opsx:archive` | 归档已完成的变更 |
| `/opsx:explore` | 提案前探索想法 |

变更以**规格驱动**：提案 → 评审 → 实施 → 归档，每一步都有产物，避免"AI 改完就忘、下次重复改"。

### 4.9 AutoRun：省的是"审批摩擦"，不是 token

CodeBuddy 平台上，4 个执行类 sub-agent **默认开启 AutoRun**（工具调用免逐条审批）：`coder-lite` / `coder-standard` / `coder-senior` / `tester`。其余 6 个（architect、reviewer、reviewer-b、recorder、director、goal-evaluator）保留逐条确认——因为它们涉及设计、审查、归档等"需要人盯一眼"的环节。

```bash
budget setup autorun list              # 状态查看：全局选择清单 + 当前安装态实况
budget setup autorun on reviewer       # 为单个 agent 开启
budget setup autorun off coder-lite    # 为单个 agent 关闭
```

> ⚠️ **必须说清的安全边界**：AutoRun 使该 agent 权限范围内**所有**工具调用免人工审批。4 个执行类 agent 的 `bash_allow: ["*"]`，意味着它们可以**无审批执行任意 shell 命令**（`rm -rf`、`git push -f` 均命中 `*`）。审批是最后一道人工闸门，请在知情后再开启。默认开启执行类是"效率优先"的取舍，团队应按自身风险偏好收紧。

### 4.10 在实践中长出来的跨平台套件：从"够用"到"可复用"

BudgetBuddy 不是先设计好完整架构再落地的，而是在真实的研发迭代里被一个个痛点"逼"出来的。回看它的演进，大致经历了三个阶段，恰好对应三次认知升级。

**阶段一：单点可用——先把"省钱"跑通**

最初的目标很朴素：让简单任务别再消耗最贵的模型。做法是给不同角色配不同模型、再抽成三档预设。这个阶段"能用"，但还只是一个**单平台的配置集合**，谈不上可复用。

**阶段二：可治理——把"省钱"变成"可控"**

单点可用之后，新问题暴露得很快：AI 会在错误方向上无限重试、审查流于形式、同一个坑反复踩。于是补上了三件套——Coder Guard（踩坑记忆）、Review Gate 升级 + Director 根因分型（死循环出口）、循环上限（预算断路器）。到这一步，它才从"配置集"变成**工作流**。

**阶段三：跨平台——把"可控"做成"可复用"**

当团队里同时出现 CodeBuddy / OpenCode / Claude Code / Codex 多种宿主时，四份配置各改各的会迅速腐化。于是把角色、规则、流程、模型收敛为单一 `core/` 源，用平台 YAML 做声明式映射，用 manifest + SHA256 做增量安装。到这一步，它才成为**跨平台套件**。

三次认知升级可以浓缩成一句话：

| 阶段 | 认知 | 关键机制 |
| --- | --- | --- |
| 单点可用 | 省钱 = **选对模型** | 三档预设 + 按角色配模型 |
| 可治理 | 省钱 = **可控地收敛** | Guard + Review Gate + 循环上限 |
| 跨平台 | 可控 = **可复用、可升级、可治理** | 单一源 + 平台 DSL + 哈希增量 |

> 这条路径说明：**跨平台不是一开始的设计目标，而是"实践规模变大后的必然要求"**。也正因如此，它保留了大量来自真实踩坑的机制（guard、上限、幂等状态、哈希增量），而不是纸面架构。

***

## 五、接入指南：从 0 到第一次"受控交付"

### 5.1 前置条件

| 依赖 | 说明 |
| --- | --- |
| 宿主平台 | CodeBuddy Code / OpenCode / Claude Code / Codex 任一（CodeBuddy CLI 建议 v2.90+） |
| Python 3 | QuickStart 向导、hook、状态管理需要，需在 PATH 中 |
| curl | 在线安装用 |
| Superpowers（推荐） | TDD、系统化调试等质量实践；未安装工作流仍可运行 |

### 5.2 安装（一行命令）

```bash
# 交互式：选择平台 + 作用域（项目 / 全局）
curl -fsSL https://raw.githubusercontent.com/fxdgg/BudgetBuddy/main/install.sh | bash

# 非交互：四平台全部安装（推荐）
BUDGET_PLATFORM=all bash install.sh

# 只装单个平台（示例：OpenCode 全局）
BUDGET_PLATFORM=opencode BUDGET_GLOBAL=1 bash install.sh
```

> ⚠️ **信任边界**：`curl | bash` 会以你的权限执行远端脚本。建议先 `curl -fsSL ... | less` 审查，再执行。安装器下载 release 后会**强制 SHA256 校验**，校验失败即中止。

**手动安装**：

```bash
git clone https://github.com/fxdgg/BudgetBuddy.git
cd BudgetBuddy
bash install.sh
```

**平台落点**：

| 平台 | 安装目录（项目级 / 全局） | 管理面 |
| --- | --- | --- |
| CodeBuddy | `.codebuddy/` / `~/.codebuddy/` | `~/.budgetbuddy/` |
| OpenCode | `.opencode/` / `~/.config/opencode/` | `~/.budgetbuddy/` |
| Claude Code | `.claude/` / `~/.claude/` | `~/.budgetbuddy/` |
| Codex | `.codex/skills/` / `~/.codex/skills/` | `~/.budgetbuddy/` |

> 项目级与全局级可共存，**项目级优先**。团队统一配置建议装在项目级并随仓库提交（便于 review 与回滚）；个人常用工具链装全局。

### 5.3 安装后验证（三步）

```bash
# 1) 校验安装完整性（按 manifest 比对）
budget setup validate

# 2) 查看当前 agent / 模型配置
budget setup show

# 3) 看状态：guard 汇总 + 活跃变更 + agent 配置
budget setup status
```

若 `validate` 失败，优先检查：是否用 IDE 面板改过 agent 文件（会破坏哈希）、是否项目级与全局级冲突、`settings.json` 是否被其他工具覆盖。

### 5.4 第一次运行

```bash
# CodeBuddy / Claude Code
/budget:start "新增用户登录 API，JWT 鉴权"

# OpenCode
/budget-start "新增用户登录 API，JWT 鉴权"

# Codex（无 slash 命令，用触发词）
budget-start: 新增用户登录 API，JWT 鉴权
```

自然语言触发同样有效（"开始开发"、"实现 XX 功能"、"修复 XX bug"）。

**过程中常用的三个查询**：

```bash
/budget:status          # 当前走到哪个阶段、哪个任务
budget setup guard      # 看某 coder 的失败记录
budget setup stats      # 工作流统计
```

### 5.5 模型配置：先定档，再微调

```bash
# 第一步：选档（大多数团队从 balanced 开始）
budget setup agent preset balanced

# 第二步：按需微调单个角色
budget setup agent custom tester deepseek-v4-flash   # 测试角色压成本
budget setup agent custom reviewer deepseek-v4-pro   # 审查角色保质量

# 第三步：核对
budget setup show
budget setup diff balanced    # 当前配置 vs 预设，一眼看出改了啥
```

**接入外部模型**（不改内置文件）：

```bash
# 方式一：CodeBuddy 客户端配置会被自动读取
#   ~/.codebuddy/models.json

# 方式二：指向外部模型清单（: 分隔，支持 ~ 展开）
export BUDGET_EXTERNAL_MODELS="~/my-models.json:~/team-models/"

budget setup models    # 列出所有可选模型 ID
```

### 5.6 通知接入（可选但强烈建议）

在项目根 `.budget/notify.json`（项目级）或 `~/.budgetbuddy/notify.json`（全局级）配置。**项目级存在即生效，不与全局合并**。

```bash
# 配置好后验证一次
budget notify "通知链路自检" N1
```

建议先只开少量关键事件（如"审查升级耗尽""循环超限""目标达成"），确认渠道通畅后再逐步放开，避免消息轰炸。

### 5.7 升级、回滚与卸载

```bash
budget update          # 增量更新（等价于重跑安装器）
budget setup reinstall # uninstall + init 组合重装
budget setup uninstall # 离线卸载（按本地清单）
```

**升级不会覆盖你的自定义**：非官方文件按哈希识别并保留；`~/.budgetbuddy/auto-run.json` 等用户状态在卸载时也不清除，重装后经安装重放恢复。

### 5.8 Windows 注意

不要用 PowerShell / cmd 直接跑 `curl | bash`（PowerShell 的 `curl` 是 `Invoke-WebRequest` 别名）。请用 **Git Bash** 或 **WSL**。

***

## 六、落地最佳实践

下面每一条都来自"这套东西在真实项目里怎么用才不出事"，而不是功能罗列。

### 6.1 把"任务标签"当成第一等公民

Coder Guard 的降级、coder 的路由，全都依赖**任务标签**。标签打得粗，护栏就形同虚设。

**实践建议**：

- 用**动词 + 对象 + 风险**三段式打标签，例如 `config_edit`、`crud_single`、`api_endpoint`、`concurrency`、`security_crypto`、`cross_module_refactor`；
- 高风险标签（`concurrency`、`security`、`db_migration`）**默认不派 lite**，直接 `coder-standard` 起步；
- 标签粒度以"历史上是否出现过同类失败"为准——**踩过坑的组合才值得单独建标签**，不要为了标签而标签。

### 6.2 预设选择：先问"这次失败的代价"，再问"这次省多少钱"

很多团队的误区是"无脑 economic"。正确的决策顺序是**先看失败代价**：

| 场景 | 推荐预设 | 理由 |
| --- | --- | --- |
| 脚手架、批量小改、文档、lint | `economic` | 失败代价低、可重试，省钱优先 |
| 常规业务迭代（大多数时候） | `balanced` | 成本与质量的甜点区 |
| 核心链路、安全、支付、并发、大仓重构 | `quality` | 一次失败的成本远超模型差价 |
| 正在试点的团队 | `balanced` + 收紧循环上限 | 先建立信任，再谈极致省钱 |

> 一句话：**省钱的前提是"能收敛"。在无法收敛的任务上省钱，是最贵的省钱。**

### 6.3 让审查真正起作用，而不是"走过场"

审查失效是 AI 工作流最普遍的隐性风险。三条实践：

1. **保持 reviewer 只读**：不要为了"省一轮"给 reviewer 加 Write 权限。审查者的价值在"独立视角"，一旦它能顺手改代码，就会倾向于"改到能过"，而不是"指出问题"。
2. **双审要真的"不同"**：主审（reviewer）看实现质量与规格一致性，辅审（reviewer-b）看技术合理性与架构取舍；条件允许时用**不同厂商**的模型，交叉验证才能发现单一模型的系统性盲区。
3. **可选接入机器预审（OCR）**：由 OpenCodeReview CLI 扫 diff 给出候选问题，作为**探测器**补充给审查员，但**不是门禁、不阻断流程**。未安装时工作流完全不受影响（优雅降级）。

```bash
npm i -g @alibaba-group/open-code-review
ocr config provider && ocr config model   # 或 ocr delegate 复用宿主额度
budget setup ocr                          # 安装规则模板到 ~/.opencodereview/rule.json
```

### 6.4 用"上限"管预算，而不是用"感觉"

BudgetBuddy 的每个循环都有上限，落地时要**主动收紧**而不是放任：

| 旋钮 | 默认 | 收紧建议 |
| --- | --- | --- |
| 同级自修复 | 2 次 | 保持 |
| 审查升级 | 3 轮 | 试点期可降到 2 轮，快速暴露问题 |
| 单任务循环 | 5 轮 | 大仓重构可降到 4 轮 |
| Goal 轮数 / 调用 | 8 轮 / 80 次 | 用 `stop_after_turns` 内嵌更紧限制 |

**为什么上限比 prompt 重要**：AI 在错误方向上会"越努力越浪费"。上限是**预算的断路器**，它保证最坏情况下成本可预测。

### 6.5 与 TDD / Superpowers 协同：分工而不是替代

- **多 Agent 系统**解决"谁来做、用什么模型、花多少钱"；
- **Superpowers**（TDD、系统化调试）解决"怎么做才对"。

两者是**互补**关系，不是替代：coder 按 TDD 的红-绿-重构推进，reviewer 按代码审查标准把关，tester 负责验证。未安装 Superpowers 时工作流仍可运行（Leader 手动执行等效步骤），但装了之后"质量下限"会明显抬高。

### 6.6 大仓与团队落地：三阶段推进

参考大仓 Harness 实践的教训（"阶段不可合、门禁不可省、半自动才是当前最优解"），我们建议：

**阶段一：单点试点（1–2 周）**

- 选 1 个"任务类型清晰、失败可回滚"的模块；
- 用 `balanced`，只开 AutoRun 的执行类 agent；
- 目标不是"省多少钱"，而是**验证收敛性**：任务能否稳定走完五阶段、Director 触发率是否可接受。

**阶段二：团队推广（3–4 周）**

- 统一项目级安装，配置随仓库提交；
- 建立**任务标签规范**与**预设选择规范**（写进团队文档）；
- 接入通知，让"卡点"可见；
- 开始用 `budget setup stats` 做周度复盘。

**阶段三：度量与调优（持续）**

- 用第七章的公式算"加权成本"，和"全 Opus 基线"对比；
- 按任务分布调整预设（例如把高频低风险任务批量切 `economic`）；
- 把反复失败的组合沉淀成 guard 记录与规则。

> **不要一步到位**。"撞墙之后删掉机制，而不是修这个 bug"同样适用：如果某个多 Agent 环节在你们团队**长期负收益**，正确的动作是**砍掉它**，而不是加更多 prompt 去救。

### 6.7 五个常见反模式

| 反模式 | 后果 | 纠正 |
| --- | --- | --- |
| 让 Leader "顺手改一下" | 上下文膨胀、成本失控、规则崩塌 | 一律委派 coder |
| 所有任务都用 `quality` | 预算爆炸 | 按失败代价分级 |
| 给 reviewer 写权限 | 审查失去独立性 | 只读 |
| 无上限重试 | 在错误方向烧钱 | 用循环上限做断路器 |
| 用 IDE 面板编辑 agent | 哈希冲突、升级失败 | 直接改 `core/agents/*.md` |

***

## 七、度量：如何证明"真的省了钱"

不要用"感觉便宜了"汇报，用可复算的公式。

### 7.1 加权成本公式

把一次任务的花费抽象为：

```
加权成本 = Σ（各 agent 的 token 用量 × 该 agent 所用模型的成本倍率）
```

其中"成本倍率"以某个基准模型为 1 单位（BudgetBuddy 的模型目录里每个模型都带倍率字段）。

### 7.2 一个可复算的对照示例

假设一次需求消耗：

| 角色 | token 占比 | 全 Opus 方案倍率 | BudgetBuddy balanced 倍率 |
| --- | --- | --- | --- |
| architect | 5% | x3.50 | x2.00 |
| coder-\*（合计） | 25% | x3.50 | x0.05 ~ x0.13 |
| reviewer / reviewer-b | 10% | x3.50 | x0.13 ~ x0.65 |
| tester / recorder | 10% | x3.50 | x0.00 ~ x0.65 |
| Leader 编排 | 50% | x3.50 | x2.00 |

> 说明：以上"token 占比"是**示例假设**，用于演示算法；真实占比需用 `budget setup stats` / 网关账单导出后替换。重点不在具体数字，而在**方法**：把成本拆到"角色 × 倍率"，你才能看到钱到底花在哪。

### 7.3 三个必须长期盯的指标

1. **单位任务加权成本**（公式见上）——最直接的"省没省"；
2. **Director 触发率**——反映"方案质量 / 任务拆分"的健康度，触发率过高说明拆解有问题；
3. **审查升级率**——反映 coder 路由是否合理；频繁升级意味着"该用 standard 的任务被派给了 lite"。

> 如果只允许看一个指标，就看 **审查升级率**：它是"模型路由准不准"的温度计。

***

## 八、边界与诚实清单

一套工程化方案的可信度，往往取决于它敢不敢说清"不适用于什么"。

- **不替代架构决策**：architect 产出的是"候选方案"，关键架构仍需人拍板；
- **不能消除幻觉**：它用门禁和审查**降低**幻觉的交付风险，但不能让模型"不产生幻觉"；
- **AutoRun 有安全代价**：执行类 agent 的 `bash_allow: ["*"]` 意味着无审批执行任意命令，必须知情；
- **Codex 形态是"降级兼容"**：无 slash 命令、无 frontmatter 模型、无 hooks 通知，靠自然语言触发与 Leader 运行时解析档位；
- **预设不是银弹**：`economic` 的省建立在"失败可重试"之上，高风险任务用它可能反而更贵；
- **项目级安装的模型/persona 会回退全局**：多项目共存时，注意 `budget setup list` 的"全局选择 vs 当前安装态"两栏差异。

***

## 九、总结：省钱是结果，"可控"才是能力

回到开头那个问题：为什么疯狂用 AI 写代码反而更贵？

因为**贵从来不是单价问题，而是"用错模型 + 撑爆上下文 + 反复返工"的复合结果**。

BudgetBuddy 给出的答案不是"更聪明的 prompt"，而是一套**可收敛的工程结构**：

- **角色分工**让"谁来做"可配置；
- **模型路由**让"多少钱"可控制；
- **有限循环 + 根因分型**让"卡住"有出口；
- **Guard / state / notify 落盘**让"经验"可复用；
- **单一源 + 哈希增量**让"多平台"不变形。

它最终交付的不是"更便宜的 token"，而是一种**可度量、可回顾、可收敛的 AI 研发方式**。省钱只是这套方式的自然结果。

> 如果你只想记住一句话：**把每一分 token，花在"对的模型做对的事"上；把每一次失败，变成下一次不再犯的数据。**

***

## 附录 A：命令速查

| 目的 | CodeBuddy | OpenCode | Claude Code |
| --- | --- | --- | --- |
| 启动工作流 | `/budget:start <需求>` | `/budget-start <需求>` | `/budget:start <需求>` |
| 目标循环 | `/budget:goal <目标>` | `/budget-goal <目标>` | `/budget:goal <目标>` |
| 查看进度 | `/budget:status` | `/budget-status` | `/budget:status` |
| 发起变更 | `/opsx:propose` | `/opsx-propose` | `/opsx:propose` |
| 实施变更 | `/opsx:apply` | `/opsx-apply` | `/opsx:apply` |
| 归档变更 | `/opsx:archive` | `/opsx-archive` | `/opsx:archive` |
| 探索想法 | `/opsx:explore` | `/opsx-explore` | `/opsx:explore` |

**setup 常用子命令**：`init` / `show` / `status` / `validate` / `diff` / `stats` / `agent preset|custom|inherit` / `persona` / `guard` / `autorun` / `models` / `update` / `uninstall` / `quickstart`。

## 附录 B：仓库结构（节选）

```
BudgetBuddy/
├── core/                  # 单一中立源 —— 只在这里改
│   ├── agents/            # 10 个 agent 定义
│   ├── commands/          # budget + opsx 命令模板
│   ├── docs/              # architecture.md、personas、模型模板
│   ├── hooks/             # 通知 hook
│   ├── lib/               # setup / 状态机 / guard / notify
│   ├── models/            # budget-models.json + schema
│   ├── personas/          # 主题（default/tech-legends/sanguo/shuihu）
│   ├── platform/          # 四平台映射 DSL
│   ├── rules/             # P0 规则 + 语言规范
│   ├── skills/            # budget-workflow、budget-notify、openspec
│   └── setup.sh
├── dist/                  # 构建产物（禁止手改）
├── scripts/               # build.py、scan-brand.py、build-release.sh
├── tests/                 # 单元测试
├── install.sh             # 四平台安装器
└── VERSION
```

## 附录 C：相关资源

- **本项目**：https://github.com/fxdgg/BudgetBuddy
- **质量实践**：Superpowers（TDD、系统化调试）
- **可选预审**：OpenCodeReview（https://open-codereview.ai）

***

*本文基于 BudgetBuddy v0.4.0 的真实实现撰写；文中数字与机制均可在仓库 `core/` 与 `docs/` 中找到对应出处。*
