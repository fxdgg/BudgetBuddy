# Acceptance: foundation — BudgetBuddy 全量首版（v0.1.0）T13 终验报告

> 验收时间：2026-10-18 22:55 CST
> git HEAD：`34bc7776d547063ba52373c9689f8021750fb531`（工作区干净，验收期间零源码改动）
> 验收人：tester（T13，test_only）
> 验收口径：设计文档 `docs/plans/2026-10-16-budgetbuddy-architecture-design.md` §11 七条，按 `design.md` §14 修正口径核验（commands×7、rules×12、通知四渠道、门禁扫描范围按 D §5）
> 验证环境：macOS（darwin）/ bash / python3 3.11；安装演练以临时目录 + 隔离 `HOME` 执行，不触碰真实用户环境；全部临时验证物用后已清理

## 一、逐条验收结果

### 标准 1：仓库结构（对照 design §16 文件清单逐文件核对）——✅ 通过（附 P2-1 清单偏差）

| 核对项 | 预期 | 实际 | 结果 |
|--------|------|------|------|
| core/agents | 10 | 10（architect/coder-lite/coder-standard/coder-senior/reviewer/reviewer-b/tester/recorder/director/goal-evaluator） | ✅ |
| core/skills | 6 目录 12 文件 | 6 目录 12 文件（budget-workflow 5：SKILL/router/phases/goal/reference；budget-notify 3：SKILL/notify.py/load-env.sh；openspec×4 各 1） | ✅ |
| core/commands | 7（budget 3 + opsx 4） | 7（budget: start/status/goal；opsx: apply/archive/explore/propose） | ✅ |
| core/rules | 12 | 12（3 P0 + 8 代码规范 + rtk） | ✅ |
| core/models | 2 | 2（budget-models.json + budget-models.schema.json） | ✅ |
| core/personas | 1 | 1（personas.json，5 主题 × 11 角色键） | ✅ |
| core/lib | 24 | **23（缺 rtk.sh，见 P2-1）** | ⚠️ |
| core/docs | 4 | 4（MODEL_SELECTION.template.md/PERSONAS.md/architecture.md/opencode-setup-notes.md） | ✅ |
| core/hooks | 1 | 1（budget-notify-hook.py） | ✅ |
| core/platform + setup.sh | 3 | 3（codebuddy.yaml/opencode.yaml/setup.sh） | ✅ |
| scripts/ | 3 | 3（build.py/scan-brand.py/build-release.sh） | ✅ |
| install.sh | 1 | 1 | ✅ |
| dist/ 双平台 | codebuddy 71 文件入清单 / opencode 60 | 71 / 60（含 .manifest.json 自身共 72 / 61 文件） | ✅ |
| 仓库文档 | README 双语/CHANGELOG/VERSION/LICENSE/CODEBUDDY/AGENTS | 全部存在；CODEBUDDY.md 与 AGENTS.md diff 逐字一致；VERSION=0.1.0 | ✅ |
| tests/ | design §16.3 列 8 | 实际 13（缺 test_guard.py 见 P2-2；多 6 个实现期增补测试，见 P3-2） | ⚠️ |

src 合计：实际 75 / design 76（唯一差异 `core/lib/rtk.sh`）。

### 标准 2：构建门禁链——✅ 通过

- `python3 scripts/build.py --check`：exit 0；`--strict` 复跑：exit 0。仅一条预期告警（opencode 平台 routing.hook 为空不分发 hooks，符合设计——OpenCode 无 hooks 机制）。
- 两次构建幂等比对：`dist/codebuddy/.manifest.json` 与 `dist/opencode/.manifest.json` 前后 diff 均为空（字节级一致）。
- `scan-brand.py`：扫描 223 个文本文件，0 违禁词，exit 0（`--check` 内嵌执行 + 独立复跑均通过）。

### 标准 3：双平台安装演练——✅ 通过

**CodeBuddy 项目级（临时目录，非交互 `BUDGET_PLATFORM=codebuddy BUDGET_GLOBAL=0`）**：
- 本地模式安装 exit 0，71 文件同步；断言：agents×10 / commands budget×3 + opsx×4 / skills×6（budget-workflow 5 文件 + budget-notify 3 文件 + openspec×4）/ rules×12 mdc / hooks（budget-notify-hook.py）/ lib×23 / setup.sh（可执行 -rwxr-xr-x）/ budget-models.json / personas.json / docs×3（MODEL_SELECTION/PERSONAS/architecture，opencode-setup-notes 按路由不分发）——全部符合。
- `budget setup show`：平台探测 codebuddy:project，10 agent 清单 + balanced 模型配置输出正常。
- `budget setup validate`：47 项检查全部通过（文件完整性 + JSON 数据校验 + hooks 注入状态）。
- hooks 注入：settings.json 三事件（Notification: permission_prompt + idle_prompt / PreToolUse: Bash / SubagentStop）+ superpowers 插件 `superpowers@codebuddy-plugins-official: true`，hook 命令带 `test -f` 守卫。
- 幂等重装：71 文件全部 skip、settings.json 字节级一致、hooks「幂等跳过，无重复注入」。

**OpenCode 全局（隔离 HOME，`BUDGET_PLATFORM=opencode BUDGET_GLOBAL=1`）**：
- 结构 29 文件（agent×10 + command×7 + skill×12）→ `~/.config/opencode/`；管理面 30 文件（lib×23 + setup.sh + models + personas + docs×4 含 setup-notes.md）→ `~/.budgetbuddy/`；exit 0。
- AGENTS.md 标记区块合并：预置用户内容完整保留 + `<!-- BudgetBuddy:begin/end -->` 外层标记 + 12 个二级 `budget-*:begin/end` 标记区块。
- 幂等重装：结构 29 / 管理面 30 全部 skip；AGENTS.md sha256 字节级一致（区块数保持 12，无重复注入）；清单外用户文件（user-custom.md / user-keep.txt）保留且未被改动。

**uninstall → reinstall 链路（P1 修复后语义验证）**：
- `uninstall --yes`：settings.json 注入项移除后为空 → 文件删除（**零残留**，含备份文件）；79 个本套件文件删除 + 空目录清理；清单外 user-extra.md 保留；用户数据目录（.budget/ 与 ~/.budgetbuddy/）保留；budget 包装器移除。
- reinstall：71 文件恢复 + hooks 三事件 + superpowers 全部恢复；清单外文件仍在。

### 标准 4：测试全量——✅ 通过

`env -u BASH_ENV -u CODEBUDDY_SESSION_ID python3 -m unittest discover -s tests`：**Ran 622 tests in 61.372s — OK**（622/622 全绿，exit 0）。

### 标准 5：notify 四渠道 mock 演练——✅ 通过

- `tests.test_notify` 全量：61 个测试通过（四渠道 payload 构造：企微 markdown / 钉钉 markdown+HMAC-SHA256 签名 URL / 飞书 interactive 卡片 / custom raw POST；双级配置降级、load-env 导出集、secret 掩码、任一成功即停、全失败静默 exit 0、5s 超时、webhook scheme 白名单、hooks 三事件）。
- 端到端 N11 演练（mock custom 渠道，本机回环 HTTP 接收器）：`budget notify "<N11 消息>" N11` exit 0；接收 payload 为 raw text/plain，消息体含 `[budget]` 前缀、**项目名**（`$(basename "$PWD")` 实际解析为演练目录名）与**详情/统计字段**——与 goal.md N11 模板一致。
- 通知点 N1-N11 人工审计：11 个节点全部有调用示例（`budget notify "$MSG" Nx || true`）与消息模板（N1-N4/N7-N10 于 phases.md，N5/N6 于 router.md 与 goal.md，N11 于 goal.md；SKILL.md 含 N1-N11 全表与落位指引）。

### 标准 6：setup.sh 核心子命令冒烟——✅ 通过

临时安装中：`agent preset economic`（模型切换生效）→ `agent preset balanced`（还原）→ `persona list`（5 主题）→ `persona set sanguo`（11 角色映射写入）→ `init --yes`（数据目录初始化）→ `show` / `validate`（标准 3 已验）——全部通过。

### 标准 7：release 打包——✅ 通过

`bash scripts/build-release.sh`：门禁（--check --strict）通过 → `budgetbuddy-0.1.0.zip`（541499 字节，163 条目：dist/ + VERSION）+ `.sha256` 生成 → `shasum -c` 校验 **OK** → 产物已清理（release 产物不提交 git，工作区保持干净）。

### 附加审计项（tasks 5.1 要求）

- **P0 三条规则人工逐条抽查**：`core/rules/budget-{leader-no-code,coder-guard,workflow-enforcement}.md` 与 SKILL.md「强制执行规则（P0）」内联章节**逐字一致**（机器 diff 无告警 + 人工比对确认）；OpenCode 侧 AGENTS.fragment.md 含 12 个二级标记区块（安装演练实证）。
- **工作流机制完备性**（P §11 第 7 条）：5 阶段（方案设计/方案双审/分级实现/复审/收尾归档）✓、Coder Guard 联动（router.md 13 处引用 + 5 次窗口失败 ≥2 降级语义）✓、Review Gate（Phase 2 评审门，最多 3 轮）✓、3 轮失败应急 + 循环上限 6 次（3 轮分级 review + 2 次 tester 自修复 + 1 次 Director 终裁）✓、Director 6 类裁决表 ✓、N1-N11 通知点齐全 ✓。
- **bash -n 语法冒烟**：19 个 shell 脚本全部通过（core/lib/*.sh×15 + core/setup.sh + core/skills/budget-notify/load-env.sh + install.sh + scripts/build-release.sh）。
- **行为类 Scenario**（router 分级评估、DSL 单一消费者、README 宣传口径）：按 specs 标注为人工审计项，不作为自动化用例；本次以结构审计 + 文档核对覆盖。

## 二、问题列表

| # | 级别 | 问题 | 影响 | 建议 |
|---|------|------|------|------|
| P2-1 | P2 | `core/lib/rtk.sh` 缺失：design §8.2/§16.1 与 tasks 3.4（T10a）均要求 lib 24 文件含 rtk.sh，specs/setup-cli「lib 24 文件模块化」为【MUST】；实际 23 文件，且该文件从未进入 git 历史 | 功能影响为零（setup.sh 将 rtk.sh 列为可选模块，缺失时静默跳过；无子命令分发依赖；uninstall 清单含该文件名但 rm -f 不报错；README 未宣传）；属 spec/design 文件清单符合性偏差，reviewer 审计基准（§16）与实现不一致 | 补齐 rtk.sh（RTK 工具通用适配说明），或走变更流程修订 design §8.2/§16.1 与 specs/setup-cli 的 24 文件口径为 23 |
| P2-2 | P2 | `tests/test_guard.py` 缺失：design §16.3 与 tasks 3.5（T10b）要求 guard 单测（记录追加、窗口滚动、降级判定、边界「最近 5 次恰 2 次失败」）；实际 tests/ 无任何 guard 测试覆盖（grep 零命中），T10b 验收标准「单测全部通过」中该文件从未存在 | Coder Guard 降级判定（A14 核心语义：5 次窗口失败 ≥2 降级）无自动化测试兜底；guard.sh 功能本身存在且 do_status 有汇总实现 | 补写 tests/test_guard.py 覆盖窗口滚动与降级边界；或修订 design §16.3 清单 |
| P3-1 | P3 | hooks 注入成功提示「备份: settings.json.bak-budget」为固定文案：全新安装场景（settings.json 原不存在）hooks_inject.py 按设计跳过备份，但提示行仍输出备份路径 | 仅提示口径与实际行为不同步（行为符合设计：无可备份内容即不生成备份文件）；可能误导用户以为存在恢复点 | hooks.sh 按注入引擎返回的实际备份状态输出提示 |
| P3-2 | P3 | tests/ 实际 13 个测试文件 vs design §16.3 列 8 个：多出的 6 个（test_hooks_inject/test_init/test_persona/test_quickstart/test_update/test_validate）为实现期增补 | 测试增强非缺陷，但 §16.3 文件清单未同步，审计基准漂移 | 归档前同步 design §16.3 清单（连同 P2-2 一并处理） |

## 三、遗留事项

1. **在线安装模式未对真实远端演练**（Q1）：`BUDGET_REPO_URL` 当前为 GitHub raw 占位地址（仓库未推送远端），在线模式（curl|bash → releases/latest 版本发现 → zip 下载 → SHA256 强制校验链路）无法端到端验证；本次以**本地模式**（仓库 dist 直接消费）完成安装全链路演练。推送远端后须修正 install.sh 顶部地址并复跑门禁与在线安装验证。
2. **opencode 三档预设 provider/model ID 待核对**（Q2）：budget-models.json `_meta` 已标注待确认项，上线发布前必须清零（阻塞上线，不阻塞本次验收）。
3. **release 产物**：zip + .sha256 已生成并校验通过，按「release 产物不入 git」约定验证后清理；正式发布时由维护者重跑 `scripts/build-release.sh` 上传托管方。
4. **P2-1/P2-2/P3-2 的清单同步**：建议在归档（/opsx:archive）前由 coder 补齐或以变更流程修订清单口径，保持 specs/design/实现三者一致。

## 四、结论

**【验收通过】**

P §11 七条验收标准（按 D §14 修正口径：commands×7、rules×12、四渠道、扫描范围按 D §5）全部通过：构建门禁链干净且幂等、双平台安装/幂等/卸载重装链路全绿、622 项测试全绿、notify 四渠道 mock + N11 端到端通过、19 个 shell 脚本语法冒烟通过、release 打包校验链路通过、N1-N11 与 P0 人工审计通过。发现的问题均为清单符合性/提示口径类（P2×2 + P3×2），不影响七条验收标准与核心功能，已列入问题清单建议归档前处理。
