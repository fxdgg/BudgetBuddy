# BudgetBuddy 架构说明

> 本文档描述 BudgetBuddy 的组件关系与数据流。工作流级（五阶段、角色协作）流程图见 README 的「架构」章节；本文聚焦构建链路与运行时组件。

## 总览

BudgetBuddy 的核心设计是**单一中立源 + 构建期平台适配**：所有内容只在 `core/` 维护一份，`scripts/build.py` 按 `core/platform/*.yaml` 声明的映射 DSL 生成三平台产物，安装器把产物落到各平台的约定位置。

```mermaid
flowchart LR
    subgraph SRC["core/（单一中立源）"]
        AGENTS["agents/*.md<br/>10 个 agent"]
        CMDS["commands/{budget,opsx}/*.md<br/>7 个命令"]
        SKILLS["skills/*/<br/>6 个 skill"]
        RULES["rules/*.md<br/>12 条规则"]
        HOOKS["hooks/*.py"]
        LIB["lib/<br/>24 个管理面模块"]
        MODELS["models/budget-models.json"]
        PERSONAS["personas/personas.json"]
        DOCS["docs/*<br/>含模板与说明"]
        DSL["platform/*.yaml<br/>映射 DSL"]
    end

    subgraph BUILD["scripts/"]
        BP["build.py<br/>YAML 解析 + schema 校验<br/>frontmatter 重写 + 变量替换<br/>routing 落位 + manifest"]
        SCAN["scan-brand.py<br/>品牌门禁"]
        REL["build-release.sh<br/>zip + sha256"]
    end

    subgraph DIST["dist/（构建产物，禁手改）"]
        DC["codebuddy/"]
        DCC["claudecode/"]
        DO["opencode/"]
    end

    INST["install.sh<br/>下载 + SHA256 校验<br/>增量同步 + 本地清单"]

    subgraph RT["运行时（用户侧）"]
        CB["CodeBuddy<br/>.codebuddy/ 或 ~/.codebuddy/"]
        CC["Claude Code<br/>.claude/ 或 ~/.claude/"]
        OC["OpenCode<br/>.opencode/ 或 ~/.config/opencode/"]
        MGMT["~/.budgetbuddy/<br/>管理面 + 数据"]
    end

    SRC --> BP
    BP -->|"原子替换"| DIST
    BP --> SCAN
    DIST --> REL
    REL -->|"release zip"| INST
    SRC -->|"本地仓库直装"| INST
    INST -->|"结构性文件"| CB
    INST -->|"结构性文件"| CC
    INST -->|"结构性文件"| OC
    INST -->|"管理面 + 数据目录"| MGMT
    CB -.->|"读取"| MGMT
    CC -.->|"读取"| MGMT
    OC -.->|"读取"| MGMT
```

## 构建链路

1. **解析**：`build.py` 用内置的最小 YAML 子集解析器读取 `core/platform/*.yaml`（无第三方依赖），并做 DSL schema 校验（缺 routing 键等即构建失败）
2. **转换**：按 DSL 逐文件转换——agent frontmatter 按平台 emit/drop 规则重写（权限三态映射为 CodeBuddy/Claude Code `permissionMode` 或 OpenCode `permission` map）；正文模板变量（`{{TASK_TOOL}}` 等六变量）按平台白名单精确替换
3. **渲染**：`docs/MODEL_SELECTION.template.md` + `budget-models.json` 按平台渲染出 `docs/MODEL_SELECTION.md`（占位符与六变量共用替换器但白名单独立）
4. **落位**：routing 规则决定每个源文件的目标路径（CodeBuddy/Claude Code 命令 `/budget:start`、OpenCode 命令 `/budget-start`；OpenCode 与 Claude Code 侧 12 条规则分别合并为单文件 `AGENTS.fragment.md`/`CLAUDE.fragment.md` 标记区块）
5. **清单**：写 `dist/<platform>/.manifest.json`（路径 → SHA256，按键排序、无时间戳），作为安装器增量同步与升级差集清理的依据
6. **原子性**：先构建到 `dist/<platform>.new/` 临时目录，全部成功后原子替换；失败保持原样

## lib 模块分组

```mermaid
flowchart TB
    SETUP["setup.sh<br/>子命令分发入口"]
    subgraph BASE["基础层（硬依赖）"]
        COLORS["colors.sh"]
        UTILS["utils.sh"]
        PLATFORM["platform.sh<br/>运行时平台探测"]
        SHELL["shell.sh"]
    end
    subgraph LIFE["生命周期"]
        INIT["init.sh<br/>数据目录/gitignore/hooks"]
        UPDATE["update.sh"]
        UNINSTALL["uninstall.sh"]
    end
    subgraph MODEL["模型与预设"]
        MODELS_SH["models.sh"]
        PRESET["preset.sh<br/>agent preset/custom/inherit"]
        RESOLVER["model_resolver.py"]
        RTK["rtk.sh"]
    end
    subgraph STATE["状态与护栏"]
        STATE_PY["budget-state.py<br/>状态机（单份，A4）"]
        GUARD["guard.sh<br/>Coder Guard"]
    end
    subgraph DISPLAY["交互与展示"]
        PERSONA["persona.sh + persona_expand.py"]
        VALIDATE["validate.sh"]
        DISPLAY_PY["display.py / banner.py<br/>run_summary.py"]
        INTERACTIVE["interactive.sh"]
        QUICKSTART["quickstart.py"]
    end
    subgraph NOTIFY["通知"]
        NOTIFY_SH["notify.sh"]
        HOOKS_SH["hooks.sh + hooks_inject.py<br/>settings.json 注入"]
    end

    SETUP --> BASE
    SETUP --> LIFE
    SETUP --> MODEL
    SETUP --> STATE
    SETUP --> DISPLAY
    SETUP --> NOTIFY
    STATE_PY -.->|"skill 文档经固定路径<br/>$HOME/.budgetbuddy/lib/ 引用"| SKILLREF["budget-workflow skill"]
```

- **基础层**：`platform.sh` 运行时五级探测（codebuddy 项目级 → codebuddy 全局 → claudecode 项目级 → claudecode 全局 → opencode 项目级优先/全局），均未命中显式报错
- **状态机单份化**：`budget-state.py` 仅 lib 一份，skill 文档以 `$HOME/.budgetbuddy/lib/budget-state.py` 固定路径引用（三平台落位后均成立）
- **hooks 注入**：仅 CodeBuddy；注入前备份 `settings.json.bak-budget`，临时文件 + 原子 rename 写入，同时负责 superpowers 插件启用检测

## 运行时数据流

```mermaid
flowchart LR
    subgraph WF["budget-workflow skill（Leader 会话）"]
        DISPATCH["任务分派<br/>router.md"]
        PHASES["五阶段执行<br/>phases.md / goal.md"]
    end
    GUARDJ["coder-guard.json<br/>~/.budgetbuddy/projects/&lt;name&gt;/memory/<br/>最近 5 次窗口"]
    STATEJ["goal-state.json / start-state.json<br/>.budget/ 或 ~/.budgetbuddy/<br/>current_step + 状态锁"]
    PERSONAJ["persona-active.json<br/>项目级 &gt; 全局级"]
    NOTIFYJ["notify.json<br/>项目级 &gt; 全局级（不合并）"]

    DISPATCH -->|"分派前查询降级"| GUARDJ
    PHASES -->|"写锚点/读锚点/状态锁"| STATEJ
    WF -->|"Step 0 硬门禁读取"| PERSONAJ
    PHASES -->|"budget notify 调用"| NOTIFYENG["notify.py"]
    NOTIFYJ --> NOTIFYENG
    NOTIFYENG -->|"四渠道 webhook<br/>任一成功即停/失败静默"| CHANNELS["企微 / 钉钉加签 / 飞书卡片 / 自定义"]
```

- **状态机防脱轨**：Leader 每次等待用户回复前写 `current_step` 锚点、收到回复后读锚点，禁止仅凭 context 记忆推断流程位置；Director 调用前强制检查状态锁防重复调用
- **Coder Guard 固定全局路径**：跨会话汇总降级判定（最近 5 次失败 ≥2 → lite→standard→senior 逐级改派）；项目级 memory/ 仅存项目态数据
- **配置双级降级**：persona 与 notify 配置均为「项目级存在即生效、否则降级全局级，不合并」
