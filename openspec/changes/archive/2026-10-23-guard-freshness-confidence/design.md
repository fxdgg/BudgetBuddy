# Design — guard-freshness-confidence

## Context

- Coder Guard 记录（`$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json`）：history 条目含 `timestamp/coder/tags/result/escalated_to`，summary 按 coder×tag 计数；写入端 guard_append/guard_reset（guard.sh 内嵌 python heredoc）。
- 读取端三个文件、四个读取面：`guard.sh guard_query`（概览 + 判定两模式，内嵌 python heredoc 计算最近 5 次窗口失败与连续失败，输出降级建议文本）与 `guard.sh guard_summary`（bash 汇总；顶层 `budget status` 经 notify.sh `do_status` → `_budget_status_guard` 复用该函数，notify.sh 本身零改动）；`display.py guard_section`（`budget setup stats` 命令的「Coder Guard 护栏」段：总记录/失败/降级/最近 5 条，setup.sh `stats)` 分支 `exec python lib/display.py`）；`run_summary.py guard_section`（markdown 摘要：failures/escalations/recent_failures；独立汇总工具，当前无 agent 自动调用，手动/测试以脚本路径 exec 形态调用）。
- 降级硬规则（P0 budget-coder-guard / router.md Step 2 / SKILL.md）：最近 5 次窗口失败 ≥2 → 降级；连续 3 败 → Director。
- lib 产物经 `_build_lib` 字节平移至四平台 dist 的 `lib/`，安装态同步至 `$HOME/.budgetbuddy/lib`（同目录结构）。

## Goals / Non-Goals

**Goals:**
- guard 记忆获得保鲜（时间衰减加权）与置信度标签（有效样本量 + 陈旧标注）
- 四个读取面（guard_query / guard_summary（含 budget status 链）/ budget setup stats（display.py）/ run_summary）输出一致的保鲜与置信信息
- Leader 分派前查询时能看到「降级建议的可信度」，避免基于陈旧证据误降级

**Non-Goals:**
- 不改变降级硬规则语义（P0 规则、router.md、SKILL.md 零改动）
- 不改写入端与 coder-guard.json 格式（无数据迁移）
- 不做跨 agent 质量趋势（review 评分/一次通过率——属方案 B，另行提案）
- 不做 guard.json 落盘的预计算缓存（读取时实时计算，记录量级 ~百条无性能问题）

## Decisions

### D1：衰减模型 = 指数半衰期，读取时计算

**选择**：权重 `w = 0.5 ** (age_days / half_life)`，默认 `half_life = 30` 天，`BUDGET_GUARD_HALF_LIFE_DAYS` 环境变量覆盖（非法值回退默认并 stderr 提示）。读取时对 history 实时计算，不写回文件。
**理由**：半衰期语义直观（30 天前的记录权重恰为一半）；单调递减无跳变；写入端零改动零迁移。
**备选**：①滑动时间窗（90 天内全权重、窗外零权重）——rejected：硬边界跳变，第 89 天与第 91 天权重突变；②线性衰减——rejected：长尾权重过高（一年前记录仍有 ~0.08 权重）。

### D2：置信档与陈旧标注两维正交，不合成单一分数

- **置信档** = f(`n_eff`)：`n_eff = Σw`（按 coder×tag 交集过滤后的匹配条目）；`n_eff < 2` → 低、`< 4` → 中、`≥ 4` → 高。低置信包含「记录太少」与「记录太旧（权重衰减后不足）」两种情况，天然覆盖陈旧场景的样本面。
- **陈旧标注**（独立维度）：该组合最新记录年龄 > 90 天（`BUDGET_GUARD_STALE_DAYS` 覆盖）→ `stale: true`。回答「这条记忆多久没更新了」，与样本量无关。
- **两阈值独立不联动**：半衰期与陈旧天数是两个独立参数——覆盖 `BUDGET_GUARD_HALF_LIFE_DAYS` 后陈旧阈值不随之联动（默认 90 = 3×30 的巧合关系仅在默认值下成立）。
**理由**：合成单一分数会伪精确；两维各自可解释（Leader 看到「中置信 + 陈旧」= 样本尚可但太久没用，与「低置信 + 新鲜」= 刚开始记录，处置不同）。

### D3：参考层定位——硬规则字面不动，低置信加「仅供参考」标注

**选择**：guard_query 的判定输出（「触发降级保护，建议改派 X」等）保持既有逻辑与文案；在其后追加一行保鲜与置信信息；当 `n_eff < 2` 或 `stale` 时额外标注「⚠ 记录陈旧/样本不足，降级建议仅供参考」。
**理由**：改 P0 规则文本会触发四平台 prompt 行为变更 + P0 一致性校验链（build.py check_p0_consistency），风险收益比不划算；时间衰减方向天然保守（旧失败权重降低 → 只会减少误降级，真降级仍由次数窗口硬规则兜底）。置信层先以只读参考落地，观察使用反馈后再评估是否升级为决策输入。

### D4：guard_metrics.py 双形态（import + CLI），四端复用单一实现

- **函数形态**：`load_metrics(guard_file, coder=None, tags=None, now=None)`（供 display.py / run_summary.py 同目录 import——display.py 经 setup.sh `stats)` 分支以脚本路径 exec（`sys.path[0]` = lib 目录），run_summary.py 同为脚本路径 exec 形态，dist 安装态（`~/.budgetbuddy/lib`）同目录结构不变，import 天然成立；`now` 参数可注入便于单测）
  - **返回形态两种**：`coder` 指定时返回单组合 dict（JSON 键见下）；`coder=None` 时返回 per-coder 列表形态 `{'available': bool, 'per_coder': [<单组合 dict>, ...]}`（available 对齐 display.py 既有不可用语义；按 coder 名字典序，覆盖 summary 概览 / display / run_summary 的「每 coder 一行」需求，避免调用方逐 coder 循环调用）
  - **import 容错（与子进程容错对称）**：display.py / run_summary.py 的 `import guard_metrics` MUST 延迟导入（函数内 import 或 try/except 包裹），import 失败（模块缺失/语法错误）时降级为「不展示置信摘要、其余段照常输出 exit 0」——与 guard.sh「子进程失败跳过保鲜段」两层容错语义对称
- **CLI 形态**：`python3 guard_metrics.py [--file <path>] [--coder <c>] [--tags <t,...>] --json`（供 guard.sh 子进程调用——其内嵌 python heredoc 无 `__file__` 不能 import；文件路径 guard.sh 子进程统一经 `BUDGET_GUARD_FILE` 环境变量传递，`--file` 参数供手动/测试独立使用；coder/tags 经 CLI 参数传递——heredoc 结束后 bash 层 `$coder`/`$tags_arg` 变量仍可用，直接拼 CLI 参数最简；guard_query 与 guard_summary 均经此路径取数）
- **子进程失败不阻断**：guard.sh 调用 guard_metrics.py 失败（python 缺失/文件损坏/非零退出）时仅跳过保鲜段输出，主查询/汇总照常返回（读取端增强的容错语义）
- **四端一致口径**：「数值一致」限定**无 tag 的 coder 全量口径**（coder=None 或 query 不带 tag）：带 tag 的 guard_query 判定模式为 coder×tag 交集口径，属明细查询，不参与四端一致性断言（其 n_eff 语义为「该组合的加权样本」，与概览口径天然不同）；guard_query 概览模式（无 coder）展示 per-coder 列表（与 summary/display/run_summary 同口径同数据源）
- **输出 JSON 键**（两形态一致）：`{coder, tags, n_eff, weighted_failures, weighted_success_rate, confidence, stale, newest_age_days, half_life_days, matched}`；置信档取值 `low/medium/high`（中文标签由各读取端渲染，数据层保持英文机器值）
- **timestamp 容错**：history 条目按写入端格式 `%Y-%m-%dT%H:%M:%SZ`（guard.sh append 段）解析 age；条目 timestamp 缺失或无法解析 → 权重按 0（最保守——坏数据不抬高 n_eff）且不参与 `newest_age_days` 计算（陈旧判定只用可解析条目）
**备选**：三端各写一份计算——rejected：输出漂移风险；guard.sh heredoc 内 import lib 路径——rejected：heredoc 无脚本路径锚点；改 notify.sh 的 `_budget_status_guard`——rejected：其复用 guard_summary 即可传导，notify.sh 零改动。

### D5：lib 计数一并修正（漂移修复）

「lib 24 文件模块化」requirement 的 24 已因 agent-autorun（autorun.py）与 ocr 集成（ocr-setup.py）两次变更漂移（均未同步计数）。本次修正为实际值：guard_metrics.py 落位后 `core/lib/` 共 **27 个代码模块**（16 .sh + 11 .py）+ 1 个数据模板（ocr-rule.json），六组归组补全：基础层（colors/utils/platform/shell，4）、生命周期（init/update/uninstall，3）、模型与护栏（models/preset/model_resolver/guard/guard_metrics/rtk/ocr-setup，7）、persona 与校验（persona/persona_expand/validate/budget-state/display，5）、交互与汇总（interactive/quickstart/run_summary/banner/autorun，5）、通知与 hooks（notify/hooks/hooks_inject，3）——4+3+7+5+5+3=27。

## Risks / Trade-offs

- [权重数学错误] → 单测锁定半衰期数学（0 天=1.0、30 天=0.5、90 天=0.125）与 n_eff 聚合
- [display/run_summary import 失败] → dist 同目录结构（_build_lib 平移）+ 集成测试覆盖安装形态路径
- [三端输出不一致] → 单一实现源（guard_metrics.py），三端仅做渲染
- [环境变量非法值] → 回退默认 + stderr 提示，不阻断（查询命令容错语义与 guard_query 解析失败 exit 1 的既有行为区分：配置回退不是错误）
- [半衰期 30 天默认值是否合适] → 环境变量可调；默认值参考「月度迭代节奏」，使用反馈后再调
- [「仅供参考」标注的认知风险] → 标注不改变硬规则结论的强制性：低置信 ≠ 可豁免降级——窗口内失败 ≥2 仍触发降级，标注仅提示「证据可信度」，Leader 不得据标注跳过硬规则（spec「硬规则语义不变」scenario 锁定判定文案不变即此语义的行为面保证）

## Migration Plan

1. 实施顺序：guard_metrics.py（模块）→ guard.sh 集成 → display.py / run_summary.py 集成 → 单测 → 门禁与实测验证
2. 回滚：`git revert` 即可；无数据迁移、无格式变更、无 prompt 变更——回滚后读取端恢复原输出

## Open Questions

- 置信档阈值（2/4）是否需要按 tag 维度细分？→ 初版统一阈值，观察 guard_query 实际使用反馈（n_eff 分布）后再议
- `budget status` 的置信摘要是否需要排序（按 n_eff 升序突出低置信）？→ 实施时按 coder 名字典序（与既有 summary 输出一致），排序属展示优化另行提案
