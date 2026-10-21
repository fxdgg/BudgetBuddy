# agent-autorun 最终审查 Follow-up 记录（Recorder）

> 来源：最终审查（结论：通过，评分 A）的 7 项 follow-up。均不阻塞归档；供归档后按需处理。
> 记录时间：2026-10-20（Recorder，Phase 5 归档沉淀）。
> 约束：build.py 正被 add-codex-platform 变更并发编辑——凡涉及 build.py 的条目**仅记录不修改**，避免并发冲突。

## F1. README 双语安全段 architect 权限标注精确化（低优先级）

- **位置**：`README.md` L239、`README_CN.md` L239 安全须知段。
- **现状**：git 类 agent 统一标注 `bash_allow: ["git *"]`。
- **问题**：architect 实际为 `bash_allow: ["git *", "openspec *"]`（`core/agents/architect.md` frontmatter 实证），`openspec *` 模式未在安全段列明（可无审批执行 `openspec` 相关命令）。
- **建议**：双语安全段将 architect 单独标注 `["git *", "openspec *"]`，或补一句「architect 另含 `openspec *`」。

## F2. build.py L679 注释「七→八」未同步（仅记录不修改）

- **位置**：`scripts/build.py` L679 注释「§3.5 精确七表达式」。
- **问题**：任务 1.2 将 `EMIT_EXPRESSIONS` 由七表达式扩为八表达式（新增 `auto_run`），L88-91 处注释已同步，但 L679 `validate_dsl` 内同类注释仍写「七表达式」，与实际集合不符（纯注释，无功能影响）。
- **处置**：**仅记录不修改**——build.py 正被 add-codex-platform 变更并发编辑，由该变更收尾时顺带同步，或下一改动 build.py 的变更处理。

## F3. `autorun list` missing 态页脚措辞区分「未初始化/损坏」（低优先级）

- **位置**：`core/lib/autorun.py` L458-459 页脚。
- **现状**：状态栏（L411-424）已区分 missing（未初始化）/ corrupt（损坏）两态；但页脚对两种非 ok 态共用一句「（状态栏异常，差异比对略；修复状态文件后可比对）」。
- **问题**：missing（未初始化）是正常首用形态，用「异常 + 修复」措辞会误导用户以为文件损坏。
- **建议**：页脚按状态分流——missing 态措辞如「（未初始化，差异比对略；运行 on/off 种子化基线后可比对）」，corrupt 态保留现修复指引。

## F4. installer 全局态重放专测（可选加固）

- **背景**：任务 2.5 已按 B1 修订将 install.sh 重放钩子纳入 `tests/test_installer.py` 自动化（钩子落点/无状态不重放/损坏告警不阻断/二次安装 apply 幂等）。
- **建议**：如后续追加加固，可补「全局状态文件存在 + 多平台共装」组合场景的专测（重放仅作用于 codebuddy 分支、opencode/claudecode 分支零调用的断言），当前自动化覆盖已满足 spec MUST 级。

## F5. OQ1/OQ3 文档建议文本待真实 IDE 验证定论后落位（依赖外部条件）

- **背景**：`verification-open-questions.md` OQ1/OQ3 的「文档口径建议」两段文本（设置页与 frontmatter 优先级、AutoRun × permissionMode 层级）因无真实 CodeBuddy IDE 会话无法实证，本次未落入 README 双语。
- **落位条件**：用户在真实 IDE 会话完成端到端验证后——若确认「IDE 侧优先」，将 OQ1 建议文本中「请以 IDE 设置页当前显示为准」升级为显式口径「以 IDE 设置为准」并去除条件语气；OQ3 按实证结论更新「验证前文档不承诺二者语义正交」表述。验证前 README 不承诺优先级与正交性（现状即安全口径）。

## F6. autorun.py L448-455 重复 if 合并（可读性）

- **位置**：`core/lib/autorun.py` L448-455（`cmd_list` 安装态遍历）。
- **现状**：连续两个 `if value == 'true':`——前者收集 `actual` 清单，后者计算展示 `mark`。
- **问题**：纯可读性问题（无功能缺陷），重复条件易误导后续修改。
- **建议**：合并为单个 `if value == 'true':` 分支内先 `actual.append(name)` 再置 `mark`，`elif` 链保持不动。

## F7. test_autorun.py L563 行宽 121 → ≤120（规范）

- **位置**：`tests/test_autorun.py` L563（`ListCorruptReadonlyTests` 类 docstring，实测行宽 121，为全仓唯一超 120 行）。
- **建议**：折行或压缩文案至 ≤120，对齐仓库代码规范行宽口径。
