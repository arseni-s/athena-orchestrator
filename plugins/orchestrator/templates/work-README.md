# Work package specs

One spec per work package, `<ID>-<slug>.md`, linked from the status table in
[../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md). Status lives only in the plan,
never in a spec.

A spec says what to build and how to prove it. The implementer builds exactly the spec;
work found outside it becomes a follow-up. Write **Verify** steps that a machine can run:
the orchestrator and the reviewers run them, and their real output goes in the PR.

Add the words **plan mode** to a spec to have its plan reviewed before any code is
written (the profile's `paths.design_review` does the same by path).

## Template

```markdown
# <ID>: <title>

| Field | Value |
|---|---|
| Depends on | <IDs, or —> |
| Target | <date> |
| Decisions | <the ADRs that apply> |

## Goal
One or two sentences: what is true when this is done.

## Scope
- What to build, one bullet per piece.
- **Out of scope**: what a reader might expect here but is not.

## Verify
1. `<command>`: <the output that proves it>
2. <a manual step only when nothing can be automated; say why>

## Docs
The docs to add or update in the same PR.
```
