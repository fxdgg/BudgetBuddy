## Why

方案 A 补齐了 guard 记忆的保鲜与置信度，但「任务完成后的持续评估」仍缺失：reviewer 评分（A/B/C/D）散落在归档 change 的 verdict 自由文本里，无结构化提取、无跨任务趋势聚合——无法回答「agent 是否在退化」（评分连续下滑、Phase 2 一次通过率下降、驳回轮数上升）。本变更为每次变更归档时沉淀**结构化质量指标**，并在查询面（budget setup stats / run summary）展示**趋势与告警**，形成任务后的持续评估闭环。

## What Changes

- **reviewer / reviewer-b 输出格式追加结构化标记行**：报告末尾追加一行机器可解析的 HTML 注释标记 `<!-- budget-verdict: {...} -->`（reviewer 含 `rating`（A/B/C/D）+ `conclusion`（pass/revise/escalate）+ `round`；reviewer-b 含 `conclusion`（pass/fail）+ `round`）——人类阅读零干扰，产物天然携带结构化信号；Phase 2 双审与 Phase 4 终审（均走 reviewer）自动覆盖
- **recorder 归档流程追加指标采集步骤**（recorder.md + phases.md Step 6 prompt 同步）：归档时调用 `python3 $HOME/.budgetbuddy/lib/metrics.py record --change-id <id> --change-dir <目录>`（脚本递归扫描 change 目录 .md 提取全部 budget-verdict 标记，聚合该变更指标）；标记缺失时人工参数兜底（`--phase2-rating` 等）
- **新增 `core/lib/metrics.py`**（budget-state.py 直调先例：无 setup 子命令，stdlib only，import + CLI 双形态）：`record` 子命令（提取标记 + guard.json 时点快照 → 追加 `~/.budgetbuddy/projects/<name>/memory/metrics.json` 的 history，含 change_id/date/phase2_rating/phase2_rounds/reviewer_b_conclusion/final_rating/guard_failures（history 失败条数）/ guard_history_total（R3 分母）/ guard_downgrades（escalated_to 派生））；`trend` 计算（最近 N 次序列 + 告警判定：final 评分连续 ≥3 次下降、phase2 一次通过率（rounds==1 占比）< 50%、guard 失败率 > 40%）；CLI `--json`（供查询面取数）
- **查询面趋势段集成**（display.py / run_summary.py，延迟导入容错模式同方案 A）：`budget setup stats` 与 run summary 增「质量趋势」段（最近 N 次变更的评分序列 / 一次通过率 / 告警行）；告警仅在查询面呈现，**不新增通知事件**（N1-N11 语义零改动）
- **新增 `tests/test_metrics.py`**：标记提取（多形态产物：gate-review.md / reviews/ 子目录）、record 聚合、trend 告警判定（三条规则各自命中与不命中）、幂等（同 change 重复 record 去重）、容错（标记缺失/坏 JSON/导入失败降级）、查询面集成

## Capabilities

### Capabilities（ADDED requirements）
- `agent-roster`（已有 capability 追加 ADDED）：reviewer / reviewer-b 结论结构化标记（budget-verdict）
- `workflow-orchestration`（已有 capability 追加 ADDED）：归档质量指标采集（recorder）与查询面趋势告警

### Modified Capabilities
- `setup-cli`：lib 模块化计数 27 → 28（metrics.py 归「交互与汇总」组）

## Impact

- **agent 定义**：`core/agents/reviewer.md`、`core/agents/reviewer-b.md`（输出格式章节 +1 行标记约定）、`core/agents/recorder.md`（归档流程 +1 步）——改后必须 `build.py --check` 同步四平台 dist
- **工作流文档**：`core/skills/budget-workflow/phases.md`（Step 6 recorder prompt 模板 +1 行调用指令）
- **lib**：新增 `core/lib/metrics.py` + 修改 `display.py` / `run_summary.py`（趋势段，延迟导入容错同 A 模式）
- **不触碰**：guard.sh / guard_metrics.py（A 的成果零改动，metrics 只读 guard.json 做快照）、notify.sh / N1-N11 事件、P0 规则、router.md、SKILL.md
- **数据**：`~/.budgetbuddy/projects/<name>/memory/metrics.json`（新文件，本地持久化不提交 git，同 coder-guard.json 语义）
- **依赖**：无新增（stdlib only）
