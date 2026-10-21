# repo-docs Delta

## MODIFIED Requirements

### Requirement: README 双语文档

`README.md`（英文）与 `README_CN.md`（中文）内容对等，包含：项目定位（多 Agent 省钱研发工作流套件、三平台支持）、安装方式（install.sh 一行安装 + 手动安装）、三平台快速开始（CodeBuddy `/budget:start` / OpenCode `/budget-start` / Claude Code `/budget:start`，含 claudecode 项目级/全局安装说明）、架构说明（Mermaid 流程图，Leader→architect→分级 coder→tester→双 reviewer→recorder、Director 终裁）、模型三档预设表（三平台列）、可用命令表、setup 子命令表、通知配置说明（四渠道 webhook，**Claude Code 端 hooks 三事件通知已支持（Notification/PermissionRequest/SubagentStop）**）、目录结构、开发指南（core 单一源 + build.py 多平台构建、门禁命令）、许可协议（design.md §16.3-T12）。【MUST】

#### Scenario: 双语对等

- **WHEN** 对照两份 README 章节结构
- **THEN** 章节与信息点一一对应，无单语独有关键信息

#### Scenario: 架构图可渲染

- **WHEN** 在支持 Mermaid 的渲染器中打开 README
- **THEN** 架构图正常渲染且与工作流文档（router/phases）的角色与流程一致

#### Scenario: 三平台快速开始

- **WHEN** 检查 README 快速开始章节
- **THEN** 三个平台各自的安装命令与工作流入口命令均给出，Claude Code 端 hooks 通知能力有明确说明
