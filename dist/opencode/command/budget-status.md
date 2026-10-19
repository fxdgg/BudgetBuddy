---
description: 查看当前工作流状态：budget 状态机进度、活跃 OpenSpec 变更与任务完成度
---

查看 BudgetBuddy 当前状态。

执行以下诊断步骤并汇总输出：

**1. 工作流状态机（budget-state.py）**
```bash
python3 "$HOME/.budgetbuddy/lib/budget-state.py" find 2>/dev/null || echo "[budget] 状态机脚本未找到"
```
- 输出 `found: true` → 读取其中的状态文件路径，提取 `current_step`、`completed_steps`、`agent_calls_used`/`max_agent_calls` 等字段
- 输出 `found: false` 或脚本缺失 → 标注「无进行中的工作流」

**2. 活跃 OpenSpec 变更**
```bash
openspec list --json 2>/dev/null || echo "[budget] 无活跃变更或 openspec 未安装"
```

**3. 任务进度**
读取活跃 change 的 `openspec/changes/<name>/tasks.md`（如存在），统计 `- [x]`（已完成）与 `- [ ]`（未完成）任务数量；文件不存在时跳过本项。

**4. 最近 git 提交**
```bash
git log --oneline -5 2>/dev/null || echo "[budget] 非 git 仓库"
```

将以上输出整理为表格或结构化报告，包含：
- 当前工作流状态（状态机 current_step、已完成步骤、agent 调用计数）
- 活跃变更列表和任务进度（N/M）
- 下一步建议
