## ADDED Requirements

### Requirement: README 双语文档

`README.md`（英文）与 `README_CN.md`（中文）内容对等，包含：项目定位（多 Agent 省钱研发工作流套件、双平台支持）、安装方式（install.sh 一行安装 + 手动安装）、双平台快速开始（CodeBuddy `/budget:start` / OpenCode `/budget-start`）、架构说明（Mermaid 流程图，Leader→architect→分级 coder→tester→双 reviewer→recorder、Director 终裁）、模型三档预设表、可用命令表、setup 子命令表、通知配置说明（四渠道 webhook）、目录结构、开发指南（core 单一源 + build.py 双平台构建、门禁命令）、许可协议（design.md §16.3-T12）。【MUST】

#### Scenario: 双语对等
- **WHEN** 对照两份 README 章节结构
- **THEN** 章节与信息点一一对应，无单语独有关键信息

#### Scenario: 架构图可渲染
- **WHEN** 在支持 Mermaid 的渲染器中打开 README
- **THEN** 架构图正常渲染且与工作流文档（router/phases）的角色与流程一致

### Requirement: 仓库元数据

`VERSION` 内容 `0.1.0`；`CHANGELOG.md` 首条记录 v0.1.0（全量首版：双平台支持、10 agent、工作流、通知、预设、安装器）；`LICENSE` 为 MIT（含版权行）（design.md §16.3-T12）。【MUST】

#### Scenario: 版本一致
- **WHEN** build-release.sh 打包
- **THEN** zip 名含 VERSION 读取的版本号 0.1.0

### Requirement: 自举开发说明双入口

`CODEBUDDY.md` 与 `AGENTS.md` 内容一致（互为指针说明），向自举开发的 AI 会话说明：本仓库的结构（core 单一源/dist 产物/禁手改 dist）、构建与门禁命令（`python3 scripts/build.py --check`）、开发流程（openspec 变更工作流 + Leader 禁写代码 + 分级 coder）、品牌合规约束（违禁词门禁）（design.md §16.3-T12）。【MUST】

#### Scenario: 双平台自举
- **WHEN** CodeBuddy 与 OpenCode 分别在仓库根打开会话
- **THEN** 各自读取到等价的项目说明（CODEBUDDY.md / AGENTS.md）

### Requirement: core/docs 四份文档

`core/docs/` 含：`MODEL_SELECTION.template.md`（模型选择文档模板，A6 占位符）、`PERSONAS.md`（persona 主题使用说明）、`architecture.md`（架构说明 + Mermaid 图，产物并入 README 或独立分发）、`opencode-setup-notes.md`（opencode 平台安装说明、模型 provider 前置条件、hooks 插件扩展点说明）（design.md §16.1-T12）。【MUST】

#### Scenario: opencode 扩展点说明
- **WHEN** opencode 用户需要 hooks 等价能力
- **THEN** setup-notes.md 给出插件扩展点指引与前置条件

#### Scenario: 模板占位符
- **WHEN** 构建期渲染 MODEL_SELECTION.template.md
- **THEN** 全部占位符被 budget-models.json 数据填充，产物无残留占位符
