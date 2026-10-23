# workflow-orchestration Delta Spec

## ADDED Requirements

### Requirement: 归档质量指标采集与查询面趋势告警

Phase 5 归档（recorder）SHALL 在执行 openspec archive **之前**执行质量指标采集（archive 会将 change 目录移动至 `archive/<date>-<id>/`，之后扫描将落空——采集时扫描原 `openspec/changes/<id>/` 目录）：调用 `python3 $HOME/.budgetbuddy/lib/metrics.py record --change-id <id> --change-dir <change目录>`（递归扫描 change 目录 .md 提取全部 budget-verdict 标记，聚合 phase2_rating/phase2_rounds/reviewer_b_conclusion/final_rating，并快照 guard.json 的全量失败/降级计数），写入 `~/.budgetbuddy/projects/<project-name>/memory/metrics.json`（history 追加，同 change_id 重复 record 幂等覆盖；标记缺失字段可人工参数兜底，全缺失记 null 不阻断）。`budget setup stats`（display.py）与 run summary（run_summary.py）SHALL 以延迟导入容错模式（import 失败降级为不展示趋势段、其余照常 exit 0，同 guard_metrics 先例）展示「质量趋势」段：最近 N 次（默认 5）final 评分序列、phase2 一次通过率、guard 失败率，及告警行——R1 评分严格连续下降（最近 ≥3 条）、R2 一次通过率 < 50%、R3 guard 失败率 > 40%（**metrics.json 最新一条快照口径**：guard_failures / guard_history_total，样本 ≥5——分子分母同为 history 快照口径，不混实时值；R2 分母为 0 时不计算不告警）。告警 MUST 仅在查询面呈现（不推送通知、不触发降级、不影响任何流程判定——纯参考层）；N1-N11 通知事件、guard 写入端、降级硬规则 MUST NOT 改变。metrics 采集失败（脚本异常/标记全缺失且未兜底）MUST NOT 阻断归档流程本身。本条属提示词行为约束与查询面能力，验收方式为人工审计 + 单元测试 + 构建产物一致性校验。【MUST】

#### Scenario: 归档时自动采集

- **WHEN** recorder 归档一个含 budget-verdict 标记的变更（采集先于 openspec archive 执行）
- **THEN** metrics.json 的 history 追加该 change 记录（评分/轮数/双审结论/guard 快照四类字段齐备），归档流程正常完成

#### Scenario: 标记缺失人工兜底

- **WHEN** 变更产物缺 budget-verdict 标记且 recorder 以 `--phase2-rating` 等参数显式补录
- **THEN** 显式参数优先于扫描结果，指标记录完整；未兜底的缺失字段记 null，归档不被阻断

#### Scenario: 幂等重录

- **WHEN** 同一 change_id 重复执行 record
- **THEN** history 按 change_id 去重更新（覆盖非追加），recorded_count 不虚增

#### Scenario: 同轮多文件标记消歧

- **WHEN** reviews/reviewer-a.md 与 reviews/round2-verdict.md 均含 round=2 的 reviewer 标记
- **THEN** phase2_rating 取文件路径字典序最大者的标记（确定性 tie-breaker）

#### Scenario: final_rating 缺失不触发退化告警

- **WHEN** 某变更终审无评分（final_rating 为 null）且其后变更评分为 B、C
- **THEN** R1 连续下降序列在 null 处中断（A→null→B→C 不告警；A→B→C 无 null 才告警）

#### Scenario: 趋势段与告警呈现

- **WHEN** metrics.json 积累 ≥3 条记录且 final 评分序列为 A → B → C
- **THEN** `budget setup stats` 与 run summary 的「质量趋势」段显示评分序列并输出退化告警行

#### Scenario: 采集失败不阻断归档

- **WHEN** metrics.py 调用异常（脚本缺失/内部错误）
- **THEN** 归档流程照常完成（stderr 提示采集失败），指标记录缺失

#### Scenario: 容错降级

- **WHEN** display.py / run_summary.py import metrics 失败
- **THEN** 两命令其余段照常输出退出码 0，无「质量趋势」段

#### Scenario: 通知与降级零改动

- **WHEN** 告警规则命中
- **THEN** 仅查询面输出告警行——无 N1-N11 事件触发、guard 记录不写入、降级判定不参与
