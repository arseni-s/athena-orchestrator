# Implementation plan: {{project_name}}

**The only place where work status lives.** Every session, human or orchestrator, starts
here. How the work is done: [PROCESS.md](PROCESS.md). Every decision the orchestrator
makes: [decisions/log/](decisions/log/README.md).

## Status

Statuses: `todo` · `in progress (<date>, <branch>, <who>)` · `waiting for approval` ·
`blocked: <reason>` · `done (PR #<n>)` · `cut` (only the user sets it). Rows owned by
`human` are the user's; the orchestrator never picks them. Specs are in
[work/](work/README.md).

| ID | Work package | Owner | Depends on | Target | Status |
|---|---|---|---|---|---|
| <ID> | [<title>](work/<ID>-<slug>.md) | orchestrator | — | <date> | todo |

## Open questions

Each question has a safe default, so none blocks the work. A question with no safe default
says "none: ask the user", and the orchestrator stops the package that needs it. When an
answer arrives, apply it and remove the row.

| # | Question | Safe default until answered | Where it lands |
|---|---|---|---|

## Follow-up register

**Every open follow-up lives here**, with the package that will do it, or `unscheduled`.
When a package is claimed, its open rows go into the implementer's brief and are in scope.
When it merges, its rows are closed and new ones are added, in the same commit. The
`unscheduled` rows are listed in every session report, for the user to schedule or drop.

| Ref | Follow-up | Target | Status |
|---|---|---|---|

## Access inventory

One row per platform the agent works on. The agent has no access that is not listed here.
Every grant and every revocation is a decision log entry. The close-out package
(`/athena-orchestrator:close-out`) revokes or rotates each row and records its final status.

| Platform | Used for | Credential | Scope | Injected by | At close-out | Status |
|---|---|---|---|---|---|---|
