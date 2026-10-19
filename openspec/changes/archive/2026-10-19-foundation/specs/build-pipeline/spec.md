## ADDED Requirements

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

build.py 内置最小 YAML 子集解析器（约 150 行，Python3 stdlib only，不引 PyYAML），仅支持 platform DSL 实际用到的语法：两空格缩进嵌套 map、块式 list（`- item`）、块式 list 项为 map（`- key: value` + 缩进续行——opencode.yaml 的 extra_outputs 即此形态）、行内流式 `{}`/`[]`、单/双引号与裸标量（含引号内冒号如 `"/{group}:{name}"` 与值后行内注释）、空字符串 `""`、`#` 注释；解析失败或 DSL schema 不符即 build 失败（design.md §4 / 调整点 A5）。全部语法形态以 tests/test_build.py 固定用例锁定。【MUST】

#### Scenario: 解析两份平台 yaml
- **WHEN** build 解析 core/platform/codebuddy.yaml 与 opencode.yaml
- **THEN** 全部字段正确加载为 Python 数据结构，无第三方依赖 import

#### Scenario: 块式 list-of-map 解析
- **WHEN** 解析含 `- kind: agents_fragment` 及缩进续行（source/dest/markers）的 extra_outputs
- **THEN** 正确加载为 list[map]，构建产出 AGENTS.fragment.md 合并声明

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
