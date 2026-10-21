# repo-docs Delta Spec

## MODIFIED Requirements

<!-- 基线口径说明：本 MODIFIED 基于在途变更 add-codex-platform 归档后的四平台口径叠加 OCR 段（归档顺序依赖见 design.md Migration Plan 第 3 条——建议 add-codex-platform 先归档）。 -->

### Requirement: README 双语文档

`README.md`（英文）与 `README_CN.md`（中文）内容对等，包含：项目定位（多 Agent 省钱研发工作流套件、**四平台**支持）、安装方式（install.sh 一行安装 + 手动安装）、四平台快速开始（CodeBuddy `/budget:start` / OpenCode `/budget-start` / Claude Code `/budget:start` / Codex 自然语言触发 skill + `multi_agent` 前置条件说明，含 claudecode 项目级/全局安装说明）、架构说明（Mermaid 流程图，Leader→architect→分级 coder→tester→双 reviewer→recorder、Director 终裁）、模型三档预设表（四平台列，codex 列为 gpt-5.6 部署别名三档 + 映射前提注）、可用命令表、setup 子命令表（含 `ocr` 子命令一行说明，codex preset 降级语义注明）、通知配置说明（四渠道 webhook，**Claude Code 端 hooks 三事件通知已支持（Notification/PermissionRequest/SubagentStop）**、Codex hooks 实验态不支持）、**可选集成说明（OCR Pre-Review Integration：开源 OpenCodeReview CLI 的安装 `npm i -g @alibaba-group/open-code-review`、模型配置二选一——`ocr config provider/model` 或 `ocr delegate` 委托模式免 key、规范规则集——`budget setup ocr` 将 `budget-*-style` 提炼的规则模板安装到 `~/.opencodereview/rule.json`（含项目级 `.opencodereview/rule.json` 优先级说明）、定位为机器预审 detector + reviewer 裁决 judge 非门禁、未安装/未配置时全流程照常的降级语义、Claude Code 用户可选 settings.json permissions.allow 白名单加速提示一句、官方文档链接 open-codereview.ai；不含任何内网地址与私有基建信息）**、目录结构（含 dist/codex/）、开发指南（core 单一源 + build.py 多平台构建、门禁命令）、许可协议。【MUST】

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
