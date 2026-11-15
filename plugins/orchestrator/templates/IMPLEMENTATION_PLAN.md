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

One row per platform the agent works on, the secrets manager included: the agent's own
identity there is a row like any other. The agent has no access that is not listed here.
No row is an account-wide token, and each token has an expiry date where the platform
offers one. Every grant and every revocation is a decision log entry. The close-out
package (`/athena-orchestrator:close-out`) revokes or rotates each row and records its
final status.

| Platform | Used for | Credential | Scope | Injected by | At close-out | Status |
|---|---|---|---|---|---|---|

## Safeguards

What still protects the project when a machine or a credential is compromised. A row is
`done (<date>)` only with its proof, or `not needed: <reason>` (no database, so no
backup). The orchestrator lists every other row in each session report. Switching one off
needs the user's word.

| Safeguard | How it is done here | Proved by | Status |
|---|---|---|---|
| A backup the platform cannot delete, with a tested restore | <where the dumps go, how often, and the credential that can add but not delete> | <the date of the last tested restore, and its output> | todo |
| Dependencies installed late and without scripts | <the package manager; where its release-age (7 days) and install-script settings are set; CI installs from the lockfile> | <the command that prints the active settings, and its output> | todo |
| Committed secrets are caught | <push protection on the git host; the scan step in CI> | <a CI run in which the scan ran> | todo |
| The agent's own identity in the secrets manager | <its name; read-only; no production values; the access token's lifetime> | <its row in the access inventory> | todo |
