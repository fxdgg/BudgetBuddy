# OpenCode 平台安装与配置说明

> 本文档面向 OpenCode 用户，说明 BudgetBuddy 在 OpenCode 平台的落点、前置条件与平台差异。构建期本文件平移为 `dist/opencode/docs/setup-notes.md`（CodeBuddy 产物不分发本文件）。

## 安装落点

| 内容 | 项目级安装 | 全局安装 |
|------|-----------|---------|
| agent（10 个） | `.opencode/agent/*.md` | `~/.config/opencode/agent/*.md` |
| command（7 个） | `.opencode/command/*.md` | `~/.config/opencode/command/*.md` |
| skill（6 个） | `.opencode/skill/<name>/` | `~/.config/opencode/skill/<name>/` |
| 规则（12 条） | 合并进 `AGENTS.md` 标记区块 | 合并进 `AGENTS.md` 标记区块 |
| 管理面（setup.sh / lib / models / personas / docs） | `~/.budgetbuddy/` | `~/.budgetbuddy/` |
| 数据目录 | `.budget/`（项目态） | `~/.budgetbuddy/`（全局态） |

- **项目级优先**：`.opencode/agent/` 存在本套件 agent 时优先于 `~/.config/opencode/agent/`；项目级与全局级可共存
- **管理面恒为全局单点**（`~/.budgetbuddy/`）：setup.sh、lib、budget-models.json、personas.json、docs 统一装在这里，双平台一致；平台结构目录只装 agent/command/skill 等结构性文件——保证安装器增量同步永不触碰用户数据
- **`budget` CLI**：`~/.local/bin/budget`（建议加入 PATH）

## AGENTS.md 合并机制

OpenCode 没有 CodeBuddy 式的 rules 目录机制。BudgetBuddy 的 12 条规则在构建期合并为单文件 `AGENTS.fragment.md`，安装器将其以标记区块形式幂等合并进目标 `AGENTS.md`：

```text
<!-- BudgetBuddy:begin -->
...（12 条规则的标记区块，含 P0 三条与代码规范）...
<!-- BudgetBuddy:end -->
```

- 合并幂等：重装/升级不会重复追加区块
- 区块外内容一律不触碰；卸载时仅移除标记区块内的内容
- 项目根的 `AGENTS.md` 是 OpenCode 会话的项目说明入口（等价于 CodeBuddy 侧的 `CODEBUDDY.md`），本套件的规则区块随安装自动并入

## 模型 provider 前置条件

OpenCode 侧的模型 ID 采用 `provider/model` 格式（如 `anthropic/claude-sonnet-4.6`、`deepseek/deepseek-v4-pro`）。使用预设前，须在 OpenCode 的配置文件（`opencode.json`，位于 `~/.config/opencode/` 或项目根）中配置对应 provider 的 API key：

```json
{
  "provider": {
    "anthropic": { "npm": "@ai-sdk/anthropic", "options": { "apiKey": "{env:ANTHROPIC_API_KEY}" } },
    "deepseek":  { "npm": "@ai-sdk/deepseek",  "options": { "apiKey": "{env:DEEPSEEK_API_KEY}" } }
  }
}
```

- 各 provider 的可用模型清单可用 `opencode models` 查看；预设引用的 ID 须在该清单中存在
- 未配置 key 的 provider 对应的 agent 调度会失败——请按所用预设补齐对应 provider（`budget setup show` 可查看当前各 agent 绑定的模型）
- 预设切换：`budget setup agent preset economic|balanced|quality`（重写 `agent/*.md` frontmatter 的 `model` 字段）；单 agent 覆写：`budget setup agent custom <agent> <provider/model>`

## 命令调用形态差异

CodeBuddy 与 OpenCode 的斜杠命令命名约定不同（构建期由 routing 规则派生，同一份中立源）：

| 中立命令 | CodeBuddy 形态 | OpenCode 形态 |
|---------|---------------|---------------|
| budget start | `/budget:start` | `/budget-start` |
| budget goal | `/budget:goal` | `/budget-goal` |
| budget status | `/budget:status` | `/budget-status` |
| opsx propose | `/opsx:propose` | `/opsx-propose` |
| opsx apply | `/opsx:apply` | `/opsx-apply` |
| opsx archive | `/opsx:archive` | `/opsx-archive` |
| opsx explore | `/opsx:explore` | `/opsx-explore` |

- CodeBuddy 用 `组:名称` 冒号形式；OpenCode 用 `组-名称` 连字符形式（命令名由产物文件名承载）
- OpenCode 产物命令仅输出 description frontmatter（name 与 argument-hint 丢弃）

## hooks 等价能力（插件扩展点）

OpenCode 当前没有 CodeBuddy 式的 settings.json hooks 机制（Notification / PreToolUse / SubagentStop 三事件注入）。BudgetBuddy 在 OpenCode 侧的功能等价途径：

- **工作流内通知**：不受影响——通知由 Leader 在流程节点直接调用 `budget notify "<消息>" <事件名>`（notify.py 经管理面运行），不依赖 hooks
- **事件驱动通知的等价实现**：如需在工具调用/子代理停止等事件上触发通知，建议通过 OpenCode 的插件机制扩展——插件可在其生命周期钩子中调用 `~/.budgetbuddy/lib/` 下的 notify 入口（`budget notify` 或直接执行 notify.py），消息格式与事件名（N1–N11）沿用本套件约定
- **superpowers 质量实践**：CodeBuddy 侧由 hooks.sh 自动启用插件；OpenCode 侧无此机制，工作流已内置降级路径（相关步骤退化为 Leader 自行执行对应实践），无需额外配置
- **规则强制力**：OpenCode 侧 P0 三规则经 AGENTS.md 标记区块 + skill 内联章节双层落位（CodeBuddy 侧为 rules 目录 + 内联），语义一致

## 常见问题

- **`budget` 命令找不到**：确认 `~/.local/bin` 在 PATH 中，或执行 `budget setup init shell` 注入别名
- **agent 未被调度**：确认安装落点正确（`~/.config/opencode/agent/` 或项目 `.opencode/agent/`）；运行 `budget setup validate` 校验安装完整性
- **模型调用失败**：见上文「模型 provider 前置条件」，用 `opencode models` 核对 ID 存在性并补齐 API key
