# {{lens}}: {{project_name}}

<!-- What this lens means in this project. Short: aim for under 40 lines; when it grows past
that, merge or retire items, on the user's word. It never changes the rubric, the report
format, the budget or the safety rules. Every section is optional, except in
correctness.md, which needs at least "Sources of truth" and "Cases to trace". Only the user
changes this file: the destroy gate asks before every edit, and reviewers read it as it is
on the main branch. -->

## Sources of truth
- <file the reviewer reads before judging: an ADR, a rule file, a contract>

## Check
- <a project-specific check; name the severity when it is not obvious>

## Invariants
<!-- Correctness: rules that hold for every input (a round trip returns the original; a
balance is never negative; running it twice is the same as once; the new code gives the
old code's answer). Each one is a property test, not a handful of examples. -->
- <an invariant, and where it is decided>

## Rules from misses
<!-- Each one is something a review missed and the user or development caught: what in a
diff wakes it, the check, and where it came from. A reviewer applies an item only when
its trigger matches the diff. -->
- <trigger: what in a diff wakes it> → <the check>. (<package ID, log entry>)

## Cases to trace
- <a concrete input, failure, or user and task, to walk through the diff>

## Heavy tools
<!-- What this lens may run beyond reading and tests, and only for what. Delete the
section to allow none. -->
