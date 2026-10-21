---
description: Leader 禁写业务代码。Leader 禁止直接编写或修改业务代码，所有代码修改必须通过 spawn_agent 工具调度分级 coder agent 执行；即使是 1 行 typo 也必须委派 coder-lite 执行。
globs: ["**/*"]
alwaysApply: true
---

# leader-no-code（Leader 禁写业务代码）

Leader 禁止直接编写或修改业务代码，所有代码修改必须通过 spawn_agent 工具调度分级 coder agent 执行；Leader 仅允许编辑平台配置目录（CodeBuddy 的 `.codebuddy/` 或 OpenCode 的 `.opencode/`）、`openspec/*`、`docs/*`、`*.md` 等流程与文档白名单文件（即 `.codebuddy/*` 或 `.opencode/*` 按平台），即使是 1 行 typo 也必须委派 coder-lite 执行。
