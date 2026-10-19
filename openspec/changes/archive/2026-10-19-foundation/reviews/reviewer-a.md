# Reviewer-A 主审报告：openspec 变更 `foundation`（v0.1.0 全量首版）

- 审查人：Reviewer-A（主审，视角：落地可行性 / 任务可执行性 / 解析器与转换边界 / 工作量 / 测试转化）
- 审查对象：`openspec/changes/foundation/{proposal.md, design.md, specs/*, tasks.md}`
- 审查方式：逐文件通读 + 参照项目实际文件规模逐项测量 + 产出自身品牌合规独立扫描

## 结论：【需修改】

方案骨架正确（门禁先行、依赖线性化、单一源转换链路、A1-A10 调整点均有据），但存在 **5 个任务严重超出 ≤2h 约束**（其中 T10 超标约 3 倍以上）、**3 处依赖定义错误/前向依赖**、**5 处构建管线实现死角**。这些问题不修，coder 开工后必然出现任务中途膨胀、拆单返工与验收口径混乱。与辅审（Reviewer-B）的问题清单无重叠（其聚焦需求完整性/安全，本报告聚焦可执行性）。

### 规格合规（方案内部一致性）

- ✅ 11 个 capability / 50 个 MUST Requirement 与 proposal 声明一致；spec 均符合 ADDED Requirements + WHEN/THEN Scenario 格式。
- ✅ tasks 与 design §16 文件清单基本对齐（数量误差已被辅审 P2-12/P2-13 覆盖，不重复）。
- ❌ 依赖定义三处错误（见 F10/F11）；T1a 验收与 §3.1 强校验自相矛盾（见 F6）。
- 说明：proposal 称「13 个任务」，tasks.md 实际为 T1 拆 3 子任务 + T2-T13 共 15 个执行单元，口径建议统一为「13 任务 / 15 执行单元」。

### 一、工作量与任务粒度（P1，阻塞开工，均有实测依据）

- **F1｜T10 严重超标**（tasks.md 3.2）：声称「业务层 16 文件」（实 17，辅审已计），实测参照规模合计 **约 4400 行**：quickstart.py 1007、budget-state.py 508、hooks_inject.py 406、display.py 277、persona_expand.py 249、rtk.sh 211、notify.sh 210、hooks.sh 197、model_resolver.py 195、models.sh 195、preset.sh 181、guard.sh 180、run_summary.py 167、persona.sh 150、validate.sh 137、interactive.sh 131、banner.py 33，另加 2 个测试文件，且全部需 BUDGET_* 前缀改写 + 双平台路径适配 + 去品牌。coder-senior 2h 不可达（估 6h+）。**建议拆 4**：①模型与护栏（models/preset/model_resolver + test_preset.py）②状态机与护栏（budget-state/guard + test_state.py）③persona/校验/展示/交互（persona/persona_expand/validate/display/interactive/banner/run_summary）④通知与 hooks（notify/hooks/hooks_inject）+ quickstart.py 单列（1007 行独占一单仍偏大，可再对半）。
- **F2｜T9 超标**（tasks.md 3.1）：setup.sh（参照 140 行）+ 基础层 7 文件合计 **约 2600 行**（init.sh 793、update.sh 654、uninstall.sh 445 为大头）。**建议拆 3**：①setup.sh + colors/utils/platform/shell（约 530 行）②init.sh 单列③update + uninstall。
- **F3｜T3 超标**（tasks.md 2.2）：5 文件 **1929 行**（SKILL 411 / router 366 / phases 453 / goal 658 / reference 41）高语义密度改写，叠加 N 点通知重接、P0 内联一致性、全量模板变量化。**建议拆 3**：①SKILL+router②phases③goal+reference。
- **F4｜T1a 超标且职责过宽**（tasks.md 1.1）：解析器（~150 行）+ DSL schema 校验 + 双平台转换管线 + manifest + MODEL_SELECTION 渲染 + CLI，估 500-700 行 Python；且 **MODEL_SELECTION 渲染依赖 T8 才创建的 budget-models.json**，T1 时点只能 stub 验证。**建议**：模板渲染移至 T8（数据就位后实现并真实验证），T1a 聚焦解析器+校验+转换+manifest；或再拆「解析器+单测」与「管线+幂等」两单。
- **F5｜T8 超标**（tasks.md 2.7）：budget-models.json（参照 690 行重构 + Q2 要求的 30 个 opencode ID 逐一核对，纯研究工作）+ schema + personas.json（410 行 + 5 主题新角色名创作，受辅审 P1-4 牵连扩大）+ 2 份文档。**建议拆 2**：models+schema+template / personas+PERSONAS.md。

### 二、边界情况与实现死角（P2，开工前须补设计）

- **F6｜空 core 冒烟与强校验矛盾**：design §3.1 校验①要求「10 个 name 恰为 §6 角色清单」，而 T1a 验收要求空 core 构建 exit 0；同时 MODEL_SELECTION 渲染与 model_role 解析均依赖尚不存在的 models 数据。需在 design §4 定义降级规则（如：agents/ 为空时跳过集合完备性校验、models 缺失时跳过渲染），否则 T1a 无法按验收执行。
- **F7｜YAML 子集解析器语法覆盖缺口**（design §12-A5 vs §3.5）：opencode.yaml 的 `extra_outputs` 是**块式 list 项为 map**（`- kind: agents_fragment` + 缩进续行 source/dest/markers），A5 语法清单未包含此形态——按字面实现将直接解析失败。需在 A5 补充该形态，或把 extra_outputs 改写为行内流式。
- **F8｜幂等 Scenario 缺确定性输出规定**：design §4/A7 未要求 manifest 及生成文件按键排序；os.walk 遍历顺序不稳定，build-pipeline「两次构建 manifest diff 为空」可能间歇性失败。需明确「manifest 与一切生成 JSON 按键排序输出」。
- **F9｜docs routing 三处死角**（design §3.5/A6）：①opencode「仅 opencode-setup-notes.md」的限制只存在于 YAML 注释，DSL 无法表达，build.py 必须特判（违背「DSL 仅声明数据」原则）；②codebuddy 的 `docs: "docs/{name}.md"` 平移规则会把 MODEL_SELECTION.template.md 原样复制进产物，与 A6「渲染产物」冲突，需声明模板文件排除规则；③A6 占位符语法未定义，且 docs 渲染与 §3.3 六变量替换管线的关系（是否共用、是否白名单）未声明。
- **F13｜T1a 未指派 tests/test_build.py**：design §16.3 将其归 T1，但 1.1/1.2/1.3 任务文本均未包含创建动作；且 F7/F8 相关边界（引号内冒号如 `invoke: "/{group}:{name}"`、值后行内注释、空字符串 `""`、块式 list-of-map）应作为固定用例写入该测试。

### 三、依赖与任务自包含（P2）

- **F10｜T1c 前向依赖**（tasks.md 1.3）：build-release.sh 读取 VERSION，但 VERSION 归 T12 创建（design §16.3）；T1 时点验收「zip 名含版本号」不可执行。建议 VERSION 提前至 T1c 创建（内容 0.1.0）。
- **F11｜依赖指针错误**（tasks.md 4.1 与依赖图）：T11 写「依赖 1.3（manifest 格式）」——manifest 格式由 **1.1** 定义，1.3 是 release 打包；依赖图又显示 4.1 依赖 3.2 而正文写 3.1。两处均需更正。
- **F15｜T2 的 REF 形式不合规**（tasks.md 2.1）：「REF 用户 opencode 迁移版 ~/.config/opencode/agent/*.md」为家目录绝对路径，不符合 design 头部「REF: + 相对路径、根路径由 Leader 注入」约定（该目录在参照根之外，注入机制覆盖不到）；实测该目录仅 9 个 agent（无 goal-evaluator），任务应明确 goal-evaluator 只取参照 codebuddy 版改写。

### 四、可测试性（P2/P3）

- ✅ build/brand/notify/preset/state 五类 Scenario 均可转化为自动化测试，验收要点可执行；notify 的 HMAC 固定向量 + mock 不外呼设计良好。
- **F12｜高风险逻辑无测试归属**：specs/installer 的 AGENTS.md 幂等合并、manifest 增量同步、卸载差集，与 specs/setup-cli 的 guard 降级窗口（最近 5 次、失败 ≥2）均为最易出错的可自动化逻辑，但 §16.3 测试清单无 test_installer / test_guard；T9 验收要求的 platform.sh 三分支单测同样无归属文件。建议补齐或显式并入任务。
- **F16｜P0 一致性 diff 判定规则未定义**（design §3.4）：「语义一致」无法机器判定，需给出可执行规则（如规范化文本逐条比对）或降级为「条目数/关键词校验 + 人工审计」，否则该告警机制形同虚设。
- P3：行为类 Scenario（router 评估、DSL 被非 build 工具消费、README 不宣传待确认项）属提示词类产品固有属性，可接受，建议在 spec 中标注「人工审计」类别以免 T13 误当自动化项。

### 五、品牌合规残留（独立扫描确认，与辅审同向不重复展开）

对 4 份主产物 + 11 个 spec 全文扫描，命中位置：**tasks.md 第 6 行**（参照项目根路径明文，最严重，即辅审 P1-5）；tasks.md 第 4/21/34/39/44/55/65 行、design.md 第 157 行、specs/brand-compliance 第 5/12 行（均为违禁词表字面量、去品牌说明引用或 REF 品牌文件名，属辅审 P2-3/P2-4 范畴）。除上述外未发现新的残留位置。

### 评分：【C】

方向与框架合格，但按 ≤2h 粒度承诺衡量，5 个任务（T1a/T3/T8/T9/T10）实测超标、依赖图含错误指针、构建管线有 5 处未定义行为——须完成上述 F1-F13 修订（均为文档级修订，成本低）后方可派发实现。

### 处置建议

1. F1-F5（任务拆分）与 F6-F9（设计补丁）在 T1 开工前一次性修订 design.md/tasks.md；
2. F10/F11/F15 随 tasks.md 修订一并更正；F12/F13 补入测试清单与任务文本；
3. F14/F16 等其余项作为实现期注意项交 coder 消化、T13 验收抽查；
4. 品牌残留按辅审 P1-5/P2-3/P2-4 一并清除。
