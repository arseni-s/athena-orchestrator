# Decision log

Every decision the orchestrator makes, one file per work package (`<ID>.md`). To revisit
something, start with the **Flagged** column, then open the file. Each entry's **Revise
by** line says what to change. To undo a whole package, revert its squash commit.

Architecture-level decisions are not recorded here; they are ADRs in [../](../README.md).

## Index

Newest first. The orchestrator adds a row when a package is merged, blocked or stopped.

| Package | Date | Outcome | PR | Decisions | Flagged |
|---|---|---|---|---|---|

## File template

```markdown
# <ID>: <work package title>

| Field | Value |
|---|---|
| Spec | <link> |
| Branch / PR | wp/<id>-<slug> / #<n> |
| Outcome | merged <sha> / blocked / stopped / waiting for approval |
| Rounds | <n> of 3 |
| Dates | <start> to <end> |

## Summary
Two or three sentences: what was built, what was left out, what to look at.

## Decisions

### D1: <short title>
- **Kind**: default chosen | finding dismissed | finding deferred | spec deviation | scope cut | status correction | stop | access | other
- **Decision**: what was decided.
- **Why**: the reason, naming the ladder rung (hard rule, ADR-NNNN, spec, architecture, existing pattern, boring option, open question default).
- **Alternatives**: what else was possible.
- **Revise by**: the setting, file or commit to change (for example "revert <sha>").
- **Flag**: review | none

## Review findings

| ID | Severity | Lens | Claim | Verdict | Resolution |
|---|---|---|---|---|---|

## Follow-ups
Work found but kept out of scope. Each one is also in the follow-up register in
docs/IMPLEMENTATION_PLAN.md, with a target package or `unscheduled`.
```
