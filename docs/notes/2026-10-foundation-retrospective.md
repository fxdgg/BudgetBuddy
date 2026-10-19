# foundation 变更复盘（v0.1.0 全量首版）

- 变更：`openspec/changes/foundation`——24 任务全部完成，636 测试全绿，226 文件零违禁词，双平台产物 72+61 文件
- 周期：2026-10-16 至 2026-10-19；coder→tester→双 reviewer 全链路，两轮方案评审 + 逐批次代码审查

## 关键经验

1. **门禁先行**：违禁词扫描（T1b）与构建系统（T1a）作为首批任务，全程拦截品牌残留——后续 20+ 任务零品牌事故，reviewer 每轮独立扫描均通过。
2. **单一源+构建转换**：core/ 改一处、双平台产物自动一致；手写 YAML 子集解析器（~150 行）足以支撑 platform DSL，无需 PyYAML 依赖。
3. **P0 一致性约定**：rules 文件采用「紧凑单段 + 与 SKILL 内联条目同关键词集」的写法，构建期 80% 关键词匹配即可自动校验三层落位一致性。
4. **bash 3.2 陷阱**：macOS 自带 bash 中 `$var` 后紧跟全角标点（如中文括号）会被并入变量名导致 unbound variable——统一使用 `${var}` 花括号界定。
5. **测试环境隔离**：IDE 会话注入（BASH_ENV 指向 safe-delete shim）会包装 `rm` 干扰测试——测试脚手架统一 `env -u BASH_ENV -u CODEBUDDY_SESSION_ID` 剥离。
6. **子代理上下文上限**：超 500 行级别的单任务（T9c/T10c）易触发上下文中断——拆分为「主体实现 + 收尾修复」两次派发是有效模式。
7. **双审交叉验证**：主审（实现可行性）与辅审（技术合理性）问题零重叠；语义漂移（guard 职责、通知点数量）与数据缺口（provider_map）均由辅审捕获，工作量超标（5 任务超 2h）均由主审捕获。

## 遗留事项

1. 在线安装模式因 BUDGET_REPO_URL 为占位地址未做真实远端演练（本地模式已全链路验证）——推送远端后补一次在线安装冒烟。
2. opencode 预设 7 个模型 ID 待确认（budget-models.json `_meta.unconfirmed_opencode_ids` 已标注）——上线前清零。
3. 第三个 agent 平台扩展切入点：新增 `core/platform/<name>.yaml` + build.py 转换器（frontmatter 映射与 routing 落位），安装器加平台分支。
