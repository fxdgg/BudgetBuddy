# setup-cli Delta

## MODIFIED Requirements

### Requirement: superpowers 插件启用

`core/lib/hooks.sh` 在 hooks 注入同时检测并启用 CodeBuddy superpowers 插件：检查 settings.json 的 `enabledPlugins`，未启用则注入 `"superpowers@codebuddy-plugins-official": true` 并提示重启或手动执行 `/plugin superpowers`；`setup init` 与安装器 codebuddy 路径均调用该启用流程；`SKILL_NS="superpowers:"` 前缀的 skill 引用依赖该插件（design.md §9/§12-A11）。claudecode 形态注入 hooks 但**跳过**插件启用（Claude Code 无插件机制，仅注入 Notification/PermissionRequest/SubagentStop 三事件）；opencode 形态两者均跳过。【MUST】

#### Scenario: 安装后插件启用

- **WHEN** codebuddy 平台完成安装/init 且 settings.json 未启用 superpowers
- **THEN** enabledPlugins 含 superpowers 条目，用户收到重启或手动启用提示

#### Scenario: 已启用幂等跳过

- **WHEN** settings.json 已启用 superpowers 时重跑注入
- **THEN** 该条目不重复注入（幂等），settings.json 其余内容不变

#### Scenario: claudecode 注入不含插件

- **WHEN** claudecode 形态执行 hooks 注入
- **THEN** settings.json 含三事件 hook 条目、无 enabledPlugins 变更

#### Scenario: claudecode 卸载清理注入

- **WHEN** claudecode 形态执行卸载
- **THEN** settings.json 的本套件 hook 条目被精确移除（用户第三方 hooks 保留）、`.claude/hooks/` 文件删除
