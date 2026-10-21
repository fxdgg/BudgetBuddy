# claudecode-platform Delta

## MODIFIED Requirements

### Requirement: claudecode 平台 DSL 映射与产物结构

`core/platform/claudecode.yaml` 遵循 §3.5 DSL schema（七顶层必填字段 + routing 九键 + emit 表达式白名单），产出 `dist/claudecode/`：agent 落位 `agents/{name}.md`、命令落位 `commands/{group}/{name}.md`（调用形式 `/budget:start`，与 codebuddy 同构）、skill 落位 `skills/{skill}/`、rules 经 `extra_outputs` agents_fragment 合并为 `CLAUDE.fragment.md`（routing.rule 与 dest 一致）、**hook 落位 `hooks/budget-notify-hook.py`（v0.2.1 起分发，Notification/PermissionRequest/SubagentStop 三事件经注入引擎写入 `.claude/settings.json`）**、models/personas/lib/setup/docs 平移。`EMIT_EXPRESSIONS` 七表达式零扩展，camelCase 输出键（`permissionMode`/`maxTurns`）经 emit 键名实现。【MUST】

#### Scenario: 构建产出三平台

- **WHEN** 运行 `python3 scripts/build.py` 且 core/ 内容齐备
- **THEN** dist/claudecode/ 生成完整产物（agents×10、commands×7、skills×6、CLAUDE.fragment.md、hooks/budget-notify-hook.py、models、personas、lib、setup.sh、docs），manifest 覆盖全部产物文件

#### Scenario: agent frontmatter 映射

- **WHEN** 检查 dist/claudecode/agents/{name}.md 的 frontmatter
- **THEN** 含 `name`、`description`、`model`（balanced 预设烘焙值）、`tools`（PascalCase 列表）、`permissionMode`（edit 全放开→acceptEdits、受限→plan）、`maxTurns`（源存在时），且不含 `model_role`/`permissions` 中立键

#### Scenario: hooks 分发与注入

- **WHEN** claudecode 安装完成
- **THEN** `.claude/hooks/budget-notify-hook.py`（或 `~/.claude/hooks/`）存在，对应 settings.json 含本套件三事件 hook 条目（Notification/PermissionRequest/SubagentStop）
