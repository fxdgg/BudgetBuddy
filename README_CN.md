# BudgetBuddy — 多 Agent 省钱研发工作流套件

**中文** | [English](README.md) | [变更日志](CHANGELOG.md) | [许可协议](LICENSE)

BudgetBuddy 是一套多 Agent 省钱研发工作流。它把每个任务路由到「对的 sub-agent + 对的模型」：简单任务消耗廉价 token，只有硬任务才消耗昂贵 token。单一中立源（`core/`）构建出 **CodeBuddy** 与 **OpenCode** 双平台产物；其他 agent 平台可通过扩展构建 DSL（`core/platform/*.yaml`）接入。

## BudgetBuddy 是什么？

一个典型的编码需求混合着琐碎修改、常规功能和少数真正的难题。全部跑顶级模型浪费预算，全部跑廉价模型又搞不定难题。BudgetBuddy 把工作拆分给 **10 个专业 sub-agent**，按角色分配模型，并套上强制的五阶段工作流（方案 → 双审 → 分级实现 → 复审 → 归档）。

本套件自举开发：本仓库自身就是用 BudgetBuddy 的工作流开发的。

## 功能特性

- **10 个专业 sub-agent** — architect、coder-lite / coder-standard / coder-senior、reviewer + reviewer-b（双审）、tester、recorder、director（终裁）、goal-evaluator
- **五阶段工作流** — 方案设计 → 方案双审 → 分级实现 → 复审与回归 → 归档；阶段不可跳过
- **模型三档预设** — `economic` / `balanced` / `quality`，一条命令切换；支持按 agent 的 `custom` 覆写与 `inherit`（继承主面板模型）
- **5 套 persona 主题** — default（专业）、tech-legends、sanguo、shuihu、genshin；角色名与称呼随主题切换
- **通用 webhook 通知** — 企微机器人 / 钉钉机器人（HMAC-SHA256 加签）/ 飞书机器人（卡片）/ 自定义 webhook，11 个工作流事件开关（N1–N11）
- **Coder Guard 护栏** — 按 coder × 任务标签记录最近 5 次成败；失败 ≥2 次自动触发分级降级
- **Goal Loop** — 目标驱动宏循环：定义目标 → 跑 pipeline → 验证 → 未达标则迭代（最多 8 轮，含安全边界）
- **openspec 变更管理** — propose / apply / archive / explore 命令 + 规格驱动的变更跟踪
- **双平台构建** — 单一 `core/` 源，`scripts/build.py` 产出 `dist/codebuddy/` 与 `dist/opencode/`
- **Superpowers 集成** — 在正确阶段引用质量实践 skill（TDD、系统化调试）；插件缺失时优雅降级

## 安装

### 在线安装（一行命令）

```bash
curl -fsSL https://raw.githubusercontent.com/fxdgg/BudgetBuddy/main/install.sh | bash
```

> ⚠️ **信任边界**：`curl | bash` 会以你的权限执行远端脚本。建议先审查脚本（`curl -fsSL https://raw.githubusercontent.com/fxdgg/BudgetBuddy/main/install.sh | less`）再执行。安装器下载 release zip 后**强制 SHA256 校验**——校验失败即中止，绝不安装损坏的包。

交互模式会询问平台（CodeBuddy / OpenCode / 两者）与作用域（项目 / 全局）。非交互：

```bash
BUDGET_PLATFORM=opencode BUDGET_GLOBAL=1 bash install.sh   # OpenCode 全局安装
```

### 手动安装

```bash
git clone <本仓库地址> BudgetBuddy
cd BudgetBuddy
bash install.sh
```

### 平台说明

| 平台 | 结构文件落点 | 管理面 |
|------|-------------|--------|
| CodeBuddy | `.codebuddy/`（项目级）或 `~/.codebuddy/`（全局） | `~/.budgetbuddy/` |
| OpenCode | `.opencode/`（项目级）或 `~/.config/opencode/`（全局） | `~/.budgetbuddy/` |

- **CodeBuddy**：agents/rules/skills/commands 落入 `.codebuddy/`；hooks 注入 `settings.json`（注入前备份）并自动启用 Superpowers 插件；`budget` CLI 写入 `~/.local/bin/budget`。
- **OpenCode**：agents/commands/skills 落入 OpenCode 目录；rules 以标记区块形式合并进 `AGENTS.md`；hooks 无原生等价物——插件扩展点见 `core/docs/opencode-setup-notes.md`。
- Windows：请使用 Git Bash 或 WSL（PowerShell 会把 `curl` 别名为 `Invoke-WebRequest`）。
- 项目级与全局级安装可共存；项目级优先。

## 快速开始

### CodeBuddy

```
/budget:start "新增用户登录 API，JWT 鉴权"
```

### OpenCode

```
/budget-start "新增用户登录 API，JWT 鉴权"
```

Leader 会分析需求，依次调度 architect → 双 reviewer → 分级 coder → tester → 复审 → recorder，最后汇报结果。目标驱动迭代：

```
/budget:goal "持续改进直到全部测试通过且覆盖率 >= 80%"   # CodeBuddy
/budget-goal "持续改进直到全部测试通过且覆盖率 >= 80%"   # OpenCode
```

### 常用命令

| 命令（CodeBuddy） | 命令（OpenCode） | 用途 |
|------------------|------------------|------|
| `/budget:start <需求>` | `/budget-start <需求>` | 启动五阶段工作流 |
| `/budget:goal <目标>` | `/budget-goal <目标>` | 启动 / 恢复 Goal Loop |
| `/budget:status` | `/budget-status` | 查询工作流进度 |
| `/opsx:propose` | `/opsx-propose` | 发起一个新的 openspec 变更 |
| `/opsx:apply` | `/opsx-apply` | 实施变更中的任务 |
| `/opsx:archive` | `/opsx-archive` | 归档已完成的变更 |
| `/opsx:explore` | `/opsx-explore` | 提案前探索想法 |

自然语言触发（"开始开发"、"实现 XX 功能"、"修复 XX bug"）同样激活工作流。

### setup 子命令（`budget setup <子命令>`）

| 子命令 | 用途 |
|--------|------|
| `init [shell]` | 初始化数据目录（`.budget/`、`~/.budgetbuddy/`）；`init shell` 注入 shell 别名 |
| `show` | 展示当前 agent / 模型配置 |
| `status` | 状态查询（guard 汇总 + 活跃变更 + agent 配置） |
| `agent preset\|inherit\|custom` | 切换模型预设 / 继承面板模型 / 覆写单个 agent |
| `persona list\|set\|expand\|show` | persona 主题管理 |
| `validate` | 按 manifest 校验安装完整性 |
| `diff [preset]` | 当前配置 vs 预设对比（默认 `balanced`） |
| `stats` | 工作流统计 |
| `update` | 增量更新（`budget update` 为顶层快捷别名） |
| `reinstall` | uninstall + init 组合重装 |
| `uninstall` | 卸载（离线可用，按本地清单） |
| `guard` | 查询 / 重置 Coder Guard 记录 |
| `quickstart` | 交互式快速上手引导（别名 `tour`、`wizard`） |
| `models` | 查看模型目录 |
| `notify "<消息>" <事件名>` | 发送通知（顶层入口 `budget notify`） |
| `help` | 显示帮助 |

## 架构

```mermaid
flowchart TD
    U(["用户"]) -->|"/budget:start"| L["Leader — 只编排，绝不写代码"]

    subgraph P1["Phase 1 · 方案设计"]
        A["architect"]
    end
    subgraph P2["Phase 2 · 方案双审"]
        R1["reviewer — 主审"]
        R2["reviewer-b — 辅审"]
    end
    subgraph P3["Phase 3 · 分级实现（逐任务）"]
        C["coder-lite / coder-standard / coder-senior"]
        T["tester"]
        RV["reviewer"]
        C --> T
        T -->|"失败 — 同级自修复，最多 2 次"| C
        T -->|"通过"| RV
        RV -->|"驳回 — 升级 coder 档位，最多 3 轮"| C
    end
    subgraph P4["Phase 4 · 复审与回归"]
        FR["reviewer"]
    end
    subgraph P5["Phase 5 · 归档"]
        REC["recorder"]
    end

    L -->|"需求"| P1
    P1 -->|"proposal.md + design.md"| P2
    P2 -->|"gate-review.md — 双审通过"| P3
    P3 -->|"全部任务通过"| P4
    P4 -->|"最终审查报告"| P5
    P5 -->|"归档 + Coder Guard 更新"| L

    P2 -->|"第 3 次驳回 — 用户裁决"| U
    P3 -->|"循环超 5 轮 — 暂停（N3）"| U
    P3 -->|"3 轮全败"| D["Director — 终裁"]
    D -->|"A/B/C — 自动恢复"| P3
    D -->|"D/E/F — 上报用户"| U

    GL["Goal Loop（/budget:goal）"] -.->|"Phase 0 — 目标定义"| L
    L -.->|"Phase 6 — 目标验证"| GE["goal-evaluator"]
    GE -.->|"有差距 — 迭代，最多 8 轮"| L
    GE -.->|"达成 — N11"| L
```

### 核心规则

- **Leader 绝不写代码** — 所有代码修改必须经分级 coder agent 执行，哪怕一行 typo
- **tester 与 reviewer 不可跳过** — 每个任务必须先过 tester 验证、再过 reviewer 审查才算完成
- **Review Gate 升级** — 审查不通过自动升级 coder 档位（lite → standard → senior），最多 3 轮；单任务循环上限 5 轮（3 轮分级审查 + 2 次同级自修复），超限暂停等待用户
- **Director 终裁** — 3 轮全败时 Director 做六类根因分型；A/B/C 触发自动恢复，D/E/F 上报用户
- **Coder Guard** — 分派前 Leader 查询该 coder 在任务标签上的失败记录；最近 5 次失败 ≥2 次即强制降级

组件级架构图见 [`core/docs/architecture.md`](core/docs/architecture.md)。

## 模型预设

| 预设 | 定位 | 典型形态 |
|------|------|---------|
| `economic` | 省钱模式 | 免费/廉价模型承担大部分角色；仅终裁用高级模型 |
| `balanced` | 平衡（推荐） | 高价值模型给 architect/reviewer，中档给 coder，廉价给 tester/recorder |
| `quality` | 质量模式 | 顶级模型给 architect/coder-senior/director，其余用强模型 |

```bash
budget setup agent preset economic    # 切换预设（重写 agent frontmatter）
budget setup agent custom coder-lite kimi-k2.7   # 覆写单个 agent 的模型
budget setup agent inherit coder-lite            # 继承主面板模型
budget setup show                     # 查看结果
```

完整目录（模型、档位、成本、别名、双平台预设表）在构建期生成到 `dist/<platform>/docs/MODEL_SELECTION.md`。

## 消息通知

在 `.budget/notify.json`（项目级）或 `~/.budgetbuddy/notify.json`（全局级）配置一次即可；项目级存在即生效（不合并）：

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

- **11 个事件开关（N1–N11）** — 设计评审驳回、审查升级耗尽、循环超限、Director 介入、阶段流转、目标达成等
- **投递语义** — markdown 消息体、每渠道 5 秒超时、任一成功即停、全部失败静默（绝不阻断工作流）
- **安全** — 配置文件 `chmod 600`（仅 owner 可读）；webhook/secret 不经环境变量、命令行参数与日志传递；错误输出仅含脱敏后的主机名

## 目录结构

```
BudgetBuddy/
├── core/                  # 单一中立源 — 在这里改
│   ├── agents/            # 10 个 agent 定义
│   ├── commands/          # budget（start/status/goal）+ opsx（4 个）命令模板
│   ├── docs/              # architecture.md、opencode-setup-notes.md、personas、模型模板
│   ├── hooks/             # CodeBuddy 通知 hook
│   ├── lib/               # 管理面模块（setup、状态机、guard、notify 等）
│   ├── models/            # budget-models.json + schema
│   ├── personas/          # 5 套 persona 主题
│   ├── platform/          # codebuddy.yaml / opencode.yaml 映射 DSL
│   ├── rules/             # 12 条规则（3 条 P0 + 8 条代码规范 + rtk）
│   ├── skills/            # budget-workflow、budget-notify、4 个 openspec skill
│   └── setup.sh           # budget setup 入口
├── dist/                  # 构建产物（禁止手改）
│   ├── codebuddy/
│   └── opencode/
├── scripts/               # build.py、scan-brand.py、build-release.sh
├── tests/                 # 单元测试（python3 -m unittest）
├── install.sh             # 双平台安装器
└── VERSION
```

## 开发指南

- **改 `core/`，绝不改 `dist/`** — `dist/` 是生成物；手改会被覆盖且过不了检查
- **构建与门禁**：`python3 scripts/build.py --check`（`--strict` 可将告警升级为失败）
- **品牌门禁**：`python3 scripts/scan-brand.py` — 扫描 `core/`、`dist/`、`scripts/`、`install.sh`、`README.md`、`README_CN.md`、`CHANGELOG.md` 中的违禁词（参照项目品牌词）；门禁必须 exit 0
- **测试**：`python3 -m unittest discover -s tests`
- **发布**：`bash scripts/build-release.sh` — 先跑检查、读取 `VERSION`、打包 `budgetbuddy-<version>.zip` + `.sha256`
- **变更管理**：走 openspec 工作流（`/opsx:propose` → 评审 → `/opsx:apply` → `/opsx:archive`）；Leader 只编排不写代码——所有修改经分级 coder agent 执行

## 许可

[MIT](LICENSE) — Copyright (c) 2026 BudgetBuddy Contributors
