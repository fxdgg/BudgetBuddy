# Design — agent-quality-trend

## Context

- Phase 2 双审产物形态不固定：`gate-review.md`（单文件）或 `reviews/`（reviewer-a.md / reviewer-b.md / roundN-verdict.md）——采集必须递归扫描 change 目录而非依赖固定文件名。
- Phase 4 终审走 reviewer（同一定义，输出格式含评分 A/B/C/D）；Phase 2 轮数经 `completed_steps` 的 `3-reviewer-<a|b>-r<round>` 状态锁可追溯，但归档后 state 文件随 change 目录归档。
- recorder 为归档执行者（openspec archive + Coder Guard 更新）；lib 直调先例：budget-state.py 无 setup 子命令，skill 文档经 `$HOME/.budgetbuddy/lib/` 固定路径 python3 调用。
- guard.json（A 已补保鲜/置信）含 per-coder 成败 history 与 summary；metrics 只读快照不复用其计算。
- 方案 A 已建立「延迟导入 + 子进程」两层容错与「单一实现源」模式（guard_metrics.py），B 复用同一模式。

## Goals / Non-Goals

**Goals:**
- 每次变更归档时自动沉淀结构化质量指标（评分/轮数/双审结论/guard 快照）
- 查询面（budget setup stats / run summary）展示跨任务趋势与退化告警
- 采集零人工成本（标记自动提取）+ 人工兜底（标记缺失可传参）

**Non-Goals:**
- 不新增通知事件（N1-N11 零改动——告警只在查询面呈现，通知联动待使用反馈另议）
- 不改降级硬规则 / guard 写入端（metrics 只读 guard.json 快照，不反向影响降级判定）
- 不做 per-task 粒度指标（初版 change 级：per-task 驳回轮数分布等观察需求后再议）
- 不做定期回归评测集（方案 C，远期）
- 不回填历史归档 change（无标记的历史产物不补录，从本变更后开始积累）

## Decisions

### D1：结构化标记 = HTML 注释单行 JSON（budget-verdict）

**选择**：reviewer / reviewer-b 输出格式章节末尾追加约定——报告最后一行输出 `<!-- budget-verdict: {"rating":"A","conclusion":"pass","round":1} -->`（reviewer）；`<!-- budget-verdict: {"conclusion":"fail","round":2} -->`（reviewer-b，无 rating 字段——其结构本就无评分）。
**适用范围限定**：标记**仅在 Phase 2（方案评审）与 Phase 4（终审）输出**——Phase 3 per-task 审查不输出 budget-verdict（防止 round 值污染聚合）；标记行位于报告正文末尾、任何 code fence **之外**（保证 HTML 注释渲染语义成立）。
**理由**：HTML 注释在 markdown 渲染中零干扰（人类阅读不变）；单行 JSON 正则可稳定提取——**整行匹配**（行首 `<!-- budget-verdict:` 且行尾 `-->`，嵌在段落/反引号 code span 内的行不匹配——防止方案文档等引用格式示例的行被误提取）；round 字段由 reviewer 按当前评审轮次自报（Phase 2 的 r1/r2/r3，Phase 4 终审填 0 区分——终审无轮次语义）；字段极简（3 键内），避免给 reviewer 增加输出负担。
**备选**：①独立 JSON 文件落盘——rejected：reviewer 是只读角色（edit_allow: []）不能写文件，落盘归 Leader/Recorder 增加流程复杂度；②固定格式表头行——rejected：与人类阅读的报告结构耦合，正则提取脆弱。

### D2：采集 = 脚本递归扫描 + recorder 单点触发 + 人工参数兜底

**选择**：`metrics.py record --change-id <id> --change-dir <path>` 递归扫描 change 目录全部 .md（`os.walk` 默认 `followlinks=False` 天然防符号链接环），提取全部 budget-verdict 标记，聚合规则：
- **Phase 2**：`round` 最大且非 0 的 reviewer 标记 → phase2_rating / phase2_rounds；**同 round 多文件标记**（如 reviews/reviewer-a.md 与 reviews/round2-verdict.md 并存）→ 取**文件路径字典序最大**者（确定性 tie-breaker，稳定可测）
- **Phase 4 终审**：`round==0` 的 reviewer 标记 → final_rating（终审报告落盘 change 目录——phases.md Step 5 prompt 本变更补「评分 A/B/C/D + 标记行 + 落盘 final-review.md」输出要求，消除既有「Step 5 只要求通过/不通过」与 reviewer.md 评分格式的不一致）
- **reviewer-b**：round 最大标记 → reviewer_b_conclusion（Phase 4 无 reviewer-b，天然不污染）
- **final_rating 缺失**（终审无评分的存量流程）→ 记 null，R1 趋势序列在 null 处中断（中断不计入连续下降，不触发告警）
标记缺失字段 → 人工参数兜底（`--phase2-rating A --phase2-rounds 1 --final-rating A --reviewer-b pass`，显式优先）；同 change_id 重复 record → 幂等覆盖（按 change_id 去重更新，非追加）。
**理由**：形态不固定的产物（gate-review.md / reviews/ 子目录）靠递归扫描兜住；recorder 是唯一归档执行者（单点写入，无并发）；幂等覆盖让补录/重跑安全。
**备选**：Leader 在 Phase 2/4 产出时即时写入——rejected：Leader 是编排角色，采集动作分散到两个 Phase 增加流程侵入；recorder 单点采集时机最自然（归档 = 任务终点 = 指标定格）。

### D3：存储 = metrics.json 与 coder-guard.json 同域平铺

**选择**：`~/.budgetbuddy/projects/<project-name>/memory/metrics.json`，结构 `{"history": [{change_id, date, phase2_rating, phase2_rounds, reviewer_b_conclusion, final_rating, guard_failures, guard_history_total, guard_downgrades}], "recorded_count": N}`；guard_failures 为 record 时刻 guard.json **history 中 `result=='failure'` 的条目数**（与分母同口径——不用 summary 聚合：summary 只归带 tags 条目且多 tag 重复计数，口径不可比）；guard_history_total 为 history 总条数（R3 分母）；guard_downgrades 为 history 中 escalated_to 非空条目数（派生口径，供趋势展示与未来差分，初版告警规则不消费）——三者均为时点快照。
**理由**：与 coder-guard.json 同目录同语义（本地持久化、不提交 git、project 隔离）；快照式 guard 计数避免 metrics 与 guard 双写耦合。
**备选**：并入 coder-guard.json——rejected：职责混杂（guard 是分派护栏数据，metrics 是质量评估数据），读写端会互相牵连。

### D4：趋势与告警 = 三条规则，查询面呈现，容错模式复用 A

**选择**：`metrics.py` 的 `trend(limit=N)`（默认 N=5）：final_rating 序列、phase2 一次通过率（rounds==1 的占比）、guard 失败率（**metrics.json 最新一条快照口径**：guard_failures / guard_history_total——与 record 快照同源，不混实时值）。告警规则：
- R1 退化趋势：最近 ≥3 条 final_rating 严格递减（如 A→B→C）
- R2 一次通过率低：最近 N 条中 phase2_rounds==1 占比 < 50%
- R3 失败率高：**metrics.json 最新一条快照的** guard 失败率（guard_failures / guard_history_total，样本 ≥5 才告警——口径统一取快照，不混实时值，保证趋势语义一致）
**呈现**：display.py / run_summary.py 延迟导入 metrics（try import + 失败降级不展示，同 A 容错模式）增「质量趋势」段：评分序列一行（`A → A → B`）、一次通过率、命中告警各一行（`⚠ 退化趋势: 评分连续下降` 形态）。告警不推送通知、不影响任何判定——纯查询面参考。
**理由**：三条规则各自独立可解释、参数少；查询面呈现与 A 的「参考层」哲学一致（先观察，不动决策）。
**备选**：立即联动降级/通知——rejected：评估闭环先积累数据观察误报率，联动属后续变更。

### D5：lib 计数 27 → 28（metrics.py 归「交互与汇总」组）

「交互与汇总」组 5 → 6（interactive/quickstart/run_summary/banner/autorun/metrics——run_summary 相邻语义）；六组 4+3+7+5+6+3=28。

## Risks / Trade-offs

- [reviewer 忘输出标记] → 兜底链：record 人工参数补录 + 历史不回填（指标缺失记 null 不阻断）；标记纪律写入 reviewer.md 输出格式章节为 MUST 级
- [标记行与报告其他 HTML 注释混淆] → 提取正则锁定 `budget-verdict:` 前缀；坏 JSON 行跳过并 stderr 提示
- [Phase 4 终审标记 round 填错] → 约定 round:0 = 终审（写入 reviewer.md 标记说明）；非 0 且 round 最大者归 Phase 2
- [display/run_summary import 失败] → 延迟导入降级（同 A 模式已验证）
- [recorder 忘执行 record] → phases.md Step 6 prompt 模板显式列出调用行（与 Coder Guard 更新同级的清单项）；metrics.json 缺失时趋势段显示「暂无指标」
- [评分序列跨变更不可比] → A/B/C/D 本就是 reviewer 语义档位；趋势看的是**序列形态**（下滑/稳定）非绝对值，语义成立

## Migration Plan

1. 实施顺序：agent 定义标记（reviewer → reviewer-b → recorder）→ phases.md Step 6 → metrics.py → display/run_summary 集成 → 单测 → 门禁实测
2. 回滚：`git revert`；metrics.json 属用户数据不回收（无迁移负担）

## Open Questions

- 趋势段是否进 `budget status`（顶层）？→ 初版只进 `budget setup stats` 与 run summary（budget status 走 guard_summary 链，属 guard 域）；观察使用反馈后另议
- goal loop 模式是否也记 metrics？→ 初版仅 start 模式（归档语义明确）；goal 归档产物形态不同，后续提案
