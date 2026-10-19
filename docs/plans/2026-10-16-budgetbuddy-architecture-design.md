# BudgetBuddy 架构设计

> 日期：2026-10-16 | 状态：已确认（用户已批准）
> 参考：内部参照项目（本地路径已略；禁止复制其品牌标识）及 `~/.config/opencode/` 下的 opencode 迁移版

## 1. 项目定位

BudgetBuddy 是一套**多 Agent 省钱研发工作流套件**，功能对等参照项目（9+1 个子 agent、5 阶段工作流、Coder Guard、Review Gate、Director 终裁、模型分级预设、personas、通知、hooks、openspec 集成），但：

1. **双平台**：同时支持 CodeBuddy（`.codebuddy/`）与 OpenCode（`~/.config/opencode/` 全局或 `.opencode/` 项目级），架构可扩展第三个平台
2. **品牌合规**：不包含参照项目名、其归属组织与公司标识、内部渠道域名及其中文角色系称呼等任何文字或标识（词表由 scripts/scan-brand.py 唯一权威承载，转义编码存储；大小写不敏感，构建门禁强制）
3. **单一源**：`core/` 中立格式定义，`scripts/build.py` 生成双平台发行版，改一处双平台生效

## 2. 目录结构

```
BudgetBuddy/
├── core/                          # ★ 单一源（中立格式，日常只改这里）
│   ├── agents/                    # 10 个 agent 中立定义
│   │   ├── architect.md  coder-lite.md  coder-standard.md  coder-senior.md
│   │   ├── reviewer.md  reviewer-b.md  tester.md  recorder.md
│   │   └── director.md  goal-evaluator.md
│   ├── skills/
│   │   ├── budget-workflow/       # SKILL.md + router.md + phases.md
│   │   ├── budget-notify/         # SKILL.md + notify.py + load-env.sh
│   │   ├── openspec-apply-change/
│   │   ├── openspec-archive-change/
│   │   ├── openspec-explore/
│   │   └── openspec-propose/
│   ├── commands/                  # start.md / status.md / goal.md（中立模板）
│   ├── rules/                     # 见 §8
│   ├── models/budget-models.json
│   ├── personas/personas.json
│   └── platform/                  # 平台适配定义
│       ├── codebuddy.yaml
│       └── opencode.yaml
├── scripts/
│   ├── build.py                   # core/ → dist/codebuddy/ + dist/opencode/
│   ├── scan-brand.py              # 违禁词扫描门禁（exit 1 = 失败）
│   └── build-release.sh           # 打包 zip 产物
├── dist/                          # 构建产物（提交到 git，安装器消费）
│   ├── codebuddy/                 # → 安装到 .codebuddy/（项目）或 ~/.codebuddy/（全局）
│   │   ├── agents/ commands/budget/ rules/ skills/ hooks/ lib/
│   │   ├── setup.sh  budget-models.json  personas.json
│   │   └── docs/（MODEL_SELECTION.md、PERSONAS.md、架构图）
│   └── opencode/                  # → 安装到 ~/.config/opencode/ 或项目 .opencode/
│       ├── agent/  command/  skill/
│       ├── AGENTS.fragment.md     # 规则合并片段（安装器写入 AGENTS.md 标记区块）
│       └── setup-notes.md         # opencode 平台的 setup 说明
├── install.sh                     # 双平台在线安装器
├── README.md  README_CN.md  CHANGELOG.md  VERSION  LICENSE(MIT)
├── CODEBUDDY.md + AGENTS.md       # 自举开发说明（两份内容一致，双平台各自读取）
├── openspec/                      # 本项目自举开发用变更工作区
└── docs/plans/                    # 设计文档
```

## 3. 中立格式规范

### 3.1 Agent 中立 frontmatter（core/agents/*.md）

```yaml
---
name: architect
description: <一句话职责描述>
model_role: architect              # 由 budget-models.json 按 平台×预设 解析为具体模型 ID
tools: [read, write, edit, bash, grep, glob, webfetch, websearch]   # 中立小写工具名
permissions:
  edit_allow: ["openspec/**", "docs/**"]    # 允许编辑的 glob（缺省 "*"=全部）
  bash_allow: ["git *", "openspec *"]      # 允许执行的命令模式（缺省 "*"=全部）
max_turns: 8                      # 可选
---
<正文：平台中立措辞 + 模板变量>
```

### 3.2 平台转换映射（core/platform/*.yaml 声明，build.py 执行）

| 中立概念 | CodeBuddy 产物 | OpenCode 产物 |
|---------|---------------|--------------|
| frontmatter | `name` / `description` / `model` / `permissionMode` / `tools`（PascalCase）/ `max_turns` | `description` / `mode: subagent` / `model` / `permission: {edit: {"*": "deny", "<glob>": "allow"}, bash: {"*": "ask", "<pattern>": "allow"}}` |
| 文件位置 | `.codebuddy/agents/<name>.md` | `agent/<name>.md` |
| 命令 | `commands/budget/<cmd>.md` → `/budget:<cmd>` | `command/budget-<cmd>.md` → `/budget-<cmd>` |
| 规则 | `rules/budget-*.mdc`（原生 rules 机制） | `AGENTS.fragment.md` 标记区块（安装器合并进 AGENTS.md） |
| 子代理调用 | `Agent({subagent_type, prompt, description})` | `task({subagent_type, prompt, description})` |
| skill 引用 | `superpowers:brainstorming` | `brainstorming` |
| 项目说明 | "通过内置 Read/Grep 自行分析项目结构" | "启动时读取项目根目录 AGENTS.md（如保留 CODEBUDDY.md 一并参考）" |
| 工具名 | Read/Write/Edit/Bash/Grep/Glob/WebFetch/WebSearch | read/write/edit/bash/grep/glob/webfetch/websearch |

### 3.3 正文模板变量（build.py 替换）

| 变量 | CodeBuddy | OpenCode |
|------|-----------|----------|
| `{{TASK_TOOL}}` | `Agent` 工具，参数 `subagent_type` | `task` 工具，参数 `subagent_type` |
| `{{SKILL_NS}}` | `superpowers:` 前缀 | 空 |
| `{{PROJECT_DOC}}` | 自行分析项目结构 | 读 AGENTS.md |
| `{{AGENT_DIR}}` | `.codebuddy/agents/` | `~/.config/opencode/agent/`（项目级 `.opencode/agent/` 覆盖） |
| `{{GUARD_PATH}}` | `$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json` | 同左（双平台统一） |
| `{{RULES_DIR}}` | `.codebuddy/rules/`（不存在则 `$HOME/.codebuddy/rules/`） | `AGENTS.md` 标记区块 |

正文措辞原则：能用中立表述就不用变量（如"使用内置读取/搜索工具"）；仅语法级差异用变量。

### 3.4 P0 强制规则纵深防御

leader-no-code、coder-guard、流程强制 3 条 P0 规则，除平台规则文件外，**同时内联**进 budget-workflow SKILL.md（双平台一致），确保 opencode（无原生 rules）也有同等约束。

## 4. 数据目录（双平台统一，与宿主配置目录解耦）

| 层级 | 路径 | 内容 |
|------|------|------|
| 项目级 | `.budget/` | `persona-active.json`、`notify.json`、`memory/`（gitignore） |
| 全局 | `~/.budgetbuddy/` | 同名文件 + `projects/<project-name>/memory/coder-guard.json`、`bin/budget` |

- `.codebuddy/`、`.opencode/` 只放结构性文件 → 安装器增量同步永不碰用户数据
- `budget` CLI 包装器 → `~/.local/bin/budget`（对应参照项目做法），子命令：`setup` / `notify` / `status` / `update`
- 读取优先级：项目级 > 全局级，两者皆无 → 跳过（通知）/ 用默认（persona）

## 5. 模型目录（core/models/budget-models.json）

```json
{
  "_meta": {...},
  "aliases": {"opus": "...", "kimi": "...", ...},
  "models": {"paid": {...参照项目目录，去除内部引用...}, "free": {...}},
  "platforms": {
    "codebuddy": {
      "presets": {"economic": {...}, "balanced": {...}, "quality": {...}}
    },
    "opencode": {
      "presets": {"economic": {...}, "balanced": {...}, "quality": {...}},
      "note": "模型 ID 为 provider/model 格式，依赖用户 opencode.jsonc 已配置的 provider"
    }
  }
}
```

- **codebuddy** 预设：沿用 CodeBuddy 模型 ID（claude-opus-4.7-1m / deepseek-v4-pro-ioa / deepseek-v4-flash-ioa / kimi-k2.7-ioa / glm-5.2-ioa / hy3-ioa / gemini-3.5-flash / claude-haiku-4.5 等），角色映射与参照项目 balanced 一致
- **opencode** 预设：使用 opencode 官方 catalog 的 provider/model ID（anthropic / openai / google / zhipu / deepseek / moonshotai 系），实现时从 opencode 文档确认具体 ID；三档预设对应"免费优先 / 均衡 / 质量"
- `budget setup agent custom <provider/model>` 可覆写任意角色（重写 agent frontmatter model 字段）

## 6. 通知（通用 webhook，替换参照项目的内部通知工具）

### 6.1 notify.json（项目 `.budget/notify.json` > 全局 `~/.budgetbuddy/notify.json`）

```json
{
  "enabled": true,
  "channels": {
    "wecom":  {"type": "wecom_bot",  "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"},
    "dingtalk": {"type": "dingtalk_bot", "webhook": "https://oapi.dingtalk.com/robot/send?access_token=xxx", "secret": "SECxxx"},
    "feishu": {"type": "feishu_bot", "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx", "secret": "xxx"},
    "custom": {"type": "custom", "webhook": "https://...", "format": "raw"}
  },
  "events": {
    "N1": {"enabled": true, "channels": ["wecom"]},
    "...N2..N10 同参照项目通知点..."
  }
}
```

### 6.2 notify.py 行为

读配置 → 按 events 开关与渠道列表 → 按渠道类型格式化（企微 markdown / 钉钉 markdown+HMAC-SHA256 签名 / 飞书 interactive 卡片 / custom 原样 POST）→ `urllib` 发送，5s 超时 → 任一成功即停，全失败静默（`|| true` 语义）→ exit 0。Token 不落命令行参数。

### 6.3 通知点

保留参照项目 N1-N10 全部节点（3轮驳回、循环超限、reviewer 误判、Director 介入、Phase 2 通过、Phase 3 完成、全流程完成、需用户裁决），消息前缀 `[budget]`，模板中的变量来源表不变。

## 7. 构建系统（scripts/build.py，Python3 stdlib only）

- 输入：`core/**` + `core/platform/*.yaml`
- 输出：`dist/codebuddy/**`、`dist/opencode/**`（先清空再生成，保证幂等）
- 转换：frontmatter 重写（§3.2）、正文变量替换（§3.3）、文件落位/改名（agents→agents、commands→budget 命名、rules→mdc/AGENTS fragment）
- `--platform codebuddy|opencode` 选择性构建；`--check` 构建后自动跑违禁词扫描
- **scan-brand.py**：扫描 core/ dist/ scripts/ install.sh README* CHANGELOG* 全部文本，违禁词表（大小写不敏感，词类：参照项目名/归属组织与公司标识/内部渠道域名/中文角色系称呼/旧环境变量前缀）以转义编码存储于 scan-brand.py 唯一载体；命中即 exit 1 并输出文件:行号

## 8. 组件对等清单（参照项目 → BudgetBuddy）

| 参照组件 | BudgetBuddy 对应 | 备注 |
|---------|-----------------|------|
| 9 agents + goal-evaluator | core/agents/ 10 个 | 内容改写为中立格式，去品牌 |
| 参照 workflow skill | budget-workflow | SKILL.md + router.md + phases.md，通知调用改 `budget notify`，前缀 `[budget]` |
| 参照 notify skill | budget-notify | 通用 webhook 实现（§6） |
| openspec 4 skills | 同名保留 | 内容基本中立，仅改引用 |
| 参照 /start /status /goal 命令 | /budget:start /budget:status /budget:goal（opencode: /budget-start 等） | |
| 12 条 rules | budget-leader-no-code / budget-coder-guard / budget-workflow-enforcement（开发流程强制执行）+ 8 个代码规范（C++/CSS/Go/Java/Python/SQL/TypeScript/tRPC）+ budget-rtk（可选） | 规范内容去除品牌引用后保留 |
| 参照 models.json | budget-models.json | §5 |
| personas.json（6 主题） | personas.json（5 主题） | **剔除品牌专属主题**，保留 default/tech-legends/sanguo/shuihu/genshin |
| setup.sh + lib/（20+ 文件） | dist/codebuddy/setup.sh + lib/ | 子命令：init/show/agent preset\|inherit\|custom/persona/validate/diff/stats/update/uninstall；`budget` CLI 包装器 |
| hooks（3 事件） | dist/codebuddy/hooks/ | Notification/PreToolUse/SubagentStop → budget notify；opencode 以文档说明插件扩展点 |
| install.sh | install.sh | 双平台选择 + 项目/全局 + SHA256 增量同步（保护非本套件文件） |
| MODEL_SELECTION.md / PERSONAS.md / 架构图 | dist/codebuddy/docs/ | 架构图用 Mermaid 重绘 |
| CODEBUDDY.md | CODEBUDDY.md + AGENTS.md | 自举说明双份 |

## 9. 安装器（install.sh）

- `curl -fsSL $BUDGET_REPO_URL/install.sh | bash`，顶部 `BUDGET_REPO_URL` 变量可配置（默认 GitHub raw 占位地址，推送后修正）
- 交互选择：① 平台（codebuddy / opencode / both）② 项目级 / 全局级（`--global` 跳过交互；`BUDGET_PLATFORM`、`BUDGET_GLOBAL` 环境变量支持非交互）
- codebuddy：复制 dist/codebuddy/ → `.codebuddy/`（项目）或 `~/.codebuddy/`（全局）；写 `~/.local/bin/budget` 包装器
- opencode：复制 dist/opencode/{agent,command,skill} → `~/.config/opencode/`（全局）或 `.opencode/`（项目）；AGENTS.fragment.md 合并进对应 AGENTS.md（`<!-- BudgetBuddy:begin/end -->` 标记，幂等）
- SHA256 清单增量同步：非本套件文件（哈希不在清单中）一律保留
- 依赖检查：curl/tar/python3；Windows 提示 Git Bash/WSL（不照抄内部镜像 URL）

## 10. 任务拆分建议（architect 可调整，每任务 ≤2h）

| # | 任务 | 建议标签 | 建议级别 |
|---|------|---------|---------|
| T1 | 项目骨架 + build.py + scan-brand.py + platform/*.yaml + 空构建冒烟 | cross_module | senior |
| T2 | core/agents/ 10 个中立 agent | copy_pattern | standard |
| T3 | budget-workflow skill（SKILL/router/phases） | copy_pattern, cross_module | senior |
| T4 | budget-notify skill（notify.py/load-env.sh）+ hooks | api_endpoint | standard |
| T5 | openspec 4 skills | copy_pattern | lite |
| T6 | commands 3 个（start/status/goal） | copy_pattern | lite |
| T7 | rules 11 个（3 强制 + 8 规范 + rtk） | copy_pattern, docs_only | standard |
| T8 | budget-models.json + personas.json | config_edit | standard |
| T9 | setup.sh 主入口 + lib 基础层（colors/utils/platform/shell/init/update/uninstall） | cross_module | senior |
| T10 | lib 业务层（models/preset/model_resolver/guard/persona/persona_expand/validate/stats/state/notify/hooks/quickstart/banner） | cross_module | senior |
| T11 | install.sh 双平台安装器 | cross_module | senior |
| T12 | README/README_CN/CHANGELOG/LICENSE/VERSION/CODEBUDDY.md/AGENTS.md/docs | docs_only | standard |
| T13 | 全量构建 + 双平台安装演练 + 违禁词门禁 + 幂等验证 | test_only | standard |

依赖：T1 → T2-T8（内容填充，可部分并行）→ T9-T10 → T11 → T12 → T13。

## 11. 验收标准

1. `python3 scripts/build.py` 成功生成 dist/codebuddy/ 与 dist/opencode/ 完整产物，重复构建幂等（两次构建产物哈希一致）
2. `python3 scripts/scan-brand.py` 全仓 0 违禁词（exit 0）
3. CodeBuddy 安装演练（临时目录）：agents×10、skills×6、commands×3、rules×11、hooks、setup.sh 可执行且 `show`/`validate` 正常
4. OpenCode 安装演练：agent×10、command×3、skill×6、AGENTS.md 合并幂等
5. `budget notify` 三渠道格式化单测通过（mock 发送，不实际外呼）
6. setup.sh 核心子命令（init/show/agent preset/persona/validate）冒烟通过
7. 工作流文档（SKILL/router/phases）与参照项目功能对等：5 阶段、Coder Guard、Review Gate、3轮失败应急、Director 6类裁决、N1-N10 通知点齐全
