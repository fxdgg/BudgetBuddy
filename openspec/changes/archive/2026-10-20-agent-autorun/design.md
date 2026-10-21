# 设计：子代理 AutoRun 免审批（agent-autorun）

> 承接 proposal 与 specs。核心策略：**中性源单字段 + CodeBuddy 单平台映射 + 运行时用户切换器（状态文件 + 行级补丁 + 安装重放）**；OpenCode/Claude Code 明确不映射并文档化降级。

## Context

CodeBuddy IDE 的 Subagent 调度中，子 agent 每次工具调用弹审批框（仅「允许一次/拒绝」），执行类 agent（coder 三级 + tester）高频调用被严重拖慢。官方机制：Subagent frontmatter `enabledAutoRun: true`（设置页 Agent Tab "Auto Run" 项）开启后免逐条审批。

仓库现状（已核实）：

- 中立源 `core/agents/*.md` frontmatter：name/description/model_role/tools/permissions(edit_allow/bash_allow)/max_turns（如 `core/agents/tester.md` L1-9）
- `core/platform/codebuddy.yaml` L19-28：`agent_frontmatter.emit` 输出 name/description/model/tools/permissionMode/max_turns；`drop: [model_role, permissions]`
- `scripts/build.py`：`EMIT_EXPRESSIONS`（L88-91，七表达式）；`rewrite_agent`（L871-901，按 emit 表逐表达式分发，`{max_turns}` 走「仅源存在时输出」L895-898）；`validate_agent`（L765-803，max_turns 正整数校验 L798-801）；YAML 层 `parse_yaml` 已支持 `true`→bool（L236-239）、`_dump_scalar` 已支持 bool→`true`（L536-537）——**序列化层零改动**
- 运行时补丁先例：`core/lib/model_resolver.py` `rewrite_agent_file`（L247-301）——仅触碰 `model` 一行、锚点（name/description/mode 最后出现行之后）、行尾保留、临时文件原子写
- agent 文件写入入口：`install.sh` `install_codebuddy`（L905-949，`sync_manifest_tree` 增量同步 L925、`upgrade_diff_cleanup` L929、`write_local_manifest` L936）；另一写入口 `budget setup preset`（`model_resolver.py` `rewrite_agent_file`）仅触碰 `model` 行、不涉 `enabledAutoRun`——两写入口字段不相交，双写漂移论证实质成立；`budget setup update`（`core/lib/update.sh` L385 `do_update`）**不刷新 agent 文件**（仅同步 lib 与管理面数据）；`budget setup reinstall`（`core/lib/uninstall.sh` L1010）清除结构文件后须重跑 install.sh
- 分发先例：`core/setup.sh` L520-528 quickstart/stats 直调 python（`exec "$BUDGET_PYTHON" "$BUDGET_LIB_DIR/xxx.py"`，模块缺失报错指引 update）
- 基线：门禁三命令全绿（build --check / scan-brand / unittest；测试计数随仓库演进会漂移——本方案第 2 轮修订时实测 709 OK / 93s 全绿，**以实施时实测为准**，由 task 1.4 / 4.1 刷新记录）

## Goals / Non-Goals

**Goals:** 4 个执行类 agent 在 CodeBuddy 平台开箱免审批；其余 6 个 agent 提供用户可自主操作的持久化「允许全部」机制（`budget setup autorun`）；三平台行为明确（codebuddy 映射、opencode/claudecode 文档化降级）；存量安装平滑升级、用户选择不丢失；门禁三命令 + 测试覆盖。

**Non-Goals:** OpenCode/Claude Code 新增 auto-run 字段或权限映射改动；IDE 弹窗改造（「允许一次」为既有能力）；per-task 临时授权；改动 6 个保留 agent 的默认值。

## Decisions

### D1 中性源字段：`auto_run`（可选布尔，缺省不输出）

- **命名**：snake_case `auto_run`，与 `model_role`/`max_turns` 风格一致；语义 = 「subagent 调用工具是否需逐条人工确认」的交互策略声明。
- **默认值**：缺省（不写 key）= 不声明免审批。**不采用 `auto_run: false` 显式默认**——emit 采用「仅源存在时输出」（`{max_turns}` 先例，build.py L895-898），6 个保留 agent 源文件零改动即得正确产物，diff 最小。
- **为什么不放进 `permissions`**：`permissions` 表达「允许什么操作」（edit_allow/bash_allow 三态），`auto_run` 表达「已允许的操作是否还需逐条确认」——正交关注点；且 OpenCode/Claude Code 无对应权限键，混入会破坏三平台权限映射的封闭性。
- **备选被否**：① 平台 yaml 持清单（`agent_frontmatter.auto_run: [...]`）——把 per-agent 属性搬去 DSL，违背「core/ 单一中立源、内容修改都在 core/agents」的仓库纪律；② 布尔字符串 `"true"`——YAML 层 round-trip 会引入引号形态漂移，且 validate 需额外兼容，无收益。

### D2 三平台映射

| 平台 | 映射 | 依据 |
|------|------|------|
| codebuddy | emit `enabledAutoRun: "{auto_run}"`，仅源存在时输出 | 官方 frontmatter 字段；emit 输出键名任意（camelCase `permissionMode` 先例，claudecode.yaml L25 注释），零 schema 扩展 |
| opencode | **不映射** | OpenCode 审批机制即 permission map（`ask`/`allow`/`deny`，官方 docs：allow = 免审批）。4 个目标 agent 既有映射已等价：coder 三者 edit/bash 全 allow；tester bash allow（edit deny 为只读设计，非审批问题）。`auto_run` 经 emit 白名单机制天然丢弃 |
| claudecode | **不映射（无等效机制）** | Claude Code 子代理 frontmatter 无 per-subagent auto-run 开关；审批由会话权限模式 / settings.json permissions 承担。降级：文档指引（settings.json `permissions.allow` 规则或权限模式），运行时 `budget setup autorun` 在该平台输出替代指引并 exit 0 零改动 |

- 三平台 yaml 中仅 codebuddy.yaml 改一行；opencode.yaml/claudecode.yaml **零改动**（不映射 = 不加 emit 项，drop 机制天然覆盖）。

### D3 build.py 扩充点（精确到函数）

1. `EMIT_EXPRESSIONS`（L88-91）：集合加 `'auto_run'`，注释「七表达式」→「八表达式」。
2. `rewrite_agent`（L895-898 `{max_turns}` 分支之后）：新增 `elif expr == '{auto_run}':` 分支——`if 'auto_run' in fm: out[out_key] = fm['auto_run']`（布尔直出，`_dump_scalar` 渲染 `true`）。
3. `validate_agent`（L798-801 max_turns 校验之后）：`auto_run` 存在时必须为 `bool`（拒绝字符串/整数），错误文案风格与既有一致。
4. **新增 `_build_agent_bash_patterns` 函数 + `_build_all`（L1654 `_build_agents` 调用行之后）增一行调用**——为映射 `{auto_run}` 的平台生成免审批 bash 模式数据文件（详见 D7，A1 修订新增锚点）。
5. 不改 `parse_yaml`/`dump_*`/`validate_dsl` 主体逻辑（白名单集合即校验入口，新表达式自动获得「域内合法」身份；集合外占位符拒绝行为不变，既有 EmitWhitelistTests 回归）。

> A1 修订注记：build.py 改动锚点由三处（白名单/rewrite/validate）扩为四处（+ 数据文件生成），全部位于同一文件 `scripts/build.py`（文件范围表内既有修改项），不新增范围外文件。

### D4 「允许全部」用户选择机制：`budget setup autorun`

**形态**：新模块 `core/lib/autorun.py`（Python stdlib only；argparse 子命令 `list`/`on`/`off`/`apply`），经 `core/setup.sh` 分发层新增 `autorun)` case——完全复用 quickstart/stats 直调形态（L520-528 先例）：`detect_platform` 注入形态变量 → `exec "$BUDGET_PYTHON" "$BUDGET_LIB_DIR/autorun.py" "$@"`；模块缺失时报错并指引 `budget setup update`。**不新增 shell 包装文件**（python 单文件自足，降低 lib 文件数与管理面同步面）。

**配置（状态文件）**：`~/.budgetbuddy/auto-run.json`，`{"agents": ["coder-lite", ...]}`（排序确定、indent 2、sort_keys）。全局单点——全局固定路径用户数据先例为 `~/.budgetbuddy/notify.json`（quickstart.py 数据目录解析；coder-guard.json 实为项目级 `projects/<name>/memory/`，不作本机制先例）；不设项目级覆盖（状态语义全局一致，安装态随探测而定，见下「作用域」）。

**作用域（多安装形态语义）**：`on`/`off` 的补丁作用域 = **当前探测到的安装态**（`detect_platform` 注入的 `BUDGET_PLATFORM_KIND`/`BUDGET_AGENTS_DIR`；`core/setup.sh` L485-488 stats 分发先例：`detect_platform >/dev/null || true` 后 export 四变量传入子进程）。探测优先级：项目级 codebuddy > 全局 codebuddy > claudecode > opencode；项目级优先、多平台共装 codebuddy 优先。因此：① 同一机器多个项目级安装时，全局状态文件记录选择、补丁只落当前项目——**多项目需逐项目各执行一次** `on`/`off`（场景：项目 A `off coder-lite` 后全局状态记录关闭，但项目 B 安装态仍开启）；② `list` **双栏输出**（全局状态清单 + 当前安装态实况逐 agent 比对）暴露两者差异；③ 状态文件存在后为唯一真源——此后经 IDE 设置页的手动变更不再被种子化吸收，且可能被下次 install 重放覆盖（差异经 list 双栏暴露；「从未用过 autorun」窗口的漂移见 Risks）。

**unknown 形态**：`detect_platform` 五级均未命中时 kind=unknown（`|| true` 不阻断、unknown 流入子进程）——`on`/`off`/`apply` **非零退出**并提示先安装 BudgetBuddy 或以 `BUDGET_PLATFORM=codebuddy|claudecode|opencode` 显式指定；`list` 仍 exit 0（全局清单 + 实况栏提示未检测到安装形态）。

**损坏状态文件**：`on`/`off`/`apply` 遇 JSON 解析失败 → **非零退出 + 提示修复路径（编辑或删除 `~/.budgetbuddy/auto-run.json`），绝不覆盖写**（否则用户基线永久丢失）；install 路径上 apply 非零即告警继续（installer spec 既有场景）。

**生效方式（行级补丁）**：`on`/`off`/`apply` 对已安装 `.codebuddy/agents/<name>.md` frontmatter 做**单行补丁**——算法复刻 `model_resolver.py` `rewrite_agent_file`（L247-301）：`on` = 有 `enabledAutoRun` 行则改值 `true`、无则在锚点行（name/description 最后出现行之后）插入；`off` = 删除该行；保留原行尾（CRLF/LF）、临时文件原子写、frontmatter 其余字段与正文逐字节保留。`apply` = 全量对齐（清单内 on、清单外 off），供安装重放调用。`on` 输出的安全知情提示（列目标 agent 免审批的 bash 模式）数据来源见 D7。

**种子化**：状态文件缺失时 `on`/`off` 先扫描已安装 agent 再变更。进基线口径：**仅「`enabledAutoRun` 行存在且值解析为 `true`」的 agent**——若 IDE 关闭态写入形态为 `enabledAutoRun: false`（行在值假），按「行存在」判定会把用户手动关闭翻转为开启（用户手动关闭 X 后执行 `autorun on Y`，X 被纳入开启基线，此后 install 重放把 X 重新打开——显式关闭被静默翻转）；验证确认前，按值判定是唯一安全口径。写入形态与 Open Question「IDE 关闭时的写入形态」联动端到端验证；若实证为删行形态则可简化（保持按值判定亦正确）。用户此前经 IDE 设置页 Agent Tab 的手动开启（值 `true`）被保留为基线，不丢失。

**与构建/安装流程的关系**：

- 构建期：`auto_run`（4 个默认）→ dist 产物，**构建不读用户状态文件**（repo 纯净，构建确定性不受用户环境影响）。
- 安装期：`install.sh` `install_codebuddy` 在 `upgrade_diff_cleanup`（L929，含其告警块 L930-932）之后、`write_local_manifest`（L936）之前插入重放钩子（L933-935 区间，步骤编号「2.5) AutoRun 状态重放」）——状态文件存在则 `"$BUDGET_PYTHON" "$install_root/lib/autorun.py" apply`（lib 刚随 `sync_manifest_tree` L925 同步就位）；失败仅告警不阻断。dist agent 文件写入入口为 install.sh（preset 的 `rewrite_agent_file` 仅碰 model 行，字段不相交），重放单点即无 `enabledAutoRun` 双写漂移。
- update 期：`do_update` 不刷新 agent 文件（现状核实）→ 用户切换天然存活，**零改动**。
- 有效 agent 名 = 已安装 agents 目录 .md 主名；未知名非零退出并列可用名（不引入 budget-models.json 依赖，补丁对象就是安装态文件本身）。

### D5 兼容性与存量升级路径

- **存量用户升级**：重跑新版本 install.sh（installer spec「升级」语义：清单内文件被新 dist 覆盖）→ 4 个执行类 agent 获得 `enabledAutoRun: true`；若用户已有状态文件 → 重放恢复其选择；若无 → dist 默认值成立。
- **用户手动编辑（IDE 设置页）**：安装覆盖会丢手动补丁——由「种子化 + 重放」组合消解：首次 `autorun on/off` 把手动开启种子化进状态文件，此后 install 重放保持。
- **回滚**：`auto_run` 为纯增量字段——旧版本 build/install 不识别 `enabledAutoRun` 键但不受影响（frontmatter 未知键忽略）；状态文件为独立新文件，卸载不动用户数据（`do_uninstall` 按本地清单删结构文件，`~/.budgetbuddy/` 用户数据保留）；**重装后 install 重放会静默恢复旧免审批选择——README 须明示「autorun 选择持久化于用户数据目录，卸载不清除，重装后恢复」（知情权，建议 7）**。
- **产物回归**：opencode/claudecode 产物零变化（不映射 auto_run，按 D7 门控不生成数据文件）；codebuddy 产物为 4 个 agent 文件各 +1 行 + `agents/.bash-patterns.json` 新增一件（D7）

### D6 测试策略

- `tests/test_build.py`（unittest，既有分类风格）：① `EmitWhitelistTests` 增 `{auto_run}` 被接受用例（含真实 codebuddy.yaml emit 断言 `enabledAutoRun → {auto_run}`）；② `PermissionMappingTests` 增 `rewrite_agent` 用例——源含 `auto_run: True` → 产物含 `enabledAutoRun: true`；源缺省 → 产物不含该键；③ `FrontmatterValidationTests` 增 `auto_run` 非布尔（`"true"`/`1`）→ BuildError 用例；④ 既有七表达式拒绝用例（`{tools}`/`{skill}`/`{toolz}`）回归不动；⑤ **D7 数据文件用例**（`BuildPipelineTests` 或新分类）：codebuddy 构建产物含 `agents/.bash-patterns.json` 且 10 个 agent 的 bash_allow 与 `core/agents/*.md` 源一致；opencode/claudecode 构建产物不含该文件（逐字节不变回归）
- **`tests/test_autorun.py`（新增）**：复刻 `tests/test_preset.py` `RewriteUnitTests(SandboxTestCase)` 沙盒模式（L195-209 公共沙箱 + L103-106 子进程直调 lib python 先例）——tmp 目录伪造 agents 目录 + 隔离 HOME + 子进程直调 `core/lib/autorun.py`，把原「沙盒手动验证」项转为自动化用例：① 补丁插入/改值/删除与锚点（name/description 最后出现行之后）；② CRLF 行尾保留；③ 幂等（重复 on/off 字节稳定）；④ 种子化仅值 `true` 进基线（`enabledAutoRun: false` 行不翻转）；⑤ apply 全量对齐（清单内 on/清单外 off）；⑥ 损坏 JSON 非零退出且状态文件字节不被改写；⑦ unknown 形态 on/off 非零退出、list exit 0；⑧ opencode/claudecode 降级 exit 0 零文件修改（mtime/内容双核验）；⑨ list 双栏输出；⑩ list 遇损坏状态文件只读展示（状态栏明示损坏 + 修复指引，退出码 0，状态文件字节不变——O1 锁定）；⑪ `.bash-patterns.json` 存在时 `on` 输出列目标 agent 的 bash 模式、缺失时降级通用提示且不阻断（D7）。门禁三命令随之覆盖 autorun.py 关键行为（幂等/CRLF/锚点/损坏降级不再依赖手动）
- **installer 集成面并入 `tests/test_installer.py` 自动化（B1 修订）**：原「沙盒手动验证」留法理由不成立——仓库事实是 `tests/test_installer.py` 已有 41 例 subprocess 驱动 install.sh 端到端（mini 仓库 + dist 副本 + HOME 隔离，覆盖同步跳过/覆盖、升级差集清理、失败降级不阻断、重装幂等，`InstallerSandbox` 先例），与 test_autorun 沙盒模式同构；「tests 不分发内嵌测试的纪律」管的是 dist 分发面，不构成仓库内 installer 测试留手动的理由。installer spec 的 4 个 MUST 场景按该先例自动化完全可行：在 `test_installer.py` 增补 AutoRun 重放用例类——① 钩子落点（`upgrade_diff_cleanup` 后、`write_local_manifest` 前；状态文件存在时 apply 被调用，reviewer 的 `enabledAutoRun` 被重放恢复）；② 无状态文件不重放（dist 默认 4 个在位）；③ 损坏状态文件 apply 失败仅告警不阻断、安装完成且状态文件字节不变；④ 二次安装 apply 幂等（终态与首次一致、文件字节稳定——注意非默认状态下第二次同步会先以 dist 重覆盖偏差 agent，再由 apply 重放恢复，见 installer delta「重放不影响安装幂等性」场景）
- 沙盒手动验证仅保留真实终端形态抽查（自动化不覆盖人机交互呈现）：unknown 形态与 list 双栏呈现（含损坏态）、opencode/claudecode 形态冒烟（降级 exit 0 零修改，mtime/内容双核验）、旧安装缺 `.bash-patterns.json` 时 `on` 输出降级为通用提示、`on` 对 architect（git 类）与 coder-lite（`*`）的醒目提示呈现核对
- 门禁：`python3 scripts/build.py --check`（含 dist 同步）、`python3 scripts/scan-brand.py`（README/CHANGELOG 在扫描范围）、`python3 -m unittest discover -s tests`

### D7 `autorun on` 安全知情提示的 bash 模式数据来源（A1 修订）

**问题（第 2 轮主审阻塞项）**：spec/design/tasks 要求 `autorun on` 输出「列出该 agent 免审批的 bash 模式」，但安装态环境无此数据——dist 产物 agent frontmatter 仅含 name/description/model/tools/permissionMode/max_turns（`permissions` 被 `core/platform/codebuddy.yaml` L28 `drop` 丢弃），dist 树中无任何 bash_allow 数据，`core/agents/` 中立源不随安装分发。

**决策：build 期从 `core/agents/*.md` 生成轻量权限数据文件，随 CodeBuddy dist 分发。**

- **产物**：`dist/codebuddy/agents/.bash-patterns.json`（安装后落 `<install_root>/agents/.bash-patterns.json`），内容 `{"agents": {"<agent-name>": {"bash_allow": [...]}, ...}}`（10 个 agent 全集、键排序、indent 2、末尾换行，与 `.manifest.json` 同风格 JSON 序列化；`bash_allow` 缺省按 `_permission_lists` 既有口径 `["*"]`）
- **单一中立源保持**：数据由 `core/agents/*.md` frontmatter `permissions.bash_allow` 生成（该字段已经 `validate_agent`/`_permission_lists` 三态校验，构建期即保证合法），autorun.py **零硬编码权限表**，core/agents 修改后重建即同步，无漂移
- **门控（影响面收敛）**：仅当平台 `agent_frontmatter.emit` 映射 `{auto_run}`（即映射 AutoRun 的平台）时生成；opencode/claudecode 不映射故不生成——两平台产物**逐字节不变声明仍成立**
- **build.py 落点**（D3 第 4 锚点）：新函数 `_build_agent_bash_patterns(core_dir, dist_dir, dsl)`——遍历 `core/agents/*.md` 读 frontmatter（与 `_build_agents` 同源遍历，`.md` 限定），按门控判定后写 `dist_dir / <routing.agent 模板父目录> / '.bash-patterns.json'`（路径由 routing 派生，不新增 DSL 键、不动 `validate_dsl`）；`_build_all` 在 `_build_agents` 调用行之后增一行调用
- **分发零额外改动**：`gen_manifest`（`rglob('*')`）收录点文件；`sync_manifest_tree` 按清单逐条目同步（无点文件过滤，`cp -p` 落位）→ install.sh 无需为数据文件加任何逻辑，本地清单自动收录；文件位于 agents/ 内不影响 autorun.py 的 `.md` 主名扫描（有效 agent 名 = .md 主名，数据文件被天然忽略）
- **运行时读取与降级**：autorun.py 从 `BUDGET_AGENTS_DIR/.bash-patterns.json` 读目标 agent 的 `bash_allow`；**文件缺失（旧安装未重建 dist / 手动拷贝安装）时降级为通用知情提示**（明示「AutoRun = 权限范围内所有工具调用免人工审批」但不列具体模式），不阻断 on 流程；`bash_allow` 为 `[]`（显式全禁止）时提示无 bash 权限
- **备选否掉**：① autorun.py 硬编码 10 agent 权限表——违反「core/ 单一中立源」纪律且随 core/agents 演进漂移；② 并入 `personas.json` 类既有数据文件——personas 经 routing 三平台全分发，会破坏 opencode/claudecode 逐字节不变影响声明；③ 降级为通用知情文案（不列模式）——削弱安全知情强度，且 spec L33/L68-71 已锁定 MUST 级「列出 bash 模式」，为主审非首选
- **影响声明同步**：文件范围表不变（`scripts/build.py` 为表内既有修改项，`dist/**` 为表内既有重新生成项）；dist 变更面由「codebuddy 四文件 +1 行」扩为「四文件 +1 行 + `agents/.bash-patterns.json` 新增一件」；opencode/claudecode 零变化不变

## 文件范围

| 文件路径 | 修改类型 | 说明 |
|---------|---------|------|
| `core/agents/coder-lite.md` | 修改 | frontmatter 加 `auto_run: true`（L9 max_turns 后一行） |
| `core/agents/coder-senior.md` | 修改 | 同上 |
| `core/agents/coder-standard.md` | 修改 | 同上 |
| `core/agents/tester.md` | 修改 | 同上 |
| `core/agents/architect.md` | ❌ 不修改 | 保留逐条确认 |
| `core/agents/director.md` | ❌ 不修改 | 保留逐条确认 |
| `core/agents/goal-evaluator.md` | ❌ 不修改 | 保留逐条确认 |
| `core/agents/recorder.md` | ❌ 不修改 | 保留逐条确认 |
| `core/agents/reviewer.md` | ❌ 不修改 | 保留逐条确认 |
| `core/agents/reviewer-b.md` | ❌ 不修改 | 保留逐条确认 |
| `core/platform/codebuddy.yaml` | 修改 | emit 加 `enabledAutoRun: "{auto_run}"`（L26 max_turns 项后） |
| `core/platform/opencode.yaml` | ❌ 不修改 | 不映射（permission map 已等效） |
| `core/platform/claudecode.yaml` | ❌ 不修改 | 不映射（无等效机制，文档降级） |
| `scripts/build.py` | 修改 | L88-91 白名单 + L895-898 后新分支 + L798-801 后新校验 + `_build_agent_bash_patterns` 新函数与 `_build_all` 一行调用（D3 第四锚点 / D7） |
| `core/lib/autorun.py` | 新增 | list/on/off/apply（stdlib only） |
| `core/setup.sh` | 修改 | 分发 case + help 文案 |
| `install.sh` | 修改 | `install_codebuddy` 差集清理后、写本地清单前插入重放钩子 |
| `tests/test_build.py` | 修改 | emit 白名单 / rewrite / validate 用例 + D7 数据文件生成用例（codebuddy 含 / opencode、claudecode 不含） |
| `tests/test_autorun.py` | 新增 | 复刻 RewriteUnitTests 沙盒模式：补丁锚点/CRLF/幂等/种子化按值判定/损坏降级/unknown/降级/双栏 |
| `README.md` | 修改 | AutoRun 说明 + autorun 用法 + 平台差异（品牌扫描范围） |
| `README_CN.md` | 修改 | 同上（中文版） |
| `CHANGELOG.md` | 修改 | Unreleased → Added |
| `dist/**` | 重新生成 | 由 build.py 生成，禁手改；codebuddy 侧新增 `agents/.bash-patterns.json`（D7），opencode/claudecode 零变化 |

## 同类路径对照

审批/权限类变更强制对照——10 个 agent × `auto_run` 声明与 3 平台 × 映射路径全量审视，防只改一条路径：

| 路径 | auto_run 声明 | CodeBuddy 产物 | OpenCode | Claude Code | 本次修改 |
|------|--------------|---------------|----------|-------------|---------|
| core/agents/coder-lite.md | `true` | `enabledAutoRun: true` | 不映射（既有全 allow） | 不映射（无机制） | ✅ |
| core/agents/coder-standard.md | `true` | `enabledAutoRun: true` | 同上 | 同上 | ✅ |
| core/agents/coder-senior.md | `true` | `enabledAutoRun: true` | 同上 | 同上 | ✅ |
| core/agents/tester.md | `true` | `enabledAutoRun: true` | 同上（bash allow） | 同上 | ✅ |
| core/agents/architect.md | 不声明 | 不含该键 | 不映射 | 不映射 | ❌ 不修改（正确基准） |
| core/agents/reviewer.md | 不声明 | 不含该键 | 不映射 | 不映射 | ❌ 不修改（用户可 autorun on） |
| core/agents/reviewer-b.md | 不声明 | 不含该键 | 不映射 | 不映射 | ❌ 不修改（用户可 autorun on） |
| core/agents/recorder.md | 不声明 | 不含该键 | 不映射 | 不映射 | ❌ 不修改（用户可 autorun on） |
| core/agents/director.md | 不声明 | 不含该键 | 不映射 | 不映射 | ❌ 不修改（用户可 autorun on） |
| core/agents/goal-evaluator.md | 不声明 | 不含该键 | 不映射 | 不映射 | ❌ 不修改（用户可 autorun on） |
| core/platform/codebuddy.yaml | emit `{auto_run}` → `enabledAutoRun` | — | — | — | ✅ |
| core/platform/opencode.yaml | 无 auto_run emit 项 | — | — | — | ❌ 不修改（正确基准：白名单机制天然丢弃） |
| core/platform/claudecode.yaml | 无 auto_run emit 项 | — | — | — | ❌ 不修改（正确基准） |

## Risks / Trade-offs

- [用户手动编辑安装态文件与状态文件双写漂移] → 单一重放入口（install.sh apply）+ 首次切换种子化扫描（仅值 `true` 进基线）；手动编辑只在「从未用过 autorun」窗口可能被 install 覆盖，窗口内有文档明示「请用 budget setup autorun 而非手改」；状态文件存在后为唯一真源，差异经 `list` 双栏暴露
- [行级补丁与未来 frontmatter 结构演进错位] → 锚点策略复刻 `rewrite_agent_file`（name/description 最后出现行之后），与 model 重写同源；on/off 幂等，重复执行字节稳定
- [非 codebuddy 用户误期待 AutoRun] → 子命令降级指引（exit 0 明示无机制）+ README 双语平台差异表 + CHANGELOG Known Limitations 口径
- [emit 白名单扩充引入拼写漂移] → 复用 `_EMIT_PATTERN` 域校验 + 既有 EmitWhitelistTests 拒绝用例回归 + 新增 `{auto_run}` 接受用例
- [apply 在安装期失败阻断安装] → 失败仅告警不阻断（installer delta 场景锁定），状态可后验修复
- **[安全·显式声明] AutoRun = 权限范围内所有工具调用免人工审批，审批是最后一道人工闸门**：coder 三级与 tester 的 `bash_allow: ["*"]`，默认免审批后子代理可无审批执行任意 shell 命令（`rm -rf` / `git push -f` 均命中 `*`）；tester 的 `edit_allow: []`（只读）不变，但其 bash 全放开（非只读命令集）——auto_run 只改「确认」不改「允许」。缓解：dist 默认开启仅限 4 个执行类 agent；README/CHANGELOG/`autorun on` 输出显式知情提示（列 bash 模式，`*` 醒目）
- **[安全] `autorun on architect`/`on recorder`（reviewer/reviewer-b 同为 git 类）** → architect `bash_allow: ["git *", "openspec *"]`、recorder `["git *"]`，开启后可无审批执行 `git push --force` / `git clean -fd` / `git checkout -- .` 等高危命令——属「bash 非全禁止但含高危模式」类 agent。缓解：`on` 输出列出该 agent 将免审批的 bash 模式，git 类给醒目提示；README 同口径
- [多项目级安装 × 全局状态文件语义差] → on/off 作用域明示为当前探测安装态（多项目逐项目执行）；list 双栏（全局清单 + 当前安装态实况）；文档明示多项目用法
- [损坏状态文件被覆盖写致基线永久丢失] → on/off/apply 遇解析失败非零退出 + 提示修复，绝不覆盖写（tests/test_autorun.py ⑥ 锁定字节不变）
- [旧安装缺 `agents/.bash-patterns.json` 致 `on` 安全提示无模式可列] → 构建期由 `core/agents/*.md` 生成、随 dist manifest 同步自动落位（D7）；文件缺失时 autorun.py 降级为通用知情提示（不列具体模式）不阻断开启；升级 dist 后自动获得（tests/test_autorun.py ⑪ 锁定降级路径）

## Migration Plan

1. build.py 三处扩充 + tests 用例（纯增量，既有表达式行为不变）→ 门禁回归
2. core/agents 四文件 + codebuddy.yaml 一行 → 构建，dist/codebuddy 四产物 +1 行，opencode/claudecode 逐字节不变
3. autorun.py + setup.sh 分发 + install.sh 重放钩子 + build.py 数据文件生成（D7）→ tests/test_autorun.py 自动化用例 + tests/test_installer.py 重放用例 + 真实终端形态抽查
4. README 双语 + CHANGELOG（scan-brand 自检）→ 全量门禁终验 → 归档（版本 minor，如 0.3.0）

## Open Questions

- CodeBuddy IDE 设置页 Agent Tab 的 Auto Run 开关与 frontmatter `enabledAutoRun` 的优先级关系（前端验证：两者应为同一持久化态的不同入口；若 IDE 侧优先，文档需明示「以 IDE 设置为准」——端到端验证时确认）
- **IDE 关闭时的写入形态**：设置页关闭某 subagent 的 Auto Run 时，IDE 是删除 `enabledAutoRun` 行还是写入 `enabledAutoRun: false`？种子化按值判定（仅 `true` 进基线）在两种形态下均安全，但须端到端验证实证确认（联动 D4 种子化口径）
- **`enabledAutoRun` 与 `permissionMode`（plan/acceptEdits）的层级关系**：若 Auto Run 压制 plan 模式审批，则对 architect 开 AutoRun 的权限面比预想更宽（plan 模式下的编辑/命令确认也被免掉）——须列入端到端验证；验证前文档不承诺二者语义正交
- `enabledAutoRun` 是否为 CodeBuddy 稳定 frontmatter 键（当前依据官方文档与设置页对应关系；若版本间更名，构建映射单点可改）
