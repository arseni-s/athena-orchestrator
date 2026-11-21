---
name: adopt
description: Set up a new or existing project for athena-orchestrator. It maps what the repo already has, asks only what it cannot infer, then writes the profile, the plan, the process docs, the PR template and CI from templates, never overwriting a file. Use when the user types /athena-orchestrator:adopt, or asks to set a project up for the orchestrator or /athena.
argument-hint: "[path to the repo]  (default: the current repo)"
---

# Adopt a project

You set a repository up so that the orchestrator (`athena-orchestrator:orchestrate`, typed as
`/athena`) can run it. You write the files yourself: this is the bootstrap, done before
the orchestrator exists in the project. The templates are in
`${CLAUDE_PLUGIN_ROOT}/templates/`; their `README.md` lists each one, its target, and
every `{{placeholder}}`. The profile format is the plugin's profile reference
(`docs/PROFILE.md` in the plugin's repository).

**The one rule: never overwrite.** A file that exists is kept as it is. You may append a
missing section to it only when the user approved that in the mapping (step 3). When the
project already has something in another place (an ADR folder, a plan, a CI workflow), you
point the profile at it instead of creating a second one.

## 1. Check where you are

0. **Not in bypass-permissions mode.** Writing the profile and `.claude/settings.json`
   asks the user first, and in bypass mode the gates deny those writes instead, because a
   question cannot reach the user there. If the session is in that mode, ask the user to
   leave it (Shift+Tab), and stop.
1. Find the repo root: `git rev-parse --show-toplevel` in the argument's folder, or in
   the current one. Not a git repo: stop, and offer `git init`.
2. Check the profile: `python "${CLAUDE_PLUGIN_ROOT}/scripts/athena_profile.py" check`
   in the repo root (`python3` where `python` is not Python 3.11+; neither: stop, the
   gates need Python 3.11+).
   - **Exit 0**: the project is adopted already. Run steps 2 and 3 only for what is
     missing (lens files, templates whose targets do not exist, a plan section such as
     "Safeguards" that an earlier version did not have, the feature map and the
     **end-to-end harness** package when the profile's `verify.e2e` is empty and the plan
     has no such package, the `/athena` shortcut), and never touch the profile.
   - **Exit 1**: a profile exists but is invalid. Report its problems and stop: the user
     fixes the profile, because only the user changes it.
   - **Exit 2**: carry on.
3. Check the working tree: `git status --porcelain`. Uncommitted changes: stop and ask the
   user to commit or stash them first, so adopting lands as one reviewable commit. Two
   exceptions, which go into adopt's commit: `.claude/settings.json`, when its only change
   is the `enabledPlugins` entry that `claude plugin install --scope project` writes (it
   is merged in step 4.4), and a new `.claude/session-secrets.json` (step 1.4).
4. **The agent's credentials**, before anything else, so that one session restart (if
   any) comes now and not halfway through. Run
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/session_secrets.py" check` in the repo root. It
   prints names only.
   - `config` true, `stored` true, `vaults` exactly one, and every name in `env` also in
     `in_this_session`: done, carry on.
   - The same, but names missing from `in_this_session`: the setup happened after this
     session started. Ask the user to start a new session and run adopt again, and stop.
   - Otherwise the user stores the project's service account token once. What they need
     first, in 1Password (say it in these words if they have not done it): a vault for
     the project's development values; in it, an **API Credential** item for each agent
     token, its title naming the service (`GitHub ...`, `Railway ...`; the GitHub token
     fine-grained, this repository only: contents and pull requests read and write,
     actions and commit statuses read, nothing else); and a **service account** with read
     access to that vault only. Then open the setup in a terminal of its own, where the
     token never passes through the session:
     `cmd /c start "athena setup" python "${CLAUDE_PLUGIN_ROOT}/scripts/session_secrets.py" setup "<repo root>" --pause`
     on Windows (elsewhere the user runs the same `python ... setup` in a terminal). The
     user copies the token in 1Password and presses Enter there. Run `check` again: it
     shows the vault and the variables it found. A missing variable: the user fixes the
     item's type or title and runs the setup again. Then ask the user to start a new
     session and run adopt again, and stop.
   - The user has no service account yet and wants to adopt anyway: carry on without one.
     The access package then sets it up, and its spec says how.

## 2. Survey (read only)

Map what exists before you decide anything. Read; do not run builds, installs or anything
that writes. Never read `.env` files.

| Look for | Where | It decides |
|---|---|---|
| Hard rules and conventions | `CLAUDE.md`, `AGENTS.md`, `.claude/rules/`, `CONTRIBUTING.md` | `{{hard_rule}}`; whether both memory files exist |
| What the project is | `README.md`, manifests, the code's top folders | `{{project_name}}`, `{{project_summary}}` |
| Main branch | `git symbolic-ref --short refs/remotes/origin/HEAD`, else `git branch --show-current` | `{{main}}` |
| Gate commands | `package.json` scripts, `pyproject.toml`, `Makefile`, `justfile`, `Cargo.toml`, `go.mod`, existing CI steps | `{{gate_command}}`, `repo.setup` |
| A plan or backlog | `docs/`, `ROADMAP.md`, `TODO.md`, `PLAN.md` | `plan.plan`, and the first status rows |
| ADRs | `docs/decisions/`, `docs/adr/`, `doc/adr/`, `docs/architecture/decisions/` | `plan.adrs`, `{{adr_number}}` |
| Specs | `docs/work/`, `docs/specs/`, `specs/` | `plan.specs` |
| Architecture docs | `docs/ARCHITECTURE.md`, `docs/architecture/`, published API contracts | `repo.architecture` |
| CI | `.github/workflows/*.yml` and the job that runs the tests | `{{required_check}}`; whether `ci.yml` is written |
| PR template | `.github/pull_request_template.md`, `.github/PULL_REQUEST_TEMPLATE/` | whether the template is written |
| Hosting and deploys | `Dockerfile`, `railway.*`, `fly.toml`, `vercel.json`, `Procfile`, deploy scripts | `{{deploy_dev}}`, `{{deploy_prod}}`, `paths.ops` |
| Database and migrations | `migrations/`, `db/`, `alembic/`, `prisma/` | `paths.full_panel`, `paths.ops`, the event-table package |
| User interface | `templates/`, `static/`, `src/components/`, `app/`, `pages/`, `frontend/` | `paths.ux`, and whether `ux.md` is needed |
| End-to-end tests | `playwright.config.*`, `cypress.config.*`, `e2e/`, `tests/e2e/`, `*.spec.ts` beside a browser tool, API or CLI tests that start the app, their scripts in the manifest; a list of features or user flows in the docs | `verify.e2e` and `verify.smoke` when a harness starts the product and runs its flows; the feature map's first rows; whether the harness package is needed |
| Auth, config, secrets handling | `auth/`, `config.*`, `.env.example`, lockfiles | `paths.security` |
| Secrets on disk | by name only, never read: tracked `.env` files (`git ls-files`), untracked ones (`.env`, `.env.local`); `.infisical.json`; `op://` reference files; the platform's variable names (never values) | the secrets manager, the "identity" safeguard row, the push script's targets; a tracked `.env` file that is not an example file is the first thing in the report |
| Dependency install settings | the lockfile (which package manager), `.npmrc`, `pnpm-workspace.yaml`, `bunfig.toml`, `pyproject.toml` / `uv.toml`, and how CI installs | the "dependencies" safeguard row |
| Secret scanning | CI steps, `.gitleaks.toml`, `.infisical-scan.toml`, pre-commit config | the "secrets are caught" row; `{{secret_scan}}` |
| Backups | scheduled workflows, backup or dump scripts, the hosting config, the runbook | the "backup" safeguard row |
| Claude settings | `.claude/settings.json`, `.claude/agents/`, `.claude/skills/` | the settings merge; names that could confuse |
| The `/athena` shortcut | `~/.claude/skills/athena/SKILL.md` | step 6 |
| The agent's credentials | `.claude/session-secrets.json`, `session_secrets.py check` (step 1.4) | the "identity" safeguard row and the access inventory: done when check shows the one vault |

Decide which state the project is in: **new** (little or no code, no docs) or **existing**.
For a new project every template applies. For an existing one, most decisions are a
mapping.

## 3. Ask, then present the mapping

1. **Ask once.** Put every question you could not answer from the survey in one message
   (use the question tool where you have one, at most four questions per call). Propose an
   answer for each, so the user can just confirm. Typically:
   - the one-line summary, and what a **user-visible bug** looks like here
     (`rubric.user_visible`);
   - the **realistic conditions** a bug shows up under (`rubric.conditions`);
   - which environments are **development** (what a merge deploys to, and everything
     the agent may control), what counts as **production**, and how the user deploys
     production by hand (auto-deploy off, a chosen commit from the platform's dashboard);
   - the command that **rebuilds development from scratch**, if there is one, and what
     in development was set up by hand and is not yet in seed or setup code;
   - which credentials **act in the real world with no test account** (a portal login, a
     signing key, a payment account): they stay in production only, and development
     works against a fake of that service;
   - the **hard rules**: what must never happen;
   - which code is **critical** (where a bug is visible or loses data:
     `paths.full_panel`);
   - the **flows that matter**: what users come to do, in their words, for the feature
     map's first rows, and which few of them show that a deployment is alive (`smoke`);
   - the **safeguards** the survey could not see: whether the database has a backup
     outside the hosting platform, and whether a restore was ever tested.
2. **Present the mapping**: one table, one row per template in the templates README, with
   its target and one action:
   - `create`: the target does not exist; it is written from the template;
   - `map`: the project has it somewhere else; the profile points there (say which key);
   - `append`: the file exists and lacks a section the orchestrator reads (for example
     the plan's "Follow-up register" or "Access inventory", or the PR template's
     sections); the section is appended, nothing else changes;
   - `keep`: the file exists and works as it is;
   - `skip`: not needed here (say why: no user interface, no database).

   Below it: the profile you will write, in full, the seed packages (step 4.6), and the
   plan's "Safeguards" table as the survey found it: each of the six rows `done` with
   what proves it, `not needed` with the reason, or `todo` with what is missing. Mark a
   row `done` only on evidence you read, never on a guess.
3. **Wait for one approval** of the mapping. Apply the changes the user asks for. Do not
   write anything before this approval. **This approval is the user's review of the
   adoption**: everything that sets the rules (the profile, the settings, the ADR) is in
   front of them now, so there is no second review of the commit afterwards. Say so
   under the mapping, together with: "Approving also accepts the orchestration ADR, which
   gives the orchestrator full control of the development environments, and lets it
   merge each package once you approve its summary. Production stays yours: it holds no
   credential for it, and you deploy it by hand. Say if you want it left Proposed."

## 4. Write

Work in the repo's main checkout, on a new branch `adopt-athena-orchestrator` from the main
branch. Writes go through the file tools, never a shell heredoc.

1. **Fill every placeholder** from the survey and the answers. A value you still do not
   have becomes a `TODO(adopt): <the question>` line, and goes in the report. No `{{`
   placeholder is ever left in a file you write.
2. **The profile**, `.claude/orchestration/project.toml`, from `project.toml`. Fill in the
   `[paths]` and `[docs]` patterns from the survey: `docs.code` lists every folder with
   behaviour, `docs.docs` every documentation path. Set a `[plan]` key only where the
   project's path differs from the default. `[verify]`: when the survey found a harness
   that starts the product and runs its flows, its commands go in `e2e` (and the
   smoke subset in `smoke`); otherwise both stay empty and the harness package builds
   it. The destroy gate asks before this write: that is expected; say so before you
   write. Then check it with the loader until it exits 0.
3. **Lens files** in `.claude/orchestration/lenses/`, from `lens.md`: `correctness.md`
   always (the domain truth: its sources, what to check, its invariants, five or so
   concrete inputs to trace), and `ux.md` when `paths.ux` is not empty. Add
   `reliability.md` or another lens only where the survey found something specific to
   say. Short: under 40 lines each. The destroy gate asks before each of these writes
   too: lens files are the profile.
4. **Settings.** Merge `settings.json` into the project's `.claude/settings.json`: add
   the `enabledPlugins` entry and the `PreToolUse` stub hook, and keep every key and hook
   the file already has. Never replace the file. The destroy gate asks here too.
5. **Documents**, each `create` or `append` from the mapping: `CLAUDE.md` (and
   `AGENTS.md` byte-identical, when the project keeps both), the plan, `PROCESS.md`, the
   ADR index, the spec template, the feature map (`FEATURES.md`, with a row for each flow
   the user named or the survey found, `smoke` marked), the log index, the PR template,
   and `ci.yml` when the
   project has no CI. CI gets one step per gate command, after the setup steps the
   toolchain needs; those install from the lockfile only. Before them comes the
   secret-scan step (`{{secret_scan}}`): `gitleaks` or `infisical scan` over the pull
   request's commits, with the scanner installed at a version you looked up and pinned,
   never `latest` and never a script piped into a shell. If you cannot pin one, write a
   `TODO(adopt)` line there, and the scan becomes part of the safeguards package. A
   project that has CI already keeps its workflow: the scan step goes in the safeguards
   package. The ADR (`adr-orchestrated-development.md`) takes the next free
   number. Its status is `Accepted, <date> (by the user, approving the adoption)`, or
   stays `Proposed` when the user said so: only the user accepts it, and the approval
   is that acceptance.
6. **Seed packages.** Replace the plan's example row with the rest of the bootstrap
   (the orchestration model, section 13), one row and one short spec each, from the spec
   template, with IDs that fit the plan's scheme:
   - **access** (owner `human`): the wall around production (the orchestration model,
     section 12). The access inventory; the secrets manager, **1Password unless the
     project already runs Infisical or the user picks it**: vaults `<project>-dev` and
     `<project>-prod`, an item per platform environment (`railway-development`,
     `railway-production`) with one field per **secret**, every secret moved there from
     the platform and from local files (rotating any that ever showed in a transcript, log
     or commit), and `scripts/push_secrets.py` from the template to copy each item to its
     environment (the user runs the production push); plain settings in
     `config/development.env` and `config/production.env`, committed, read by the app
     from the file `APP_ENV` names (`APP_ENV` is the one plain variable on the platform;
     defaults stay in code; the platform's own references stay on the platform); credentials that act in the real
     world with no test account go in the `-prod` vault only; tokens scoped to this
     project and to the **development**
     environments only, with expiry dates and no account-wide token; production's
     auto-deploy switched off, so it deploys only when the user starts it; branch
     protection on the main branch (pull request and the required check, no force push,
     no deletion, nobody exempt). A private repository on a git host plan without branch
     protection (GitHub Free) needs a paid plan for it: ask the user, and if they go
     without, the spec records the choice and that the merge guard is then the only check
     on the main branch. The agent's database role owns the development
     database; in production it gets no role, or a read-only one on named schemas. In
     the secrets manager the agent gets **its own identity**: a 1Password service account
     with read access to this project's `-dev` vault only, or an Infisical machine
     identity with the Viewer role in a project without production values. Its token is
     stored once with `session_secrets.py setup` (step 1.4; done already when adopt found
     the service account), and the plugin's session-start hook loads the agent's tokens
     from `.claude/session-secrets.json`. The agent's git host token is fine-grained, for
     this repository only: contents and pull requests read and write, actions and commit
     statuses read (the merge guard reads CI from them), and no administration,
     environments or deployments permission. The user keeps no CLI login
     of the hosting platform and no admin session of the secrets manager on this
     machine. Real values leave every `.env` file. Its Verify steps prove the wall: each
     agent credential pointed at production is refused (a call that changes nothing even
     if allowed, never a write and never a listing that prints values), a direct push to
     the main branch is refused (where there is branch protection), the identity cannot open the `-prod` vault (a listing of
     item names, never a value), and `push_secrets.py development --check` reports
     nothing only on the platform;
   - **end-to-end harness** (owner `orchestrator`, unless `verify.e2e` is set; first among
     the orchestrator's packages, and every package that changes what the product does
     depends on it; its spec contains the words "end-to-end harness", which is how the
     orchestrator finds it): one command that starts the product (against local services,
     or development) and runs every `active` flow in the feature map the way its user
     would, through the real entry point: a browser test tool for a web interface
     (Playwright, unless the project already uses another), requests to the running
     service for an API, the built binary for a command-line tool. It prints one line per
     flow ID, pass or fail; on a failure, the step that failed and the evidence (a
     screenshot or trace for a page, the request and response for an API), saved to a
     folder that git ignores. It waits for conditions, never for a fixed time, and runs
     in a few minutes. A smoke subset (the flows marked `smoke`) runs against the
     development deployment. The tool installs under the dependency safeguards (release
     age, no install scripts unless allowed by name; a browser download is the tool's own
     setup step, named in the spec). The run joins CI's required check where the product
     can start in CI. The package adds the `[verify]` commands to the profile, which the
     destroy gate puts to the user. Its Verify steps: the run passes every flow; a flow
     broken on purpose in a scratch branch fails it with the step and the evidence; the
     smoke run passes against development;
   - **dev rebuild** (owner `orchestrator`, unless the safeguard is `done`): one command
     that takes an empty development environment to a working one: migrations, a seed
     script with invented data (never a copy of production), and whatever else
     development holds outside the database (files in storage, test users in a sign-in
     service, webhooks), with development's variables pushed from the `-dev` vault by
     `push_secrets.py development`. Everything someone set up in development by hand goes into it.
     Its Verify steps run the command against an empty database and show the app and the
     end-to-end tests working on the result;
   - **backup** (owner `human`, only when the project has a database and the backup
     safeguard is not `done`): a scheduled dump of each database to storage at another
     provider, written with a credential that can add files and cannot delete them, and
     kept out of the agent's reach. Its Verify steps: a dump from the last day exists; a
     delete with the backup credential is refused; one restore into a scratch database
     succeeds, with a row count that matches. The user may have the orchestrator write
     the job; the storage account and its credential are the user's;
   - **safeguards** (owner `orchestrator`, for the rows that are not `done`): the
     package manager's minimum release age set to 7 days and dependency install scripts
     off (npm: `min-release-age` and `ignore-scripts` in `.npmrc`; pnpm:
     `minimumReleaseAge`, in minutes, in `pnpm-workspace.yaml`; check the names against
     the documentation of the installed version; another package manager: the settings
     its documentation names, and if it has none, the spec says so and the row stays
     open as a question for the user), CI installing from the lockfile only,
     and the secret-scan step in CI when adopt did not write it. Its Verify steps print
     the active settings and show a CI run in which the scan ran. A package that needs
     its install script is allowed by name, and listed in the spec for the user;
   - **docs and boundary tests** (owner `orchestrator`): the doc indexes list every doc,
     links resolve, `CLAUDE.md` and `AGENTS.md` match, every ADR is indexed, and the
     project's architectural boundaries are tests;
   - **event table and heartbeat** (owner `orchestrator`, only when the project has a
     database): copy `log_event.sql` next to its spec, as `<ID>-log_event.sql`, for the
     implementer to start from;
   - the user's own first packages, when they named any, each with the flows it adds or
     changes under "End to end", and the harness package among its dependencies.

   Specs of packages the user cannot notice (access, backup, safeguards, docs and
   boundary tests) say `End to end: none` with the reason, so they can run before the
   harness. The dev rebuild and the event table name the smoke flows, so they wait for it.

## 5. Verify

Run these and keep their real output for the report:
1. the profile loader: exit 0;
2. `git grep -n "{{[a-z_]*}}"` over the files you wrote: no hits (GitHub's `${{ ... }}`
   in a workflow is not a placeholder);
3. each `repo.gates` command once, in the repo root. A failing gate is not yours to fix:
   report it, and it becomes the first package or an open question;
4. `git diff --stat` against the main branch: only the files in the approved mapping
   changed.

Then commit on the `adopt-athena-orchestrator` branch: `Adopt athena-orchestrator` plus the list of
created and appended files, and **land it on the main branch**: the user approved exactly
this change in step 3, so they never merge it by hand.
- **No remote**: `git switch <main>`, `git merge --ff-only adopt-athena-orchestrator`, then
  delete the branch.
- **A remote**: push the branch, open a PR (`gh pr create`) with the mapping as its body,
  wait for its checks, then `gh pr merge --squash --delete-branch`, and pull the main
  branch. The merge guard applies: if it or a check refuses, stop and report why; never
  work around it.

Either way, check afterwards that `git show <main>:.claude/orchestration/project.toml`
works: the orchestrator refuses to run until the profile is on the main branch.

## 6. The `/athena` shortcut

Plugin skills are always namespaced, so the plugin ships a user-level shortcut that makes
`/athena` work in every project. Copy `${CLAUDE_PLUGIN_ROOT}/shim/athena/SKILL.md` to
`~/.claude/skills/athena/SKILL.md` when that file does not exist. When it exists:
- it is the plugin's shim (its description starts with `athena-orchestrator shortcut`) and
  differs from the plugin's copy: replace it with the plugin's copy, and say so;
- otherwise it is the user's own `athena` skill: never touch it. Tell the user that
  `/athena` is theirs, and that the orchestrator is `/athena-orchestrator:orchestrate`.

## 7. Report

One screen:
- the project's state (new or existing) and the mapping as applied: created, mapped,
  appended, kept, skipped;
- the verify output from step 5, trimmed;
- every `TODO(adopt)` line, with its file and question;
- the **safeguards** table: each row and its status. A tracked `.env` file that is not
  an example file is named first. You have not read it: the user checks whether it holds
  real values, and if it does, rotates them and moves them to the secrets manager;
- **what the user does next**, in order:
  1. only if they left the orchestration ADR `Proposed`: accept it when ready (any
     Claude session can mark it Accepted on their word), since the orchestrator will not
     run before;
  2. do the **access** package (owner `human`), and fill in the plan's access inventory;
  3. do the **backup** package (owner `human`) when there is one, before the first
     package that writes to a real database;
  4. make CI's check name match `merge.required_check`, and require it in the branch
     protection of the main branch; switch on the git host's secret scanning and push
     protection for the repository;
  5. switch off auto-deploy for the production environment, if the access package has
     not: from now on production deploys only when they start it;
  6. start a new Claude Code session in the repo, so the plugin's hooks load, and run
     `/athena`. When there is no end-to-end harness yet, its package runs first: until it
     lands, packages that change what the product does wait, because none of them can
     be done without being seen working;
- **what no plugin can do for them** (the orchestration model, section 12.6), in four
  lines: a passkey or hardware key on email, the git host, the hosting platform, the
  secrets manager and the domain registrar; a password manager instead of
  browser-saved passwords; a standard, non-administrator user for daily work; a
  repository from an unknown source opened in a cloud development environment, never
  trusted straight away.

There is no end phase to switch to. When an engagement ends, the user revokes the
credentials in the access inventory (each row says how); the agent never held a
production credential, so production needs no rotation unless a value leaked.
