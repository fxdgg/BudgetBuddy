## Why

Coder Guard 是 BudgetBuddy 唯一跨会话的 agent 记忆，但其「最近 5 次窗口内失败 ≥2 触发降级」是**次数窗口**语义：没有时间衰减——3 个月前的失败与昨天的失败同权重；没有置信度标签——Leader 分派时无法判断记录的可信度（样本量是否充分、记录是否新鲜）。长期间隔后恢复使用时，降级判定可能基于陈旧证据（误降级、浪费预算）；连续成功也无法让历史失败淡出。guard 记忆缺少「保鲜 + 置信」两层参考信息。

## What Changes

- **新增 `core/lib/guard_metrics.py`**（Python stdlib only，可 import + CLI 双形态）：对 coder-guard.json 做**时间加权统计**——指数半衰期权重 `0.5^(age_days / half_life)`（默认半衰期 30 天，`BUDGET_GUARD_HALF_LIFE_DAYS` 环境变量可覆盖）；按 coder（×可选 tag 交集）输出：`n_eff`（有效样本数 = Σ权重）、加权失败数、加权成功率、**置信档**（低 / 中 / 高：`n_eff` < 2 / < 4 / ≥ 4）、**陈旧标注**（该组合最新记录年龄 > 90 天，`BUDGET_GUARD_STALE_DAYS` 可覆盖）
- **三个读取文件、四个读取面集成**（单一实现源，多端复用；`core/lib/guard.sh` 承载两个读取面）：
  - `core/lib/guard.sh` 的 `guard_query`：概览模式与判定模式均追加「保鲜与置信」段（经子进程调用 guard_metrics.py CLI，`BUDGET_GUARD_FILE` 环境变量传参先例沿用）
  - `core/lib/guard.sh` 的 `guard_summary`：汇总输出追加每 coder 置信摘要行——`budget status`（顶层命令，经 notify.sh `do_status` → `_budget_status_guard` 复用 guard_summary）由此获得置信度展示
  - `core/lib/display.py`（`budget setup stats` 的实现）：「Coder Guard 护栏」段追加每 coder 一行置信摘要（有效样本 / 置信档 / 陈旧标注）
  - `core/lib/run_summary.py`（独立汇总工具）：`guard_section` 追加加权统计与置信档（markdown 摘要段）
- **降级硬规则语义不变**：「最近 5 次失败 ≥2 降级」「连续 3 败 → Director」仍字面成立（P0 规则文件 budget-coder-guard、router.md、SKILL.md 零改动）；置信度是硬规则之上的**参考层**——guard_query 判定输出在低置信（`n_eff` < 2 或陈旧标注命中）时附加「记录陈旧/样本不足，降级建议仅供参考」一行
- **写入端与数据格式零改动**：guard_append / guard_reset / coder-guard.json 结构不动（history 条目本就含 timestamp）；加权为读取时计算，不落盘、无迁移
- **新增 `tests/test_guard_metrics.py`**：半衰期权重数学、置信档边界、陈旧标注、空/缺文件、coder×tag 隔离、三读取端输出集成

## Capabilities

### Modified Capabilities
- `setup-cli`：「Coder Guard 护栏」requirement 的 query 语义扩展（保鲜 + 置信度参考层）；「lib 模块化」requirement 计数随新增模块与既有漂移一并修正（guard_metrics.py 归「模型与护栏」组）

## Impact

- **代码**：`core/lib/` 新增 1（guard_metrics.py）+ 修改 3（guard.sh 含 query/summary 两函数 / display.py / run_summary.py）；dist 经 `_build_lib` 字节平移自动同步四平台（零 DSL 改动）
- **范围边界**：`budget status` 的 guard 段走 notify.sh → guard.sh guard_summary（本次经 guard_summary 集成覆盖）；`budget setup stats` 走 display.py（直接集成）。spec MODIFIED「lib 24 文件模块化」保留主 spec 原标题作归档合并锚点（24 为历史计数，正文修正为 27）
- **不触碰**：agent 定义（core/agents/）、P0 规则（core/rules/）、工作流文档（core/skills/）、notify.sh（do_status 复用 guard_summary 无需改动）——prompt 行为零变化，纯读取端增强
- **依赖**：无新增（stdlib only）
- **风险面**：读取端 import/子进程路径（dist 安装态同目录结构保障）；权重数学（单测锁定）；三端输出一致性（单一实现源）
