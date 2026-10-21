# 方案双审记录（gate-review）：agent-autorun

| 轮次 | 主审 reviewer（实现可行性） | 辅审 reviewer-b（技术合理性） | 结论 |
|---|---|---|---|
| R1 | 通过（附 3 项补强：test_autorun.py 自动化覆盖、种子化按值判定、install.sh 行号修正） | 驳回（3 必修：种子化口径翻转风险、多安装形态语义缺口、安全性未显式化） | 驳回 → 退回修订 |
| R2 | 驳回（1 阻塞 A1：`autorun on` 输出 bash 模式在安装态无数据来源；2 重要 B1/B2：验证策略理由失实、installer spec 幂等场景前提不严谨） | 通过（3 项遗留建议 O1/O2/O3 不阻塞） | 驳回 → 退回修订 |
| R3（增量） | 通过（A1/B1/B2/C/D/E/O1/O2/O3 九项修订全部落实，与仓库现状实证一致） | 通过（A1 修订 D7 成立；O1/O2/O3/B2 均成立） | **通过** |

## 关键修订落订

- **A1（design D7）**：bash 模式数据来源 = build 期从 `core/agents/*.md` 生成 `dist/codebuddy/agents/.bash-patterns.json`，门控「仅 emit 映射 `{auto_run}` 的平台生成」，opencode/claudecode 逐字节不变声明保持成立；运行时文件缺失降级通用提示不阻断。
- **种子化口径**：仅「`enabledAutoRun` 行存在且值解析为 true」进基线，`false` 行视为用户显式关闭不翻转。
- **多安装形态语义**：on/off 作用域 = 当前探测到的安装态；unknown 形态 on/off/apply 非零退出；list 双栏（全局状态 + 安装态实况）；list 损坏态只读展示 exit 0。
- **安全显式化**：proposal/design 声明「AutoRun 使该 agent 权限范围内所有工具调用免人工审批」；Risks 覆盖 `bash_allow: ["*"]` 与 `git *` 高危场景；README/`autorun on` 输出落实知情提示。
- **验证策略**：install.sh 钩子集成改由 `tests/test_installer.py` 增补重放用例自动化（该文件已有 41 例 subprocess 端到端先例）。
- **installer spec 幂等场景**：WHEN 限定两路径（无状态/默认一致 → 同步全跳过；非默认 → 同步重覆盖 + apply 重放，终态一致 + apply 字节级幂等）。

## 门禁基线

设计阶段实测：`build.py --check` exit 0；`scan-brand.py` 289 文件零违禁；`unittest` 709 OK（以实施时实测为准）。

## 结论

**Phase 2 通过，进入 Phase 3 分级实现。**
