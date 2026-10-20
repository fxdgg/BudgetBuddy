# build-pipeline Delta

## MODIFIED Requirements

### Requirement: 全量与选择性构建

`python3 scripts/build.py` 输入 `core/**` + `core/platform/*.yaml`，输出全部已声明平台（当前为 codebuddy/opencode/claudecode）的完整产物（含 docs/ 平移与渲染产物）；`--platform <name>` 仅构建指定平台（平台清单构建期从 `core/platform/*.yaml` 枚举，非硬编码元组）；流程为：构建到临时目录 `dist/<platform>.new/` → 逐类别转换（agent/命令 frontmatter 重写 / 变量替换 / 落位改名）→ lib/models/personas/docs 处理（平移或渲染）→ rules 合并（opencode 生成 AGENTS.fragment.md、claudecode 生成 CLAUDE.fragment.md）→ §3.1 校验 → 写 .manifest.json → 全部成功后原子替换 `dist/<platform>/`（design.md §4）。【MUST】

#### Scenario: 默认全量构建

- **WHEN** 运行 `python3 scripts/build.py` 且 core/ 内容齐备

- **THEN** dist/codebuddy/、dist/opencode/ 与 dist/claudecode/ 均生成完整产物（agents×10、skills×6、commands×7、rules 落位或合并、models、personas、lib、setup.sh、docs）

#### Scenario: 选择性构建

- **WHEN** 运行 `python3 scripts/build.py --platform claudecode`

- **THEN** 仅 dist/claudecode/ 被重建，dist/codebuddy/ 与 dist/opencode/ 保持不变

#### Scenario: 未知平台名

- **WHEN** 运行 `python3 scripts/build.py --platform <未在 core/platform/ 声明的名字>`

- **THEN** build 以非零退出并报错列出可用平台清单

#### Scenario: 校验失败保持原样

- **WHEN** core 中任一文件违反中立源校验（§3.1）或 DSL schema（§3.5），或任一构建步骤失败

- **THEN** build 以非零退出并清理临时目录，`dist/<platform>/` 保持构建前原样（无半成品产物落盘，不污染已提交的 dist）

## ADDED Requirements

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

## MODIFIED Requirements

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
