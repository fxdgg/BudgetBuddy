# repo-docs Delta Spec

## MODIFIED Requirements

### Requirement: README 双语文档

`README.md`（英文）与 `README_CN.md`（中文）内容对等，包含：项目定位（您的预算伙伴；分工明确、门禁严格的多 Agent 编排 AI 研发团队、**四平台**支持）、安装方式（install.sh 一行安装 + 手动安装 + **大陆网络与镜像说明——默认直连 GitHub 失败时自动回退 ghproxy 类镜像链、`BUDGET_MIRROR` 钉死/禁用用法、`BUDGET_VERSION` 显式指定逃生通道（直达 releases/download/<tag>，无重定向段，镜像 latest 发现不可用时可用）、第三方通道信任边界与 SHA256 校验说明，双语对等**）、四平台快速开始（CodeBuddy `/budget:start` / OpenCode `/budget-start` / Claude Code `/budget:start` / Codex 自然语言触发 skill + `multi_agent` 前置条件说明，含 claudecode 项目级/全局安装说明）、架构说明（Mermaid 流程图，Leader→architect→分级 coder→tester→双 reviewer→recorder、Director 终裁）、模型三档预设表（四平台列，codex 列为 gpt-5.6 部署别名三档 + 映射前提注）、可用命令表、setup 子命令表（含 `ocr` 子命令一行说明，codex preset 降级语义注明）、通知配置说明（四渠道 webhook，**Claude Code 端 hooks 三事件通知已支持（Notification/PermissionRequest/SubagentStop）**、Codex hooks 实验态不支持）、agent 可观测性章节（guard 保鲜与置信 + 质量趋势与退化告警，双语对等）、**可选集成说明（OCR Pre-Review Integration：开源 OpenCodeReview CLI 的安装 `npm i -g @alibaba-group/open-code-review`、模型配置二选一——`ocr config provider/model` 或 `ocr delegate` 委托模式免 key、规范规则集——`budget setup ocr` 将 `budget-*-style` 提炼的规则模板安装到 `~/.opencodereview/rule.json`（含项目级 `.opencodereview/rule.json` 优先级说明）、定位为机器预审 detector + reviewer 裁决 judge 非门禁、未安装/未配置时全流程照常的降级语义、Claude Code 用户可选 settings.json permissions.allow 白名单加速提示一句、官方文档链接 open-codereview.ai；不含任何内网地址与私有基建信息）**、目录结构（含 dist/codex/）、开发指南（core 单一源 + build.py 多平台构建、门禁命令）、许可协议（design.md §16.3-T12）。【MUST】

#### Scenario: 大陆镜像说明双语对等

- **WHEN** 对照两份 README 的安装章节
- **THEN** 镜像自动回退、BUDGET_MIRROR 三态用法、信任边界与校验说明在两份文档一一对应，无单语独有信息
