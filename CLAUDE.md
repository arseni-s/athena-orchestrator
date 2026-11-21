# athena-orchestrator

A Claude Code **plugin** that packages the orchestration model: an orchestrator session
that runs a plan of work packages, delegates coding to an implementer subagent and review
to single-lens reviewer subagents, logs every decision, and merges each package to test
once the user approves its summary. The design is
[docs/MODEL.md](docs/MODEL.md). Read it fully before you build anything; it is the spec.

**The name.** The plugin is `athena-orchestrator`, so that a stranger can tell what it
does from a plugin list. It was `athena-ergane` until 13 Nov 2026; this repo's folder and
[docs/TRIAL.md](docs/TRIAL.md), a record of runs under the old name, still use that.
*Athena Ergane*, "Athena the Worker", was Athena's title as patron of
skilled craft. She guided craftsmen rather than doing their work: she helped build the
*Argo* and the Trojan Horse, and she shared a temple and a festival with Hephaestus. The
orchestrator does the same: it guides skilled subagents and never codes itself. The
review panel may be called **Argus**, after the hundred-eyed watchman. He was beaten only
when monotony lulled every eye to sleep, which is why reviewers start fresh, stay narrow
and work to short budgets. Use `athena-orchestrator` everywhere; the user-level shortcut
stays `/athena`.

**Status: bootstrapping.** Steps 1–9 are done: the skeleton, the profile schema
([docs/PROFILE.md](docs/PROFILE.md)) with an example, the agents, the `orchestrate`
skill, the gates (`scripts/athena_profile.py`, `destroy_gate.py`, `ops_gate.py`,
`docs_gate.py`, wired in `hooks/hooks.json`), the templates (`templates/README.md`
lists each one, its target and its `{{placeholders}}`), the `adopt` skill, and
the `/athena` shortcut (`shim/athena/SKILL.md`). Step 10, the
trial, is done as far as a local repo allows (below).

**Decisions from the design review (12 Nov 2026)**. They override the source material
wherever it differs:
- **One project is one repository.** No lanes, no sync check, no companion branches.
- **Development and production, not phases (19 Nov 2026)**, MODEL.md section 12. The agent
  has full control of the development environments, resets and deletes included, to test
  end to end. It holds no credential that reaches production, and the user deploys
  production by hand (auto-deploy off, a chosen commit from the platform's dashboard).
  Development rebuilds from scratch with one command, and anything set up there by hand
  becomes seed or setup code. `destroy_gate.py` denies only what reaches beyond
  development: the platform project or an environment, the repository, the main branch,
  the secrets manager. This replaced the `development`/`observe` phases, the `close-out`
  skill and `deploy.freeze_check`: a project rarely ends cleanly, and the user now
  decides when production deploys. The engine knows no dates, deadlines or checkpoints.
- **Platform rules cover Railway, git, gh, `docker push`, and the 1Password and Infisical
  CLIs** only. Add another platform's rules when a project uses it.
- **1Password is the default secrets manager (19 Nov 2026)**, MODEL.md section 12.3. Every
  secret lives there once, in a `-dev` and a `-prod` vault per project, one item per
  platform environment. Plain settings live in `config/<environment>.env`, committed and
  read by the app through `APP_ENV`; a change to `config/production.env` always gets the
  ops and security lenses and is flagged. No import mode: secrets are entered by hand,
  once. `templates/push_secrets.py` copies an item to its Railway
  environment (values on stdin; production with `--skip-deploys`, run by the user only).
  The agent's service account reads the `-dev` vaults only. Infisical stays supported for
  projects that use it; its free plan's per-account limits ruled it out as the default.
  Injection hides a value from the transcript, not from the agent, so development holds
  only values that are cheap to lose, and a credential with no test account stays in
  production.
- **The agent's tokens load at session start (21 Nov 2026)**, MODEL.md section 12.3. One
  1Password service account per project, opening only its `-dev` vault; the user stores
  its token once with `scripts/session_secrets.py setup` (adopt step 1.4 opens the
  window), which writes `.claude/session-secrets.json` from what the token opens. The
  plugin's SessionStart hook loads the variables; the merge guard reads `GH_TOKEN` itself,
  and reads CI from Actions jobs when a fine-grained token cannot read check runs. This
  replaced a launcher, which left an editor opened any other way without tokens.
- **Done means it ran (21 Nov 2026)**, MODEL.md section 4.1. A package that changes what
  the product does is done only when the running product did it: `verify.e2e` starts the
  product and runs every flow in the feature map (`docs/FEATURES.md`) at the gates and
  after the rebase, and `verify.smoke` checks development after each merge. Until a
  project has a harness, `adopt` seeds an "end-to-end harness" package and product
  packages wait for it. With it: reviewers read the spec, lens files, hard rules and
  feature map from the main branch, lens files sit behind the destroy gate's ask, each
  review names the commit it read, a pre-existing problem never blocks, flaky tests are
  fixed at the cause, invariants get property tests, and a `miss` proposes a lens rule.
  From an article on how the Claude Code team verifies; its observe-mode gate with a
  two-block escape and its single tuned reviewer were left out on purpose (MODEL.md 14).
- **The broker** ([docs/BROKER.md](docs/BROKER.md)) is a design note. Build it when a
  project needs it.
- The reliability and UX lenses are general; a project's specifics go in its lens files.
- **Every merge waits for the user (13 Nov 2026).** Per package the orchestrator builds,
  reviews and opens the PR, then presents an approval summary (what changed, how it was
  checked, flagged decisions, questions) and merges only on the user's "approved". A
  requested change is a fix round outside the round cap. `adopt` lands the adoption
  itself: approving its mapping is the review.
- **Secrets and safeguards (15 Nov 2026)**, MODEL.md sections 12.3 and 12.6. Infisical is
  the secrets manager the gates know: its commands that print values or a token are
  denied, a secret or folder delete is denied, and the command an injector runs
  (`infisical run --`, `railway run`, `railway ssh`) is read too. The agent has its own
  read-only identity there, never the user's login. Every project's plan has a
  "Safeguards" table: an off-platform backup with a tested restore, dependency installs
  with a 7-day release age and no install scripts, a secret scan in CI, and that
  identity. **No container for the agent and no credential broker by default**: both
  were weighed, with Infisical Agent Vault (BROKER.md), and left for a project that
  needs them.
- **One orchestrator per repo, enforced (18 Nov 2026)**, MODEL.md section 3.3. A lease for
  parallel sessions was ported from a project without git, then weighed and left out: the
  user's approval sets the pace, and parallel branches would conflict on the plan file.
  Instead `scripts/athena_lock.py` gives the orchestrator a lock in the git common
  directory; a second one stops. Two rules came with it: no hand-offs to the user
  mid-task, and no whole-folder write-back over a change made after the load.

**Trial (step 10)**, recorded in [docs/TRIAL.md](docs/TRIAL.md). Run 1 drove the
installed hooks with sample events and found `installed_plugins.json` at the stub's
default path. Run 2, a real session, showed that **in bypass-permissions mode a hook's
"deny" holds but its "ask" is ignored**, so every gate now denies what it would ask in
that mode; it also found the destroy gate missed a delete written into a script and then
run, now closed. Run 3 ran `adopt` and `/athena` end to end in a real session on a
throwaway local repo; both passed, up to the PR step that needs a remote. Not yet
trialled: the PR, CI and merge path and a fix round, which wait for a real project, the
dev/prod split of 19 Nov 2026, and the end-to-end run and smoke check of 21 Nov 2026.

## Hard rules

- **This repo is public. No client content anywhere in it.** No client names, domains,
  data or paths, in the engine, the docs, the tests or a commit message. The boundary
  test's forbidden words live in `tests/client_terms.txt`, which is gitignored; without
  it the test skips. Everything specific to
  one project lives in that project's **profile** (`.claude/orchestration/project.toml`
  and `lenses/*.md`). Test: could a second, unrelated project use this file unchanged? If
  not, it belongs in a profile.
- **Every change under `plugins/` bumps `version`** in
  `plugins/orchestrator/.claude-plugin/plugin.json`, in the same commit (semver: patch
  for a fix, minor for a feature or behaviour change). Installs from git update by
  version, so an unbumped change never reaches users.
- **Gates fail closed.** A hook that crashes, cannot parse a command, or cannot find its
  config answers "ask" or "deny", never "allow".
- **Test gates by importing them** and passing commands as strings. Never run the
  dangerous command to see whether the gate catches it. Never write files through a
  shell heredoc.
- Hooks are Python 3, **standard library only**, and must work on Windows (Git Bash and
  PowerShell) and POSIX. That is why the profile is TOML: Python 3.11+ reads it with
  the built-in `tomllib`, and the standard library has no YAML parser.
- `claude plugin validate --strict .` and `claude plugin validate --strict plugins/orchestrator`
  pass before every commit, and so do the tests: `python -I -m unittest discover -s tests`
  (standard library `unittest`, no installs). `tests/test_boundary.py` enforces the first
  rule; `tests/test_agents.py` keeps the agents' shared Rubric, Safety and Modes sections
  identical, so change them in every agent at once. `tests/test_templates.py` keeps the
  templates listed, their placeholders documented, and their tables and PR body in step
  with the `orchestrate` skill. `tests/destroy_gate_cases.json` is the
  destroy gate's case list: add a case with every rule change.
- Docs change with code. `docs/MODEL.md` is updated whenever the design changes.
- Keep it small. No speculative options; add a profile setting only when a real
  project needs it.

## Target layout

```
.claude-plugin/marketplace.json        this repo is its own marketplace
plugins/orchestrator/
  .claude-plugin/plugin.json           name "athena-orchestrator", version
  skills/orchestrate/SKILL.md          the loop, reading the project profile
  skills/adopt/SKILL.md                set up a new or existing project
  agents/*.md                          implementer, review-*, finding-verifier
  hooks/hooks.json, scripts/*.py       destroy gate, ops gate + merge guard, docs gate, orchestrator lock
  templates/                           CLAUDE.md, plan, PROCESS.md, spec, ADR, log, PR, CI, log-table SQL
  shim/athena/SKILL.md                 user-level shortcut, copied to ~/.claude/skills/athena/
docs/MODEL.md                          the design
docs/PROFILE.md                        project.toml schema and lens-file format
docs/BROKER.md                         design note: the access broker (not built)
examples/sample-profile/               a fictional project's profile
tests/                                 gate tests (import + command strings)
```

## Build order

Each step is one commit, validated.

1. Skeleton: `marketplace.json`, `plugin.json`, empty component folders; validate.
2. Profile schema (`docs/PROFILE.md`) and a fictional example profile. List every value
   the source skill, agents and hooks hard-code (paths, gate commands, panel triggers,
   freeze dates, prod CLIs) and decide: engine or profile.
3. Agents: generalize from the source. Each reviewer reads its project lens file from the
   profile.
4. `orchestrate` skill: generalize from the source, reading the profile.
5. Hooks: destroy gate, ops gate + merge guard, docs gate, configured from the profile, with tests.
   Add the fallback stub that projects keep in their own settings ("gate missing → ask").
6. Templates.
7. `adopt` skill (new project, and existing project: map what exists, never overwrite).
8. `close-out` skill (MODEL.md section 12). Removed on 19 Nov 2026 with the access phases.
9. The `/athena` shortcut. Plugin skills are always namespaced (`/athena-orchestrator:orchestrate`),
   with no alias mechanism, but user-level skills are not. A user-level skill `athena`
   (`~/.claude/skills/athena/SKILL.md`) passes its arguments straight to the
   `athena-orchestrator:orchestrate` skill, so `/athena`, `/athena B5` and `/athena all` work in
   every project. `adopt` installs it if it is missing, and never overwrites a user's own
   `athena` skill.
10. Trial: adopt a throwaway sample project end to end and record what broke.
