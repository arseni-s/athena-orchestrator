# The Orchestration Model

A project-agnostic description of an AI-driven development process in which one
**orchestrator** session runs a plan of work packages. Subagents do all of the coding and
reviewing, and every decision is written down so a human can audit and revise it later.

This document is for an agent that is setting the model up in a new project, or working
inside it. Read it fully before you create any files. Section 13 lists what you must
tailor to the project. Everything else is the invariant core.

---

## 1. The problem this solves

A solo developer (or a very small team) with parallel LLM sessions has two bottlenecks:
the human reading every diff, and LLM output that is confident but not always correct.
The model removes the first bottleneck and guards against the second:

- **The human stops reviewing diffs** and reviews **decisions** instead: for each package,
  a short approval summary (what changed, how it was checked, the flagged decisions, the
  open questions). The human's "approved" is what merges it.
- **Independent, single-lens reviewer agents** replace human code review. A verifier
  agent filters out their false positives.
- **Mechanical gates** (hooks, CI, a merge guard) enforce the rules that matter most, so
  no agent can skip them, whatever it believes.
- **Bounded autonomy**: the orchestrator builds, reviews, opens PRs, and has full control
  of the project's development environments; it merges once the human approves the
  package. It holds no credential that can change production, the few destructive
  actions that could reach beyond development never run from it, and it must stop and
  ask for anything that changes policy.

---

## 2. Core principles

1. **The orchestrator decides; it never codes.** It writes only plan status, the decision
   log and PR text. Every change to code, tests, config or specs goes through an
   implementer subagent. This keeps its context small and its judgement independent of
   the work it judges.
2. **Trust nothing self-reported.** The orchestrator re-runs the gates and the Verify
   steps itself. Reviewers re-run at least one Verify step. A "done" with no real output
   is sent back.
3. **One lens per reviewer.** Each reviewer checks one question (spec, domain
   correctness, reliability, security, tests, ops, UX…) and is told to stay out of the
   others. Narrow lenses find more than one generalist does, and they make the findings
   comparable.
4. **Review depth matches risk.** A full panel runs where a bug is user-visible or loses
   data. A light panel runs elsewhere, and docs-only changes get a single reviewer. Risk
   is decided by **package ID and by changed paths**, so a "low-risk" package that
   touches critical code still gets the full panel.
5. **Severity drives action.** Only Blockers and Majors are fixed within a package.
   Minors and Nits become tracked follow-ups. This prevents endless polishing rounds.
6. **Bounded rounds.** At most 3 fix-and-review rounds, then stop and escalate. Rounds 2
   and later are **fix-only**: confirm the fixes and check the fix diff for regressions.
   Do not re-review everything.
7. **Disprove before you fix.** A verifier agent tries to refute each Blocker and Major.
   A false Blocker costs a round and adds risk. A real one waved through costs far more,
   so doubt is resolved on the safe side: an unrefuted Blocker counts as confirmed.
8. **Accepted decisions are binding.** Architecture Decision Records (ADRs) and the hard
   rules outrank the spec, the brief and the agent's opinion. An agent may *draft* an ADR
   as `Proposed`; only the human accepts one.
9. **Write every decision down, with an undo path.** Each non-trivial choice gets a log
   entry with a **Revise by** line (the file, setting or commit to change). Each package
   lands as **one squash commit**, so `git revert` undoes it cleanly.
10. **Prefer the boring option.** Reliability over features, the smaller diff,
    reversible over irreversible, configurable over hard-coded, and existing patterns
    over new ones.
11. **Rules that matter are enforced mechanically.** A written rule that an agent can
    forget will be forgotten eventually. Hooks and CI turn the critical ones into hard
    stops that fail closed.
12. **Docs change with code**, in the same PR, and a gate enforces it.
13. **Full control of development, a wall around production.** The human should not have
    to copy logs, query results or CI output between systems, or approve every deploy. So
    the agent has full control of the project's **development environments**, resets and
    deletes included, to build and test end to end. **Production** is out of its reach:
    it holds no credential that can change it, and the human deploys production by hand,
    from merges they approved. Development must rebuild from scratch with one command, so
    damage there costs minutes. Secrets are injected at runtime and never visible in the
    session, and every credential is scoped to this one project. Details in section 12.

---

## 3. Architecture

```
                         ┌──────────────────────────────┐
           Human ◄──────►│  ORCHESTRATOR (1 per project)│  reads: plan, process, ADRs
   (approvals, flagged   │  decides · never edits code  │  writes: status, decision log, PR
    decisions, ADRs)     └──────┬─────────┬─────────┬───┘
                                │         │         │
                 brief          │         │         │  brief (parallel, one message)
             ┌──────────────────▼──┐   ┌──▼─────────▼──────────────┐
             │ IMPLEMENTER          │   │ REVIEW PANEL (read-only)  │
             │ plan-only | implement│   │ spec · correctness ·      │
             │ | fix round N        │   │ reliability · security ·  │
             │ works in a worktree  │   │ tests · ops · ux · combined│
             └──────────┬───────────┘   └──────────┬────────────────┘
                        │ structured report        │ structured findings
                        ▼                          ▼
                 orchestrator re-runs      ┌──────────────────┐
                 gates + Verify itself     │ FINDING-VERIFIER │ tries to refute
                                           │ Blocker/Major    │ CONFIRMED/REFUTED/
                                           └──────────────────┘ UNCERTAIN
        ─────────────────────────────────────────────────────────────────────
        MECHANICAL LAYER: destroy gate · ops gate · merge guard · docs gate · CI
```

### 3.1 Roles

| Role | Model tier | Writes? | Job |
|---|---|---|---|
| **Orchestrator** | strongest | plan status, log, PR text only | Pick work, brief subagents, re-run gates, decide on findings, present the approval summary, merge on the human's approval, log. |
| **Implementer** | strongest | code in its worktree; commits, never pushes | Build exactly the spec (or a plan, or a fix round). Return a structured report with real output. |
| **Spec reviewer** | mid | no | Scope met, nothing extra, ADRs and boundaries kept, docs updated. Always runs. |
| **Correctness reviewer** | strongest | no | The project's domain truth: is the data or logic right? Thinks in adversarial concrete inputs. |
| **Reliability reviewer** | strongest | no | When something goes wrong, does it fail safely, recover, and say what happened? Thinks in failures. |
| **Tests reviewer** | mid | no | Are the tests honest? Have any been weakened or hollowed out? Is the Verify output real? Is the diff the simplest one? |
| **Security reviewer** | mid | no | Secrets, PII, injection, least privilege, forbidden write paths, dependencies. |
| **Ops reviewer** | mid | no | Migrations, deploy config, scripts, CI, protected windows, runbook. Path-triggered. |
| **UX reviewer** | mid | no | The user interface and its usability: clarity, feedback, errors, forms, consistency, accessibility, devices. Path-triggered. |
| **Combined reviewer** | mid | no | Correctness, reliability and tests in one pass, for the light panel. |
| **Finding-verifier** | strongest | scratch files in temp only | Try to disprove each Blocker and Major finding. It is on the strongest tier because it can dismiss a Blocker. |

Give the strongest tier to the roles whose mistakes are costly: the implementer, the deep
lenses, and the verifier. Lenses that work through a checklist can run on a cheaper model.

### 3.2 Files and records (the system's memory)

| Artifact | Purpose | Owner |
|---|---|---|
| `CLAUDE.md` / `AGENTS.md` | Hard rules, conventions, gotchas. Loaded by every session. Keep the two byte-identical if both exist. | human |
| `docs/IMPLEMENTATION_PLAN.md` | **The only place status lives.** Status table (ID, package, owner, depends on, target, status), open questions with safe defaults, the **follow-up register**. | orchestrator updates status |
| `docs/work/<ID>-<slug>.md` | One spec per work package: goal, scope, **Verify steps** (runnable), docs to update, ADRs that apply. | human / planning session |
| `docs/decisions/NNNN-*.md` | ADRs: accepted, binding, never re-opened except by a new ADR that supersedes. | human accepts |
| `docs/decisions/log/<ID>.md` + index | Decision log, one file per package. | orchestrator |
| `docs/PROCESS.md` | The human-readable process: panels, rubric, merge conditions, approval list. | human |
| `.claude/orchestration/project.toml` | The **profile**: gate commands, panel paths, environments ([PROFILE.md](PROFILE.md)). | human |
| `.claude/orchestration/lenses/*.md` | What each lens means in this project: sources of truth, checks, cases to trace. | human |
| `.claude/rules/*.md` | Path-scoped rules (frontmatter `paths:`), loaded when matching files are touched. | human |

The orchestrator skill, the agent files and the gate hooks are not in the project: they
come from the `athena-orchestrator` plugin, which reads the profile. The project keeps only the
profile and its own documents.

### 3.3 One project, one repository

- A project is **one repository**: the code, the plan, the specs and the decision log
  live together. Work that spans two repositories is two projects, each with its own
  plan.
- Run **one orchestrator per project**, started in the repo so its hooks apply. Never run
  two in the same repo: they would claim the same package, deploy to test over each
  other's checks, and conflict on the plan file in every rebase. The orchestrator takes
  the repo's **lock** at session start (`scripts/athena_lock.py claim`) and gives it back
  at session end. The lock is one file in the git common directory, so every worktree
  shares it. It names the holder's Claude process: a second orchestrator stops, and a
  crashed holder's lock frees itself once its process has ended. A holder it cannot check
  counts as live, and only the human frees that one (`release --force`).
- Parallel orchestrators were weighed (18 Nov 2026) and left out. The human's approval
  sets the pace, not the implementer, and one orchestrator already moves on to
  independent packages while summaries wait. Revisit when packages pile up while the
  human waits for work. Even then, two implementers in one orchestrator come before two
  orchestrators, because one session sees what both touch.
- **Nothing is handed to the human mid-task.** Agents never ask the human to press a
  button, dismiss a prompt, restart an app or copy output across. They script it. A
  desktop app is a viewer that a script reopens, and the work lives in files. The human is
  asked only for an approval or a decision (section 8).
- Each package is claimed in its own **git worktree** next to the repo
  (`<repo>-wp-<id>`) and its own branch (`wp/<id>-<slug>`). No two sessions ever share a
  branch.
- Rows in the plan owned by `human` are the user's. The orchestrator never picks them.

---

## 4. The loop, per work package

**Session start**
1. Read the hard rules, the plan, the process ADRs and PROCESS.md. Leave the large docs to
   the subagents.
2. Check the profile and take the repo's lock (section 3.3; another orchestrator holding
   it means stop). It stops when the adoption is not merged to the main branch, or the
   ADR that grants it its authority is still `Proposed`.
3. **Reconcile status**: for every unfinished row, check git and the PRs to see whether
   the work already landed. Fix any drift, and log it as a `status correction`.
4. Note the follow-up register rows whose target package is done but which are still
   open, and the `unscheduled` rows, for the session report.
5. **Pick** the given ID, or the first `todo` row whose dependencies are done. Never pick
   rows owned by the human.

**Per package**
1. **Claim**: create a fresh worktree from the main branch, commit `in progress (date,
   branch, orchestrator)`, and create the log file. Copy the package's open follow-up
   rows into the brief.
2. **Design review** (only for high-risk areas, or when the spec says so): the implementer
   writes a plan in `plan-only` mode, and the spec and correctness reviewers check it
   before any code is written. Approve it, or send it back once.
3. **Implement**: brief the implementer (section 7).
4. **Gates**: the orchestrator runs the gate commands and every automatable Verify step
   itself. A failure goes back to the implementer and counts as a round.
5. **Panel**: choose its size (section 5) and log the choice in one line. Dispatch all
   reviewers **in one message, in parallel**.
6. **Verify findings**: send the Blocker and Major findings to the verifier, except when:
   - two lenses raised the same finding independently, so it is CONFIRMED; or
   - the orchestrator runs a **safe reproduction** (a test or an import, never the risky
     command itself) and sees it fail, so it is CONFIRMED.
7. **Decide**:
   | Verdict | Blocker | Major | Minor / Nit |
   |---|---|---|---|
   | CONFIRMED | fix | fix | follow-up |
   | UNCERTAIN | fix | orchestrator's call, logged | follow-up |
   | REFUTED | dismiss, log reason | dismiss, log reason | — |

   Send exactly the findings to fix back to the implementer, then return to step 4.
   Rounds 2 and later are fix-only (section 5.3). **After 3 rounds with an open Blocker
   or Major, stop.**
8. **PR**: push, then open the PR with the body template (section 9).
9. **Log and status**: finish the log, add its row to the log index, set status `done (PR
   #n)`, and update the follow-up register. Commit all of it **in the same commit as the
   code**, so the code and its reasoning land together.
10. **Approval**: present the package's **approval summary** to the human: what changed
    (in behaviour, not files), how it was checked (gates, Verify, panel and findings), the
    flagged decisions, the questions that need the human, the follow-ups. Then wait. A
    question is answered; a requested change goes back to the implementer as a fix round
    (outside the round cap, since the human chose it) and the summary is presented again.
    Meanwhile the orchestrator may carry on with packages that do not depend on this one,
    and present the waiting summaries together. Silence is never approval.
11. **Merge**, on the human's "approved": record the approval on the PR, rebase on the main
    branch, re-run the gates, check every merge condition, then squash-merge (never
    auto-merge), wait for CI, and never work around the guard. Check that the merge
    landed on the main branch, remove the worktree and record the squash SHA.

**Session end**: one-screen report covering the packages waiting for approval (their
summaries in full), what was merged, blocked and in progress; the flagged decisions with
links; status corrections; open follow-ups; and what the human must do next.

---

## 5. Review panel

### 5.1 Panel selection

- **Full panel** (spec, correctness, reliability, security, tests): a fixed list of
  high-risk package IDs, **or any diff that touches a full-panel path**, whatever its ID.
- **Light panel** (spec + combined): everything else.
- **Docs-only diff**: spec only.
- **Path-triggered lenses**, added on either panel: ops (migrations, deploy, scripts, CI),
  UX (user-facing UI paths), and security on the light panel (hooks, agent settings, CI
  workflows, env and secret handling, auth, DB roles, dependency manifests).
- The combined reviewer raises a Major if the diff touches full-panel code, because that
  means the wrong panel was chosen.

### 5.2 Rubric (shared by every reviewer)

**Severity**
- **Blocker**: user-visible wrong output; data loss; a forbidden write path; a hard rule
  or accepted ADR broken; a leaked secret or PII; an exploitable hole; **faked Verify
  output or a test weakened to pass**; a migration that fails in an environment.
- **Major**: likely to fail under realistic conditions (restart, reconnect, delete, empty
  input, edge time); a spec requirement missing; a critical path without a test; new
  behaviour without docs.
- **Minor**: real, but unlikely or cheap to fix later.
- **Nit**: style or naming. At most 3 per reviewer, and never blocking.

**Every finding** has `id`, `severity`, `file:line`, `claim` (one sentence), `scenario`
(the concrete inputs or state that lead to the wrong outcome), `evidence` (what was read
or run) and `fix` (the smallest one). **A finding without a scenario is a Nit at most.**

**Do not report** preferences, rewrites into another style, features outside the spec, or
anything an accepted ADR already decided.

### 5.3 Rounds

- **Round 1**: the chosen panel reviews the whole diff.
- **Round 2 and later (fix-only)**: the reviewer that raised the findings confirms the
  fixes in `fix-confirm` mode and reads the **fix-round diff** (`<prev head>..HEAD`) for
  regressions. If the findings span more than two lenses, the verifier confirms them
  instead. Only new Blocker or Major findings count.
- **Escalation inside a fix round**: if the fix diff is large (about 100+ lines) or
  rewrites the logic the findings were in, the owning lens re-reviews the **whole** diff.
  A rewrite can introduce a new bug that a fix-only check would miss.
- A reviewer may re-raise a dismissed finding only with **new evidence**.

### 5.4 Reviewer budget and safety

- **Budget**: about 15 tool calls per review (about 25 for the deep lenses on the full
  panel). No heavy tooling (containers, fuzzing) except where a lens needs it to check
  its core question. Reports stay under 300 words, with Blockers and Majors first.
- **Safety**: reviewers and the verifier run real shells, so:
  - they work only in the worktree, never in the main checkout;
  - they never run a command that changes anything outside the worktree (deploy, push,
    tag, prod or network writes), **not even as a probe**;
  - they never write files through a shell heredoc. Use the file-writing tool, and only
    in a temp directory they create;
  - to test a gate or command classifier, they import it and pass the command **as a
    string**, and never execute the command being tested.

---

## 6. Decision ladder

When any question comes up, answer it with the first rung that applies:

1. **Hard rules and accepted ADRs.** These are absolute. Breaking one is a Blocker,
   whatever the spec says.
2. **The package spec**: scope, Verify steps, the docs section.
3. **Architecture doc and path-scoped rules** (and any published contract between repos).
4. **Existing patterns in the repo.** Copy what is there before inventing.
5. **The boring option**: the reliable, smaller, reversible, configurable one.
6. **An open question**: use the safe default named in the spec or plan. If the question
   is new, add it to "Open questions" with a safe default and carry on.
7. **Still undecidable**, or every answer breaks rungs 1–3: **stop the package.**

Every answer from rungs 4–7 is logged, and so is every spec deviation, every dismissed or
deferred finding, and every status correction. When in doubt, log it.

**Flag: review** marks the entries the human should read: anything that changes
user-visible behaviour, chooses a default for an open question, deviates from the spec,
or dismisses a Blocker.

**Scope**: work found outside the spec is not done. It becomes a follow-up. A minimal
spec deviation is allowed only when it touches no ADR or hard rule, and it is logged with
a flag.

---

## 7. Briefs (subagents start cold)

Give each subagent everything it needs and nothing it does not.

**Implementer brief**: package ID, spec path, repo, worktree, branch; the mode
(`plan-only` | `implement` | `fix round N`); for a fix round, **the findings verbatim and
nothing else**; binding decisions already made; the open follow-up rows (which are in
scope); the gate commands to run before reporting.

**Implementer rules** (in its agent file):
- Check that it is in the right worktree and branch. Read the hard rules, the spec, the
  matching path rules and the listed ADRs. Copy existing patterns.
- Write tests first for critical behaviour.
- **Never** weaken, skip, focus or delete a test to get green. Never edit expected values
  without proving the new ones are right. Never fake or paraphrase Verify output.
- In a fix round, fix exactly the findings with the smallest change. If it thinks a
  finding is wrong, it does not fix it and explains why, with evidence.
- No new dependency unless the spec needs one. No prod access. No heredoc file writes.
- Out-of-scope problems go in the report as follow-ups. It commits but never pushes,
  opens PRs or merges.

**Implementer report**:
```
MODE: plan-only | implement | fix round N
STATUS: done | blocked (<one line>)
CHANGES: <file, what, why>
TESTS ADDED/CHANGED: <for any changed existing test, why the old expectation was wrong>
GATES: <each gate command + final summary lines, verbatim>
VERIFY: <each Verify step + real output, verbatim, trimmed>
DECISIONS: <each choice the spec did not dictate: what, why, alternative>
FINDINGS NOT FIXED: <id: reason with evidence>   (fix rounds)
NEW DEPENDENCIES: <or none>
FOLLOW-UPS: <or none>
```

**Reviewer brief**: repo, worktree, diff range (`origin/<main>...HEAD`), spec path,
changed files; round, panel and mode (`full` | `fix-confirm`); in `fix-confirm`, the
fixed findings verbatim and the fix-round range; in a later `full` review, the earlier
findings in its lens with their resolutions; and **the budget and safety line in every
brief**.

**Reviewer report**:
```
LENS: <name>
VERDICT: approve | changes required
FINDINGS:
- id: <LENS>-1
  severity: Blocker | Major | Minor | Nit
  file: path:line
  claim / scenario / evidence / fix: ...
<lens-specific coverage line, e.g. INPUTS TRACED, INCIDENTS CONSIDERED, VERIFY RE-RUN>
```
`FINDINGS: none` when clean. No padding.

**Verifier report**: per finding, `verdict` (CONFIRMED | REFUTED | UNCERTAIN), `severity`
(unchanged or proposed, with a reason), `basis` (reproduction or reading, with file:line).

A malformed or vague report (a finding with no scenario, a "done" without output) is sent
back **once**.

---

## 8. Escalation: what always needs the human

The orchestrator never does these on its own. It says what will change and why, then
waits:
- anything a gate denied. A **destructive command the destroy gate denies** (section
  12.2, layer 5) never runs from the agent, even with approval: if the work truly needs
  one, the human runs it in their own terminal;
- accepting, changing or superseding an ADR (drafting one as `Proposed` is fine);
- changing a hard rule or the profile;
- **weakening a gate**: hooks, CI, branch protection, skipping or deleting tests,
  bypassing the docs gate;
- **weakening a safeguard** (section 12.6): switching off or bypassing the package
  manager's release-age or install-script setting, the secret scan, or the backup job;
- cutting a package from scope;
- an open question with **no safe default**;
- deleting branches or worktrees it did not create;
- granting, widening, extending or re-granting any platform access (section 12), above
  all anything that would reach production, and any step that would make a secret's
  value visible in the session.

Its own work needs no approval: branches, worktrees, PRs, status, the log, and anything in
the development environments, resets and deletes included. A decision that changes what
production will do after the merge (a migration, a production setting, a deploy step) is
flagged for review in the log. **Merging is the exception**: every package merges only on
the human's approval of its summary (section 4). A merge deploys to development;
production waits until the human deploys it by hand.

**Approvals without babysitting**
- **Queue and continue.** When a package needs an approval, the orchestrator marks it
  `waiting for approval`, records the exact ask, and moves on to any package that does
  not depend on it. Pending asks reach the human together, in one message, when nothing
  else can run or at the end of the session. Only the dependent chain waits.
- **A procedure, not loose commands.** A platform step that has dependent parts (apply,
  check, roll back if the check fails) is written by the implementer as one script with
  its own conditions, so it runs, or is approved, as one unit.
- **Notify when blocked.** When the orchestrator is waiting on the human, it sends one
  push notification (through the agent tool's built-in push, if it has one). A
  user-level `Notification` hook is the deterministic backstop: it fires on permission
  and idle prompts, and pushes to the phone only when the machine has been idle. The
  push carries the project name and the kind of event, never content.

**Stop conditions (per package)**: the round cap is reached; the package cannot be done
without breaking a hard rule or an ADR; it needs an item from the escalation list; a gate
fails for a reason outside the package; a dependency turns out not to be done. On a stop:
set the status to `blocked: <reason>`, log a `stop` entry with a flag, add the log index
row, remove nothing, and move on.

**Stop the session** when the main branch is red, or two stops in a row share a cause.

**Never push past a dead end** by weakening a test, widening scope, or editing an ADR.

---

## 9. Merge conditions and PR body

The orchestrator merges only when **all** of these hold:
- the gates are green (CI on the PR head commit; until CI exists, gates re-run by the
  orchestrator with output in the PR);
- the Verify steps were run, and their real output is in the PR;
- no confirmed Blocker or Major is open;
- docs are updated (the docs gate passes);
- the branch is rebased on the current main branch, with gates re-run after the rebase;
- the decision log is written and linked, and the follow-up register is updated;
- the PR body follows the template;
- the human approved the package after reading its approval summary.

**PR body**
```markdown
## <ID>: <title>
Spec: <link> · Decision log: <link>

### What changed        <3–6 bullets>
### Verify (real output)  <command + trimmed output per step>
### Gates               <commands + result lines, as re-run by the orchestrator>
### Review panel
| Lens | Round(s) | Blocker | Major | Minor | Outcome |
### Decisions           <D<n>, title, flag>
### Follow-ups          <or "none">
```

**Definition of done**: gates green, Verify run with real output in the PR, docs updated,
no open Blocker or Major, decision log written, approved by the human, squash-merged, and
deployed to development. Production waits for the human (section 12.3, rule 5).

---

## 10. Decision log and follow-up register

**Log file** `docs/decisions/log/<ID>.md`:
```markdown
# <ID>: <title>
| Field | Value |  (spec, branch/PR, outcome + sha, rounds n of 3, dates)

## Summary        two or three sentences; what to look at
## Decisions
### D1: <title>
- **Kind**: default chosen | finding dismissed | finding deferred | spec deviation |
  scope cut | status correction | stop | access | other
- **Decision** / **Why** (name the ladder rung) / **Alternatives**
- **Revise by**: the setting, file, or commit to change
- **Flag**: review | none
## Review findings  | ID | Severity | Lens | Claim | Verdict | Resolution |
## Follow-ups
```
The **index** (`log/README.md`) has one row per package: package, repo, date, outcome,
PR, the number of decisions, and the flagged entries. The human reads the flagged column
first.

ADRs hold architecture-level decisions. The log holds execution-level ones. Do not mix
them.

**Follow-up register**: one table in the plan. It is the only place open follow-ups are
tracked, each with a **target package** or `unscheduled`. Per-package logs mention
follow-ups, but the register is authoritative, because follow-ups recorded only in
scattered logs get lost.
- On **claim**, the package's open rows are copied into the implementer brief and are in
  scope.
- On **merge**, new follow-ups are added and the package's own rows are closed, in the
  same commit.
- At **session start**, rows still open whose target is done are reported.
- In **every session report**, the `unscheduled` rows are listed, so the human can
  schedule or drop them.

---

## 11. The mechanical layer

Agents forget written rules, so the critical ones are hooks and CI. Every gate **fails
closed**: if the gate script is missing or errors, the call is denied or sent to the
human, never allowed silently.

**Bypass-permissions mode.** There, Claude Code honours a hook's "deny" but never shows
its "ask" to the human, so an ask would let the call through (found in the trial). Every
gate therefore turns its asks into denies when the session is in that mode, and says so:
the human leaves bypass mode to approve the call, or does it by hand.

| Gate | Mechanism | What it enforces |
|---|---|---|
| **Docs gate** | PreToolUse + Stop hook | A commit or a session end with behaviour changes but no doc changes is blocked (explicit, reviewable opt-out marker only). |
| **Docs tests** | test suite | Indexes list every doc, links resolve, mirrored files are byte-identical, every ADR is indexed. |
| **Destroy gate** | PreToolUse hook on shell, edit and MCP tools | The destructive actions whose reach spans environments are denied (the list is in section 12.2, layer 5): the platform project or an environment, the repository, the main branch, the secrets manager. Destruction inside development is allowed. Edits to the profile or the agent settings ask first, so a session cannot switch a gate off by itself. Needs no configuration. |
| **Ops gate** | PreToolUse hook on shell tools | Deploys and platform commands run (the agent's credentials reach development only). A merge without green checks, or a direct push to the main branch → deny (the merge guard). Commands that print secrets → deny, including the secrets manager's own listing and export commands and whatever an injector runs (`op run -- printenv`, `infisical run -- printenv`); commands it cannot read well enough to rule out a hidden merge or push → ask. |
| **Merge guard** | the same hook | `merge` is denied unless every check on the PR head passed; auto-merge is denied; direct pushes to main are denied. It also covers **aliases, extensions and API endpoints** that reach the same action, and non-built-in subcommands go to the human. |
| **CI** | the CI provider | Lint, build, tests, docs tests and boundary tests on every PR; actions pinned to SHAs. |
| **Boundary tests** | test suite | Architectural boundaries (e.g. "module X never imports Y", "no client-specific names in the generic core") are tests, not just advice. |

Test a gate by importing its classifier and feeding it command strings. Never run a
dangerous command to see whether the gate catches it.

---

## 12. Platform access and credentials

**Goal**: full speed in development, a wall around production. The agent has full
control of the project's development environments: it deploys, changes variables, resets
and reseeds databases, and creates and deletes services there, so it can run end-to-end
tests without the human relaying anything. It holds no credential that can change
production. Production runs only what the human deploys there by hand, from merges they
approved. A few actions whose reach spans both
environments stay denied, and a secret is never visible to the agent.

This replaced two access phases on 19 Nov 2026: broad access including production during
development, then a read-only "observe" phase after a close-out. A project rarely ends
cleanly. Every new request from a stakeholder meant re-opening development and
re-granting production access, so the line was drawn in time when it belonged between
environments.

### 12.1 Two kinds of environment

| | Development | Production |
|---|---|---|
| Repo and CI | full, through worktrees and PRs; the merge guard applies | what production runs comes from the main branch, which changes only by a merge the human approved |
| Hosting platform | full: deploys, variables, restarts, logs, creating and deleting services, volumes and deployments | **no agent token**; auto-deploy is off, and the human deploys it by hand (12.3, rule 5) |
| Database | full: the agent's role owns the database, so it can drop, reset and reseed | at most a read-only role on named schemas, for diagnosis (12.3, rule 4) |
| Secrets | development values, injected at runtime through the agent's read-only identity | never held, never visible |
| Logs | the platform's, directly | the channels in 12.5 |
| Destructive commands | allowed, except the few whose reach spans environments (12.2, layer 5) | out of reach: the agent holds no credential for them |

Development can be one environment or several: a shared dev, a staging, a temporary one
per PR. The test is simple: **everything the agent's credentials can change is
development, and development can be rebuilt from scratch** (12.6, safeguard 5).

### 12.2 The layers

The wall around production is made of credentials, not hooks. The layers are listed
strongest first: the first four are enforced on the server, where no prompt injection
reaches; the rest are on the agent's machine.

1. **Credential scope.** What a token cannot do, nothing can make the agent do with it.
   Every credential the agent holds is scoped to this one project and to its development
   environments. None can change production. This is the wall; the layers below narrow
   what happens on each side of it.
2. **Production deploys only by the human's hand.** Production's auto-deploy is off on
   the platform, no production credential exists in CI, and the human deploys a chosen
   commit of the main branch from the platform's dashboard. Server-side branch protection
   on the main branch (a pull request and the required check, no force push, no deletion,
   and nobody exempt) keeps what can reach production reviewed. No merge, branch, CI run
   or agent token deploys to production. Where the git host's plan offers no branch
   protection (a private repository on GitHub Free), the human may go without it: the
   access package records the choice, the merge guard is then the only check on the main
   branch, and the human checks the commit they deploy against the session report.
   Production stays out of reach either way, because it deploys only by hand.
3. **A broker, where the platform cannot scope.** A small service holds a real platform
   token and offers the agent only named operations ("read logs", "deploy this
   service"), refusing all others. It is the answer when a platform cannot scope a token
   to development, or when the agent should read production logs without any production
   token. It is optional and built when a project needs it; the design is in
   [BROKER.md](BROKER.md).
4. **Database privileges.** In development the agent's role owns the database, so
   dropping a table or reseeding is its own business. In production the agent has no
   write role at all: migrations run there as part of the deploy, under the migration
   role, never from the agent's session. Point-in-time recovery is on in production.
5. **The destroy gate.** A hook that denies the few destructive actions whose reach is not
   limited to development, even with approval: the human runs those in their own
   terminal. The list:
   - deleting or transferring the hosting platform's **project**, or deleting one of its
     **environments**: the project holds production too, and an environment delete can
     name production. The human removes a temporary environment, or the platform removes
     its PR environments by itself;
   - deleting, archiving, renaming or transferring the **repository**, or changing its
     visibility; deleting releases, or the git host's secrets or variables (they can
     hold CI's production credential); a force push or delete of the main branch, or a
     force push that does not name its branch;
   - deleting in the **secrets manager**: a 1Password item, document, vault, user or group
     (a vault can hold production values), or an Infisical secret or folder (a sync
     carries the delete to every environment, production included);
   - writing a file that holds one of these as a platform API call, or a script (shell,
     PowerShell, batch, CI YAML, Makefile, package.json, any `#!` file) that holds any of
     them;
   - running a script that holds any of them (`sh x`, `bash x`, `source x`, `./x`,
     `pwsh -File x`): the gate reads the script, so writing one first does not get round
     it.

   Everything else destructive is allowed: `DROP`, `TRUNCATE` and bulk deletes on the
   development database, and deleting development services, volumes, variables and
   deployments. The gate cannot see which environment a command reaches (the connection
   is injected at runtime), and it does not need to: layer 1 makes everything the agent
   can reach development.

   It also asks before any edit to the profile or the agent settings, so a session cannot
   switch a gate off by itself.
6. **The ops gate.** It denies commands that print secrets, and asks before a command that
   changes a secret or switches the secrets manager's login. The merge guard denies a
   merge until every check on the PR passed, and a direct push to the main branch.
7. **Secrets never enter the session** (rule 3 below). A manipulated agent cannot leak a
   key it never saw.

**Prompt injection.** It arrives in text the agent reads: database rows, logs, issues, PR
comments, web pages, dependency files. Reading cannot be prevented, so the design limits
what a manipulated agent can do: it can damage development, which costs one rebuild
(12.6, safeguard 5); it cannot reach production (layers 1 and 2), use a secret (layer 7)
or touch another project (layer 1). Most reading is done by reviewers, which cannot write
at all. The hooks are a speed bump, not a wall: a script that calls a platform's API
directly never passes through them, which is why the server-side layers come first.

### 12.3 Rules

1. **Access inventory.** The plan has an "Access inventory" table with one row per
   credential: the platform, what the agent uses it for, the environments it reaches
   (never production for anything that writes), how it is injected, and how it is
   revoked. The agent has no access that is not listed there. Every grant and every
   revocation is a decision log entry.
2. **Isolate every credential to one project and to development.** A leaked or misused
   token must never reach another project or production. Use project- and
   environment-scoped tokens. A tool that only works with an account-wide token is not
   used: pick another route. Give every token an expiry date where the platform offers
   one.

   **Where each kind of variable lives (19 Nov 2026):**

   | Kind | Where | How it reaches the app |
   |---|---|---|
   | Secrets (tokens, keys, passwords, signing keys) | the secrets manager, a `-dev` and a `-prod` vault | the push script copies them to the platform's variables |
   | Plain settings (limits, flags, model names, IDs that are not secret) | `config/<environment>.env`, committed | the app reads the file named by `APP_ENV`, the one plain variable on the platform; defaults stay in code |
   | The platform's own values (references such as `${{Postgres.DATABASE_URL}}`, `RAILWAY_*`) | the platform | the platform; the dev rebuild recreates them |

   Settings are not secrets: in the repo they get history, review and a diff, and a change
   reaches production when the human next deploys. The file is not named `.env`, which the
   gates treat as a secret file the agent may not read. A diff that touches
   `config/production.env` always gets the ops and security lenses (`paths`), and every
   changed setting is flagged for review. A platform reference is never copied into the
   secrets manager as a value: pushed back, it would freeze a link that the platform keeps
   current.

   **The secrets manager is 1Password by default.** Every secret lives there, once; the
   platform holds a copy. Each project has two vaults, `<project>-dev` and
   `<project>-prod`, and in each vault one item per platform environment
   (`railway-development`, `railway-production`) with one field per secret: the label is
   the variable's name. A script in the repo (the `push_secrets.py` template) copies an
   item to its environment, passing values on standard input, never on a command line:
   the dev rebuild runs it for development, and the human runs it for production from
   their own terminal, where it changes production's variables without redeploying.
   Infisical, whose syncs do that copy by themselves, is the alternative for a project
   that already uses it or wants the syncs; the gates know both. Its free plan's limits
   (syncs, identities and environments per account) are what ruled it out as the default.

   **The agent has its own identity in the secrets manager, never the human's login.** A
   secrets manager puts every secret behind one login, so that login is the most valuable
   credential there is. The agent's identity (a 1Password service account, an Infisical
   machine identity) is therefore:
   - **read-only** (1Password: read access to the vault; Infisical: the built-in Viewer
     role): the human adds and changes secrets, so no value passes through the session;
   - **limited to development values.** It is given the `-dev` vaults only, never a
     `-prod` one; a 1Password service account cannot be given the human's own vaults at
     all. One service account may serve every project's development vault: a leak then
     exposes development values only, which are cheap to lose by design (rule 3). In
     Infisical, where the plan cannot limit an identity to an environment, production
     lives in a second project the identity is not a member of;
   - **kept out of the transcript.** Each project has its own service account, which opens
     exactly that project's `-dev` vault. The human stores its token once, in their own
     terminal, with `scripts/session_secrets.py setup` (adopt opens the window): the token
     comes from the clipboard and goes into the operating system's credential store
     (Windows Credential Manager), never into a file in the repository or the transcript.
     The same run finds the vault and the agent's token items in it (API Credential items
     whose title names GitHub or Railway) and writes `.claude/session-secrets.json`: the
     credential's name, the vault, and the `op://` reference behind each variable, no
     value. The plugin's SessionStart hook then loads them into every session, however
     the editor was opened: it checks that the token opens exactly that vault, and prints
     variable names only. Hooks do not see those variables, so the merge guard reads
     `GH_TOKEN` itself the same way. (A launcher that started the editor with the token
     was tried first, 21 Nov 2026: an editor opened any other way had no tokens, and
     nothing said so.) The loader knows 1Password only; an Infisical project starts the
     session with its access token in the environment;
   - **able to merge with a fine-grained git host token.** Such a token has no permission
     that reads check runs, so GitHub refuses `gh pr checks` and the PR's
     `statusCheckRollup` to it. The merge guard then reads the same facts from the
     GitHub Actions jobs on the PR's head commit and the commit statuses, which the
     token can read with **Actions: read** and **Commit statuses: read**;
   - **within its limits.** 1Password service accounts have hourly and daily request
     limits per plan, the daily one shared by every service account in the account. Tests
     need no secrets, and the app reads its variables from the platform, so 1Password is
     read only when the push script runs;
   - **an inventory row**, like any other credential.

   **Nothing on the agent's machine reaches production.** The agent runs as the human's
   operating-system user, so it can use any login that user has on the machine, whatever
   the agent's own tokens are scoped to. So:
   - the human keeps **no CLI login** of the hosting platform or an admin session of the
     secrets manager on that machine. The human's production access lives in the browser,
     behind a passkey, or on another user account or machine;
   - the agent's **git host credential** is a fine-grained token for this one repository:
     contents and pull requests (read and write), actions and commit statuses (read), and
     no administration, environments or deployments permission. It cannot change branch protection, read CI's production
     credential, or approve a production deployment.
3. **Secrets never enter the transcript.** Inject them into the process at runtime
   through the secrets manager's CLI (`op run --env-file=<refs> -- <command>`, where the
   file holds `op://` references and no values; or `infisical run -- <command>`). Never
   paste values, never keep real values in `.env` files, and never let the agent read
   one. Anything that appears in the context is stored in session transcripts on disk and
   may be passed to subagents. Development secrets count too: they include paid API keys
   and test accounts. The ops gate denies commands that print secrets: `env`, `printenv`,
   `cat .env`, platform "list variables" commands, the secrets manager's own listing,
   export and token commands (`op read`, `op inject`, `op item get`, `op signin`,
   `infisical export`), a one-line dump of the whole environment, and any of these run
   through an injector (`op run -- printenv`, `infisical run -- printenv`, `railway run
   env`). Limitation: this stops accidental exposure, not a determined process. A program
   that was handed a secret can still print it, and no gate reads what a program does. So
   **plan as if the agent can read every value its identity reaches**: development holds
   only values that are cheap to lose (a test bot, API keys with low spending limits, test
   accounts, invented data). A credential that acts in the real world and has no test
   account (a portal login, a signing key) stays in production only, and development
   works against a fake of that service. Rotating the development secret is the
   backstop; a production secret was never within reach.
4. **Database roles.**
   - **Development:** the agent's role owns the development database, or the agent runs
     the migrate command against it. It can create, drop, reset and reseed.
   - **Production:** a **migration role** owns the schema and is used only by the deploy.
     An **app role** reads and writes rows for the app. The agent gets no role there,
     except, if the project grants it, a **read-only role** for diagnosis, which:
     - can connect and `SELECT` on named schemas only (the app event table's schema
       first), with default privileges so that future tables in those schemas are
       readable too;
     - has no access to secret or personal-data tables or columns (expose a redacted view
       instead);
     - has a statement timeout, a connection limit, and `default_transaction_read_only =
       on`;
     - is proved by a test: a write attempt with it fails.
5. **The human deploys production, by hand.** A merge to the main branch deploys to
   development. Production's auto-deploy is switched off, and the human deploys the commit
   they choose (normally the head of the main branch, once it has run in development) from
   the platform's dashboard. No production credential exists in CI or near the agent, so
   nothing but the human can start a production deploy. `deploy.prod` says how this
   project does it. The cost is that the platform's deploy history is the only record of
   what was released, so each session report lists what is ready for production, and the
   human checks the deployed commit against it. The agent never deploys there itself.
6. **Rotate in one place.** Platform environment variables are **copied from the secrets
   manager** (the push script, or an Infisical sync), never edited on the platform, so a
   rotation is one change and one push. The push script lists any variable that exists on
   the platform only, so nothing is kept there alone. Use the secrets manager's built-in
   rotation where it supports the credential type. Rotate at once whenever a secret value shows up in a
   transcript, log, commit or PR.
7. **The wall is proved before the orchestrator runs**, and again whenever access
   changes. The access package's Verify steps:
   - each of the agent's credentials, pointed at production, is refused. Use a call that
     changes nothing even if it is allowed (the environment's status, a list of its
     services), never a write and never a listing that prints values;
   - a direct push to the main branch is refused by the git host (unless the access
     package records that the plan has no branch protection), and a merge leaves
     production unchanged (its auto-deploy is off);
   - the git host token cannot read or change branch protection;
   - the production read-only role, if granted, can read, and a write attempt with it
     fails;
   - development rebuilds from scratch (12.6, safeguard 5).
8. **When the work stops, nothing about production changes.** There is no phase to
   switch. When an engagement ends, the human revokes the inventory's credentials (each
   row says how) and logs it. The agent never held a production credential, so nothing in
   production needs rotating unless a value leaked. A new request later re-grants the
   development credentials from the inventory, and the wall is proved again.

### 12.4 Who holds what

| Credential | Agent | App | Human |
|---|---|---|---|
| Dev database, owner role | yes, injected at runtime | — | — |
| Prod database, migration role (owner) | never | never | through the deploy they start |
| Prod database, app role | never | yes | — |
| Prod database, read-only role (named schemas, no PII) | if the project grants it | — | — |
| Platform token, development environments | yes, injected at runtime | — | — |
| Platform access, production | never | — | yes, in the dashboard |
| Secrets-manager identity (read-only, development values) | yes, as a short-lived token | — | — |
| Git host token (this repository, no administration) | yes | — | — |
| Backup storage credential (can add, cannot delete) | never | the backup job only | — |
| Broker token, if there is a broker | yes | — | — |
| Log sink, read-only query token | yes | — | — |
| Log sink, ingest token | never | yes | — |

### 12.5 Production logs the agent can read

The agent reads development logs on the platform directly. Production's logs reach it
through channels that need no production platform token. Use two, because each one
covers the other's blind spot:
- **App event table** (for example `ops.log_event`: time, level, source, event, message,
  a `context` JSON column). The app writes warnings, errors and lifecycle events
  (startup, shutdown, reconnects, job runs), plus a periodic heartbeat row. It works the
  same way on any hosting platform, and the production read-only role can query it. Cap
  it with a scheduled retention delete (for example 30 days). Everything written to it
  must already be free of secrets and PII, because the agent reads it.
- **A log service with read-only query tokens** (for example Axiom: an advanced API token
  limited to querying one dataset). The agent reads logs there without holding any
  platform token. Prefer the shipping route that needs **no platform token at all**: the
  app sends a copy of its logs to the service itself (the vendor SDK or OpenTelemetry), or
  sends them to a forwarder such as Vector over the private network, which holds only
  the service's ingest token. Sidecars that read the platform's log API instead (for
  example Locomotive on Railway) are **not used**: they need an account-level platform
  token, which breaks per-project isolation (12.3, rule 2).
- **A broker** (12.2, layer 3) is the third option when the platform's own logs are
  wanted: it reads them with the platform token it holds and hands the agent only log
  lines.
- **Blind spots.** None of these routes carries build logs, and app-sent routes miss
  output from before the logger starts. Cover them with:
  - the deploy status the platform reports to the git host, which the agent can read
    with the git host's CLI;
  - the heartbeat row: when it stops, the app is down and the human checks the platform.

### 12.6 Safeguards every project has

The layers above limit what the agent can do. These six limit what a mistake, a poisoned
dependency or malware that collects every credential on the machine can cost. Those are
the common ways a small team loses data (section 14). The plan has a "Safeguards" table
with one row for each, and what proves it.

1. **A backup the platform cannot delete, with a tested restore.** A scheduled dump of
   each production database goes to storage at another provider, written with a
   credential that can add files and cannot delete them. A platform's own backups do not
   count: they can go in the same call that deletes what they protect. One restore into a
   scratch database is done and recorded, because an untested backup is a guess. No gate
   and no rule replaces this: it is the only safeguard that still works after the damage
   is done.
2. **Dependencies are installed late and without scripts.** The package manager waits
   before it installs a newly published version (a minimum release age of 7 days), does
   not run dependencies' install scripts, and installs from the lockfile only in CI. A
   poisoned release is usually found and pulled within hours, so a build that waits never
   installs it. Nobody switches these off to get a build through: a package that needs
   its install script is allowed by name.
3. **Committed secrets are caught before they land.** The git host's push protection is
   on, and CI scans every pull request's commits for secrets. A secret that reached a
   commit is rotated, whatever happens to the commit.
4. **The agent's own identity in the secrets manager** (12.3, rule 2): read-only, limited
   to development values, short-lived in the session.
5. **Development rebuilds from scratch with one command.** The command takes an empty
   database to the current schema (the migrations) and loads the data development needs
   (a seed script in the repository). It also recreates whatever else development holds
   outside the database: files in storage, test users in an external sign-in service,
   webhooks registered with a third party. **Nothing in development exists only where it
   was made.** Anything someone puts there by hand (a stakeholder's demo accounts, the
   fixtures the end-to-end tests expect, a setting changed in a dashboard) is turned into
   seed or setup code in the next package, so the rebuild brings it back. The seed data is
   invented, never a copy of production, and holds no real secret. Development's
   secrets come back the same way: the rebuild runs the push script, which copies them
   from the `-dev` vault; its settings are in `config/development.env`. Proved by running the
   command once against an empty environment and recording the output, and again
   whenever a migration, the seed or the setup changes; CI can do it on every PR. This is
   what makes the agent's full control of development safe: a destroyed development
   environment costs one command, not a loss.
6. **Production is out of reach, proved** (12.3, rule 7): every agent credential is
   refused there, the main branch takes no direct push, and no login on the agent's
   machine reaches production.

**What the engine cannot enforce** is the human's own machine and accounts, where the
same threats arrive: a passkey or hardware key on the email account, the git host, the
hosting platform, the secrets manager and the domain registrar; a password manager
instead of passwords saved in the browser; a standard, non-administrator user for daily
work; and a repository from an unknown source opened in a cloud development environment
or the editor's restricted mode, never trusted straight away.

**Not part of the default: a container for the agent, and a credential broker.** Both
were weighed (15 Nov 2026). A container per project limits a poisoned dependency to that
project, and a broker (12.2, layer 3) keeps real credentials out of the agent's
environment. Each costs setup and a changed daily workflow, and a broker only keeps its
promise when the agent already runs in a container. The six safeguards above cover the
more common threats for less. A project that needs more adds them: [BROKER.md](BROKER.md).

---

## 13. Adapting the model to a new project

**Invariant (keep as is)**: the roles and the never-codes rule; re-running gates; one
lens per reviewer; the verifier and its CONFIRMED/REFUTED/UNCERTAIN rules; the severity
scale and finding format; fix-only rounds with the large-diff escalation; the 3-round
cap; the decision ladder; the decision log with Revise-by; the follow-up register;
squash-per-package; the escalation list; reviewer safety; fail-closed gates.

**Tailor (fill these in per project)**. The answers go in the project profile: settings
in `project.toml`, lens knowledge in `lenses/*.md`, hard rules in `CLAUDE.md`.
[PROFILE.md](PROFILE.md) maps each item to its key.

| Item | Question to answer |
|---|---|
| Hard rules | What must never happen? (forbidden write paths, data that must never be logged, boundaries between modules or repos) |
| "User-visible" | What does a visible bug look like here (wrong number, broken page, bad API response, corrupt file)? It defines Blocker. |
| Correctness lens | What is the domain truth, and where is its single source? Which adversarial inputs should the reviewer trace? |
| Reliability lens | Which dependencies can fail, and what must survive it? Which failures should the reviewer trace? |
| UX lens | Is there a user interface? Who uses it, for which tasks, on which devices? If there is none, drop this lens. |
| Full-panel IDs and paths | Which packages and directories hold the code where a bug is visible or loses data? |
| Path triggers | Which paths wake ops and security on the light panel? |
| Gate commands | The exact install, lint, build, test and boundary-check commands. |
| Environments | Which environments are development (the agent's)? What counts as production, and how does the human deploy it by hand? Which command rebuilds development? |
| Model tiers | Which roles get the strongest model? Keep the verifier strong. |
| Budgets | Tool-call budgets and the heavy tools each lens may use. |
| Access inventory | Which platforms does the agent work on? How is each credential scoped to this one project and to development? How does production deploy from the main branch without the agent's credentials? Which credentials can the secrets manager rotate, and which need a manual step? |
| Safeguards | Where does the off-platform backup go, and who tested a restore? Which package manager, and how are its release-age and install-script settings set? Which secret scan runs in CI? Which command rebuilds development, and what goes in the seed? How was the wall around production proved? |
| Observability | Does the agent get a production read-only role, and which schemas can it see? Which are PII? What goes in the event table? Is there a log sink with read-only tokens? |

**Bootstrap order** (each step is itself a work package, done the manual way before the
orchestrator exists):
1. `CLAUDE.md` with hard rules; `IMPLEMENTATION_PLAN.md` with a status table, open
   questions and the follow-up register; an ADR index; a spec template with a Verify
   section.
2. Access: the access inventory, the secrets manager (1Password by default: a `-dev` and a
   `-prod` vault, and the push script that copies each to its platform environment), the
   agent's own read-only identity in it, tokens scoped to the
   project and to development, the production deploy route from the main branch with
   branch protection, the database roles (the agent owns development; in production at
   most a read-only role), and runtime injection for every command that needs a secret.
   With it, the safeguards of 12.6: the off-platform backup and its tested restore, the
   dependency install settings, the secret scan, the one-command development rebuild, and
   the proof that production is out of reach.
3. The plugin enabled at project scope, and the profile: gate commands, panel paths,
   environments, the docs gate patterns and the lens files. The plugin's gates enforce
   what the profile sets.
4. Docs tests; CI with the gate commands and a check named as `merge.required_check`;
   boundary tests.
5. PR template, `PROCESS.md`, and the decision log README with its template. Accept an
   ADR that grants the orchestrator its authority: to merge each package once the human
   approves it, and to have full control of the development environments.
6. The app event table and heartbeat (or the log sink), so production has something the
   agent can read.
7. Only now run the orchestrator (`/athena`). Start with low-risk packages, read the
   flagged log entries closely, and tune the lenses.

The plugin's `adopt` skill (`/athena-orchestrator:adopt`) does steps 1, 3 and 5, and CI from
step 4, from templates. It maps what an existing project already has instead of
overwriting it, asks once for what it cannot infer, and writes nothing before the user
approves its mapping. Its survey also records which safeguards (12.6) the project already
has. The rest of the bootstrap (access, the backup, the dependency settings and secret
scan, the docs and boundary tests, the event table) it puts in the plan as the first work
packages, so the orchestrator does them; access and the backup are owned by the human. The user's approval of the mapping is the review:
`adopt` then lands its one commit on the main branch itself (a fast-forward without a
remote, a PR merged through CI and the merge guard with one), and the same approval
accepts the process ADR unless the user says to leave it `Proposed`. Nobody merges the
adoption by hand.

---

## 14. Lessons that shaped the rules

Each rule above exists because something went wrong without it:

- **Full re-review every round was too expensive**: several packages needed 3+ full
  rounds. This led to risk-tiered panels, fix-only rounds, cheaper models for checklist
  lenses, and per-review budgets.
- **A fix round's rewrite introduced a new Major** that a fix-only confirmation would
  have missed. This led to the fix-round diff check and the about-100-line escalation to
  a whole-diff review.
- **A reviewer's shell heredoc contained its own terminator**, so the rest of it ran as
  real commands, and a production deploy command ran three times from the main checkout.
  Only an unrelated CLI failure stopped the deploy. This led to: no heredoc file writes,
  worktree-only work, no outside-changing command even as a probe, and testing gates by
  import.
- **Follow-ups named a target package that then never did them**, because they lived only
  in per-package logs. This led to one follow-up register, copied into briefs and closed
  at merge.
- **The written rule "merge only on green" could be bypassed** through a CLI alias. This
  led to a merge guard that covers aliases and extensions and fails closed.
- **The human reviewing every PR was the bottleneck.** This led to the panel replacing
  human review, with the human reading only flagged decisions.
- **Merging without the human's word left them outside the loop.** They want to read each
  package's outcome and ask questions before it lands. This led to the approval summary
  and the human's "approved" as the trigger for every merge: the human reads a summary,
  not a diff, so the bottleneck does not return.

- **The secrets manager's own CLI was a way round the secrets rule.** The gate denied
  `printenv`, and let `infisical run -- printenv`, `infisical export` and
  `infisical secrets delete` through: the tool the model recommends for injection could
  print or delete every secret. Found by passing command strings to the imported gates
  (15 Nov 2026). This led to gate rules for the secrets manager's commands, to reading
  the command an injector runs, and to the agent's own read-only identity.
- **Injection hides a secret from the transcript, not from the agent** (19 Nov 2026). The
  agent writes the code that `op run` or `infisical run` hands the values to, so it can
  read any value its identity reaches. Weighing Infisical against 1Password for a solo
  setup also showed the free plan's per-account limits (syncs, identities, environments)
  would not cover ten projects, while the 1Password plan already paid for covers them.
  This led to 1Password as the default, a push script in place of syncs, and the rule
  that development holds only values that are cheap to lose.
- **Published incidents, not ours, shaped the safeguards (12.6).** An agent elsewhere
  deleted a production volume with an account-wide token it found in an unrelated file,
  and the platform's backups went with the volume; its written rules forbade it. In the
  same year several waves of poisoned packages collected every credential on the
  machines that installed them, within hours of release. This led to the backup the
  platform cannot delete, the release-age and install-script settings, and expiring,
  project-scoped tokens as a rule, not advice.

- **Sessions sharing one folder spoiled each other's work** in another project, which had
  no git (18 Nov 2026). A tool that loaded a whole folder and wrote all of it back dropped
  another session's edit. A session restarting a shared desktop app killed the other's
  work. One session's end-of-turn checks sent it to "fix" the other's half-finished
  change. Worktrees already prevent most of this here, and the docs gate checks only the
  session's own folder. It led to the orchestrator lock (3.3), the no-hand-offs rule, and
  the lost-update rule for the implementer and the reliability lens: a whole-folder
  write-back must not overwrite a change made after the load.

- **The line between "developing" and "finished" did not hold** (19 Nov 2026). A project
  rarely ends cleanly: a stakeholder asks for one more change, and the observe phase had
  to be re-opened, production access re-granted, and a close-out run again. Meanwhile
  the destroy gate, which treated every environment alike, stopped the agent dropping a
  test table or resetting its own database for an end-to-end test. This led to drawing
  the line between environments instead of in time: full control of development, a
  wall of credentials around production, and a one-command rebuild that makes damage in
  development cheap (section 12).

When something new goes wrong, follow the same pattern. Record the incident in the
package log, change the rule in PROCESS.md, the skill and the agent files in one PR, and
if it is policy-level, have the human accept an ADR amendment.
