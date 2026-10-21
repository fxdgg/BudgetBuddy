# build-pipeline Delta

## ADDED Requirements

### Requirement: extra_outputs rules_index kind

`extra_outputs` 支持 `rules_index` kind（新增枚举，现有 agents_fragment 不变）：`source` 为 `<目录>/**` 形态，`dest` 为轻量索引 fragment 输出（与 routing.rule 一致性校验），可选 `copy_dest` 为规则全文副本目录（构建期单真值源双输出）。索引内容：外层 markers + 按需读取指引 + source 文件一行式清单（规则名 → copy_dest 相对路径）。schema 校验：kind ∈ {agents_fragment, rules_index}；rules_index 的 dest/copy_dest 路径防逃逸与占位符校验同既有规则。【MUST】

#### Scenario: rules_index 双输出

- **WHEN** 构建含 rules_index extra_outputs 的平台（codex）
- **THEN** dest 处生成轻量索引 fragment（< 1KiB）、copy_dest 处生成 source 全文副本

#### Scenario: 未知 kind 报错

- **WHEN** DSL 声明 extra_outputs kind 不在枚举内
- **THEN** 构建失败并指出合法 kind 清单

#### Scenario: 既有平台回归

- **WHEN** codebuddy/opencode/claudecode 构建（无 rules_index 声明）
- **THEN** 三平台产物与 kind 引入前逐字节一致
