# repo-docs Specification

## Purpose
TBD - created by archiving change foundation. Update Purpose after archive.
## Requirements
### Requirement: README 双语文档

`README.md`（英文）与 `README_CN.md`（中文）内容对等，包含：项目定位（您的预算伙伴；分工明确、门禁严格的多 Agent 编排 AI 研发团队、**四平台**支持）、安装方式（install.sh 一行安装 + 手动安装）、四平台快速开始（CodeBuddy `/budget:start` / OpenCode `/budget-start` / Claude Code `/budget:start` / Codex 自然语言触发 skill + `multi_agent` 前置条件说明，含 claudecode 项目级/全局安装说明）、架构说明（Mermaid 流程图，Leader→architect→分级 coder→tester→双 reviewer→recorder、Director 终裁）、模型三档预设表（四平台列，codex 列为 gpt-5.6 部署别名三档 + 映射前提注）、可用命令表、setup 子命令表（含 `ocr` 子命令一行说明，codex preset 降级语义注明）、agent 可观测性章节（guard 保鲜与置信 + 质量趋势与退化告警，双语对等）、通知配置说明（四渠道 webhook，**Claude Code 端 hooks 三事件通知已支持（Notification/PermissionRequest/SubagentStop）**、Codex hooks 实验态不支持）、**可选集成说明（OCR Pre-Review Integration：开源 OpenCodeReview CLI 的安装 `npm i -g @alibaba-group/open-code-review`、模型配置二选一——`ocr config provider/model` 或 `ocr delegate` 委托模式免 key、规范规则集——`budget setup ocr` 将 `budget-*-style` 提炼的规则模板安装到 `~/.opencodereview/rule.json`（含项目级 `.opencodereview/rule.json` 优先级说明）、定位为机器预审 detector + reviewer 裁决 judge 非门禁、未安装/未配置时全流程照常的降级语义、Claude Code 用户可选 settings.json permissions.allow 白名单加速提示一句、官方文档链接 open-codereview.ai；不含任何内网地址与私有基建信息）**、目录结构（含 dist/codex/）、开发指南（core 单一源 + build.py 多平台构建、门禁命令）、许可协议。【MUST】

#### Scenario: 双语对等

- **WHEN** 对照两份 README 章节结构
- **THEN** 章节与信息点一一对应，无单语独有关键信息

#### Scenario: 架构图可渲染

- **WHEN** 在支持 Mermaid 的渲染器中打开 README
- **THEN** 架构图正常渲染且与工作流文档（router/phases）的角色与流程一致

#### Scenario: 四平台快速开始

- **WHEN** 检查 README 快速开始章节
- **THEN** 四个平台各自的安装命令与工作流入口均给出（Codex 端 multi_agent 前置与别名映射前提有说明），Claude Code 端 hooks 通知能力有明确说明

#### Scenario: OCR 可选集成章节双语对等

- **WHEN** 对照两份 README 的 OCR Pre-Review Integration 章节
- **THEN** 安装命令、配置方式（含 delegate 免 key 模式）、非门禁定位、降级语义在两份文档中一一对应，且不含内网地址或私有基建信息

#### Scenario: 品牌门禁通过

- **WHEN** 新增 OCR 章节后执行 `python3 scripts/scan-brand.py`
- **THEN** 退出码 0，无违禁词命中

### Requirement: 仓库元数据

`VERSION` 内容 `0.1.0`；`CHANGELOG.md` 首条记录 v0.1.0（全量首版：双平台支持、10 agent、工作流、通知、预设、安装器）；`LICENSE` 为 MIT（含版权行）（design.md §16.3-T12）。【MUST】

#### Scenario: 版本一致
- **WHEN** build-release.sh 打包
- **THEN** zip 名含 VERSION 读取的版本号 0.1.0

### Requirement: 自举开发说明双入口

`CODEBUDDY.md` 与 `AGENTS.md` 内容一致（互为指针说明），向自举开发的 AI 会话说明仓库结构（core 单一源/dist 产物（含 codex））、构建与门禁命令、开发流程、品牌合规约束；**四平台入口说明**——CodeBuddy 读 CODEBUDDY.md、OpenCode 读 AGENTS.md、Claude Code 经安装器合并读 CLAUDE.md、Codex 经安装器合并读 AGENTS.md 轻量区块（同一目标文件的两种区块形态：opencode 全文合并 vs codex 轻量索引——不同安装形态下互斥，同一项目只装其一）。【MUST】

#### Scenario: 双平台自举

- **WHEN** CodeBuddy 与 OpenCode 分别在仓库根打开会话
- **THEN** 各自读取到等价的项目说明

#### Scenario: 四平台口径一致

- **WHEN** 对照 CODEBUDDY.md、AGENTS.md 及 claudecode/codex 安装合并产物
- **THEN** 开发纪律表述一致，各平台读取来源注明

### Requirement: core/docs 四份文档

`core/docs/` 含：`MODEL_SELECTION.template.md`（模型选择文档模板，A6 占位符）、`PERSONAS.md`（persona 主题使用说明）、`architecture.md`（架构说明 + Mermaid 图，产物并入 README 或独立分发）、`opencode-setup-notes.md`（opencode 平台安装说明、模型 provider 前置条件、hooks 插件扩展点说明）（design.md §16.1-T12）。【MUST】

#### Scenario: opencode 扩展点说明
- **WHEN** opencode 用户需要 hooks 等价能力
- **THEN** setup-notes.md 给出插件扩展点指引与前置条件

#### Scenario: 模板占位符
- **WHEN** 构建期渲染 MODEL_SELECTION.template.md
- **THEN** 全部占位符被 budget-models.json 数据填充，产物无残留占位符

