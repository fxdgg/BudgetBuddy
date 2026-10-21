# build-pipeline Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
### Requirement: 全量与选择性构建

`python3 scripts/build.py` 输入 `core/**` + `core/platform/*.yaml`，输出 `dist/codebuddy/` 与 `dist/opencode/` 完整产物（含 docs/ 平移与渲染产物）；`--platform codebuddy|opencode` 仅构建指定平台；流程为：构建到临时目录 `dist/<platform>.new/` → 逐类别转换（agent/命令 frontmatter 重写 / 变量替换 / 落位改名）→ lib/models/personas/docs 处理（平移或渲染）→ rules 合并（opencode 生成 AGENTS.fragment.md）→ §3.1 校验 → 写 .manifest.json → 全部成功后原子替换 `dist/<platform>/`（design.md §4）。【MUST】

#### Scenario: 默认全量构建
- **WHEN** 运行 `python3 scripts/build.py` 且 core/ 内容齐备
- **THEN** dist/codebuddy/ 与 dist/opencode/ 均生成完整产物（agents×10、skills×6、commands×7、rules 落位、models、personas、lib、setup.sh、docs）

#### Scenario: 选择性构建
- **WHEN** 运行 `python3 scripts/build.py --platform opencode`
- **THEN** 仅 dist/opencode/ 被重建，dist/codebuddy/ 保持不变

#### Scenario: 校验失败保持原样
- **WHEN** core 中任一文件违反中立源校验（§3.1）或 DSL schema（§3.5），或任一构建步骤失败
- **THEN** build 以非零退出并清理临时目录，`dist/<platform>/` 保持构建前原样（无半成品产物落盘，不污染已提交的 dist）

### Requirement: 手写 YAML 子集解析器

build.py 内置最小 YAML 子集解析器（约 150 行，Python3 stdlib only，不引 PyYAML），仅支持 platform DSL 实际用到的语法：两空格缩进嵌套 map、块式 list（`- item`）、块式 list 项为 map（`- key: value` + 缩进续行——opencode/claudecode 的 extra_outputs 即此形态）、行内流式 `{}`/`[]`、单/双引号与裸标量（含引号内冒号如 `"/{group}:{name}"` 与值后行内注释）、空字符串 `""`、`#` 注释；解析失败或 DSL schema 不符即 build 失败（design.md §4 / 调整点 A5）。全部语法形态以 tests/test_build.py 固定用例锁定。【MUST】

#### Scenario: 解析全部平台 yaml

- **WHEN** build 解析 core/platform/ 下全部平台 yaml（codebuddy/opencode/claudecode）
- **THEN** 全部字段正确加载为 Python 数据结构，无第三方依赖 import

#### Scenario: 块式 list-of-map 解析

- **WHEN** 解析含 `- kind: agents_fragment` 及缩进续行（source/dest/markers）的 extra_outputs
- **THEN** 正确加载为 list[map]，构建产出 AGENTS.fragment.md / CLAUDE.fragment.md 合并声明

#### Scenario: 不支持的 YAML 语法

- **WHEN** 平台 yaml 中出现锚点、多行字符串或 YAML tag
- **THEN** 解析器报错，build 失败并指出不支持语法所在行

### Requirement: 构建幂等与 manifest 清单

每次构建在临时目录生成、成功后原子替换；构建结束写 `dist/<platform>/.manifest.json`（`{"files": {相对路径: sha256}}`），清单不含任何时间戳；manifest 与一切生成 JSON 一律按键排序输出（sort_keys），目录遍历按名称排序，文件写入统一 UTF-8 无 BOM、LF 行尾——输出确定性不受遍历顺序影响；连续两次构建（core 无改动）产物逐字节一致；manifest 是安装器增量同步与升级差集清理的构建侧依据（design.md §4 / 调整点 A7）。【MUST】

#### Scenario: 重复构建幂等
- **WHEN** core/ 无改动时连续运行两次 build
- **THEN** 两次构建后 `dist/<platform>/.manifest.json` 内容完全一致（diff 为空），且任意多次重复结果稳定

#### Scenario: manifest 覆盖全部产物文件
- **WHEN** 构建完成
- **THEN** dist/<platform>/ 下除 .manifest.json 自身外的每个文件都在 manifest 的 files 键中，且 SHA256 与磁盘文件一致

### Requirement: 空 core 与数据未就位降级

空 core 骨架与内容增量构建场景的降级规则（design.md §4）：`core/agents/` 无文件时跳过「10 个 name 恰为角色清单」集合完备性校验（已存在的文件仍执行单文件 schema 校验）；`core/models/budget-models.json` 缺失时跳过 MODEL_SELECTION.md 渲染与 model_role→model 烘焙（agent 产物不输出 model 字段并输出告警，不失败）；`core/personas/personas.json` 缺失时跳过 personas 平移。全量数据就位后全部校验自动恢复生效。【MUST】

#### Scenario: 空 core 冒烟
- **WHEN** core/ 仅含骨架目录与两份 platform yaml 时运行 build
- **THEN** exit 0，双平台产物目录与 .manifest.json 生成，无集合完备性失败或渲染错误

#### Scenario: models 缺失烘焙降级
- **WHEN** agents 已存在但 budget-models.json 缺失时构建
- **THEN** agent 产物不含 model 字段，构建输出告警但 exit 0；MODEL_SELECTION.md 不产出

### Requirement: MODEL_SELECTION.md 模板化生成

`dist/<platform>/docs/MODEL_SELECTION.md` 由 `core/docs/MODEL_SELECTION.template.md` 模板 + `core/models/budget-models.json` 数据在构建期按平台生成（模型表 + 平台说明段），不允许手写终稿；模板占位符为 `{{models_table}}`/`{{preset_table}}`/`{{platform_note}}` 三个，与 §3.3 六变量共用替换器实现但白名单独立（互不混用，未知名保留原样并告警）；渲染管线在模型数据就位（T8a）后实现并真实验证（design.md §4 / 调整点 A6）。【MUST】

#### Scenario: 模型目录变更同步文档
- **WHEN** budget-models.json 中某模型条目修改后重新构建
- **THEN** 生成的 MODEL_SELECTION.md 反映新数据，无需人工编辑文档

#### Scenario: 占位符白名单独立
- **WHEN** 模板中出现六个正文变量（如 `{{TASK_TOOL}}`）或未知占位符
- **THEN** 该变量原样保留并输出告警，不被误替换或误删除

### Requirement: --check 构建门禁与 --strict

`python3 scripts/build.py --check` 在构建成功后自动执行 `scripts/scan-brand.py`，违禁词命中即整体退出非零；`--strict` 将 §3.4 P0 一致性 diff 告警升级为构建失败（供 CI 使用，本地默认告警不阻断）（design.md §4/§3.4）。【MUST】

#### Scenario: 门禁通过
- **WHEN** 构建成功且扫描零命中
- **THEN** 命令退出码 0

#### Scenario: 门禁失败
- **WHEN** 构建成功但扫描发现任一违禁词
- **THEN** 命令退出码非零并输出违禁词扫描报告

#### Scenario: strict 模式升级 P0 告警
- **WHEN** 以 `--strict` 构建且 P0 一致性 diff 判定不一致
- **THEN** 构建以非零退出（本地无 --strict 时仅告警不阻断）

### Requirement: 平台清单数据驱动

build.py 不再持有双平台硬编码清单：① 模型条目 `platform` 枚举值由 `budget-models.json` 的 `platforms` 键集推导（数据内自洽校验）；② models 校验循环遍历 `data['platforms']` 全部键（每键三档 presets 校验）；③ MODEL_SELECTION 渲染的平台说明文案与待确认 ID 清单来自 `platforms.<p>.note` / `platforms.<p>.unconfirmed_ids` 数据字段（`note` 缺失时沿用现有常量文案回退，保证数据迁移前双平台产物逐字节不变；`_meta.unconfirmed_opencode_ids` 读侧兼容一个版本）；④ preset_table 表头按 `platforms` 键序（JSON 插入序）确定性渲染；⑤ CLI 平台 choices 与默认构建范围 glob `core/platform/*.yaml` 枚举；⑥ 构建期校验 glob 平台集合 == `platforms` 键集（双向不一致显式报错，消除双真值源漂移）。`_validate_preset_value` 改为默认 catalog_id 策略、opencode 特判 provider/model（预设值策略为 catalog_id 的平台零代码接入）。泛化为纯重构：数据未变更（note 走常量回退）时双平台产物与泛化前逐字节一致。【MUST】

#### Scenario: 泛化无回归

- **WHEN** 完成泛化（未加 claudecode.yaml、未改 models.json）后构建

- **THEN** dist/codebuddy/ 与 dist/opencode/ 的 manifest 与泛化前完全一致（hash 回归；平台说明走常量回退）

#### Scenario: 新平台零代码接入

- **WHEN** 仅新增一份 core/platform/<new>.yaml（预设值为 catalog ID 形态）与 models.json 数据段（不改 build.py）后构建

- **THEN** dist/<new>/ 按该 DSL 声明生成产物，走 catalog_id 默认校验策略，其余平台不受影响

#### Scenario: platform 键集自洽校验

- **WHEN** models.json 中某模型条目的 platform 数组含 platforms 键集之外的值
- **THEN** 构建失败并报错指出该条目与非法值

#### Scenario: 双清单漂移报错

- **WHEN** core/platform/*.yaml 集合与 models.json platforms 键集不一致（一侧有、另一侧无某平台）
- **THEN** 构建失败并报错两侧差异，不静默跳过任一平台

#### Scenario: 平台说明数据驱动

- **WHEN** models.json `platforms.claudecode.note` 存在且修改后重新构建

- **THEN** dist/claudecode/docs/MODEL_SELECTION.md 的平台说明段反映新数据；note 缺失的平台沿用常量回退文案

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

### Requirement: extra_outputs rules_index kind

`extra_outputs` 支持 `rules_index` kind（新增枚举，现有 agents_fragment 不变）：`source` 为 `<目录>/**` 形态，`dest` 为轻量索引 fragment 输出（与 routing.rule 一致性校验），可选 `copy_dest` 为规则全文副本目录（构建期单真值源双输出）。索引内容：外层 markers + 按需读取指引 + source 文件一行式清单（规则名 → copy_dest 相对路径）。schema 校验：kind ∈ {agents_fragment, rules_index}；rules_index 的 dest/copy_dest 路径防逃逸与占位符校验同既有规则。【MUST】

#### Scenario: rules_index 双输出

- **WHEN** 构建含 rules_index extra_outputs 的平台（codex）
- **THEN** dest 处生成轻量索引 fragment（< 1KiB）、copy_dest 处生成 source 全文副本

#### Scenario: 未知 kind 报错

- **WHEN** DSL 声明 extra_outputs kind 不在枚举内
- **THEN** 构建失败并指出合法 kind 清单

#### Scenario: 既有平台回归

- **WHEN** codebuddy/opencode/claudecode 构建（无 rules_index 声明）
- **THEN** 三平台产物与 kind 引入前逐字节一致

