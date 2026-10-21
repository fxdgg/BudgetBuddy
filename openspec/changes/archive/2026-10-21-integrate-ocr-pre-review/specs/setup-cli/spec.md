# setup-cli Delta Spec

## MODIFIED Requirements

<!-- 合并基线说明：本 MODIFIED 已预置在途变更 add-codex-platform 归档后的终态口径——其 MODIFIED「setup.sh 子命令体系（preset codex 降级语义）」用非标准标题后缀，本文统一回主 spec 标准标题，并并入其 codex preset 降级语义与 show 三档映射表（表述原样取自其 delta）；产物平移口径同步预置为四平台。归档顺序依赖与合并人工核对要求见 design.md Migration Plan 第 3 条。 -->

### Requirement: setup.sh 子命令体系

`core/setup.sh`（产物平移至 dist 四平台）提供子命令全集（design.md §8.1/A11）：`init`（初始化安装/注入；`init shell` 注入 shell 别名）、`show`（展示当前 agent 模型配置）、`agent preset|inherit|custom`（模型预设切换/覆写）、`persona list|set|expand|show`（主题管理）、`validate`（完整性校验）、`diff [preset]`（当前 vs 预设对比）、`stats`（工作流统计）、`update`（增量更新）、`reinstall`（uninstall+init 组合重装）、`uninstall`（卸载）、`guard`（Coder Guard 查询/重置）、`quickstart`（别名 tour/wizard，快速上手引导）、`models`（模型目录查看）、`ocr`（OCR 预审集成安装与状态检测——行为细节见「budget setup ocr 子命令」requirement）、`help`；独立入口 `budget notify` 与 `budget status`；`budget update` 为 `budget setup update` 的顶层快捷别名。环境变量前缀统一 `BUDGET_*`（BUDGET_GLOBAL/BUDGET_DIR/BUDGET_PLATFORM）。codex 探测形态下 `agent preset|custom|inherit` 降级为提示语（「codex 平台模型档位由 Leader 在 spawn 派工时按 budget-models.json 查询，无 agent frontmatter 可切换；档位查看 `budget setup show`/`budget setup models`」，exit 0 不报错）；`show` 在 codex 形态输出三档映射表（economic/balanced/quality → gpt-5.6-luna/terra/sol）；其余子命令（models/persona/guard/notify/validate/uninstall）codex 形态正常工作。【MUST】

#### Scenario: show 输出
- **WHEN** 在已安装项目执行 `budget setup show`
- **THEN** 列出每个 agent 的当前 model 与对应 model_role，格式人类可读

#### Scenario: 环境变量前缀
- **WHEN** 审计 setup.sh 与 lib 全部脚本
- **THEN** 无参照项目前缀的环境变量残留，统一使用 BUDGET_*

#### Scenario: quickstart 入口可用
- **WHEN** 执行 `budget setup quickstart`（或别名 tour/wizard）
- **THEN** 启动 lib/quickstart.py 快速上手引导（lib 模块有对应入口，无死代码）

#### Scenario: ocr 入口可用
- **WHEN** 执行 `budget setup ocr`
- **THEN** 启动 lib/ocr-setup.py 安装与检测流程（lib 模块有对应入口，无死代码；help 文案含 `ocr` 子命令说明）

#### Scenario: help 文案覆盖 ocr 子命令
- **WHEN** 执行 `budget setup help`
- **THEN** 用法行与子命令说明含 `ocr`（安装与检测语义一句话，形态先例同 autorun 的 help 覆盖）

#### Scenario: codex preset 降级提示
- **WHEN** codex 形态执行 `budget setup agent preset balanced`
- **THEN** 输出降级提示并 exit 0（无文件被修改）

#### Scenario: codex show 三档表
- **WHEN** codex 形态执行 `budget setup show`
- **THEN** 输出 codex 三档模型映射与查表说明

## ADDED Requirements

### Requirement: budget setup ocr 子命令

`budget setup ocr`（实现为 `core/lib/ocr-setup.py`，Python stdlib only，经 setup.sh 分发层直调 python，形态同 `autorun`/`quickstart`）职责为 OCR 预审集成的安装与状态检测：① 检测 `ocr` CLI（`command -v ocr`），缺失时输出 `npm i -g @alibaba-group/open-code-review` 安装指引并继续后续步骤、退出码 0（不强制安装）；② 检测模型配置可用性（存在 `ocr` 时）：检查环境变量 `OCR_LLM_URL`/`OCR_LLM_TOKEN`/`OCR_LLM_MODEL` 或 `~/.opencodereview/` 配置文件任一命中即视为已配置；未命中仅输出「未检测到模型配置——若使用 delegate 模式可忽略」提示、不阻断（退出码 0，安装步骤照常——delegate 模式无需配置，不能据此断定不可用）；③ 将规则模板安装到 OCR 全局层 `~/.opencodereview/rule.json`——模板定位优先 `ocr-setup.py` 自身 `__file__` 同目录的 `ocr-rule.json`（源自 `core/lib/ocr-rule.json`，经 `_build_lib` 字节平移至四平台 dist 的 `lib/`，与 `ocr-setup.py` 天然同目录；环境变量 `BUDGET_LIB_DIR` 可显式覆盖，正常安装态两者等价）；目标目录 `~/.opencodereview/` 不存在时 `os.makedirs` 自动创建（权限失败非零退出并提示手动创建）；写文件采用同目录临时文件原子写（参照 `core/lib/autorun.py` `_atomic_write` 先例：`tempfile.mkstemp` + `os.replace`，写失败不留半截文件）；目标不存在则写入；内容相同则幂等 no-op；内容不同则先备份并展示差异摘要、用户确认后覆盖、取消则保持原文件（绝不静默覆盖；备份默认名 `~/.opencodereview/rule.json.bak`，`.bak` 已存在时改用时间戳后缀 `rule.json.bak.<YYYYMMDDHHMMSS>`，不覆盖任何既有文件；stdin 非 TTY 的非交互环境默认跳过覆盖、输出手动路径、退出码 0）；④ 输出降级语义说明（未装 CLI / 未装规则时 BudgetBuddy 全流程照常）。模板源文件缺失（旧安装未含 `lib/ocr-rule.json`）时报错提示模块未安装并指引 `budget setup update`，退出码非零（与 autorun 分发先例一致）。子命令不依赖特定平台安装态（不补丁 agent 文件、不写 auto-run.json），codebuddy/opencode/claudecode/codex 四形态行为一致；`detect_platform` 未命中（kind=unknown）时规则安装仍可执行（模板路径按 `__file__`/`BUDGET_LIB_DIR` 解析，无安装态时提示先安装或 `BUDGET_PLATFORM=` 显式指定）。【MUST】

#### Scenario: 全新安装规则

- **WHEN** 执行 `budget setup ocr` 且 `~/.opencodereview/rule.json` 不存在
- **THEN** 模板写入该路径（目录不存在时先自动创建），输出安装结果与降级语义说明，退出码 0

#### Scenario: 幂等重装

- **WHEN** 再次执行 `budget setup ocr` 且目标文件与模板内容相同
- **THEN** no-op，不重写文件，退出码 0

#### Scenario: 用户已有规则保护

- **WHEN** 目标文件已存在且与模板内容不同
- **THEN** 生成 `.bak` 备份并展示差异，确认后覆盖、取消则原文件逐字节不变；`.bak` 已存在时本次备份用时间戳后缀路径，既有备份不被覆盖

#### Scenario: CLI 缺失不阻断

- **WHEN** 环境无 `ocr` CLI 时执行 `budget setup ocr`
- **THEN** 输出安装指引后规则安装照常完成，退出码 0

#### Scenario: 模型配置未检出不阻断

- **WHEN** CLI 已安装但环境变量与 `~/.opencodereview/` 配置文件均未检出模型配置
- **THEN** 输出「delegate 模式可忽略」提示，安装步骤照常完成，退出码 0

#### Scenario: 模板缺失报错

- **WHEN** 旧安装的模板源（`__file__` 同目录与 `BUDGET_LIB_DIR` 均无 `ocr-rule.json`）未就位
- **THEN** 非零退出并提示 `budget setup update`，不触碰 `~/.opencodereview/rule.json`

#### Scenario: 原子写不留半截文件

- **WHEN** 安装写入过程中发生 I/O 错误
- **THEN** 目标路径不出现部分内容（临时文件被清理或未被替换），重试后可正常安装

#### Scenario: 四平台行为一致

- **WHEN** 分别在 codebuddy / opencode / claudecode / codex 安装形态执行 `budget setup ocr`
- **THEN** 检测、安装、备份、提示行为一致，均不修改任何 agent 文件与平台状态文件
