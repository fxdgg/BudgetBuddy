# build-pipeline Delta

## ADDED Requirements

### Requirement: agent frontmatter emit 表达式白名单含 auto_run

`scripts/build.py` 的 `EMIT_EXPRESSIONS`（agent_frontmatter.emit 域合法占位符精确集合）为八表达式：`name`/`description`/`resolved_model`/`tools|pascal`/`permission_mode`/`permission_map`/`max_turns`/`auto_run`（无裸 `tools`）；`validate_dsl` 拒绝集合外占位符（既有行为不变）。`rewrite_agent` 对 `{auto_run}` 表达式：仅源 frontmatter 存在该键时输出布尔值（与 `{max_turns}` 的「仅源存在时输出」同构），缺省时对应产物键整体不出现；YAML 解析/序列化层零改动（`parse_yaml` 既有 `true`→bool、`_dump_scalar` 既有 bool→`true` 能力）。【MUST】

#### Scenario: {auto_run} 表达式被接受并映射

- **WHEN** codebuddy.yaml 的 `agent_frontmatter.emit` 声明 `enabledAutoRun: "{auto_run}"` 且某 agent 源含 `auto_run: true`
- **THEN** 该 agent 产物 frontmatter 输出 `enabledAutoRun: true`（键名为 emit 表输出键，camelCase 与 `permissionMode` 先例一致）

#### Scenario: 源缺省时产物键不出现

- **WHEN** 构建某未声明 `auto_run` 的 agent
- **THEN** 产物 frontmatter 不含 `enabledAutoRun` 键（不输出 false 字面量，产物最小化）

#### Scenario: 集合外占位符仍被拒绝

- **WHEN** 某平台 yaml 的 emit 域出现 `{auto_run_x}`、`{toolz}` 等集合外占位符
- **THEN** build 失败并指出合法表达式集合（八表达式清单），既有 EmitWhitelistTests 回归通过

#### Scenario: 既有 emit 表达式行为不变

- **WHEN** 构建全部平台（含未声明 `enabledAutoRun` 的 opencode/claudecode）
- **THEN** 除 4 个执行类 agent 的 CodeBuddy 产物新增一行与 CodeBuddy 新增 `agents/.bash-patterns.json` 数据文件外，三平台其余产物与变更前逐字节一致

### Requirement: 映射 auto_run 的平台生成 bash 模式数据文件

构建期为 `agent_frontmatter.emit` 映射 `{auto_run}` 的平台（当前仅 codebuddy）生成免审批 bash 模式数据文件 `<output>/agents/.bash-patterns.json`（路径由 routing.agent 模板父目录派生，不新增 DSL 键）：内容 `{"agents": {"<agent-name>": {"bash_allow": [...]}}}`（10 个 agent 全集、键排序、JSON indent 2、末尾换行），数据源为 `core/agents/*.md` frontmatter `permissions.bash_allow`（缺省按既有 `_permission_lists` 口径 `["*"]`，构建期已经 validate_agent 三态校验）；未映射 `{auto_run}` 的平台（opencode/claudecode）不生成该文件（产物零变化）。该文件供运行时 `autorun on` 安全知情提示读取（安装后随 manifest 同步落位 `agents/.bash-patterns.json`），中立源 `core/agents/` 目录本身不新增任何非 .md 文件。【MUST】

#### Scenario: codebuddy 构建生成数据文件

- **WHEN** 构建 codebuddy 平台
- **THEN** `dist/codebuddy/agents/.bash-patterns.json` 存在，含全部 10 个 agent 的 bash_allow 且与 `core/agents/*.md` 源逐项一致（如 coder-lite `["*"]`、architect `["git *", "openspec *"]`），并收入 `.manifest.json`

#### Scenario: 未映射平台不生成数据文件

- **WHEN** 构建 opencode / claudecode 平台
- **THEN** 两平台产物不含 `.bash-patterns.json`（及任何 auto-run 相关数据文件），与变更前逐字节一致
