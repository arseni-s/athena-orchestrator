## <ID>: <title>
Spec: docs/work/<ID>-<slug>.md · Decision log: docs/decisions/log/<ID>.md

<!-- The same sections as the orchestrator's PR body, plus the checklist, so one body
serves both. A manual session fills the same sections. Refresh Gates and the checklist
after the final rebase, before the merge. Merge conditions: docs/PROCESS.md. -->

### What changed
<!-- 3 to 6 bullets: what changed and why. -->

### Verify (real output)
<!-- Each Verify step in the spec: the command and its real output, trimmed to the
relevant lines. "Tests pass" is not enough. -->

### End to end (real output)
<!-- The end-to-end run on the running product (`verify.e2e`): the command, then one line
per flow, pass or fail, with the flows this package added or changed marked. For a
changed flow, the evidence (screenshot or trace path). Or "none" with the spec's reason. -->

### Gates
<!-- The gate commands and their result lines, re-run after the last rebase. -->

### Review panel
| Lens | Round(s) | Blocker | Major | Minor | Outcome |
|---|---|---|---|---|---|

### Decisions
<!-- One line per decision log entry: D<n>, title, flag. -->

### Follow-ups
<!-- Or "none". -->

### Checklist
- [ ] Work package ID and spec linked above
- [ ] Verify steps and gates run, **real output pasted** above
- [ ] End-to-end run passed on the running product, flows of this package included (or "none" with the spec's reason)
- [ ] Feature map updated for every flow added or changed; no expected result loosened
- [ ] Review panel: no open Blocker or Major finding
- [ ] Decision log written and linked above
- [ ] Docs updated (or `[no-docs]` with a reason)
- [ ] Hard rules in `CLAUDE.md` kept
- [ ] No secrets or personal data in code, fixtures or logs
- [ ] Status and follow-up register updated in `docs/IMPLEMENTATION_PLAN.md`
