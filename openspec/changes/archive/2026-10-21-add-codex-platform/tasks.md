# 任务清单：add-codex-platform

> 任务分派路由（P0 三规则）：每任务完成后经 tester 验证、reviewer 审查。

## 1. build.py rules_index kind + codex DSL 与数据

- [x] 1.1 【coder-senior | cross_module】build.py 新增 `extra_outputs` kind `rules_index`：source `<目录>/**` → dest 轻量索引 fragment（markers + 按需读取指引 + 一行式规则清单，< 1KiB）+ 可选 `copy_dest` 全文副本目录（单次遍历双输出）；kind 枚举扩展 + validate_dsl 校验（dest 与 routing.rule 一致、copy_dest 防逃逸）；**`_has_agents_fragment` 扩展为 fragment 类 kind 统一判定（agents_fragment|rules_index 均抑制 `_build_rules` 逐文件落位，防止 12 条规则覆盖写 fragment）+ 三平台回归断言**；未知 kind 报错文案更新
- [x] 1.2 【coder-standard | config_edit】新增 `core/platform/codex.yaml`（design D1 全文：agent 素材落位/emit 仅 name+description/commands 并入 skill/rule=AGENTS.fragment.md/hook 空串/docs 含 codex-runtime.md 分发/extra_outputs rules_index 含 copy_dest/body_variables 六值 TASK_TOOL=spawn_agent）；**codebuddy/claudecode/opencode 三份 YAML 同批加 `codex-runtime.md: null` docs 声明**（`_build_docs` 全平台声明要求）
- [x] 1.3 【coder-standard | config_edit】`core/docs/codex-runtime.md` 撰写（design D6 契约：开头「优先级高于 SKILL.md 调用格式块」声明、spawn_agent 调用模板/prompt 组装七要素/三档查表指引 coder-lite→luna、coder-standard→terra、coder-senior→sol/max_depth 与 max_threads 约束/并行规则；**原创行文 + scan-brand 自检零违禁词**）；**core/skills/budget-workflow/SKILL.md 规则 1 调用格式块处追加 Codex 平台注记一行**；models.json `platforms.codex` 三档 + gpt 组三别名条目（platform 仅 codex + note 部署映射前提与永久标注偏离声明）+ unconfirmed 三别名 + note；schema 同步
- [x] 1.4 【tester】构建验证：四平台构建（dist/codex 结构清点：**6 个 skill**（budget-workflow 含 SKILL.md/agents×10/commands×7/rules×12/codex-runtime.md + budget-notify 等 5 个）、AGENTS.fragment.md < 1KiB、管理面）；agent 素材 frontmatter 仅 name/description；{{TASK_TOOL}}→spawn_agent 替换零残留；**三平台回归采用预期变化白名单（dist 三平台仅 budget-models.json、MODEL_SELECTION.md 与 SKILL.md 注记行允许变化，其余产物逐字节一致）**；rules_index 未知 kind 报错；门禁三命令

## 2. 安装器 codex 分支

- [x] 2.1 【coder-senior | cross_module】install.sh `install_codex`：.codex/skills/（项目）或 ~/.codex/skills/（全局）落点、AGENTS.md 轻量区块合并（项目根/ ~/.codex/AGENTS.md，目录不存在创建；**既有区块为 opencode 全文形态时告警**）、config.toml `[features] multi_agent = true` 幂等注入（文本级四态：含键跳过/显式 false 尊重+告警/段缺键段内追加/无段文末追加；段头行首精确匹配；备份 + 原子写）、本地清单 mode codex（codex: 前缀合并写、结构前缀 skills/）、管理面 ~/.budgetbuddy/、BUDGET_PLATFORM=codex 与 all 四平台分派、交互菜单五选项
- [x] 2.2 【coder-senior | cross_module】卸载与校验：uninstall.sh codex 形态（config.toml multi_agent 键清理段空删段、AGENTS.md 区块清理、skill 目录与清单本平台段删除、共装 guard 对称）；validate.sh codex 形态（skill 结构 + AGENTS 区块 + config multi_agent 检查项）
- [x] 2.3 【tester】安装闭环验证：项目级/全局安装（skill 落点 + AGENTS 区块 + config 注入 + 备份）；幂等重装（config 单键、区块唯一）；与 opencode/claudecode 双装共存（清单段并存、卸载其一互不破坏）；卸载（config 键/区块/skill 清理、用户 TOML 零触碰）；codebuddy/opencode/claudecode 回归；注入后 `codex --help` 冒烟（TOML 未损坏）

## 3. 运行时管理面兼容

- [x] 3.1 【coder-senior | cross_module】platform.sh 探测扩展（⑤⑥ codex 两级 + BUDGET_PLATFORM=codex 显式 + 报错文案补 .codex 两级）；preset.sh/model_resolver codex 形态降级（preset/custom/inherit 提示 + show 三档表）；notify.sh（`.codex/skills/budget-notify/` 两分支）；quickstart.py（探测 + 四平台文案）；models.sh（平台计数四平台）；init.sh（codex 管理面数据落位 + hooks 跳过）
- [x] 3.2 【tester】管理面验证：codex 探测两级与报错路径；preset 降级提示（exit 0 无文件修改）；show/models/notify/validate/uninstall codex 形态；三平台回归抽查
- [x] 3.3 【coder-lite | docs_only】文档四平台口径：README 双语（定位/快速开始含 multi_agent 前提与别名映射说明/预设表 codex 列/通知 Codex 不支持/hooks 说明/目录结构）；CODEBUDDY.md+AGENTS.md（四平台入口说明 + dist/codex）；architecture.md；CHANGELOG Unreleased；**全部文档 scan-brand 自检零违禁词**

## 4. 端到端验证与测试

- [x] 4.1 【coder-standard | test_only】tests 扩展：rules_index kind 用例（双输出/未知 kind 报错/轻量断言/`_build_rules` 抑制回归）、codex DSL 解析与产物用例（素材 frontmatter/索引/变量替换）、installer codex 用例（config 注入四态/区块幂等/异形态告警/清单段）、platform 探测用例、preset 降级用例
- [x] 4.2 【tester】本机端到端（codex-cli 0.163.0）：/tmp 沙盒 install_codex → config multi_agent 生效核验（`codex` 会话/CLI 确认 spawn 工具可用性——不可用则如实记录前置条件并更新文档口径）→ codex 会话内以自然语言触发 budget-workflow skill（或 `codex exec` 派发 coder-lite spawn 实测）→ AGENTS.md 轻量区块核验
- [x] 4.3 【tester】全量门禁终验：三命令退出码 0 + 构建幂等 + 全部 delta spec 场景核对（不可验证项如实记录依赖条件）

## 5. 归档

- [x] 5.1 【recorder | docs_only】CHANGELOG 版本落位（0.3.0 minor）+ 归档准备；Leader 执行归档
