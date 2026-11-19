# Development process: the orchestrator

How work packages in {{project_name}} get built, reviewed and merged. The user reads a
short approval summary per package instead of the diff, and approves the merge. Policy: [ADR-{{adr_number}}](decisions/{{adr_number}}-orchestrated-development.md).
Plan and status: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). Every decision the
orchestrator makes: [decisions/log/](decisions/log/README.md). The engine is the
`athena-orchestrator` plugin; this project's settings are its profile,
`.claude/orchestration/project.toml`, and its lens files.

## How to run it

Start Claude Code in this repo and type `/athena` (the next package), `/athena <ID>`, or
`/athena all`. One orchestrator runs per repo: a second `/athena` in the same repo, or in
one of its worktrees, finds the first one's lock and stops. If a session crashed, its lock
frees itself once its Claude process has ended.

## The loop, per work package

1. **Claim**: status `in progress`, a worktree next to the repo (`<repo folder>-wp-<id>`)
   on branch `wp/<id>-<slug>`.
2. **Design review**, when the package touches `paths.design_review` or its spec says
   "plan mode": the implementer writes a plan, and the spec and correctness reviewers
   check it before any code is written.
3. **Implement**: the implementer subagent works in the worktree.
4. **Gates**: the orchestrator re-runs `repo.gates` and the spec's Verify steps itself.
5. **Review panel**: the full or the light panel (below) runs in parallel, one lens per
   reviewer.
6. **Verify findings**: the finding-verifier tries to disprove each Blocker and Major,
   unless two lenses raised it or a safe reproduction shows it.
7. **Decide**: only Blockers and Majors go back to the implementer; Minors and Nits become
   follow-ups. Rounds 2 and later are fix-only. At most 3 rounds, then stop.
8. **PR and decision log**: the PR is opened with the package's log in the same commit.
9. **Approval**: the orchestrator gives you the package's summary: what changed, how it
   was checked, the decisions it flagged for you, and its questions. Ask anything, or ask
   for a change (it goes back to the implementer). Reply **"approved"** to merge.
10. **Merge**: one squash commit per package, when every merge condition holds; the
    orchestrator checks that it landed. A merge deploys to development ({{deploy_dev}}); production waits for you to deploy it.

The orchestrator never edits code. It writes only plan status, the decision log and PR
text.

## Review panel

- **Full panel** (spec, correctness, reliability, security, tests): package IDs in
  `panel.full`, and any diff that touches `paths.full_panel`, whatever its ID.
- **Light panel** (spec, combined): everything else.
- **Docs-only diff**: spec only.
- **Path-triggered**, on either panel: ops for `paths.ops`, UX for `paths.ux`, and on the
  light panel security for `paths.security`.

What each lens checks in this project is in `.claude/orchestration/lenses/`.

## Rubric (all reviewers)

- **Blocker**: user-visible wrong output (here: {{user_visible}}); data loss; a hard rule
  or accepted ADR broken; a leaked secret or personal data; an exploitable hole; faked
  Verify output or a test weakened to pass; a migration that fails in an environment.
- **Major**: likely to fail under realistic conditions (the profile's `rubric.conditions`);
  a spec requirement missing; a critical path without a test; new behaviour without docs.
- **Minor**: real, but unlikely or cheap to fix later.
- **Nit**: style or naming. At most 3 per reviewer, never blocking.

Every finding has a concrete **scenario**: the inputs or state that lead to the wrong
outcome. A finding without one is a Nit at most. A Blocker the verifier cannot disprove
counts as confirmed.

## Merge conditions

The orchestrator merges only when all of these hold:
- CI is green on the PR head commit, including the `{{required_check}}` check;
- the spec's Verify steps were run and their real output is in the PR;
- no confirmed Blocker or Major is open;
- docs are updated (the docs gate passes);
- the branch is rebased on `{{main}}`, with the gates re-run after the rebase;
- the decision log is written and linked, and the follow-up register is updated;
- the PR body follows `.github/pull_request_template.md`;
- you approved the package after reading its summary.

The merge guard enforces the checks, refuses auto-merge, and refuses direct pushes to
`{{main}}`.

## Access

The orchestrator has full control of development ({{deploy_dev}}): it deploys, changes
variables, resets and reseeds databases, and creates and deletes services there without
asking, using only the access in the plan's "Access inventory". Development rebuilds from
scratch with one command, and anything set up there by hand is turned into seed or setup
code, so nothing in it is lost for good.

Production ({{deploy_prod}}) is yours. The orchestrator holds no credential for it, and
production deploys only when you start it, by hand. A decision that changes what
production will do once you deploy it (a migration, a production setting) is flagged for
review, and each session report lists what is ready for production.

## What needs the user

Every merge waits for your "approved" (step 9 above). Besides that, the orchestrator asks
first, every time, for:
- anything a gate denied;
- anything in production;
- accepting or changing an ADR (it may draft one as `Proposed`);
- changing a hard rule in `CLAUDE.md`, or the profile;
- weakening a gate: hooks, CI, branch protection, tests, `[no-docs]` on a change with
  behaviour;
- weakening a safeguard from the plan's "Safeguards" table: the package manager's
  release-age or install-script setting, the secret scan, the backup job, the
  development rebuild;
- cutting a package;
- an open question with no safe default;
- deleting branches or worktrees it did not create;
- granting or widening platform access, or anything that would show a secret's value.

**Destructive operations that reach beyond development are never done by the
orchestrator or a subagent, even with your approval**: deleting or transferring the
hosting platform's project, deleting an environment, deleting the repository, a release or
a CI secret, a force push or delete of `{{main}}`, deleting a secret in the secrets
manager. The orchestrator says what is needed, and you run it in your own terminal. The
destroy gate denies them. Destruction inside development (dropping a table, resetting the
database, deleting a service) is allowed: the rebuild brings it back.

## Revising a decision

Each decision log entry has a **Revise by** line: the setting, file or commit to change.
To undo a whole package, revert its squash commit (`git revert <sha>`). Entries marked
**Flag: review** are the ones to read; the log index counts them per package.

## When something goes wrong

Record the incident in the package's log. Change the rule here, and in the profile or a
lens file, in one PR. If the change is policy, amend the ADR above, which only the user
accepts.
