# ADR-{{adr_number}}: Orchestrated development

**Status:** Proposed, {{date}}. Only the user accepts it.

## Context

Reviewing every diff by hand is the bottleneck of a one- or two-person team working with
parallel AI sessions, and the sessions' output is confident but not always right. The
`athena-orchestrator` plugin replaces diff review with single-lens reviewer subagents and
mechanical gates, and asks the user to read decisions instead.

## Decision

- **An orchestrator session runs the plan** (`/athena`). It picks work packages from
  [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md), delegates coding to an implementer
  subagent and review to a panel of reviewer subagents, and never edits code itself.
- **The panel replaces the user's code review.** Lenses, rubric and merge conditions are in
  [PROCESS.md](../PROCESS.md).
- **Merge on approval**: for each package the orchestrator presents a summary (what
  changed, how it was checked, flagged decisions, questions). When the user replies
  "approved", it squash-merges to `{{main}}`, provided the merge conditions hold, which
  deploys to {{deploy_dev}}.
- **Full control of development**: it deploys, changes, resets and deletes in the
  development environments as the work requires, with only the access listed in the
  plan's access inventory. Development rebuilds from scratch with one command, and
  anything set up there by hand becomes seed or setup code.
- **Production is the user's**: the orchestrator holds no credential that can change
  {{deploy_prod}}, and production deploys only when the user starts it, by hand.
  Destructive operations that reach beyond development are never run by it, even with
  approval.
- **The user still decides**: ADRs, hard rules, the profile, everything in production,
  weakening a gate, cutting a package, questions without a safe default, and granting
  access.
- **Every decision is written down** in [log/](log/README.md), one file per package, each
  with a way to revise it. Every package is one squash commit, so `git revert` undoes it.
- **Bounded autonomy**: at most 3 fix-and-review rounds per package, then stop.

## Consequences

- Definition of done: gates green, Verify steps run with real output in the PR, docs
  updated, no open Blocker or Major finding, decision log written, approved by the user,
  merged and deployed to development.
- The user reads each package's approval summary and its flagged decisions instead of
  the diff, and nothing merges without their "approved". Nothing reaches production
  until the user deploys it.
- CI, the docs gate and the merge guard matter more, because no human reads the PRs.
- When an engagement ends, the user revokes the credentials in the access inventory.
  There is no phase to switch: the agent never held a production credential.
