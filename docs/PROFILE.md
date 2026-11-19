# The project profile

The engine (this plugin) holds everything that is the same in every project: the loop,
the roles, the rubric, the gates. A project tells the engine about itself in its
**profile**: one TOML file and a folder of lens files. Nothing project-specific lives
in the plugin, and nothing in the profile restates the engine.

```
<repo>/.claude/orchestration/
  project.toml          settings: gates, paths, environments
  lenses/<agent>.md     project knowledge for one subagent (correctness.md is required)
```

One project is one repository: the plan, the log and the code live together. The profile
is TOML because the hooks read it, and they use only the Python standard library
(`tomllib`, Python 3.11+). See [MODEL.md](MODEL.md) section 13 for what each setting
means in the process.

---

## 1. `project.toml`

Paths are repo-relative with `/` separators. A key with no default is required. A table
or key that is not listed here is an error, so a typo or an old setting never looks as if
it were enforced.

### Top level

| Key | Type | Default | Meaning |
|---|---|---|---|
| `schema` | int | — | Profile format version. Must be `1`. |

### `[project]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | — | Short name, used in reports, PR text and push notifications. |
| `summary` | string | — | One line saying what the project is and what matters most in it. Every subagent reads it first. |

### `[repo]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `main` | string | — | The main branch. The merge guard protects it, and always protects `main` and `master` too. |
| `setup` | list of strings | `[]` | Commands run once per session before the gates (starting a local database, for example). |
| `gates` | list of strings | — | Install, lint, build, test and boundary-check commands, in order. Non-empty. |
| `architecture` | list of strings | `[]` | Rung 3 of the decision ladder: architecture docs and published contracts. The implementer and the spec reviewer read them. |

Package worktrees go next to the repo, as `<repo folder>-wp-<id>`.

### `[plan]`

Where the records live. All optional.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `plan` | string | `docs/IMPLEMENTATION_PLAN.md` | Status table, open questions, follow-up register, access inventory, safeguards. |
| `process` | string | `docs/PROCESS.md` | The human-readable process. |
| `specs` | string | `docs/work` | Folder of `<ID>-<slug>.md` package specs. |
| `adrs` | string | `docs/decisions` | Folder of ADRs. |
| `log` | string | `docs/decisions/log` | Decision log folder; its `README.md` is the index. |
| `read_at_start` | list of strings | `[]` | Extra files the orchestrator reads at session start, besides `CLAUDE.md`, the plan and the process file (typically the ADR that adopts the process). |

Rows in the plan whose owner is `human` belong to the user; the orchestrator never picks
them.

### `[rubric]`

Project words that the shared severity rubric is read with.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `user_visible` | string | — | What a visible bug looks like here. A Blocker is "user-visible wrong output", and a log entry is flagged for review when it changes this. |
| `conditions` | list of strings | — | The realistic conditions a Major is judged against ("restart", "empty input", ...). |

### `[deploy]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `dev` | string | — | The development environments, in words: what a merge deploys to, everything the agent's credentials reach, and the command that rebuilds them from scratch. The agent has full control there. |
| `prod` | string | — | What counts as production (environments, databases and the platforms that host them) and how the user deploys it by hand. The agent holds no credential for it. A decision that changes what production will do once deployed is flagged for review. |

The access phases (`[access] phase`) and `deploy.freeze_check` were removed on 19 Nov 2026,
when access moved from phases to environments ([MODEL.md](MODEL.md) section 12). A profile
that still has them is invalid until they are deleted, and `deploy.test` is now `deploy.dev`.

### `[merge]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `required_check` | string | — | The CI check that must succeed on the PR head before the merge guard allows a merge. |

### `[panel]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `full` | list of strings | `[]` | Package IDs that always get the full panel. |

### `[paths]`

Path patterns (section 2) that decide the review panel for a diff. All default to `[]`.

| Key | Meaning |
|---|---|
| `full_panel` | A diff touching any of these gets the full panel, whatever its ID. |
| `design_review` | A package touching these gets a plan-only design review before code. |
| `ops` | Wakes `review-ops`, on either panel. |
| `security` | Wakes `review-security` on the light panel (it is always on the full panel). |
| `ux` | Wakes `review-ux`. Empty means the project has no user interface, and the lens never runs. |

### `[docs]`

The docs gate. A commit, or a session end, that changes `code` paths and no `docs` paths
is blocked.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `code` | list of patterns | — | Paths that count as behaviour. |
| `docs` | list of patterns | — | Paths that count as documentation. A path matching both is docs. |
| `hint` | string | `""` | Where docs for a change belong, appended to the gate's message. |

A complete profile is in
[examples/sample-profile/](../examples/sample-profile/.claude/orchestration/project.toml).

---

## 2. Path patterns

Matched against repo-relative paths with `/` separators, case-sensitively.

| Pattern | Matches |
|---|---|
| `db/` | everything under `db/` (a trailing `/` means a folder) |
| `Dockerfile` | exactly that path, at the repo root |
| `railway.*` | `*` matches within one path segment |
| `docs/**/*.md` | `**` matches any number of segments, including none |

---

## 3. Lens files

Each subagent reads `lenses/<agent>.md` if it exists, after its own instructions from the
plugin. The file says what that lens means **in this project**: the sources of truth,
what to check, which concrete cases to trace. It never changes the rubric, the report
format, the budget or the safety rules, which belong to the engine.

| File | Read by | Required |
|---|---|---|
| `correctness.md` | `review-correctness`, `review-combined` | **yes**: the domain truth has no generic version |
| `reliability.md` | `review-reliability`, `review-combined` | no |
| `security.md` | `review-security` | no |
| `tests.md` | `review-tests`, `review-combined` | no |
| `ops.md` | `review-ops` | no |
| `ux.md` | `review-ux` | when `paths.ux` is set |
| `spec.md` | `review-spec` | no |
| `implementer.md` | `implementer` | no |
| `finding-verifier.md` | `finding-verifier` (which also reads the file of each lens that raised a finding) | no |

The plugin's agents are dispatched as `athena-orchestrator:<agent>`, for example
`athena-orchestrator:review-spec`.

**Format.** Plain Markdown, short (aim for under 40 lines), with these sections, each
optional except where the file is required:

```markdown
# <Lens>: <project name>

## Sources of truth
Files the reviewer reads before judging (ADRs, rule files, contracts).

## Check
Project-specific checks, one bullet each. Name the severity when it is not obvious.

## Cases to trace
Concrete adversarial inputs (correctness), failures (reliability), users and tasks (ux).

## Heavy tools
What this lens may run beyond reading and tests, and only for what (for example, a
throwaway local database to check SQL). Omit to allow none.
```

---

## 4. The gates and the profile

| Gate | Needs the profile? | What it does |
|---|---|---|
| **Destroy gate** | no | Denies the destructive actions that reach beyond development (MODEL.md section 12.2, layer 5, has the list). Asks before any edit to `project.toml` or `.claude/settings*.json`. |
| **Ops gate and merge guard** | yes | The merge guard, secret-printing denials (the 1Password and Infisical CLIs' own commands, and whatever `op run`, `infisical run` or `railway run` runs, included). |
| **Docs gate** | yes | `[docs]`. |

How they behave when the profile is missing or broken. The gates fail closed, but a
project that has not adopted the plugin is not broken.

| State | Ops gate and merge guard | Docs gate | Orchestrator |
|---|---|---|---|
| No `project.toml` | Classifies commands with the built-in rules. Every opinion, including a deploy, a merge, a push without a branch and a secret-printing command, becomes "ask". | Off. | Stops: "run `/athena-orchestrator:adopt` first". |
| `project.toml` unreadable, invalid, or a required key missing | Every shell call asks, with the reason. | Every commit is denied, and a session end is sent back once, with the reason. | Stops and names the problem. |
| Valid | As configured. | As configured. | Runs. |

**Every "ask" above is a "deny" in bypass-permissions mode**, in every gate, the fallbacks
and the stub included: Claude Code never shows a hook's ask in that mode, so it would let
the call through ([TRIAL.md](TRIAL.md), F5). Leave bypass mode to approve such a call. In
particular, in bypass mode a session cannot edit the profile or the settings, and an
unadopted project's deploys, merges and secret-printing commands are denied.

`python <plugin>/scripts/athena_profile.py check [dir]` reports which state a repo is in
(exit 0 valid, 1 invalid, 2 absent).

Install the plugin at **project scope** (`enabledPlugins` in the project's
`.claude/settings.json`), which `adopt` does, so its hooks run only in projects that use
it. The gates need **Python 3.11+** on `PATH`, and **Git Bash** on Windows (Claude Code
runs hook commands with it). When a gate cannot start at all, the hook command itself
answers "ask" (at a session end, a warning).

**If the plugin goes missing.** A project's hooks vanish silently when the plugin is
uninstalled, so `adopt` also puts the stub from `templates/settings.json` in the project's
`.claude/settings.json`: a hook that asks before every shell call when the plugin is not
listed in `~/.claude/plugins/installed_plugins.json` (where the trial found it). It does not notice a plugin that is installed but
disabled; `enabledPlugins` in the same file, which the security reviewer watches, covers
that.

---

## 5. Engine or profile: the inventory

Every value the source material hard-coded, and where it went. The test for each: could a
second, unrelated project use it unchanged?

| Hard-coded in the source | Where | Decision |
|---|---|---|
| Project description in the skill and agent headers | profile | `project.summary`; project emphasis goes in lens files |
| Policy ADR paths, process file, plan path | profile | `[plan]`, with defaults matching the templates |
| Main branch, gate commands, a once-per-session setup command | profile | `[repo]` |
| Full-panel IDs and paths | profile | `panel.full`, `paths.full_panel` |
| Design-review triggers | profile | `paths.design_review`; the "plan mode" spec marker is engine |
| Path triggers for the ops, security and user-interface lenses | profile | `paths.*` |
| A client-specific screen lens | profile | the engine has a general `review-ux`; the specifics go in the project's `lenses/ux.md` |
| Domain checks in correctness, reliability, security, spec, tests, ops | profile | lens files |
| Heavy tools allowed per lens | profile | each lens file's "Heavy tools" |
| Rubric words for "visible bug" and "realistic conditions" | profile | `[rubric]`; forbidden write paths and personal-data rules are the project's hard rules in `CLAUDE.md` |
| A code freeze date, protected event windows | dropped | production deploys only by the user's hand, so the user decides when; the engine knows no dates |
| A deadline, weekly checkpoints, a cut date | plan | the plan's target dates; the session report lists the unscheduled follow-ups every time |
| What development and production are | profile | `deploy.dev`, `deploy.prod` |
| Open questions with no safe default | plan | the plan's open questions table; no default means ask |
| Required CI check | profile | `merge.required_check` |
| Docs gate code and docs patterns, where docs go | profile | `[docs]` |
| Several repos run as lanes, with a sync check and companion branches | dropped | one repo per project; two repos are two projects |
| A configurable name for the human's rows | engine | fixed: owner `human` |
| "Every production write needs approval" | changed | stronger: the agent holds no production credential at all, and the user deploys production by hand; full control of development instead |
| Ops gate rules for Railway, git, gh and `docker push` | engine | always on |
| Ops gate rules for other hosting and infrastructure tools, and the "prod" name tripwire | dropped | add a platform's rules when a project uses it |
| The destroy gate | engine | trimmed to the same platforms, and to the actions that reach beyond development; SQL is not its business |
| Merge guard: auto-merge denied, aliases and extensions, API endpoints | engine | unchanged |
| `[no-docs]` opt-out marker | engine | unchanged |
| `CLAUDE.md` = `AGENTS.md` byte-identical | engine | applies when both exist |
| Model tiers (inherit for deep roles, sonnet for checklist lenses) | engine | agent frontmatter; no profile setting until a project needs one |
| Budgets (15 / 25 tool calls, 300 words), round cap 3, ~100-line escalation | engine | invariant core |
| Escalation list, stop conditions, ladder, severity scale, report formats, log template, PR body | engine | invariant core |
| Hook timeouts (30 s ops, 15 s docs, 12 s guard, 10 s destroy) | engine | unchanged |
