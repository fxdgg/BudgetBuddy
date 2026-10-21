# codex-platform Delta

## ADDED Requirements

### Requirement: codex 平台 DSL 映射与产物结构

`core/platform/codex.yaml` 遵循 §3.5 DSL schema，产出 `dist/codex/` 为 skill 目录形态：agent 落位 `skills/budget-workflow/agents/{name}.md`（素材文档，frontmatter 仅 name/description 元数据，无 model 烘焙）、命令落位 `skills/budget-workflow/commands/{group}-{name}.md`、skill 落位 `skills/{skill}/`、rules 索引经 `extra_outputs` rules_index 生成 `AGENTS.fragment.md`（轻量索引，全文不进 fragment）、hooks 空串不分发（Codex hooks 实验态）、models/personas/lib/setup/docs 平移；`core/docs/codex-runtime.md` 经 routing.docs 分发至 `skills/budget-workflow/codex-runtime.md`（派工契约：spawn_agent 调用模板/prompt 组装规则/三档模型查表/并行与深度约束）。【MUST】

#### Scenario: 构建产出四平台

- **WHEN** 运行 `python3 scripts/build.py` 且 core/ 内容齐备
- **THEN** dist/codex/ 生成完整产物（skills/budget-workflow/{SKILL.md,agents×10,commands×7,rules×12,codex-runtime.md,子文档}、AGENTS.fragment.md、models、personas、lib、setup.sh、docs），manifest 覆盖全部产物文件

#### Scenario: agent 素材元数据

- **WHEN** 检查 dist/codex/skills/budget-workflow/agents/{name}.md 的 frontmatter
- **THEN** 仅含 `name` 与 `description`，无 model/model_role/tools/permissions/max_turns 键

#### Scenario: hooks 降级不分发

- **WHEN** 检查 dist/codex/ 产物树
- **THEN** 不存在 hooks 事件文件（构建走既有告警路径不失败）

### Requirement: rules 轻量索引与全文双通道

rules 经 `extra_outputs` 新 kind `rules_index` 单次遍历双输出：① `AGENTS.fragment.md` 轻量索引（外层 BudgetBuddy 标记 + 按需读取指引 + 12 条规则一行式清单与落点路径，总体积 < 1KiB，规避 Codex AGENTS.md 默认 32KiB 截断）；② 规则全文副本落 `skills/budget-workflow/rules/budget-{name}.mdc`（构建期从 core/rules/ 单真值源复制）。routing.rule 与 fragment dest 一致性校验同 agents_fragment 先例。【MUST】

#### Scenario: 索引轻量

- **WHEN** 构建完成检查 dist/codex/AGENTS.fragment.md
- **THEN** 含 12 条规则索引行与 skill 内全文路径指引，文件 < 1KiB（全文不在 fragment 中）

#### Scenario: 全文副本单真值源

- **WHEN** core/rules/ 某规则修改后重新构建
- **THEN** dist/codex/skills/budget-workflow/rules/ 对应文件同步更新，与 dist/codebuddy/rules/ 同源一致

### Requirement: AGENTS.md 轻量区块幂等合并与 config.toml 注入

codex 安装将 AGENTS.fragment.md 合并进目标 AGENTS.md（项目根或 `~/.codex/AGENTS.md`，标记区块幂等，机制同 AGENTS 先例）；并向目标 `config.toml`（`.codex/` 或 `~/.codex/`）注入 `[features]` 段 `multi_agent = true`（段存在缺键则段内追加、段不存在则文末追加、已存在则跳过；注入前备份 `config.toml.bak-budget`，原子写，用户其他配置零触碰）——该键是 spawn_agent/wait_agent/close_agent 工具启用前提。卸载反向清理（仅删本键，段空删段）并清理 AGENTS.md 区块。【MUST】

#### Scenario: config.toml 幂等注入

- **WHEN** 连续两次执行 codex 安装
- **THEN** config.toml 恰含一个 `multi_agent = true`，用户已有 TOML 内容原样保留

#### Scenario: 卸载清理

- **WHEN** codex 形态卸载
- **THEN** config.toml 的 multi_agent 键移除（段空则段移除）、AGENTS.md 区块清理（区块外保留）、skill 目录按本地清单删除
