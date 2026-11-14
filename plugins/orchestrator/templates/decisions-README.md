# Decision records

One file per architecture-level decision, `NNNN-<slug>.md`. **Accepted** records are
binding until a new record supersedes them. An agent may draft one as `Proposed`; only the
user accepts it.

Execution-level decisions (a default chosen, a finding dismissed, a spec deviation) are
not recorded here. They are in the decision log, [log/](log/README.md), one file per work
package.

| # | Decision | Status |
|---|---|---|

## Template

```markdown
# ADR-NNNN: <title>

**Status:** Proposed | Accepted, <date> | Superseded by [ADR-NNNN](NNNN-<slug>.md)

## Context
What forces the decision: the problem, the constraints, what was tried.

## Decision
What is decided, in a few bullets. Concrete enough that a reviewer can tell when it is
broken.

## Consequences
What becomes easier, what becomes harder, and what has to change because of it.
```
