# 模型选择指南

> 本文档由构建系统自动生成（数据源：`budget-models.json`），请勿手改。
> 三档预设体现「免费优先 → 平衡 → 质量优先」的成本梯度；档位切换：`budget setup agent preset <economic|balanced|quality>`。

## 模型目录

### 付费模型

| 厂商 | 模型 ID | 档位 | 成本 | 标签 | 可用平台 | 备注 |
|------|---------|------|------|------|----------|------|
| claude | claude-opus-5-5 | top | x3.50 | reasoning | claudecode | 官方 Claude Code 默认模型（$4/百万输入），2026-09-22 发布；经本机 Claude Code 2.1.304 实测核对（2026-10-20） |
| claude | claude-opus-4.8 | top | x3.50 | reasoning | codebuddy, opencode, claudecode |  |
| claude | claude-opus-4.8-1m | top | x3.50 | reasoning, long-context | codebuddy, opencode, claudecode |  |
| claude | claude-opus-4.7-1m | top | x3.33 | reasoning, long-context | codebuddy, opencode, claudecode |  |
| claude | claude-opus-4.7 | top | x3.33 | reasoning | codebuddy, opencode, claudecode |  |
| claude | claude-opus-4.6-1m | top | x3.33 | reasoning, long-context | codebuddy, opencode, claudecode |  |
| claude | claude-opus-4.6 | top | x3.33 | reasoning | codebuddy, opencode, claudecode |  |
| claude | claude-sonnet-5-5 | mid | x2.00 | general | claudecode | 2026-09-28 发布（$2/$10 定价）；经本机 Claude Code 2.1.304 实测核对（2026-10-20） |
| claude | claude-sonnet-4.6-1m | mid | x2.00 | general, long-context | codebuddy, opencode, claudecode |  |
| claude | claude-sonnet-4.6 | mid | x2.00 | general | codebuddy, opencode, claudecode |  |
| claude | claude-haiku-5-5 | budget | x0.67 | fast | claudecode | 2026-10-07 发布；经本机 Claude Code 2.1.304 实测核对（2026-10-20） |
| claude | claude-haiku-4.5 | budget | x0.67 | fast | codebuddy, opencode, claudecode |  |
| gemini | gemini-3.5-flash | mid | x0.99 | agent, tool-use, fast | codebuddy, opencode | Terminal-Bench 76.2%、MCP Atlas 83.6%、Agent Elo 1656 |
| gemini | gemini-2.5-pro | mid | x0.90 | reasoning | codebuddy, opencode | 已弃用：路由稳定性问题，不推荐用作 agent 模型 |
| gemini | gemini-3.1-pro | mid | x1.32 | general | codebuddy, opencode |  |
| gpt | gpt-5.5 | top | x3.31 | general | codebuddy, opencode |  |
| gpt | gpt-5.4 | top | x1.65 | general | codebuddy, opencode |  |
| gpt | gpt-5.3-codex | mid | x1.25 | code | codebuddy, opencode |  |
| gpt | gpt-5.1-codex | light | x0.90 | code | codebuddy, opencode |  |
| gpt | gpt-5.1-codex-mini | budget | x0.18 | code, fast | codebuddy, opencode |  |
| kimi | kimi-k2.7 | mid | x0.65 | code, agent, tool-use, long-context | codebuddy, opencode | K2.6 的编程专用强化版，长程任务 token 消耗显著降低 |
| kimi | kimi-k2.6 | mid | x0.50 | agent, tool-use, long-context | codebuddy, opencode | 已被 K2.7 超越，建议升级到 kimi-k2.7 |
| glm | glm-5.2 | top | x1.06 | code, agent, reasoning, long-context | codebuddy, opencode | 开源系最强文本模型之一：Terminal-Bench 81%、SWE-bench Pro 62.1%、1M context |
| glm | glm-5.1 | mid | x0.90 | code, agent | codebuddy, opencode | 已被 GLM-5.2 大幅超越，建议升级 |
| glm | glm-5v-turbo | light | x0.81 | multimodal, code, tool-use | codebuddy, opencode | 多模态视觉编程基座，适合设计稿转代码与 UI 截图分析场景 |
| glm | glm-5.0 | light | x0.68 | general | codebuddy, opencode |  |
| glm | glm-4.7 | budget | x0.23 | general, fast | codebuddy, opencode |  |
| minimax | minimax-m2.7 | budget | x0.19 | general, fast | codebuddy |  |
| minimax | minimax-m2.5 | budget | x0.13 | general, fast | codebuddy |  |
| deepseek | deepseek-v4-pro | mid | x0.13 | code, agent, reasoning, long-context | codebuddy, opencode | SWE-bench 80.6%、LiveCodeBench 93.5%、1M context，性价比极高，经本机 opencode models 核对存在 |
| deepseek | deepseek-v4-flash | budget | x0.05 | code, fast, long-context | codebuddy | SWE-bench 79.0%、1M context，极低价格 |
| deepseek | deepseek-v3.2 | budget | x0.15 | general | codebuddy | 旧版，建议升级到 V4 |
| deepseek | deepseek-flash | budget | x0.05 | code, fast, long-context | opencode | OpenCode deepseek provider 的 flash 系 ID（与 deepseek-v4-flash 同代），经本机核对存在 |

### 免费模型

| 厂商 | 模型 ID | 档位 | 成本 | 标签 | 可用平台 | 备注 |
|------|---------|------|------|------|----------|------|
| kimi | kimi-k2.5 | free | x0.00 | general, agent | codebuddy |  |
| hunyuan | hy3 | free | x0.00 | general, agent, reasoning | codebuddy | SWE-bench Verified 78.0%、GPQA 90.4%，免费模型中综合能力最强 |
| hunyuan | hunyuan-2.0-thinking | free | x0.00 | reasoning | codebuddy |  |
| opencode | deepseek-v4.1-flash-free | free | x0.00 | code, fast | opencode | OpenCode 官方免费系，经本机 opencode models 核对存在 |
| opencode | glm-5.3-flash-free | free | x0.00 | general, fast | opencode | OpenCode 官方免费系，经本机 opencode models 核对存在 |

## 预设总览（三档 × 全部平台）

| 角色 | claudecode economic | claudecode balanced | claudecode quality | codebuddy economic | codebuddy balanced | codebuddy quality | opencode economic | opencode balanced | opencode quality |
|------|------|------|------|------|------|------|------|------|------|
| architect | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | deepseek-v4-pro | glm-5.2 | claude-opus-4.7-1m | deepseek/deepseek-v4-pro | zhipu/glm-5.2 | anthropic/claude-opus-4.7 |
| coder_lite | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | hy3 | hy3 | deepseek-v4-flash | opencode/glm-5.3-flash-free | opencode/glm-5.3-flash-free | deepseek/deepseek-flash |
| coder_standard | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | deepseek-v4-flash | deepseek-v4-flash | deepseek-v4-pro | deepseek/deepseek-flash | deepseek/deepseek-flash | deepseek/deepseek-v4-pro |
| coder_senior | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | deepseek-v4-pro | deepseek-v4-pro | claude-sonnet-4.6-1m | deepseek/deepseek-v4-pro | deepseek/deepseek-v4-pro | anthropic/claude-sonnet-4.6 |
| reviewer | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | hy3 | deepseek-v4-pro | kimi-k2.7 | opencode/glm-5.3-flash-free | deepseek/deepseek-v4-pro | moonshotai/kimi-k2.7 |
| reviewer_b | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | hunyuan-2.0-thinking | kimi-k2.7 | deepseek-v4-pro | opencode/deepseek-v4.1-flash-free | moonshotai/kimi-k2.7 | deepseek/deepseek-v4-pro |
| tester | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | hy3 | kimi-k2.7 | gemini-3.5-flash | opencode/glm-5.3-flash-free | moonshotai/kimi-k2.7 | google/gemini-3.5-flash |
| recorder | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | hy3 | hy3 | claude-haiku-4.5 | opencode/glm-5.3-flash-free | opencode/glm-5.3-flash-free | anthropic/claude-haiku-4.5 |
| director | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | claude-opus-4.6-1m | claude-opus-4.7-1m | claude-opus-4.7-1m | anthropic/claude-opus-4.6 | anthropic/claude-opus-4.7 | anthropic/claude-opus-4.7 |
| goal_evaluator | claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 | kimi-k2.5 | claude-haiku-4.5 | claude-haiku-4.5 | opencode/deepseek-v4.1-flash-free | anthropic/claude-haiku-4.5 | anthropic/claude-haiku-4.5 |

## 平台说明

- 本平台预设值为 CodeBuddy 原生模型 ID（kebab-case）；构建期以 balanced 档烘焙 agent 产物的 model 字段。
- 安装后可通过 `budget setup agent preset <economic|balanced|quality>` 批量切换档位，`budget setup agent custom <模型ID或别名>` 自定义覆写（简写别名经 aliases 表解析），`budget setup agent inherit` 跟随主会话模型。

## 使用建议

- **默认档位为 balanced**：构建期 agent 产物的 `model` 字段按 balanced 预设烘焙，覆盖全部 10 个角色。
- **成本梯度不可倒挂**：coder_senior > coder_standard > coder_lite（任何预设均满足）。
- **审查与编码尽量不同厂商**：减少「自己写自己审」的同系盲区。
- **简写别名**：`budget setup agent custom <alias>` 支持简写（如 `opus`/`kimi`/`glm`），自动解析为标准 ID 后统一覆写。
- **待确认标注**：各平台未能核对的 provider/model ID 在 `budget-models.json` 的 `platforms.<平台>.unconfirmed_ids` 中列出，上线前须逐一核对清零。
