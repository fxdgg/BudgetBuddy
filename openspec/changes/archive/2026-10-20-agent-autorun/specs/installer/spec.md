# installer Delta

## ADDED Requirements

### Requirement: 安装后 AutoRun 状态重放

`install.sh` 的 `install_codebuddy` 分支在 manifest 增量同步（含升级差集清理）完成后、写入本地清单前（钩子落点：`upgrade_diff_cleanup` 调用之后、`write_local_manifest` 调用之前；install.sh L929/L936，行号随文件演进以锚点函数名称为准），若全局状态文件 `~/.budgetbuddy/auto-run.json` 存在，则以刚同步的 `lib/autorun.py` 执行 `apply`（清单内 agent 确保 `enabledAutoRun: true`、清单外确保删除该行），将用户持久化选择重放到本次同步可能被 dist 默认值覆盖的 agent 文件上；重放失败（含状态文件损坏）仅告警（提示 `budget setup autorun` 修复），不阻断安装主流程、不影响本地清单写入、不覆盖写状态文件。状态文件不存在时不执行重放（dist 默认值 = 4 个执行类 agent 免审批）。opencode/claudecode 分支无此钩子（两平台不映射 auto-run）。【MUST】

#### Scenario: 升级安装后用户选择保持

- **WHEN** 用户状态文件为「默认 4 个 + reviewer」，重新运行新版本 install.sh（agent 文件被新 dist 覆盖）
- **THEN** 同步后重放执行：reviewer 恢复 `enabledAutoRun: true`，4 个默认 agent 仍在位，其余 5 个不含该键

#### Scenario: 无状态文件不重放

- **WHEN** 首次安装且 `~/.budgetbuddy/auto-run.json` 不存在
- **THEN** 安装不执行 apply，agent 文件保持 dist 原样（4 个执行类 agent 含 `enabledAutoRun: true`）

#### Scenario: apply 失败降级告警

- **WHEN** 状态文件存在但内容损坏（JSON 解析失败）导致 apply 非零退出
- **THEN** 安装流程继续（本地清单正常写入），输出告警提示用户运行 `budget setup autorun list` 检查状态；状态文件字节保持原样（apply 不得覆盖写）

#### Scenario: 重放不影响安装幂等性

- **WHEN** 连续两次运行 install.sh：无状态文件、或状态与 dist 默认一致（默认 4 个执行类 agent）时，第二次同步全部哈希跳过（SYNC_SKIPPED，SYNC_UPDATED=0）；非默认状态（如「默认 4 个 + reviewer」）下，reviewer 经 apply 补丁后其文件哈希 ≠ dist 清单哈希，第二次同步先以 dist 重覆盖该偏差 agent（SYNC_UPDATED>0，`enabledAutoRun` 被 dist 默认值冲掉），再由 apply 重放恢复
- **THEN** 两种路径终态均与首次一致（reviewer 恢复 `enabledAutoRun: true`、默认 4 个仍在位、其余不含该键），且 apply 为字节级幂等（重复执行文件字节不变），安装主流程正常完成
