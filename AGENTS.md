# BudgetBuddy 开发指南（自举说明）

> **三入口说明**：本文件与 `AGENTS.md` 内容一致、互为指针。CodeBuddy 会话读取本文件（`CODEBUDDY.md`）；OpenCode 会话读取 `AGENTS.md`；Claude Code 会话经安装器将 `CLAUDE.fragment.md` 标记区块幂等合并进 `CLAUDE.md` 读取（构建产物，禁手改）。三份载体描述同一套约定，任选其一遵守即可；修改时必须同步更新 `CODEBUDDY.md` 与 `AGENTS.md` 两份（Claude Code 侧随 `core/` 构建再生）。
>
> **自举声明**：本仓库使用 BudgetBuddy 套件自身的工作流开发（dogfooding）。你正运行在该工作流定义的角色与规则之下。

## 项目结构

```
BudgetBuddy/
├── core/                  # 单一中立源 — 所有内容修改都在这里进行
│   ├── agents/            # 10 个 agent 定义（frontmatter + 正文）
│   ├── commands/          # 命令模板：budget/（start/status/goal）+ opsx/（apply/archive/explore/propose）
│   ├── docs/              # 架构图、OpenCode 安装说明、personas 指南、模型选择模板
│   ├── hooks/             # CodeBuddy 通知 hook
│   ├── lib/               # 管理面模块（基础层/生命周期/模型/状态/展示/通知六组）
│   ├── models/            # budget-models.json + budget-models.schema.json
│   ├── personas/          # personas.json（5 主题 × 11 角色键）
│   ├── platform/          # codebuddy.yaml / claudecode.yaml / opencode.yaml（构建映射 DSL）
│   ├── rules/             # 12 条规则（3 条 P0 + 8 条代码规范 + rtk）
│   ├── skills/            # budget-workflow、budget-notify、4 个 openspec skill
│   └── setup.sh           # budget setup 管理入口
├── dist/                  # 三平台构建产物 — 禁止手改（生成物，会被覆盖）
│   ├── codebuddy/
│   ├── claudecode/
│   └── opencode/
├── scripts/               # build.py（构建）、scan-brand.py（品牌门禁）、build-release.sh（打包）
├── tests/                 # 单元测试（unittest）
├── install.sh             # 三平台安装器
├── openspec/              # 变更管理（proposal/design/specs/tasks）
└── VERSION                # 当前版本号（0.1.0）
```

**铁律**：改 `core/`，不改 `dist/`。`dist/` 由 `scripts/build.py` 从 `core/` + `core/platform/*.yaml` 生成；手改产物会被下次构建覆盖，且 `--check` 会报源/产物不一致。

## 构建与门禁

每次内容修改后必须依次通过（提交前的硬性验收）：

```bash
python3 scripts/build.py --check          # 构建并校验（--strict 可将告警升级为失败）
python3 scripts/scan-brand.py             # 品牌合规门禁（见下节）
python3 -m unittest discover -s tests     # 全量单元测试
```

发布打包（仅维护者）：

```bash
bash scripts/build-release.sh             # check → 读 VERSION → zip + .sha256
```

## 开发流程

本仓库的所有变更走 **openspec 变更工作流**（本套件自举使用）：

1. **提案**：`/opsx:propose`（OpenCode 形态 `/opsx-propose`）创建变更（proposal/design/specs/tasks 落入 `openspec/changes/<change-id>/`）
2. **评审**：方案经双 reviewer（主审 + 辅审）评审通过后进入实施
3. **实施**：`/opsx:apply` 按任务清单逐项实施——**Leader 只编排不写代码**，所有代码修改必须通过分级 coder agent（coder-lite / coder-standard / coder-senior）执行；每个 coder 完成后经 tester 验证、reviewer 审查
4. **归档**：`/opsx:archive` 同步 specs 并归档变更记录

五阶段语义（方案设计 → 方案双审 → 分级实现 → 复审 → 归档）不可跳过；任务分派按任务标签（config_edit / api_endpoint / cross_module / security_related / docs_only 等）路由到对应 coder 级别，分派前查询 Coder Guard 降级记录。

## 品牌合规约束（P0）

- **所有产出零违禁词**：不得出现参照项目品牌词的任何形式（大小写不敏感，含前缀/后缀变体）。违禁词表的字面量定义仅存在于两处载体——`scripts/scan-brand.py` 与 `openspec/changes/foundation/design.md` §5 词表行——本文档不复制字面量，一律以「参照项目品牌词」指代。
- **扫描范围**：`core/`、`dist/`、`scripts/`、`install.sh`、`README.md`、`README_CN.md`、`CHANGELOG.md`（`tests/` 与 `openspec/` 在范围外，但 openspec 产物另有合规审计）。
- **验收**：`python3 scripts/scan-brand.py` 必须退出码 0；命中即阻断提交。
- **参照项目纪律**：参照项目一律称「参照项目」，引用其文件/组件时以 `*` 通配品牌词；参照项目根路径绝不写入任何仓库文件。

## 面向 AI 会话的行为约定

- 你在本仓库中的角色由当前工作流分派（Leader / architect / coder-* / reviewer / tester / recorder / director / goal-evaluator）；遵守对应 agent 定义与 P0 三规则（leader-no-code / coder-guard / 流程强制）
- 修改 `core/**` 后必须运行构建，确认三平台产物同步更新且无告警
- 修改文档（README/CHANGELOG 等）时注意它们在品牌门禁扫描范围内
- 输出语言以中文为主，代码/命令/路径保留英文
