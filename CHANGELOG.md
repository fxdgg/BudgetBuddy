# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-20

### Added

- **Claude Code platform support** — third platform built from the same neutral source: `core/platform/claudecode.yaml` mapping DSL, `dist/claudecode/` artifacts (`.claude/` layout with agents/commands/skills, `CLAUDE.fragment.md` rules fragment merged into CLAUDE.md marked block), `/budget:start` entry point, camelCase agent frontmatter (`permissionMode` / `maxTurns`), three presets per role (economic→haiku / balanced→sonnet / quality→opus series)
- **Data-driven platform list in build.py** — platform enumeration derived from `core/platform/*.yaml` glob plus consistency check against `budget-models.json` `platforms` key set (bidirectional mismatch fails the build); future platforms require zero converter code

### Changed

- **Installer platform selection** — interactive menu now offers four choices (CodeBuddy / OpenCode / Claude Code / All); `BUDGET_PLATFORM=claudecode|all` supported in non-interactive mode; local install manifest writes `platform_files` with per-platform namespacing (merged write keeps other platforms' entries, multi-platform co-install into `~/.budgetbuddy/` is non-destructive)
- **Runtime management plane** — `platform.sh` five-level detection (`.claude/agents/` project and global levels added, explicit `BUDGET_PLATFORM=claudecode` branch); notify / quickstart / models / preset / uninstall / validate subcommands claudecode-aware
- **Claude Code preset model IDs switched to the 5.5 series** — economic→`claude-haiku-5-5`, balanced→`claude-sonnet-5-5`, quality→`claude-opus-5-5` (old 4.5/4.6/4.8-1m IDs retired or unrecognized on the CLI); all three verified in a real Claude Code 2.1.304 environment on 2026-10-20 (zero warnings, `platforms.claudecode.unconfirmed_ids` cleared)

### Known Limitations

- Claude Code hooks notifications not shipped in this release (`budget notify` CLI remains available); adaptation deferred to a future change

### Tests

- 637 → 676 test cases (+39: build / preset / installer / platform claudecode coverage)

## [0.1.0] - 2026-10-18

First full release.

### Added

- **Dual-platform support** — one neutral source (`core/`) built by `scripts/build.py` into `dist/codebuddy/` and `dist/opencode/`; platform mapping declared in `core/platform/*.yaml` (frontmatter rewrite, body variable substitution, routing, manifest generation)
- **10 specialized sub-agents** — architect, coder-lite / coder-standard / coder-senior, reviewer + reviewer-b (dual review), tester, recorder, director (final verdict), goal-evaluator; per-role model assignment and three-state permissions
- **Five-phase workflow** — proposal & design → dual design review → tiered implementation (per-task coder → tester → reviewer loop) → final review & regression → archive; enforced P0 rules (leader-no-code, coder-guard, workflow enforcement)
- **Tiered routing & escalation** — task-tag based dispatch (lite/standard/senior), Review Gate escalation (max 3 rounds), task loop cap (5 rounds), Director 6-class final verdict
- **Coder Guard** — per-coder, per-tag failure records over a 5-attempt window; 2+ failures force tier downgrade
- **Goal Loop** — goal-driven macro loop with Phase 0 (goal definition) and Phase 6 (goal verification), max 8 iterations, safety boundaries, N11 achievement notification
- **Model catalog & presets** — `core/models/budget-models.json` with paid/free model entries, aliases, role recommendations and three presets per platform (`economic` / `balanced` / `quality`); build-time rendered `MODEL_SELECTION.md`
- **Personas** — 5 themes (default, tech-legends, sanguo, shuihu, genshin) covering 11 role keys; `budget setup persona` management
- **Notifications** — universal webhook skill with four channels (WeCom bot, DingTalk bot with HMAC-SHA256 signing, Feishu bot card, custom raw), 11 event switches (N1–N11), dual-level config lookup, silent failure; CodeBuddy hooks (Notification / PreToolUse / SubagentStop) with backup + atomic injection
- **OpenSpec integration** — 4 skills (propose / apply / archive / explore) and 7 slash commands (`/budget:start|goal|status`, `/opsx:propose|apply|archive|explore`)
- **Management plane** — `budget setup` CLI with 16 subcommands (init, show, agent, persona, validate, diff, stats, update, reinstall, uninstall, guard, quickstart, models, notify, status, help); runtime platform detection; state machine (`budget-state.py`); Superpowers plugin auto-enable
- **Installer** — `install.sh` with interactive/non-interactive modes, release version discovery, mandatory SHA256 verification, incremental manifest sync, local install manifest for upgrade diff-cleanup and offline uninstall, AGENTS.md marked-block merge
- **Build & gates** — `scripts/build.py` (atomic build, schema validation, `--check` / `--strict`), `scripts/scan-brand.py` (forbidden-term gate), `scripts/build-release.sh` (zip + sha256 packaging)
- **Tests** — unit suites for build, brand gate, installer, notify, platform detection, presets, state machine, guard
- **Docs** — bilingual README (EN/CN), architecture diagrams (Mermaid), OpenCode setup notes, personas guide, model selection template

[0.1.0]: https://github.com/fxdgg/BudgetBuddy/releases/tag/v0.1.0
