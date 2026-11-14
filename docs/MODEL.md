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
- **Bounded autonomy**: during active development the orchestrator builds, reviews,
  opens PRs, deploys and changes the project's platforms on its own; it merges once the
  human approves the package. Destructive commands never run from it,
  and it must stop and ask for anything that changes policy. After development it can
  only read.

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
13. **Broad access while building, read-only afterwards, and never destructive.** The
    human should not have to copy logs, query results or CI output between systems, or
    approve every deploy. So during the **development phase** the agent works on every
    platform the project needs, production included. Three things bound that access:
    destructive commands are denied outright, secrets are injected at runtime and never
    visible in the session, and every credential is scoped to this one project. When
    development ends, the project moves to the **observe phase**: write access is
    revoked, the keys are rotated, and the agent keeps only a read-only database role and
    readable logs. Details in section 12.

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
| **Orchestrator** | strongest | plan status, log, PR text only | Pick work, brief subagents, re-run gates, decide on findings, present the approval summary, merge to test on the human's approval, log. |
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
| `.claude/orchestration/project.toml` | The **profile**: the access phase, gate commands, panel paths, environments ([PROFILE.md](PROFILE.md)). | human |
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
  two in the same repo.
- Each package is claimed in its own **git worktree** next to the repo
  (`<repo>-wp-<id>`) and its own branch (`wp/<id>-<slug>`). No two sessions ever share a
  branch.
- Rows in the plan owned by `human` are the user's. The orchestrator never picks them.

---

## 4. The loop, per work package

**Session start**
1. Read the hard rules, the plan, the process ADRs and PROCESS.md. Leave the large docs to
   the subagents.
2. Check the profile and its **access phase**. In the observe phase the orchestrator
   reports and stops: new work re-opens development first (section 12). It also stops
   when the adoption is not merged to the main branch, or the ADR that grants it its
   authority is still `Proposed`.
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
- anything a gate denied. A **destructive command** (section 12.2) never runs from the
  agent, even with approval: if the work truly needs one, the human runs it in their own
  terminal;
- a deploy or merge while the project's freeze check blocks deploys;
- accepting, changing or superseding an ADR (drafting one as `Proposed` is fine);
- changing a hard rule, or the profile, the access phase above all;
- **weakening a gate**: hooks, CI, branch protection, skipping or deleting tests,
  bypassing the docs gate;
- cutting a package from scope;
- an open question with **no safe default**;
- deleting branches or worktrees it did not create;
- granting, widening, extending or re-granting any platform access (section 12), and any
  step that would make a secret's value visible in the session.

Its own work needs no approval in the development phase: branches, worktrees, PRs, the
deploys and platform changes a spec calls for (production included), status and the log.
A decision that writes to production is flagged for review in the log. **Merging is the
exception**: every package merges only on the human's approval of its summary (section 4).

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

**Stop the session** when the project is in the observe phase, the main branch is red, or
two stops in a row share a cause.

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
- the project's freeze check, if it has one, does not block deploys;
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
deployed to test.

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
| **Destroy gate** | PreToolUse hook on shell, edit and MCP tools | Destructive commands are denied in every phase (the list is in section 12.2). Edits to the profile or the agent settings ask first, so a session cannot switch a gate off or re-open development by itself. Needs no configuration. |
| **Ops gate** | PreToolUse hook on shell tools | Development phase: deploys and platform commands run; a deploy while the project's freeze check blocks → deny. Observe phase: deploys, merges and platform changes → deny. Both: commands that print secrets → deny; commands it cannot read well enough to rule out a hidden merge or push → ask. |
| **Merge guard** | the same hook | `merge` is denied unless every check on the PR head passed; auto-merge is denied; direct pushes to main are denied. It also covers **aliases, extensions and API endpoints** that reach the same action, and non-built-in subcommands go to the human. |
| **CI** | the CI provider | Lint, build, tests, docs tests and boundary tests on every PR; actions pinned to SHAs. |
| **Boundary tests** | test suite | Architectural boundaries (e.g. "module X never imports Y", "no client-specific names in the generic core") are tests, not just advice. |

Test a gate by importing its classifier and feeding it command strings. Never run a
dangerous command to see whether the gate catches it.

---

## 12. Platform access and credentials

**Goal**: ease while building, safety afterwards. During development the agent does and
sees everything the work needs (hosting, database, CI, logs) without the human relaying
results or approving each step. It can never destroy anything, and a secret is never
visible to it. When active development ends, it keeps its sight and loses its power.

### 12.1 Two phases

The phase is one line in the profile, `access.phase`. Only the human changes it.

| | Development | Observe (after close-out) |
|---|---|---|
| Repo and CI | full, through worktrees and PRs; the merge guard applies | read; new work re-opens development |
| Hosting platform | deploys, variables, restarts, logs, in every environment, production included | **no platform token**; logs through the channels in 12.5 |
| Database | reads and writes, through a role that owns nothing | the read-only role only |
| Destructive commands | denied | denied (and no credential could run them) |
| Secrets | injected at runtime from the secrets manager; never pasted, printed or read from files | none held; rotated at close-out |

### 12.2 The layers

No single layer is trusted. They are listed strongest first: the first three are enforced
on the server, where no prompt injection reaches; the rest are on the agent's machine.

1. **Credential scope.** What a token cannot do, nothing can make the agent do with it.
   Every credential is scoped to this one project, and to one environment where the
   platform allows it.
2. **A broker, where the platform cannot scope.** A small service holds the real platform
   token and offers the agent only named operations ("read logs", "deploy this
   service"), refusing all others. It solves the two things a token cannot: reading logs
   without being able to read secrets, and deploying without being able to delete. It is
   optional and built when a project needs it; the design is in [BROKER.md](BROKER.md).
3. **Database privileges.** The agent's write role is not the owner of anything, so it
   cannot DROP, TRUNCATE or ALTER. Migrations run under a separate migration role through
   the project's migrate command. Point-in-time recovery is on, so a bad write can be
   undone.
4. **The destroy gate.** A hook that denies destructive commands in every phase, even
   with approval: the human runs those in their own terminal. The list:
   - deleting, restoring or transferring anything on the hosting platform (a project,
     service, volume, environment, variable or domain), by CLI, API or MCP tool;
   - on a remote database: DROP, TRUNCATE, a DELETE or UPDATE without WHERE, ALTER TABLE
     ... DROP, `dropdb`, a restore that cleans first. A local database is not covered;
   - deleting, archiving, renaming or transferring the repository; deleting releases,
     secrets or variables; a force push or delete of the main branch;
   - writing a file that holds a platform delete mutation, or a script (shell, PowerShell,
     batch, CI YAML, Makefile, package.json, any `#!` file) that holds anything above;
   - running a script that holds anything above (`sh x`, `bash x`, `source x`, `./x`,
     `pwsh -File x`): the gate reads the script, so writing one first does not get round
     it.

   It also asks before any edit to the profile or the agent settings, so a session cannot
   switch a gate off or re-open development by itself.
5. **The ops gate.** In the observe phase it denies deploys, merges and platform changes.
   In both phases it denies commands that print secrets.
6. **Secrets never enter the session** (rule 3 below). A manipulated agent cannot leak a
   key it never saw.

**Prompt injection.** It arrives in text the agent reads: database rows, logs, issues, PR
comments, web pages, dependency files. Reading cannot be prevented, so the design limits
what a manipulated agent can do: nothing destructive (layers 1 to 4), nothing with a
secret (layer 6), and nothing outside this project (layer 1). Most reading is done by
reviewers, which cannot write at all. The hooks are a speed bump, not a wall: a script
that calls a platform's API directly never passes through them, which is why the
server-side layers come first.

### 12.3 Rules

1. **Access inventory.** The plan has an "Access inventory" table with one row per
   platform: what the agent uses it for, the credential, its scope, how it is injected,
   and how it is revoked or rotated at close-out. The agent has no access that is not
   listed there. Every grant and every revocation is a decision log entry.
2. **Isolate every credential to one project.** A leaked or misused token must never
   reach another project. Use project- or environment-scoped tokens. A tool that only
   works with an account-wide token is not used: pick another route. Keep one
   secrets-manager project and one machine identity per project.
3. **Secrets never enter the transcript.** Inject them into the process at runtime
   through the secrets manager's CLI (for example `infisical run -- <command>`). Never
   paste values, and never let the agent read `.env` files. Anything that appears in the
   context is stored in session transcripts on disk and may be passed to subagents. The
   ops gate denies commands that print secrets (`env`, `printenv`, platform "list
   variables" commands, `cat .env`). Limitation: this stops accidental exposure, not a
   determined process. Rotation at close-out is the backstop.
4. **Three database roles.** A **migration role** owns the schema and is used only by the
   migrate command. A **write role** for the agent in development: reads and writes
   rows, owns nothing. A **read-only role** for observe, which:
   - can connect and `SELECT` on named schemas only, with default privileges so that
     future tables in those schemas are readable too;
   - has no access to secret or personal-data tables or columns (expose a redacted view
     instead);
   - has a statement timeout, a connection limit, and `default_transaction_read_only =
     on`;
   - is proved by a test: a write attempt with it fails.
5. **Automate rotation.** Platform environment variables are **synced from the secrets
   manager**, never edited by hand, so a rotation reaches every environment by itself.
   Use the secrets manager's built-in rotation where it supports the credential type
   (database users usually are). Credentials it cannot rotate (most platform API tokens)
   get a manual step in the close-out checklist. Also rotate at once whenever a secret
   value shows up in a transcript, log, commit or PR.
6. **The close-out is a work package**, not a reminder. It revokes the platform tokens
   and the write role, rotates what the agent could reach, and sets `access.phase` to
   `observe`. Its Verify steps prove the end state:
   - each revoked token gets a real call that is refused;
   - the rotated credentials work in the app on every environment;
   - the read-only role can read, and a write attempt with it fails;
   - the logs still reach the agent (12.5);
   - every inventory row shows its final status.

   The plugin's `close-out` skill (`/athena-orchestrator:close-out`) runs it in two halves. The
   first checks that the project can close (no package open, main green, a complete
   inventory, a read-only role and a log channel), writes the package, and hands the user
   the checklist: the user does every rotation and revocation, so the agent never sees a
   new value. The second (`close-out verify`) runs the Verify steps and records them. The
   user then sets the phase and merges, because in the observe phase the agent cannot
   merge.
7. **Re-opening is explicit.** New development work re-grants access from the inventory
   and sets the phase back to `development`. The human does both. It is logged, and it
   ends with another close-out.

### 12.4 Who holds what

| Credential | Agent, development | Agent, observe | App |
|---|---|---|---|
| DB migration role (owner) | through the migrate command only | never | never |
| DB write role (owns nothing) | yes, injected at runtime | never | — |
| DB app role | never | never | yes |
| DB read-only role | yes | yes | — |
| Platform token (project-scoped) | yes, injected at runtime | never | — |
| Broker token, if there is a broker | yes | yes (read operations only) | — |
| Log sink, read-only query token | yes | yes | — |
| Log sink, ingest token | never | never | yes |

### 12.5 Logs the agent can read after development

Use two channels, because each one covers the other's blind spot:
- **App event table** (for example `ops.log_event`: time, level, source, event, message,
  a `context` JSON column). The app writes warnings, errors and lifecycle events
  (startup, shutdown, reconnects, job runs), plus a periodic heartbeat row. It works the
  same way on any hosting platform, and the read-only role can query it. Cap it with a
  scheduled retention delete (for example 30 days). Everything written to it must
  already be free of secrets and PII, because the agent reads it.
- **A log service with read-only query tokens** (for example Axiom: an advanced API token
  limited to querying one dataset). The agent reads logs there without holding any
  platform token. Prefer the shipping route that needs **no platform token at all**: the
  app sends a copy of its logs to the service itself (the vendor SDK or OpenTelemetry), or
  sends them to a forwarder such as Vector over the private network, which holds only
  the service's ingest token. Sidecars that read the platform's log API instead (for
  example Locomotive on Railway) are **not used**: they need an account-level platform
  token, which breaks per-project isolation (12.3, rule 2).
- **A broker** (12.2, layer 2) is the third option when the platform's own logs are
  wanted: it reads them with the platform token it holds and hands the agent only log
  lines.
- **Blind spots.** None of these routes carries build logs, and app-sent routes miss
  output from before the logger starts. Cover them with:
  - the deploy status the platform reports to the git host, which the agent can read
    with the git host's CLI;
  - the heartbeat row: when it stops, the app is down and the human checks the platform.

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
| Protected windows | Is there a time when nothing may deploy (a release window, a live event, a code freeze)? If so, a freeze-check command that answers it. |
| Environments | What a merge deploys to; what counts as production. |
| Model tiers | Which roles get the strongest model? Keep the verifier strong. |
| Budgets | Tool-call budgets and the heavy tools each lens may use. |
| Access inventory | Which platforms does the agent work on? How is each credential scoped to this one project? Which can the secrets manager rotate, and which need a manual step? When does active development end? |
| Observability | Which schemas can the read-only role see, and which are PII? What goes in the event table? Is there a log sink with read-only tokens? |

**Bootstrap order** (each step is itself a work package, done the manual way before the
orchestrator exists):
1. `CLAUDE.md` with hard rules; `IMPLEMENTATION_PLAN.md` with a status table, open
   questions and the follow-up register; an ADR index; a spec template with a Verify
   section.
2. Access: the access inventory, the secrets manager with environment variables synced
   to every platform, project-scoped tokens, the database roles (a write role without
   ownership, a read-only role), and runtime injection for every command that needs a
   secret.
3. The plugin enabled at project scope, and the profile: the access phase, gate commands,
   panel paths, environments, the docs gate patterns and the lens files. The plugin's
   gates enforce what the profile sets.
4. Docs tests; CI with the gate commands and a check named as `merge.required_check`;
   boundary tests.
5. PR template, `PROCESS.md`, and the decision log README with its template. Accept an
   ADR that grants the orchestrator its authority: to merge each package once the human
   approves it, and to deploy and change the platforms in the development phase.
6. The app event table and heartbeat (or the log sink), so the observe phase has
   something to read.
7. Only now run the orchestrator (`/athena`). Start with low-risk packages, read the
   flagged log entries closely, and tune the lenses.

The plugin's `adopt` skill (`/athena-orchestrator:adopt`) does steps 1, 3 and 5, and CI from
step 4, from templates. It maps what an existing project already has instead of
overwriting it, asks once for what it cannot infer, and writes nothing before the user
approves its mapping. The rest of the bootstrap (access, the docs and boundary tests, the
event table) it puts in the plan as the first work packages, so the orchestrator does
them; access is owned by the human. The user's approval of the mapping is the review:
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

When something new goes wrong, follow the same pattern. Record the incident in the
package log, change the rule in PROCESS.md, the skill and the agent files in one PR, and
if it is policy-level, have the human accept an ADR amendment.
