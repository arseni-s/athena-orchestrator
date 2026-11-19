# {{project_name}}

{{project_summary}}

## Start here, every session

1. [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md): what to work on, and the
   only place status lives.
2. [docs/decisions/](docs/decisions/README.md): accepted decisions. They are binding; do
   not re-open them. Propose a new ADR instead.
3. The spec of your work package in [docs/work/](docs/work/README.md).

Normal mode is the orchestrator (`/athena`, or `/athena-orchestrator:orchestrate`): it delegates
coding and review to subagents, presents a summary of each package, merges it when you
reply "approved", and records every decision in
[docs/decisions/log/](docs/decisions/log/README.md). How it works:
[docs/PROCESS.md](docs/PROCESS.md). Its settings are the profile,
`.claude/orchestration/project.toml`; only the user changes it.

## Hard rules

Breaking one of these is a Blocker, whatever a spec says.

- {{hard_rule}}
- **Destruction beyond development is a hard no**, even with approval: deleting the
  hosting platform's project or an environment, the repository, anything in the secrets
  manager, a force push or delete of `{{main}}`. The user runs them in their own terminal.
  The destroy gate denies them. Inside development, resets, drops and deletes are allowed:
  development rebuilds from scratch with one command. Production is the user's: the agent
  holds no credential for it, and the user deploys it by hand.
- **Secrets never enter the session.** Every secret lives in the secrets manager (the
  `-dev` and `-prod` vaults); `scripts/push_secrets.py` copies them to the platform. Plain
  settings live in `config/<environment>.env`, committed, and the app reads the one
  `APP_ENV` names.
  Commands that need one get it injected at runtime (`op run --env-file=<refs> --
  <command>`). Never read `.env` files and never print a secret's value. No real value is
  kept in a `.env` file, and only the user adds or changes a secret.
- **The safeguards stay on**: the package manager's release-age and install-script
  settings, the secret scan in CI, the backup job, and the development rebuild. Never switch one off or bypass it
  to get a build through; a package that needs its install script is allowed by name, on
  the user's word. They are listed in the plan's "Safeguards" table.
- **Docs change with code**, in the same PR. The docs gate enforces it.

## Conventions

- Work in a worktree and branch per package (`wp/<id>-<slug>`); never share a branch with
  another session.
- Tests first for critical behaviour. Never weaken, skip or delete a test to get green.
- Never write files through a shell heredoc.

## Commands

```bash
{{gate_command}}
```
