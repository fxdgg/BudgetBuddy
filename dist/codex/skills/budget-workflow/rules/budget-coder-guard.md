---
description: Coder 护栏降级。分派任务前必须查询 Coder Guard 记录（不提交 git，本地持久化），该 coder 在任务标签上最近 5 次记录中失败 ≥ 2 次即触发降级保护（lite→standard→senior 逐级改派）。
globs: ["**/*"]
alwaysApply: true
---

# coder-guard（Coder 护栏降级）

分派任务前必须查询 Coder Guard 记录（$HOME/.budgetbuddy/projects/<project-name>/memory/coder-guard.json，不提交 git，本地持久化），该 coder 在任务标签上最近 5 次记录中失败 ≥ 2 次即触发降级保护（lite→standard→senior 逐级改派），防止在已证实的高失败率组合上重复浪费预算。
