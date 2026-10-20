# 任务清单：add-claudecode-platform

> 任务分派路由（P0 三规则）：docs_only → coder-lite；config_edit/api_endpoint → coder-standard；cross_module/新机制 → coder-senior。每任务完成后经 tester 验证、reviewer 审查。

## 1. build.py 平台泛化（纯重构，先于一切 claudecode 内容）

- [x] 1.1 【coder-senior | cross_module】泛化 `_MODEL_PLATFORMS`：模型条目 platform 校验值改为由 `models.json platforms` 键集推导（数据内自洽），移除硬编码枚举；同步 `validate_models_data` 的 `for platform in ('codebuddy','opencode')` 循环为 `data['platforms']` 键遍历（含每键三档 presets 校验）；新增双清单一致性校验：`core/platform/*.yaml` 集合 == `platforms` 键集（双向不一致显式报错）
- [x] 1.2 【coder-senior | cross_module】`_validate_preset_value` 改为「默认 catalog_id、opencode 特判 provider/model」：除 opencode 外平台零代码走默认策略（claudecode 即默认分支，无需新增映射条目）
- [x] 1.3 【coder-standard | config_edit】平台说明数据驱动（含常量回退）：`_PLATFORM_NOTE_LINES` 常量改为读 `platforms.<p>.note`/`unconfirmed_ids`，**`note` 缺失时常量回退现有文案（本任务不迁移数据、不改 models.json，保证 1.5 hash 回归成立；文案初值迁移在 2.2）**；opencode 兼容读 `_meta.unconfirmed_opencode_ids` 旧键一个版本；`_render_preset_table` 表头按 `platforms` 键序循环
- [x] 1.4 【coder-standard | config_edit】CLI 平台清单动态化：`parse_args` choices 与 `main` 平台列表改为 glob `core/platform/*.yaml` 枚举；未知 `--platform` 值报错并列出可用平台
- [x] 1.5 【tester】泛化回归验证：泛化完成（未加 claudecode.yaml）后连续两次构建，dist/codebuddy 与 dist/opencode 的 `.manifest.json` 与泛化前逐字节一致（D1 hash 回归）；`python3 -m unittest discover -s tests` 全绿

## 2. claudecode DSL 与构建产物

- [x] 2.1 【coder-standard | config_edit】新增 `core/platform/claudecode.yaml`：按 design.md D2 完整映射（routing/agent_frontmatter camelCase emit/permission_mode_rule acceptEdits+plan/command_frontmatter 仅 description+argument-hint/invoke `/{group}:{name}`/body_variables 六值（TASK_TOOL=Task）/extra_outputs CLAUDE.fragment.md/hook 空串/docs 映射）
- [x] 2.2 【coder-standard | config_edit】`core/models/budget-models.json` 数据扩展（**前置于 2.3——产物 model 烘焙依赖本数据**）：`platforms.claudecode` 三档十角色预设（economic→haiku 系/balanced→sonnet 系/quality→opus 系，值 = models.paid.claude 完整 ID）、claude 组条目 platform 数组加 `claudecode`、`platforms.claudecode.note`（含现有双平台 note 文案迁移初值）与 `unconfirmed_ids` 初值（盘点未本机核对 ID）、`_meta.unconfirmed_opencode_ids` 迁移至 `platforms.opencode.unconfirmed_ids`；`budget-models.schema.json` 同步（platform 枚举/可选键）
- [x] 2.3 【coder-senior | cross_module】构建管线适配验证（依赖 2.1+2.2）：`--platform claudecode` 构建产出 dist/claudecode/（agents×10 camelCase frontmatter 含 balanced 烘焙 model、commands×7 `commands/{group}/{name}.md`、skills×6、CLAUDE.fragment.md、lib/models/personas/setup/docs、.manifest.json）；hooks 空串走既有告警路径不失败；确认 emit/EMIT_EXPRESSIONS/`_TOOL_PASCAL`/`compute_permission_mode` 零改动即通过（如有阻塞如实上报，不擅自扩 DSL）
- [x] 2.4 【tester】三平台构建验证：全量构建产物结构/manifest 完备性比对（agents×10 + commands×7 + skills×6 + fragment + 管理面）；`build.py --check` + `scan-brand.py` 退出码 0（验证 dist/claudecode 自动入扫描范围，若扫描路径硬编码双平台需上报扩展）；MODEL_SELECTION.md 三平台表列与「待确认」清单渲染正确
- [x] 2.5 【coder-standard | docs_only】`scripts/build-release.sh` 验证：zip 自动含 dist/claudecode/（manifest 驱动应零改动，实际验证并记录结论）

## 3. 安装器 claudecode 分支

- [x] 3.1 【coder-senior | cross_module】install.sh 新增 `install_claudecode`：项目级 `.claude/` / 全局 `~/.claude/` 落点（agents/commands/skills + CLAUDE.fragment.md 合并）、CLAUDE.md 幂等合并（复用 merge_agents_md：项目根 CLAUDE.md / `~/.claude/CLAUDE.md`，标记区块 + 备份 + 原子写）、本地清单 mode `claudecode`（**合并写**：files 管理面幂等覆盖 + platform_files 按平台命名空间合并保留其他平台条目，is_struct 区分复数目录前缀 agents/commands/skills）、管理面统一 `~/.budgetbuddy/`
- [x] 3.2 【coder-standard | config_edit】平台选择扩展：交互菜单四选项（CodeBuddy/OpenCode/Claude Code/全部）、`BUDGET_PLATFORM` 增值 `claudecode` 与 `all`（`both` 语义保持不变并在帮助文本标注 `all` 推荐）、main 分派与 print_summary 提示（`Claude Code 会话内输入 /budget:start 启动工作流`）
- [x] 3.3 【tester】安装器验证：空目录项目级安装（.claude/ 结构 + CLAUDE.md 标记区块 + `budget setup show` 可执行）、全局安装（~/.claude/ 落点）、`BUDGET_PLATFORM=claudecode` 非交互、幂等重装（CLAUDE.md 无重复追加、区块外内容不变）、`all` 三平台依次安装且管理面仅一份、**opencode+claudecode 双装后卸载其一**（另一平台 platform_files 记录与管理面完好）、升级差集清理按本平台段、卸载清理 CLAUDE.md 标记区块（区块外内容保留）

## 4. 运行时管理面兼容

- [x] 4.1 【coder-senior | cross_module】`core/lib/platform.sh` 探测扩展：③ 向上 `.claude/agents/`（本套件 agent）→ claudecode:project；④ `~/.claude/agents/` → claudecode:global；`BUDGET_PLATFORM=claudecode` 显式分支；探测序 codebuddy > claudecode > opencode；报错文案补 .claude 两级检测位置
- [x] 4.2 【coder-senior | cross_module】管理面兼容改造（改动面按 design D5 明示清单）：`platform.sh` 之外的四个文件——`model_resolver.py`（--platform choices 动态化、claudecode 走 catalog_id 默认策略）、`notify.sh`（`_budget_locate_notify_py` 补 claudecode:project/global 两分支，hooks 降级但 notify CLI 必须可用）、`quickstart.py`（探测补 claudecode 两级、「双平台」文案三平台化）、`models.sh`（unconfirmed 新位置读取兼容 + 平台计数文案 + 短标 map 补 claudecode）；并审计 `preset.sh`/`init.sh`/`uninstall.sh`/`validate.sh` 平台分支与 frontmatter 键名假设，为 claudecode 形态补齐（`agent preset|custom|inherit|show|diff` 读写 camelCase 键结构、hooks 注入跳过、uninstall CLAUDE.md 区块清理 + `claudecode:` 前缀段清单清理）；复审追加：uninstall 识别 claudecode 形态（现仅读 files 段、claudecode 结构靠枚举兜底——补形态感知）；install.sh 共装跳过 guard 的对称性（opencode 分支同 guard，复审发现 3，防管理面子集不变量破坏时误删）
- [x] 4.3 【tester】管理面验证：claudecode 项目级/全局探测命中与报错路径、`agent preset quality` 重写 model 且 camelCase 键无损、`agent custom` 别名解析、`setup show/validate/uninstall`（CLAUDE.md 区块清理、双装场景另一平台不受影响）、**`budget notify` 在 claudecode 形态下定位 notify.py 成功**、**`budget setup quickstart` 探测为 claudecode 且指引 `/budget:start`**、coder-guard 路径不变
- [x] 4.4 【coder-lite | docs_only】`core/docs/` 文档补充：architecture.md 三平台图支路、MODEL_SELECTION.template.md 平台说明段核对（占位符零改动验证）、CODEBUDDY.md/AGENTS.md 双入口说明扩展三平台口径（同步更新两份）

## 5. 文档、测试与门禁收尾

- [x] 5.1 【coder-lite | docs_only】README.md/README_CN.md：三平台定位、快速开始（含 Claude Code 安装与 `/budget:start` 入口、hooks 通知缺失声明）、预设表三平台列、目录结构 dist/claudecode、开发指南多平台构建口径（双语对等）
- [x] 5.2 【coder-standard | api_endpoint】tests 扩展：test_build 三平台（claudecode DSL 解析/camelCase emit/CLAUDE.fragment.md 合并/平台数据驱动用例：platform 键集自洽校验、未知 --platform 报错）、泛化 hash 回归用例、preset 三平台 frontmatter 快照、test_install claudecode 分支用例（复审 C1 必须覆盖三组断言：write_local_manifest 合并写——opencode 无前缀/claudecode: 前缀/files 磁盘存在性过滤、upgrade_diff_cleanup 命名空间 old_field 解析、共装跳过策略 local_manifest_other_platform）
- [x] 5.3 【tester】全量门禁终验：`python3 scripts/build.py --check` + `python3 scripts/scan-brand.py` + `python3 -m unittest discover -s tests` 三命令退出码 0；本机 Claude Code 环境核对 unconfirmed 清单（能核对的清零、不能的如实记录）；确认 claudecode 产物 tools 列表形态被 Claude Code 正确解析（`claude --debug` 或 `/doctor` 报告无字段告警）
- [x] 5.4 【recorder | docs_only】CHANGELOG.md 增 Unreleased 段条目（三平台支持、hooks 降级说明；版本号 bump 决策留归档时定）、知识沉淀与归档准备（`openspec validate` 通过）
