# Templates

The files the `adopt` skill puts in a project. Each row is one template and where it goes.
`adopt` never overwrites: when the target exists, it maps what is there instead (see its
skill file).

| Template | Target in the project | Bootstrap step (MODEL.md 13) |
|---|---|---|
| `project-CLAUDE.md` | `CLAUDE.md` (and `AGENTS.md`, byte-identical, if the project keeps one). Named so that Claude Code never loads it as this plugin's own memory | 1 |
| `IMPLEMENTATION_PLAN.md` | `docs/IMPLEMENTATION_PLAN.md` (`plan.plan`) | 1 |
| `decisions-README.md` | `docs/decisions/README.md` (`plan.adrs`): the ADR index and template | 1 |
| `work-README.md` | `docs/work/README.md` (`plan.specs`): the spec template | 1 |
| `project.toml` | `.claude/orchestration/project.toml`: the profile | 3 |
| `lens.md` | `.claude/orchestration/lenses/correctness.md` (required), and any other lens file | 3 |
| `settings.json` | merged into `.claude/settings.json`: enables the plugin, and the gates-missing stub | 3 |
| `ci.yml` | `.github/workflows/ci.yml` | 4 |
| `pull_request_template.md` | `.github/pull_request_template.md` | 5 |
| `PROCESS.md` | `docs/PROCESS.md` (`plan.process`) | 5 |
| `log-README.md` | `docs/decisions/log/README.md` (`plan.log`): the log index and template | 5 |
| `adr-orchestrated-development.md` | `docs/decisions/<next number>-orchestrated-development.md`, status `Proposed` | 5 |
| `log_event.sql` | the project's migrations folder, as its next migration | 6 |

## Placeholders

`{{name}}` (lowercase, no spaces) is filled by `adopt` from what it learns about the
project, and never left in a file it writes. GitHub's own `${{ expression }}` in `ci.yml`
is not a placeholder and stays as it is. A placeholder it cannot fill becomes a `TODO(adopt): <question>` line, and
the question goes in its report.

Text in `<angle brackets>` is not a placeholder. It stays in the file: it is the shape the
orchestrator or a human fills in later, for each package or decision.

| Placeholder | Meaning |
|---|---|
| `{{project_name}}` | `project.name` |
| `{{project_summary}}` | `project.summary` |
| `{{main}}` | `repo.main` |
| `{{gate_command}}` | one `repo.gates` command; repeat the line for each |
| `{{user_visible}}` | `rubric.user_visible` |
| `{{condition}}` | one `rubric.conditions` entry; repeat for each |
| `{{deploy_dev}}`, `{{deploy_prod}}` | `deploy.dev`, `deploy.prod` |
| `{{required_check}}` | `merge.required_check`; also the CI job id |
| `{{date}}` | today, `YYYY-MM-DD` |
| `{{adr_number}}` | the next free ADR number, four digits |
| `{{lens}}` | the lens a lens file is for (`Correctness`, `Reliability`, ...) |
| `{{ci_setup}}` | CI steps that install the toolchain the gates need. Installs come from the lockfile only (`npm ci`, `pnpm install --frozen-lockfile`, `uv sync --locked`) |
| `{{secret_scan}}` | the CI step that scans the pull request's commits for secrets (`infisical scan` or `gitleaks`), with the scanner installed at a pinned version, never `latest` |
| `{{hard_rule}}` | one hard rule of the project; repeat for each |
| `{{docs_hint}}` | `docs.hint` |

Paths in the templates are the `[plan]` defaults. When a project's profile sets other
paths, `adopt` writes the files there and fixes the links.
