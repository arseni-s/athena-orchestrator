# Trial (build step 10)

The plugin was called `athena-ergane` during these runs, and this record keeps that name.
It is now `athena-orchestrator`.

What happened when the plugin was installed and run against a throwaway project, and what
broke. Each finding says what was changed because of it.

## Run 1: local only (13 Nov 2026)

**Setup.** A fictional library, *Tillsum* (invoice totals, stdlib `unittest`), as a local
git repo with no remote, plus a `.env` holding a fake canary value. The repo was added as
a folder marketplace (`claude plugin marketplace add C:/DEV/athena-ergane`) and the plugin
installed **at project scope** in the trial repo (`claude plugin install
athena-ergane@athena-ergane --scope project`), so its hooks run nowhere else. Windows 11,
Git Bash, Python 3.14, Claude Code 2.1.322.

**Method.** Each command in the *installed* copy's `hooks/hooks.json` was run through Git
Bash's `sh`, as Claude Code runs it, with sample `PreToolUse` events on stdin. The
commands under test were strings inside the events; none was executed. Three states: no
profile, a valid profile in `development`, the same profile in `observe`. The profile was
the template filled in by hand, as `adopt` would fill it. A real, uncommitted code change
gave the docs gate something to judge.

**Results: every gate answered as PROFILE.md section 4 says.**

| Call | No profile | development | observe |
|---|---|---|---|
| `cat .env`, `printenv` | ask | deny (secrets) | deny (secrets) |
| `railway up` | ask | allowed | deny (observe) |
| `railway delete --yes` | deny (destroy) | deny (destroy) | deny (destroy) |
| `git push origin main` | ask | deny (merge guard) | deny (merge guard) |
| `gh pr merge --auto` | ask | deny (merge guard) | deny |
| Write `project.toml` or `.claude/settings.json` | ask (destroy gate) | ask | ask |
| Write a code file | allowed | allowed | allowed |
| `python -m unittest ...` | allowed | allowed | allowed |
| `git commit -am` with code and no docs | allowed (docs gate off) | deny (docs gate) | deny |

The fallback stub from `templates/settings.json`: silent while the plugin is installed;
"ask" (GATES MISSING) when the registry is not found.

**Answered: where `installed_plugins.json` lives.** `~/.claude/plugins/installed_plugins.json`,
created on the first install (before it, the folder holds only `known_marketplaces.json`).
It holds the key `"athena-ergane@athena-ergane"`, which is what the stub greps for. The
stub's default path is right. `CLAUDE_CODE_PLUGIN_CACHE_DIR` was unset; whether Claude
Code honours that variable is still unverified, and the default path does not depend on it.

### Findings

| # | What broke | Change |
|---|---|---|
| F1 | `claude plugin install --scope project` writes `.claude/settings.json` and leaves it uncommitted, and `adopt` stopped on any uncommitted change, so the documented order (install, then adopt) always stopped. | `adopt` step 1.3 keeps that one change and includes it in its commit. |
| F2 | A folder marketplace copies the plugin folder as it is, so the `__pycache__/` the tests left beside the gate scripts was installed too. | `tests/gatelib.py` sets `sys.dont_write_bytecode`; nothing is written under `plugins/` now. |
| F3 | Not a plugin defect: running `adopt` in a headless `claude -p` session with bypass permissions was refused by the calling session's auto-mode classifier. | Run 2 is an interactive session the user starts. |

## Run 2: bypass-permissions mode in a real session (13 Nov 2026)

The user started an interactive Claude Code session (2.1.323, VS Code) in the trial repo,
in bypass-permissions mode, with no profile yet, and asked it to make calls. The plugin
was loaded: its skills were listed, and its Stop hook ran.

| Call | The gate answers (driven directly) | What happened in bypass mode |
|---|---|---|
| `cat .env` | ask | A plain permission prompt with no gate text: most likely Claude Code's own protection of `.env` files, not the hook. The user declined. |
| `railway --version` | ask | **Ran**, with no prompt (the CLI was not installed, so it only failed). |
| `railway delete --yes` | deny | Not tested: the session's Claude refused to make the call. |
| Write `cleanup.sh` holding `railway delete --yes` | **allowed** (F4) | Written. |
| Write `note.graphql` holding `mutation { projectDelete(...) }` | deny | **Blocked**, with the DESTROY GATE message. |

**Answered: in bypass-permissions mode a hook's "deny" holds and its "ask" is ignored.**
Hook input carries the mode as `permission_mode` (confirmed in the Claude Code binary).

### Findings

| # | What broke | Change |
|---|---|---|
| F4 | The destroy gate checked written files only for Railway GraphQL delete mutations, and never read a script that a command runs. So a `railway delete` written into `cleanup.sh` and then run with `sh cleanup.sh` passed both times. | Script-like files written (shell, PowerShell, batch, YAML, Makefile, justfile, Procfile, `package.json`, any `#!` file) get the shell rules (`write-script`). A script run with `sh`, `bash`, `source`, `.`, `./x` or `pwsh -File` is read and checked, to three levels (`script-run`). An unreadable script named to an interpreter denies. 19 cases added. Application code is not scanned, so a Python file that builds SQL is not over-matched. |
| F5 | Every "ask" was a silent "allow" in bypass mode: edits to the profile and settings (so a session could switch a gate off or re-open development), an unadopted project's deploys and merges, unreadable commands, and the gates-missing stub. | Each gate denies instead of asking when `permission_mode` is `bypassPermissions`, and says why. The `hooks.json` fallbacks and the stub read the event and do the same. |

After the fixes the plugin was updated to 0.2.0 and the key calls replayed against the
installed copy: the `cleanup.sh` write is denied in every mode, and the profile edit,
`railway up` and `cat .env` (no profile) ask in normal mode and are denied in bypass mode.

## Run 3: the skills in a real session (13 Nov 2026)

One interactive session in the trial repo, in normal permission mode.

**`/athena-ergane:adopt`: passed.** It checked the repo and found no profile, surveyed
the project without reading `.env`, asked four questions in one round, and showed the
full mapping and profile before writing anything. On approval it wrote one commit on
`adopt-athena-ergane`: 14 files created, `.claude/settings.json` appended with the stub
and its `enabledPlugins` line kept, the event table skipped (no database), the ADR
`Proposed`. The user's package became T1, and the seed packages were renumbered T2
(access, `human`) and T3 (docs and boundary tests) to fit. The profile loader exits 0;
no `{{placeholder}}` or `TODO(adopt)` is left; the gates pass. The destroy gate asked
before the profile and settings writes, and the user approved. The `/athena` shortcut
was installed, identical to the plugin's copy.

**`/athena T1` ("reject negative unit prices"): passed, up to the expected stop.** The
shortcut handed off to `athena-ergane:orchestrate`, which:
- claimed T1 in `athena-trial-wp-t1` on `wp/t1-reject-negative-unit-prices`;
- dispatched the implementer, which added a two-line check, one test and a README line,
  in one commit with code and docs together (the docs gate allowed it);
- re-ran the gate itself, chose the **full panel** because the diff touches
  `paths.full_panel`, logged why, and dispatched all five reviewers in one message;
- got four approvals and one Minor (reliability: the error message names neither the sku
  nor the value), which became a follow-up. No Blocker or Major, so no verifier and one
  round;
- checked on its own, in a scratch copy, that the new test fails on the old code, because
  the tests reviewer had not;
- stopped before the PR, since there is no remote: status `blocked`, four decisions
  (three flagged for review), four `unscheduled` follow-ups in the register, and the
  log index row.

The result is right: a minimal fix, an honest test, real output, and a decision log a
human can audit in a minute.

Run elsewhere by mistake: `/athena T1` was first typed in a session in another project,
where the plugin is not enabled. The shortcut found no orchestrator and did nothing, as
designed.

### Findings

| # | What broke | Change |
|---|---|---|
| F6 | The orchestrator ran although the adoption was not merged to `main` and the process ADR was still `Proposed`. It coped (it branched from the adoption branch and logged that as a flagged decision), but its authority comes from that ADR. | `orchestrate` section 2.3: stop when the profile is not on the main branch, or an ADR in `plan.read_at_start` is still `Proposed`. MODEL.md section 4 says the same. |
| F7 | On a stop it forgot the log index row at first, and caught it itself: the skill named the index only on the merge path. | The stop conditions (skill section 8, MODEL.md section 8) add the index row and commit on the package branch. |
| F8 | `adopt` left its commit on a branch for the user to merge by hand, and the ADR for the user to edit to Accepted. The user had already approved the exact profile and mapping, so this was a second, mechanical review; it was skipped, and `/athena` then stopped on it (correctly, after F6) until the trial ended. | The approval of the mapping is the review: `adopt` lands the commit on the main branch itself (a fast-forward without a remote; a PR merged through CI and the merge guard with one), and the same approval accepts the ADR unless the user declines. |
| — | Not plugin defects: a first Edit failed because the file had not been read in that session (the model retried correctly), and one API call failed on a network error. | none |

**Observed: a local folder marketplace serves the plugin from the source.** The skills
loaded from `C:\DEV\athena-ergane\plugins\orchestrator`, not from the installed copy, so
edits in this repo reach a running trial at once. A plugin installed from a git
marketplace is served from its cached copy instead.

A second `/athena T1` (with the F6 check in place, since a folder marketplace serves the
source) found nothing changed, re-ran nothing, named what unblocks T1, and refused to
merge the adoption itself. **The trial ended here, by the user's decision** (no GitHub
repo for it).

### Not trialled

- **The PR, CI and merge path**, and the merge guard against a real PR: they need a
  GitHub remote (T2).
- **`close-out`**: it needs real platform credentials to revoke and prove refused. Trial
  it on the first real project that reaches the end of development.
- **A fix round, the verifier and the round cap**: T1 had no Blocker or Major.
