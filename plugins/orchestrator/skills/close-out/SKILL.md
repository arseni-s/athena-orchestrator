---
name: close-out
description: End active development on an athena-orchestrator project. It turns the plan's access inventory into a close-out work package, hands the user the revocations and rotations to do, proves the end state with real calls, records it, and prepares the move to the read-only observe phase. Use when the user types /athena-orchestrator:close-out, or says development is finished and access should be revoked.
argument-hint: "[verify]  (default: prepare; verify runs the checks after the user's steps)"
---

# Close out a project

Active development has ended. The agent keeps its sight and loses its power: write access
to the platforms and the database is revoked, everything the agent could reach is
rotated, and the profile's `access.phase` becomes `observe`, after which the gates deny
deploys, merges and platform changes. The rules are the orchestration model's section 12
(`docs/MODEL.md` in the plugin's repository).

The close-out is a **work package**, not a reminder: it has a plan row, a spec with
Verify steps, a decision log and a PR. Two things in it are always the user's:
- **revoking and rotating credentials.** You never revoke, delete or rotate a credential
  yourself, and you never see a new value. You list each step; the user does it, in the
  platform's console or their own terminal;
- **changing `access.phase`**, and merging the PR that changes it.

Argument: none (or `prepare`) runs steps 1 to 3 and stops at the hand-over. `verify` runs
steps 4 to 6, after the user says their steps are done.

## 1. Check that the project can close

1. `python "${CLAUDE_PLUGIN_ROOT}/scripts/athena_profile.py" check` in the repo root
   (`python3` where needed). Exit 2: there is no profile, so there is nothing to close
   out; stop. Exit 1: stop and pass on the problems. Phase already `observe`: report the
   access inventory's final statuses and stop.
2. Read the plan (`plan.plan`), and stop with a list of what to do first when any of
   these fail:
   - **No package is running**: no row is `in progress` or `waiting for approval`, and
     `git worktree list` shows no package worktrees. A package left open needs the user's
     call: finish it first, or have it `cut`.
   - **The main branch is green**: the last CI run on `repo.main` passed
     (`gh run list --branch <main> --limit 1`).
   - **The access inventory is complete**: the plan has an "Access inventory" table, and
     every row has a credential, its scope and an "At close-out" action. Access the agent
     uses that is not in the table (the survey below finds it) is added first, by the
     user.
   - **The observe phase can see**: there is a read-only database role (when the project
     has a database), and at least one log channel the agent can read without a platform
     token: the app event table, or a log service with a read-only query token. Without
     one, the project would go blind: the missing piece becomes a package to finish first.
3. **Survey what the agent can reach**, to check the inventory against: the secrets
   manager's project and machine identity, platform tokens in the session's injected
   environment (names only: never print a value), CI secrets the agent set
   (`gh secret list` prints names, not values), database roles named in the inventory,
   MCP servers in `.claude/settings.json` and `.mcp.json`. List any credential the
   inventory does not name.

## 2. Write the close-out package

On a new branch `wp/<ID>-close-out` from the main branch (the ID fits the plan's scheme):

1. **Plan row**: `<ID> | Close-out | human | <every open row it waits on> | <date> |
   in progress (<date>, wp/<ID>-close-out, close-out)`.
2. **Spec** `docs/work/<ID>-close-out.md` (`plan.specs`), from the spec template in that
   folder's `README.md`:
   - **Scope**: one checklist line per inventory row: the platform, the credential, the
     action (revoke, rotate, or keep read-only), who does it (the user), and how the
     result is proved. Then the database: the write role loses its login (or is revoked)
     and the read-only role is kept. Then the phase change.
   - **Verify**: the steps in section 4, written out with this project's commands. Each
     one names the output that passes.
3. **Log file** `<log folder>/<ID>.md`, from the log template: one decision of kind
   `access` per inventory row, with **Revise by** naming how to re-grant it, and
   **Flag: review** on each.
4. Commit: `<ID>: close-out package`. Push the branch.

## 3. Hand over to the user

Send one message with:
- the checklist, in the order to do it: rotations first (so the app gets new values
  while the old tokens still work for a last check), then revocations, then the write
  role. For each line: where to do it (the console page, or the command for the user's
  own terminal) and what "done" looks like;
- the reminder that platform variables are synced from the secrets manager, so a
  rotation reaches every environment by itself; a credential the manager cannot rotate
  is rotated by hand and its new value goes **only** into the secrets manager;
- the ask: run `/athena-orchestrator:close-out verify` when the steps are done.

Set the plan row to `waiting for approval`, commit and push. Stop. Send one push
notification if a push tool is available: the project name and "close-out waiting on
you", never content.

## 4. Verify (`verify`)

Run each check in the repo root and keep the real output. Never print a secret: inject
credentials with the secrets manager's runner, and show only results and exit codes.
- **Every revoked token is refused**: one real, read-only call with it (for example the
  platform CLI's `whoami`), which must fail with an authorization error. A call that
  succeeds is a failed check.
- **The rotated credentials work**: the app is healthy on every environment, judged by
  what the agent may still read: the health endpoint, the deploy status the platform
  reports to the git host, a fresh heartbeat row.
- **The read-only role reads and cannot write**: a `SELECT` on a named schema succeeds,
  and a write fails. Run the write inside a transaction that is rolled back, so it
  changes nothing even if the role is wrong:
  `BEGIN; INSERT INTO <a table> DEFAULT VALUES; ROLLBACK;` must fail with a read-only or
  permission error.
- **The logs still reach the agent**: the newest rows of the event table, or a query on
  the log service, through the observe-phase channel.
- **Every inventory row has a final status** (`revoked <date>`, `rotated <date>`, or
  `read-only`).

A check that fails is reported with its output, and the row stays open: never mark a row
done on a check that did not pass. When a failure needs a user step, hand it back as in
section 3 and stop.

## 5. Record

On the close-out branch, in one commit:
- the access inventory's **Status** column, row by row, with the date;
- the log file: the Verify output, trimmed, in its Summary and per decision, and its row
  in the log index;
- the plan row: `done (PR #<n>)`, once the PR exists;
- the follow-up register: rows still open are listed in the PR; they stay `unscheduled`
  for when development re-opens.

Open the PR with the orchestrator's body (What changed, Verify with real output, Gates,
Review panel `none: the user reviews`, Decisions, Follow-ups).

## 6. The phase change

Tell the user the last two steps, which are theirs:
1. set `phase = "observe"` in `.claude/orchestration/project.toml` on the close-out
   branch (the destroy gate asks before any edit to that file, so it cannot happen
   silently), and push;
2. merge the PR. From then on this session and every later one can read, and cannot
   deploy, merge or change a platform.

After the merge, run the profile check once more and report `phase: observe`.

## Re-opening

New development work re-opens the project, and only the user does it: re-grant access
from the inventory (each grant a decision log entry), set `phase = "development"`, and
plan the work. It ends with another close-out.
