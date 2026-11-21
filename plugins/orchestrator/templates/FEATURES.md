# Feature map: {{project_name}}

Every flow a user can do in the product, in the user's words, with how to do it and what
must happen. It is the guide and the grading rubric for the end-to-end run
(`verify.e2e` in `.claude/orchestration/project.toml`): the run exercises each `active` row
and prints one result line per ID. A feature is done when its row passes there, not when
its unit tests do.

**Rules**
- A package that adds or changes what the product does adds or updates its rows here, in
  the same PR, and its spec names them in "End to end".
- An existing row's expected result changes only when the package's spec asks for that
  change. Otherwise it is a test weakened to pass, a Blocker.
- A row leaves the run only with its flow: `retired (<ID of the package>)`, never quietly.
- Rows marked `smoke` are the short list run against development after every merge
  (`verify.smoke`): the flows that show the deployment is alive and doing its job.

| ID | Flow (the user's words) | Who | Steps (where it starts, what the user does) | Expected result | Smoke | Status |
|---|---|---|---|---|---|---|
| F1 | <what the user wants to get done> | <user> | <the page, command or endpoint; each action, with the selector, input or shortcut> | <what the user sees, and what is stored> | yes | active |
