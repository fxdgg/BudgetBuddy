# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
