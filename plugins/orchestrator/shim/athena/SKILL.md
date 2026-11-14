---
name: athena
description: athena-orchestrator shortcut. Runs the athena-orchestrator plugin's orchestrator in the current project - /athena for the next work package, /athena <ID> for one package, /athena all to keep going. Use when the user types /athena.
argument-hint: "[next | <package ID> | all]  (default: next)"
---

# /athena

This is a shortcut, installed in `~/.claude/skills/athena/` by the athena-orchestrator plugin's
`adopt` skill. It does nothing itself.

Invoke the skill `athena-orchestrator:orchestrate` now, with these arguments, unchanged:
`$ARGUMENTS`. Then follow that skill.

If that skill is not available, the plugin is not installed, or not enabled in this
project. Say so, do nothing else, and tell the user:
- to install it: `claude plugin marketplace add <the athena-orchestrator repository>`, then
  `claude plugin install athena-orchestrator@athena-orchestrator`;
- to set a project up for it: `/athena-orchestrator:adopt` in that project.
