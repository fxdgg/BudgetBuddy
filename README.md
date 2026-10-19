# BudgetBuddy — Multi-Agent Cost-Saving Development Workflow Kit

**English** | [中文](README_CN.md) | [Changelog](CHANGELOG.md) | [License](LICENSE)

BudgetBuddy is a multi-agent, cost-saving development workflow kit. It routes every task to the right sub-agent with the right model, so simple tasks burn cheap tokens and only hard tasks burn expensive ones. One neutral source (`core/`) builds into platform-specific distributions for **CodeBuddy** and **OpenCode**; other agent platforms can be added by extending the build DSL (`core/platform/*.yaml`).

## What is BudgetBuddy?

A typical coding request is a mix of trivial edits, routine features, and a few genuinely hard problems. Running everything on one premium model wastes budget; running everything on a cheap model misses the hard problems. BudgetBuddy splits the work across **10 specialized sub-agents** with per-role model assignment, wrapped in an enforced five-phase workflow (proposal → dual review → tiered implementation → final review → archive).

The kit is self-bootstrapped: this repository is developed with BudgetBuddy's own workflow.

## Features

- **10 specialized sub-agents** — architect, coder-lite / coder-standard / coder-senior, reviewer + reviewer-b (dual review), tester, recorder, director (final verdict), goal-evaluator
- **Five-phase workflow** — proposal & design → dual design review → tiered implementation → final review & regression → archive; phases cannot be skipped
- **Three-tier model presets** — `economic` / `balanced` / `quality`, one command to switch; per-agent `custom` override and `inherit` (follow the main panel model) also supported
- **5 persona themes** — default (professional), tech-legends, sanguo, shuihu, genshin; role names and greetings change with the theme
- **Universal webhook notifications** — WeCom bot / DingTalk bot (HMAC-SHA256 signed) / Feishu bot (card) / custom webhook, 11 workflow event switches (N1–N11)
- **Coder Guard** — per-coder, per-task-tag failure records over a 5-attempt window; 2+ failures trigger automatic tier downgrade
- **Goal Loop** — goal-driven macro loop: define goal → run pipeline → verify → iterate until the goal is met (max 8 iterations, safety boundaries included)
- **OpenSpec change management** — propose / apply / archive / explore commands with spec-driven change tracking
- **Dual-platform build** — single `core/` source, `scripts/build.py` emits `dist/codebuddy/` and `dist/opencode/`
- **Superpowers integration** — quality-practice skills (TDD, systematic debugging) referenced at the right phases; workflow degrades gracefully when the plugin is absent

## Installation

### Online install (one line)

```bash
# BUDGET_REPO_URL must point to the base URL that hosts install.sh and releases
export BUDGET_REPO_URL="<repo-base-url>"
curl -fsSL $BUDGET_REPO_URL/install.sh | bash
```

> ⚠️ **Trust boundary**: `curl | bash` executes a remote script with your privileges. Review the script first (`curl -fsSL $BUDGET_REPO_URL/install.sh | less`) before piping it to bash. The installer downloads the release zip and **enforces SHA256 verification** — it aborts on checksum mismatch and never installs a corrupted package.

Interactive mode asks for platform (CodeBuddy / OpenCode / both) and scope (project / global). Non-interactive:

```bash
BUDGET_PLATFORM=opencode BUDGET_GLOBAL=1 bash install.sh   # global OpenCode install
```

### Manual install

```bash
git clone <this-repository-url> BudgetBuddy
cd BudgetBuddy
bash install.sh
```

### Platform notes

| Platform | Structural files land in | Management plane |
|----------|--------------------------|------------------|
| CodeBuddy | `.codebuddy/` (project) or `~/.codebuddy/` (global) | `~/.budgetbuddy/` |
| OpenCode | `.opencode/` (project) or `~/.config/opencode/` (global) | `~/.budgetbuddy/` |

- **CodeBuddy**: agents/rules/skills/commands land under `.codebuddy/`; hooks are injected into `settings.json` (with backup) and the Superpowers plugin is auto-enabled; the `budget` CLI is written to `~/.local/bin/budget`.
- **OpenCode**: agents/commands/skills land under the OpenCode directory; rules are merged into `AGENTS.md` as a marked block; hooks have no native equivalent — see `core/docs/opencode-setup-notes.md` for the plugin extension point.
- Windows: use Git Bash or WSL (PowerShell aliases `curl` to `Invoke-WebRequest`).
- Project and global installs can coexist; project-level takes priority.

## Quick Start

### CodeBuddy

```
/budget:start "Add user login API with JWT auth"
```

### OpenCode

```
/budget-start "Add user login API with JWT auth"
```

The Leader analyzes the request, dispatches architect → dual reviewers → tiered coders → tester → final review → recorder, and reports back. For goal-driven iteration:

```
/budget:goal "Keep improving until all tests pass and coverage >= 80%"   # CodeBuddy
/budget-goal "Keep improving until all tests pass and coverage >= 80%"   # OpenCode
```

### Common commands

| Command (CodeBuddy) | Command (OpenCode) | Purpose |
|---------------------|---------------------|---------|
| `/budget:start <requirement>` | `/budget-start <requirement>` | Start the five-phase workflow |
| `/budget:goal <goal>` | `/budget-goal <goal>` | Start / resume the Goal Loop |
| `/budget:status` | `/budget-status` | Query workflow progress |
| `/opsx:propose` | `/opsx-propose` | Propose a new OpenSpec change |
| `/opsx:apply` | `/opsx-apply` | Implement tasks from a change |
| `/opsx:archive` | `/opsx-archive` | Archive a completed change |
| `/opsx:explore` | `/opsx-explore` | Explore ideas before proposing |

Natural language triggers ("start development", "implement X", "fix X bug") activate the same workflow.

### Setup subcommands (`budget setup <subcommand>`)

| Subcommand | Purpose |
|------------|---------|
| `init [shell]` | Initialize data dirs (`.budget/`, `~/.budgetbuddy/`); `init shell` injects the shell alias |
| `show` | Show current agent / model configuration |
| `status` | Status query (guard summary + active change + agent config) |
| `agent preset\|inherit\|custom` | Switch model preset / inherit panel model / override one agent |
| `persona list\|set\|expand\|show` | Manage persona themes |
| `validate` | Verify installation integrity against the manifest |
| `diff [preset]` | Compare current config vs a preset (default `balanced`) |
| `stats` | Workflow statistics |
| `update` | Incremental update (`budget update` is a top-level alias) |
| `reinstall` | uninstall + init combined |
| `uninstall` | Uninstall (offline, local-manifest driven) |
| `guard` | Query / reset Coder Guard records |
| `quickstart` | Interactive guided tour (aliases `tour`, `wizard`) |
| `models` | Show the model catalog |
| `notify "<msg>" <event>` | Send a notification (top-level `budget notify`) |
| `help` | Show help |

## Architecture

```mermaid
flowchart TD
    U(["User"]) -->|"/budget:start"| L["Leader — orchestration only, never writes code"]

    subgraph P1["Phase 1 · Proposal and Design"]
        A["architect"]
    end
    subgraph P2["Phase 2 · Dual Design Review"]
        R1["reviewer — primary"]
        R2["reviewer-b — secondary"]
    end
    subgraph P3["Phase 3 · Tiered Implementation (per task)"]
        C["coder-lite / coder-standard / coder-senior"]
        T["tester"]
        RV["reviewer"]
        C --> T
        T -->|"fail — self-fix, max 2"| C
        T -->|"pass"| RV
        RV -->|"reject — escalate tier, max 3 rounds"| C
    end
    subgraph P4["Phase 4 · Final Review and Regression"]
        FR["reviewer"]
    end
    subgraph P5["Phase 5 · Archive"]
        REC["recorder"]
    end

    L -->|"requirements"| P1
    P1 -->|"proposal.md + design.md"| P2
    P2 -->|"gate-review.md — both pass"| P3
    P3 -->|"all tasks pass"| P4
    P4 -->|"final review report"| P5
    P5 -->|"archive + Coder Guard update"| L

    P2 -->|"3rd rejection — user arbitration"| U
    P3 -->|"loop over 5 rounds — pause (N3)"| U
    P3 -->|"3 failed rounds"| D["Director — final verdict"]
    D -->|"A/B/C — auto recovery"| P3
    D -->|"D/E/F — escalate"| U

    GL["Goal Loop (/budget:goal)"] -.->|"Phase 0 — goal definition"| L
    L -.->|"Phase 6 — goal verification"| GE["goal-evaluator"]
    GE -.->|"gap — iterate, max 8 rounds"| L
    GE -.->|"achieved — N11"| L
```

### Key rules

- **Leader never writes code** — every code change goes through a tiered coder agent, even a one-line typo
- **tester and reviewer are mandatory** — each task must pass tester verification and reviewer review before it counts as done
- **Review Gate escalation** — failed review escalates the coder tier (lite → standard → senior), max 3 rounds; a task loop is capped at 5 rounds (3 tiered reviews + 2 self-fixes) before pausing for the user
- **Director final verdict** — when 3 rounds all fail, Director classifies the root cause (6 classes); A/B/C trigger auto-recovery, D/E/F escalate to the user
- **Coder Guard** — before dispatch, the Leader checks the coder's failure record for the task tags; 2+ failures in the last 5 attempts force a tier downgrade

Component-level diagrams live in [`core/docs/architecture.md`](core/docs/architecture.md).

## Model Presets

| Preset | Positioning | Typical shape |
|--------|-------------|---------------|
| `economic` | Maximum savings | Free/budget models carry most roles; premium model only for the final verdict |
| `balanced` | Balanced (recommended) | High-value models on architect/reviewer, mid-tier on coders, budget models on tester/recorder |
| `quality` | Maximum quality | Premium models on architect/coder-senior/director, strong models elsewhere |

```bash
budget setup agent preset economic    # switch preset (rewrites agent frontmatter)
budget setup agent custom coder-lite kimi-k2.7   # override one agent's model
budget setup agent inherit coder-lite            # follow the main panel model
budget setup show                     # inspect the result
```

The full catalog (models, tiers, costs, aliases, per-platform preset tables) is generated at build time into `dist/<platform>/docs/MODEL_SELECTION.md`.

## Notifications

Configure once in `.budget/notify.json` (project) or `~/.budgetbuddy/notify.json` (global); the project file wins when present (no merging):

```json
{
  "enabled": true,
  "channels": {
    "wecom":    {"type": "wecom_bot",    "webhook": "https://qyapi.example.com/..."},
    "dingtalk": {"type": "dingtalk_bot", "webhook": "https://oapi.example.com/...", "secret": "SEC..."},
    "feishu":   {"type": "feishu_bot",   "webhook": "https://open.example.com/..."},
    "custom":   {"type": "custom",       "webhook": "https://hooks.example.com/...", "format": "raw"}
  },
  "events": {
    "N7":  {"enabled": true, "channels": ["wecom", "dingtalk"]},
    "N10": {"enabled": true, "channels": ["feishu"]}
  }
}
```

- **11 event switches (N1–N11)** — design-review rejections, review-gate exhaustion, loop overrun, Director intervention, phase transitions, goal achievement, etc.
- **Delivery semantics** — markdown payload, 5s timeout per channel, first success stops delivery, all failures are silent (never blocks the workflow)
- **Security** — the config file is `chmod 600` (owner-only); webhook/secret values never pass through environment variables, command-line arguments, or logs; error output is sanitized to hostname only

## Repository Layout

```
BudgetBuddy/
├── core/                  # single neutral source — edit here
│   ├── agents/            # 10 agent definitions
│   ├── commands/          # budget (start/status/goal) + opsx (4) command templates
│   ├── docs/              # architecture.md, opencode-setup-notes.md, personas, model template
│   ├── hooks/             # CodeBuddy notify hook
│   ├── lib/               # management-plane modules (setup, state, guard, notify, ...)
│   ├── models/            # budget-models.json + schema
│   ├── personas/          # 5 persona themes
│   ├── platform/          # codebuddy.yaml / opencode.yaml mapping DSL
│   ├── rules/             # 12 rules (3 P0 + 8 code standards + rtk)
│   ├── skills/            # budget-workflow, budget-notify, 4 openspec skills
│   └── setup.sh           # budget setup entry
├── dist/                  # build output (do NOT hand-edit)
│   ├── codebuddy/
│   └── opencode/
├── scripts/               # build.py, scan-brand.py, build-release.sh
├── tests/                 # unit tests (python3 -m unittest)
├── install.sh             # dual-platform installer
└── VERSION
```

## Development Guide

- **Edit `core/`, never `dist/`** — `dist/` is generated; hand edits are overwritten and fail the check
- **Build & gate**: `python3 scripts/build.py --check` (also `--strict` for warning-as-error runs)
- **Brand gate**: `python3 scripts/scan-brand.py` — scans `core/`, `dist/`, `scripts/`, `install.sh`, `README.md`, `README_CN.md`, `CHANGELOG.md` for forbidden terms (the reference project's brand words); the gate must exit 0
- **Tests**: `python3 -m unittest discover -s tests`
- **Release**: `bash scripts/build-release.sh` — runs the check, reads `VERSION`, packages `budgetbuddy-<version>.zip` + `.sha256`
- **Change management**: use the OpenSpec workflow (`/opsx:propose` → review → `/opsx:apply` → `/opsx:archive`); the Leader orchestrates and never writes code itself — all edits go through tiered coder agents

## License

[MIT](LICENSE) — Copyright (c) 2026 BudgetBuddy Contributors
