# repo-docs Delta

## MODIFIED Requirements

### Requirement: README 双语文档

`README.md`（英文）与 `README_CN.md`（中文）内容对等，包含：项目定位（多 Agent 省钱研发工作流套件、三平台支持）、安装方式（install.sh 一行安装 + 手动安装）、三平台快速开始（CodeBuddy `/budget:start` / OpenCode `/budget-start` / Claude Code `/budget:start`，含 claudecode 项目级/全局安装说明与 hooks 降级声明）、架构说明（Mermaid 流程图，Leader→architect→分级 coder→tester→双 reviewer→recorder、Director 终裁）、模型三档预设表（三平台列）、可用命令表、setup 子命令表、通知配置说明（四渠道 webhook，标注 claudecode 首发不支持 hooks 通知）、目录结构、开发指南（core 单一源 + build.py 多平台构建、门禁命令）、许可协议（design.md §16.3-T12）。【MUST】

#### Scenario: 双语对等

- **WHEN** 对照两份 README 章节结构
- **THEN** 章节与信息点一一对应，无单语独有关键信息

#### Scenario: 架构图可渲染

- **WHEN** 在支持 Mermaid 的渲染器中打开 README
- **THEN** 架构图正常渲染且与工作流文档（router/phases）的角色与流程一致

#### Scenario: 三平台快速开始

- **WHEN** 检查 README 快速开始章节
- **THEN** 三个平台各自的安装命令与工作流入口命令均给出，Claude Code 端 hooks 通知缺失有明确说明

### Requirement: 自举开发说明双入口

`CODEBUDDY.md` 与 `AGENTS.md` 内容一致（互为指针说明），向自举开发的 AI 会话说明：本仓库的结构（core 单一源/dist 产物（含 claudecode）/禁手改 dist）、构建与门禁命令（`python3 scripts/build.py --check`）、开发流程（openspec 变更工作流 + Leader 禁写代码 + 分级 coder）、品牌合规约束（违禁词门禁）；三平台入口说明——CodeBuddy 会话读 CODEBUDDY.md、OpenCode 会话读 AGENTS.md、Claude Code 会话经安装器合并读 CLAUDE.md 标记区块（design.md §16.3-T12）。【MUST】

#### Scenario: 双平台自举

- **WHEN** CodeBuddy 与 OpenCode 分别在仓库根打开会话
- **THEN** 各自读取到等价的项目说明（CODEBUDDY.md / AGENTS.md）

#### Scenario: 三平台口径一致

- **WHEN** 对照 CODEBUDDY.md、AGENTS.md 与 claudecode 安装合并产物的 CLAUDE.md 标记区块

- **THEN** 开发纪律（铁律/流程/门禁）表述一致，且文档中注明 Claude Code 用户的读取来源
