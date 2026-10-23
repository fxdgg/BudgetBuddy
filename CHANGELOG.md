# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Installer: OpenCode default & mainland-China mirror chain** — the platform menu now lists OpenCode first and defaults to it in all three paths (interactive empty input, no-TTY fallback, non-interactive initial value); the `all` path installs OpenCode first; online installs fall back automatically from a direct GitHub connection through `ghfast.top` and `gh-proxy.com` (ghproxy-style third-party transport — level failure covers both network errors and redirect-semantics loss, i.e. a mirror that self-follows the `releases/latest` redirect is skipped); `BUDGET_MIRROR` pins a single mirror or disables third-party channels (`none` / `off` / `direct`); `BUDGET_VERSION` remains the escape hatch (straight to `releases/download/<tag>`, no redirect segment); the zip and its `.sha256` are always fetched as a pair from one mirror with SHA256 verification unchanged; custom `BUDGET_REPO_URL` sources (non-`github.com` hosts) never get the mirror chain layered on; `install.sh` gains a source-safe main guard (`if [[ "${BASH_SOURCE[0]:-$0}" == "$0" ]]`, pipe-entry `set -u` safe); bilingual README documents the mirror section

## [0.5.0] - 2026-10-23

### Added

- **Coder Guard memory freshness & confidence labels** — the guard memory (per-coder, per-tag failure records driving tier downgrade) now surfaces *how trustworthy the records are* alongside the downgrade verdict: new `core/lib/guard_metrics.py` (stdlib only, import + CLI dual form) computes exponentially time-decayed weights `0.5^(age/half-life)` (default 30-day half-life, `BUDGET_GUARD_HALF_LIFE_DAYS` override), effective sample size `n_eff`, a confidence tier (low < 2 / medium < 4 / high ≥ 4), and a stale flag (newest record older than 90 days, `BUDGET_GUARD_STALE_DAYS` override — the two thresholds are independent); surfaced on four read surfaces from one implementation source: `budget setup guard query` (freshness block + "records stale / insufficient sample, downgrade advice is reference-only" hint when `n_eff` < 2 or stale), `guard summary` (reused by the top-level `budget status` chain — notify.sh untouched), `budget setup stats`, and run summaries; the hard downgrade rule (≥2 failures in the last 5 attempts) is deliberately untouched — decay only informs, never weakens the gate; two-layer fault tolerance (guard.sh subprocess failure → skip the freshness block and return the main output; display/run_summary delayed import → omit the section, exit 0); unparseable timestamps weigh 0 and never affect staleness
- **Post-task quality metrics & trend alerts (continuous agent evaluation)** — reviewer / reviewer-b reports now end with a machine-parsable `<!-- budget-verdict: {...} -->` marker (rating A/B/C/D + conclusion + review round; Phase 2 rounds 1–3, Phase 4 final review round 0; Phase 3 per-task reviews deliberately excluded to avoid aggregation pollution); at archive time the recorder runs `core/lib/metrics.py record` **before** `openspec archive` (archive moves the change directory — recording afterwards would scan an empty path), aggregating phase-2 rating/rounds, reviewer-b conclusion, final rating, and a guard snapshot (history-scoped failure / total / downgrade counts — not the summary buckets, which double-count multi-tag entries) into `~/.budgetbuddy/projects/<name>/memory/metrics.json` (idempotent per change_id, atomic 0600 write, manual CLI fallback when markers are missing); same-round multi-file markers resolve by lexicographic file-path tie-breaker; marker extraction is whole-line-anchored so inline format examples inside documents are never mis-extracted; `budget setup stats` and run summaries render a "quality trend" section (rating sequence, first-pass rate, guard failure rate) with three alert rules — R1 strictly-declining ratings (null interrupts the sequence), R2 first-pass rate < 50% (zero denominator never alerts), R3 guard failure rate > 40% (latest snapshot, sample ≥ 5); alerts are query-surface-only reference — no N-event notifications fire, guard writes and downgrade rules untouched; delayed-import fault tolerance identical to the guard integration

### Fixed

- **Step 5 final-review prompt alignment** — the final-review prompt now requests the three-value verdict (通过 / 需修改 / 升级人工) matching the reviewer output format, plus the A/B/C/D rating and the round-0 verdict marker; the report lands in the change directory as `final-review.md`

### Tests

- 858 → 936 test cases (+78: 34 guard-metrics including cross-surface numeric consistency and fault-tolerance suites; 44 quality-metrics including marker-extraction edge cases, idempotent recording, alert-rule boundaries, and display/run_summary integration; lib module-count assertions updated 27 → 28)

## [0.4.0] - 2026-10-21

### Added

- **Codex platform support (fourth platform)** — built from the same neutral source: `core/platform/codex.yaml` mapping DSL emitting `dist/codex/` as a **skill-directory form** (`skills/budget-workflow/` with SKILL.md + reference docs + agents/commands material + full rules + `codex-runtime.md` dispatch contract; no Codex sub-agent TOML definitions — agent files become skill material emitting only name/description metadata, model resolved by the Leader at spawn time); new `rules_index` `extra_outputs` kind generates the lightweight `AGENTS.fragment.md` rules index (markers + on-demand reading guidance + rule list, well under 1 KiB to stay below the Codex AGENTS.md 32 KiB doc limit — full rule text lands inside the skill and is read on demand); `install_codex` in `install.sh` lands the skill directory under `.codex/skills/` (project) or `~/.codex/skills/` (global), idempotently merges the AGENTS.md lightweight block (existing OpenCode full-form block triggers a co-install warning), and idempotently injects `[features] multi_agent = true` into `config.toml` (backup + atomic write, `[features]` segment only, user config untouched; uninstall removes the key and prunes the empty segment); runtime management plane codex branches — `platform.sh` detection (project `.codex/skills/budget-workflow/` → global, `BUDGET_PLATFORM=codex`), `agent preset/custom/inherit` degrade to guidance (no frontmatter model to rewrite; tier resolved by the Leader at spawn time from `budget-models.json`), `show` prints the three-tier table, notify/quickstart/models/uninstall/validate codex-aware; `budget-models.json` `platforms.codex` three tiers economic→`gpt-5.6-luna` / balanced→`gpt-5.6-terra` / quality→`gpt-5.6-sol` (deployment aliases — map them in your deployment environment; `unconfirmed_ids` permanently marks the three aliases since they cannot be verified centrally, the alias-class pre-release clearing discipline explicitly does not apply); hooks are not distributed (Codex hooks are experimental — `budget notify` CLI remains available); slash commands degrade to natural-language skill triggers on Codex; bilingual README / architecture docs updated to the four-platform scope

## [0.3.0] - 2026-10-20

### Added

- **Execution agents AutoRun (approval-free)** — CodeBuddy sub-agents: new optional `auto_run` boolean in the neutral source (`core/agents/*.md`) mapped to frontmatter `enabledAutoRun: true` (only when present, same emit rule as `max_turns`); on by default for the 4 execution agents (coder-lite / coder-standard / coder-senior / tester) while the other 6 keep per-call approval; new `budget setup autorun list|on|off` subcommand lets users opt the rest in — choices persist in the user data dir `~/.budgetbuddy/auto-run.json` (survives uninstall, replayed on reinstall; `apply` is an internal replay command, not user-facing); install-time replay keeps choices across upgrades; `budget setup update` touches neither agent files nor the state file; OpenCode needs no change (permission map `allow` is already approval-free for these agents) and Claude Code has no per-sub-agent switch (falls back to settings.json permissions guidance); `autorun on` output lists the agent's approval-free bash patterns with an explicit safety notice — AutoRun makes every tool call in scope approval-free, approval is the last manual gate

### Known Limitations

- Claude Code has no per-sub-agent auto-run switch — approval remains with the session permission mode / `settings.json` permissions (`budget setup autorun` prints this alternative guidance and exits 0 without changing anything); OpenCode needs no change (permission map `allow` is already approval-free for the 4 execution agents)
- IDE-behavior verification pending — three items await end-to-end verification in a real IDE session: the Auto Run settings-page switch vs frontmatter `enabledAutoRun` priority, the write form when the IDE turns Auto Run off (line removal vs `enabledAutoRun: false`), and the `enabledAutoRun` × `permissionMode` (plan/acceptEdits) hierarchy (verification records: `openspec/changes/agent-autorun/verification-open-questions.md`)

### Tests

- 709 → 753 test cases (+44: build emit/rewrite/validate + `.bash-patterns.json` data-file coverage, new `tests/test_autorun.py` suite, installer AutoRun replay integration)

## [0.2.1] - 2026-10-20

### Added

- **Claude Code hooks notification adaptation** — three events (Notification / PermissionRequest / SubagentStop) delivered via the injection engine's data-driven `HOOK_EVENTS_JSON` event manifest, with payload-driven compatibility in the notify hook

### Changed

- **Hooks injection engine event manifest parameterized** — the injected event list is now sourced from `HOOK_EVENTS_JSON` (CodeBuddy default three-event behavior unchanged)

### Fixed

- **Installer co-install scenario claudecode hooks injection misjudgment** — form snapshot + explicit `settings_file` + result marker returned from the injection subshell, so Claude Code hooks are correctly injected when multiple platforms share `~/.budgetbuddy/`

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
