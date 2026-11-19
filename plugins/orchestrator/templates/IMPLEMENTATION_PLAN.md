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

One row per credential the agent holds, the secrets manager and the git host included.
The agent has no access that is not listed here. No row is an account-wide token, no row
that writes reaches production, and each token has an expiry date where the platform
offers one. Every grant and every revocation is a decision log entry. When an engagement
ends, the user revokes each row as its last column says.

| Platform | Used for | Credential | Reaches (environments) | Injected by | Revoked by | Status |
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
| The agent's own identity in the secrets manager | <the 1Password service account (or Infisical identity); read access to the `-dev` vault only; where its token is kept> | <its row in the access inventory; it cannot open the `-prod` vault> | todo |
| Development rebuilds from scratch with one command | <the command; the migrations, the seed (invented data) and the setup it runs; what it recreates outside the database> | <its run against an empty environment, with the output, and the date> | todo |
| Production is out of the agent's reach | <production's auto-deploy off, deployed by the user by hand; branch protection on {{main}}; no CLI login of the platform on the agent's machine> | <each agent credential refused on production, and a direct push to {{main}} refused, with the date> | todo |
