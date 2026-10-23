# setup-cli Delta Spec

## MODIFIED Requirements

### Requirement: Coder Guard 护栏

`core/lib/guard.sh` 提供 coder-guard.json 的查询/追加/汇总/重置（固定路径 `$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json`），记录结构与降级阈值语义对齐工作流文档 router 的定义（最近 5 次窗口、失败 ≥2 触发降级）（design.md §8.2/§8.4）。`guard query`（概览模式与判定模式）与 `guard summary`（含顶层 `budget status` 经 notify.sh `do_status` 复用的链路，notify.sh 零改动）SHALL 在既有输出之上展示「保鲜与置信」参考信息：经 `core/lib/guard_metrics.py`（新增，Python stdlib only，import + CLI 双形态，单一实现源）计算时间加权统计——指数半衰期权重 `0.5^(age_days/half_life)`（默认 30 天，`BUDGET_GUARD_HALF_LIFE_DAYS` 覆盖）、`n_eff` 有效样本数、加权失败数、加权成功率、置信档（`n_eff` < 2 低 / < 4 中 / ≥ 4 高）、陈旧标注（最新记录年龄 > 90 天，`BUDGET_GUARD_STALE_DAYS` 覆盖）；当 `n_eff` < 2 或陈旧标注命中时，guard query 判定输出 MUST 附加「记录陈旧/样本不足，降级建议仅供参考」标注（标注不改变硬规则结论的强制性）。降级硬规则（最近 5 次失败 ≥2 降级、连续 3 败建议 Director）语义 MUST NOT 改变；写入端（append/reset）与 coder-guard.json 格式 MUST NOT 改变（加权为读取时计算，不落盘）。`budget setup stats`（`core/lib/display.py` 的 Coder Guard 段）与 run summary（`core/lib/run_summary.py` 的 guard 段）SHALL 展示同一实现的置信摘要，且 `import guard_metrics` MUST 延迟导入（函数内 import 或 try/except），import 失败时降级为不展示置信摘要、其余段照常输出退出码 0（与子进程容错两层对称）。timestamp 无法解析的 history 条目 MUST 按权重 0 计（不计入 `n_eff`、不参与陈旧判定）。环境变量非法值时 MUST 回退默认值并 stderr 提示、不阻断查询；guard.sh 调用 guard_metrics.py 子进程失败时 MUST 跳过保鲜段、主查询照常返回。【MUST】

#### Scenario: 失败记录

- **WHEN** 某次 coder 任务被 review 驳回后触发记录
- **THEN** guard.json 的 history 追加条目且 summary 计数同步更新（写入端行为不变）

#### Scenario: 半衰期权重数学

- **WHEN** guard_metrics.py 计算 age 为 0 / 30 / 90 天记录的权重（默认半衰期 30 天）
- **THEN** 权重分别为 1.0 / 0.5 / 0.125，`n_eff` 为匹配条目权重之和

#### Scenario: 置信档分界

- **WHEN** 某 coder×tag 组合的 `n_eff` 分别为 1.9 / 2.0 / 3.9 / 4.0
- **THEN** 置信档分别为 low / medium / medium / high

#### Scenario: 陈旧标注与低置信参考提示

- **WHEN** 某 coder 的记录全部为 120 天前（默认阈值 90 天）
- **THEN** 陈旧标注命中（stale）；guard_query 判定输出附加「记录陈旧/样本不足，降级建议仅供参考」一行，且既有降级判定文案不变

#### Scenario: 样本不足独立触发参考提示

- **WHEN** 某 coder 仅有一条 1 天前的记录（`n_eff` = 1.0 < 2 且 stale = false）
- **THEN** 不触发陈旧标注，但 guard_query 判定输出仍附加「记录陈旧/样本不足，降级建议仅供参考」（n_eff < 2 与 stale 二者之一命中即触发）

#### Scenario: timestamp 异常条目容错

- **WHEN** history 中某条目 timestamp 缺失或格式无法解析
- **THEN** 该条目权重按 0 计（不计入 n_eff），陈旧判定不受其影响（newest_age_days 只取可解析条目）

#### Scenario: 硬规则语义不变

- **WHEN** 最近 5 次窗口内失败 ≥2（无论记录新旧）
- **THEN** 降级判定结论与集成前逐字一致（次数窗口判定不受加权影响）

#### Scenario: 四读取面一致

- **WHEN** 同一 coder-guard.json 分别经 `budget setup guard query <coder>`（不带 tag）、`budget status`（guard_summary 链路）、`budget setup stats`（display.py）、run summary（run_summary.py）查看
- **THEN** 四处展示的 n_eff / 置信档 / 陈旧标注数值一致（无 tag 的 coder 全量口径，同一实现源渲染，与 guard_metrics.py CLI `--json` 基准值相等）；带 tag 的 guard_query 判定模式为 coder×tag 交集口径，属明细查询不参与本断言

#### Scenario: 环境变量容错

- **WHEN** `BUDGET_GUARD_HALF_LIFE_DAYS` 设为非法值（如 `abc` / `0` / `-5`）
- **THEN** 回退默认 30 天，stderr 输出提示，查询正常完成退出码 0

### Requirement: lib 24 文件模块化

`core/lib/` 代码模块按六组组织（design.md §8.2）：基础层（colors/utils/platform/shell，4）、生命周期（init/update/uninstall，3）、模型与护栏（models/preset/model_resolver/guard/guard_metrics/rtk/ocr-setup，7）、persona 与校验（persona/persona_expand/validate/budget-state/display，5）、交互与汇总（interactive/quickstart/run_summary/banner/autorun，5）、通知与 hooks（notify/hooks/hooks_inject，3）——共 **27 个代码模块**（16 .sh + 11 .py）另含 1 个数据模板（ocr-rule.json，非模块，经 `_build_lib` 分发的规则模板；标题「24」为归档合并锚点保留的历史计数，正文计数已修正）。状态机 `budget-state.py` 全仓单份（A4），skill 文档经 `$HOME/.budgetbuddy/lib/budget-state.py` 引用。lib 不随产物分发内嵌测试，测试统一在仓库根 `tests/`。【MUST】

#### Scenario: guard_metrics 归组

- **WHEN** 检查 core/lib/ 目录
- **THEN** guard_metrics.py 存在且与 guard.sh、ocr-setup.py 同属「模型与护栏」组，autorun.py 归「交互与汇总」组；模块计数为 27（.sh/.py）+ ocr-rule.json 数据模板，六组枚举与目录文件一一对应无缺漏

#### Scenario: dist 同步

- **WHEN** 构建完成后核对四平台 dist 的 lib/
- **THEN** guard_metrics.py 经 `_build_lib` 字节平移分发，display.py/run_summary.py 与其同目录（import 路径成立）
