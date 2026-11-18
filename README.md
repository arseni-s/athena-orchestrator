# athena-orchestrator

A [Claude Code](https://claude.com/claude-code) plugin that runs your project's plan one
work package at a time. An **orchestrator** session decides; it never writes code. For
each package it:

1. briefs an **implementer** subagent, which builds the package in its own git worktree;
2. runs your gate commands (lint, build, tests) and the spec's Verify steps itself;
3. sends the diff to a panel of narrow **reviewer** subagents (spec, correctness,
   reliability, security, UX), sized by risk, and has a **verifier** check their serious
   findings;
4. sends confirmed findings back for a fix round, logging every decision;
5. opens the PR and shows you a summary: what changed, how it was checked, the decisions
   it flagged, its questions. **It merges only when you say "approved".**

Hooks guard the whole run: destructive commands are denied, platform writes follow the
project's access phase, merges wait for CI and your approval, and code changes must come
with doc changes.

> **Status: early.** Adopting a project and running `/athena` have been trialled end to
> end. The PR → CI → merge path, fix rounds and `close-out` have not yet run on a real
> project. Try it on something low-stakes first.

## Install

Requires Claude Code and Python 3.11+ (the hooks use only the standard library).

```sh
claude plugin marketplace add arseni-s/athena-orchestrator
cd your-project
claude plugin install athena-orchestrator@athena-orchestrator --scope project
```

Or, inside a session: `/plugin` → add marketplace `arseni-s/athena-orchestrator` → install
`athena-orchestrator`, at project scope.

Updates: `claude plugin marketplace update athena-orchestrator`, then update the plugin
from `/plugin`.

## Start

In a **new** session in the project (so the hooks load), not in bypass-permissions mode:

```
/athena-orchestrator:adopt
```

`adopt` surveys the repo and shows you a mapping of what it will create, append, point
to or skip. It never overwrites a file and writes nothing until you approve. Then it
writes the profile (`.claude/orchestration/project.toml`), the plan, the process docs,
the PR template and CI, and installs the `/athena` shortcut. It lists the steps left to
you; then, in a new session:

```
/athena          next package
/athena B5       a given package
/athena all      keep going until the plan is done or something needs you
```

One orchestrator runs per repo. A second `/athena` in the same repo, or in one of its
worktrees, stops and says which session holds it.

## Your plan

Plan however you like, then put it in this shape (a planning chat with Claude can convert
it):

- **One plan file** (default `docs/IMPLEMENTATION_PLAN.md`): a status table (ID, package,
  owner, depends on, target, status), open questions each with a safe default, a
  follow-up register, an access inventory and a safeguards table. The orchestrator picks
  the first `todo` row whose dependencies are done, and never a row owned by `human`.
- **One spec per package** (`docs/work/<ID>-<slug>.md`): goal, scope and what is out of
  it, **Verify** steps a machine can run, and the docs to update.

Packages the size of one reviewable PR, with runnable Verify steps, go best.

## Secrets and safeguards

The agent works with real credentials while it builds, so the plugin limits what a
mistake, a manipulated agent or a poisoned dependency can do with them:

- **Secrets stay out of the session.** Commands get them at runtime from a secrets
  manager (the gates know Infisical: `infisical run -- <command>`). The gates deny
  commands that print them, including the secrets manager's own listing and export
  commands. The agent uses its own read-only identity there, never your login.
- **Destructive commands are denied**, even with your approval: deletes on the hosting
  platform, the git host and the secrets manager, and destructive SQL on a remote
  database. You run those yourself.
- **Four safeguards per project**, tracked in the plan and set up by `adopt`'s first
  packages: a backup the hosting platform cannot delete, with a tested restore;
  dependencies installed only after a 7-day wait and without install scripts; a secret
  scan in CI; and the agent's own identity in the secrets manager.

The gates stop accidents, not a determined process: a program that was handed a secret
can still print it. The reasoning, and what the plugin cannot do for you, is in
[docs/MODEL.md](docs/MODEL.md), section 12.

## Docs

- [docs/MODEL.md](docs/MODEL.md): the design, in full.
- [docs/PROFILE.md](docs/PROFILE.md): the profile and lens-file reference.
- [examples/sample-profile/](examples/sample-profile/): a fictional project's profile.
- [docs/TRIAL.md](docs/TRIAL.md): what the trial runs found.

## License

See [LICENSE](LICENSE).
