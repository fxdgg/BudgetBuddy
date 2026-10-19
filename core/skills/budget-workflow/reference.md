# 参考信息（非流程必需，按需查阅）

> 本文件包含 budget-workflow 的全工作流速查表与配置参考，不参与流程执行，仅在需要时查阅。

## 全工作流速查表

### 命令速查

| 命令（CodeBuddy / OpenCode） | 用途 |
|------------------------------|------|
| `/budget:start` / `/budget-start` | 单次模式：Phase 1→2→3→4→5 |
| `/budget:goal` / `/budget-goal` | Goal Loop：Phase 0→1→2→3→4→5→6（循环）→归档 |
| `/budget:goal resume` / `/budget-goal resume` | 恢复中断的 Goal Loop |
| `/budget:status` / `/budget-status` | 查询当前 openspec change 与任务进度 |
| `/opsx:propose` / `/opsx-propose` | openspec 提案 |
| `/opsx:apply` / `/opsx-apply` | openspec 实现 |
| `/opsx:archive` / `/opsx-archive` | openspec 归档 |
| `/opsx:explore` / `/opsx-explore` | openspec 探索 |

### 阶段速查

| 阶段 | 内容 | 执行者 | 产物 |
|------|------|--------|------|
| Phase 0 | 目标定义（goal 模式） | Leader | goal.md + goal-state.json |
| Phase 1 | 需求分析 + 方案设计 | architect | proposal.md, design.md |
| Phase 2 | 方案评审 | reviewer + reviewer-b 并行 | gate-review.md |
| Phase 3 | 分级编码 + 测试 + 审查 | coder→tester→reviewer（每任务循环） | 代码 + 测试报告 + 审查报告 |
| Phase 4 | 全量最终审查 + 回归验证 | reviewer | 最终审查报告 |
| Phase 5 | 归档 | recorder | 归档记录 + Coder Guard 更新 |
| Phase 6 | 目标验证（goal 模式） | tester / reviewer / goal-evaluator | 验证报告 + 独立判定 |

### 角色速查（10 agent）

| subagent_type | 职责 | max_turns |
|---------------|------|-----------|
| architect | 方案设计、闸门评审 | 80 |
| coder-lite | 简单 CRUD/配置 | 35 |
| coder-standard | 常规功能、API、bug 修复 | 50 |
| coder-senior | 架构/安全/并发 | 70 |
| reviewer | 代码审查、规格合规（主审） | 40 |
| reviewer-b | 技术合理性审查（辅审，交叉复核） | 40 |
| tester | 编译验证、测试运行 | 40 |
| recorder | 知识沉淀、归档记录 | 30 |
| director | 终裁（只读、禁终端命令） | 15 |
| goal-evaluator | 独立目标验证判定（只读、禁终端命令） | 8 |

### 工具与数据速查

| 组件 | 位置/调用 | 说明 |
|------|-----------|------|
| budget CLI | `budget setup <子命令>` | init/show/agent/persona/validate/diff/stats/update/reinstall/uninstall/guard/quickstart/models/help |
| 通知 | `budget notify "<msg>" <Nx> || true` | 通知点 N1-N11，消息前缀 `[budget]` |
| 状态机 | `python3 $HOME/.budgetbuddy/lib/budget-state.py` | goal/start 状态读写、安全边界检查 |
| Coder Guard | `{{GUARD_PATH}}` | coder 成功/失败记录，最近 5 次窗口、失败 ≥2 触发降级 |
| persona | `.budget/persona-active.json` > `~/.budgetbuddy/persona-active.json` | 5 主题，roles 11 键（leader + 十角色） |
| 模型目录 | `budget-models.json`（`budget setup models` 更新） | 三档预设 economic/balanced/quality |
| openspec 变更 | `openspec/changes/<change-id>/` | goal 状态存 tasks.md 勾选状态 |

## 费用估算

各预设的相对成本与模型目录（budget-models.json）联动，具体单价以 `budget setup models` 更新后的目录为准；三档预设的典型相对关系：

| 预设 | 定位 | 相对成本 |
|------|------|---------|
| economic | 省钱优先（轻量模型为主） | 最低 |
| balanced | 默认推荐（分级混编） | 中等 |
| quality | 质量优先（高档模型为主） | 最高 |

**经济模式下一个完整开发流程的典型 token 分配**：
- 主会话（Leader，约 30% token）
- Coder 加权（约 40% token，大部分任务走 lite/standard）
- Reviewer（约 15% token）
- Tester（约 10% token）
- Recorder（约 5% token）

分级派发 + 免费档模型组合是成本优化的主要来源（详见 MODEL_SELECTION.md）。

## RTK 集成（可选）

- 通过 CodeBuddy hooks（`hooks/budget-notify-hook.py`，由 lib/hooks.sh 注入 settings.json）自动注册 RTK hook
- 每次发往模型的请求终端输出会被 RTK 压缩
- 成本进一步降低（终端输出不计模型 token，但会影响传输成本和延时）
- `budget setup stats` 可查看 RTK 压缩收益

## 模型预设切换

```bash
# 简单需求（省钱优先）
budget setup agent preset economic

# 中等需求（默认推荐）
budget setup agent preset balanced

# 复杂/高风险需求（质量优先）
budget setup agent preset quality
```

预设切换即时生效，无需重新 init。
