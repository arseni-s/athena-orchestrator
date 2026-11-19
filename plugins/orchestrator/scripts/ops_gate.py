"""PreToolUse hook on Bash and PowerShell: the ops gate and the merge guard (athena-orchestrator).

Configured by the project profile (`.claude/orchestration/project.toml`, docs/PROFILE.md):
`repo.main` and `merge.required_check`. Destructive commands are not this gate's job:
`destroy_gate.py` denies the ones whose reach spans environments.

    allow        Deploys and platform commands (Railway, `docker push`, release tags and
                 workflows) run without a prompt: the agent's credentials reach development
                 only, and production is deployed by the user by hand (docs/MODEL.md 12).
    deny         Merge guard: `gh pr merge` (or a `gh api` merge) unless every check on the
                 PR's head commit passed and `merge.required_check` succeeded, as `gh pr
                 view` reports; `--auto`; a `git push` to a main branch (refspec,
                 `--all`/`--mirror`, or a bare push while the current branch is a main
                 branch). It fails closed: `gh` or `git` missing, failing, timing out or
                 printing something unreadable denies.
    deny         Commands that print secrets into the transcript: `printenv`, a bare `env`,
                 `set` or `export`, the PowerShell `env:` provider, `.env` files read by a
                 reader (`cat`, `Get-Content`, `grep`, ...), Railway variable listings, the
                 Infisical commands that show values or a token (`secrets`, `secrets get`,
                 `export`, `user get token`, `login --plain`), and a one-line dump of the
                 whole environment (`console.log(process.env)`, `print(os.environ)`). The
                 command an injector runs is read too: `infisical run -- printenv`,
                 `railway run env`, `railway ssh printenv`. This stops accidents, not a
                 determined process (docs/MODEL.md section 12).
    ask          Commands the gate cannot read well enough to rule out a hidden merge or
                 push: an encoded PowerShell command, a shell reading commands from input,
                 a git or gh subcommand that is not built in, a ref named by a variable.
                 Also an Infisical command that changes secrets, switches the login, or
                 has no rule here.

Without a profile (a project that has not adopted the plugin), every opinion above becomes
"ask". With a profile that cannot be read or checked, every shell call asks.

How a command is read: it is cut into segments at unquoted `|`, `;`, `&`, newlines,
brackets (and backticks in Bash), and each segment into words, honouring quotes and the
shell's escape character. Heredoc and PowerShell here-string bodies are data, not
commands. A program counts in command position: the first word of a segment, after Bash
keywords (`if`, `do`, `!`, ...), `VAR=x` and launchers (`sudo`, `env`, `xargs`, `timeout`,
`npx`, `pnpm dlx`, `Start-Process`, ...). A string a shell runs (`bash -c "..."`, `eval`,
`watch`, `iex`, a `$(...)` inside double quotes, a heredoc fed to a shell) is read again as
a command. Backstop: an unquoted program word anywhere else (`mywrap railway up`) asks if
its classifier would. A quoted mention (`git commit -m "railway up"`) is not a command.
The table PROGRAMS maps each program to its classifier, which sees the words after it.

If the hook itself crashes it answers "ask", never silence.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import athena_profile  # noqa: E402  (the sibling module: profile loading and path patterns)

# Merge guard: all its `gh`/`git` calls share one budget, well inside the 30 s hook
# timeout (a hook timeout fails open). Tests replace GH_CMD and GIT_CMD in-process.
GUARD_BUDGET_S = 12
GH_TIMEOUT_S = 10
GIT_TIMEOUT_S = 5
GH_CMD = ["gh"]
GIT_CMD = ["git"]
# Set from the profile by `configure()`. `main` and `master` are always main branches.
DEFAULT_MAIN = frozenset({"master", "main"})
MAIN_BRANCHES: set[str] = set(DEFAULT_MAIN)
REQUIRED_CHECK = ""


def configure(data: dict[str, Any]) -> None:
    """Points the module's settings at a checked profile (or the defaults, for {})."""
    global MAIN_BRANCHES, REQUIRED_CHECK
    main = (data.get("repo") or {}).get("main")
    MAIN_BRANCHES = set(DEFAULT_MAIN) | ({main.lower()} if main else set())
    REQUIRED_CHECK = (data.get("merge") or {}).get("required_check") or ""


@dataclass(frozen=True)
class Merge:
    """A PR merge: allowed only if the PR's head commit has green checks."""
    pr: Optional[str]  # number, branch or URL; None: the current branch's PR
    repo: Optional[str] = None  # `-R owner/repo`


@dataclass(frozen=True)
class Push:
    """A push with no refspec (or of HEAD): denied if the current branch is the main one."""
    dirs: tuple[str, ...] = ()  # `git -C <dir>` values, in order
    git_dir: Optional[str] = None


@dataclass(frozen=True)
class Chdir:
    """The command changes directory, so the session's current branch may not apply."""


class Secret(str):
    """A deny reason for a command that prints secrets (not a merge guard reason)."""


class Platform(str):
    """An ask reason from a platform rule (a Railway command outside the read allowlist).
    With a profile these run; without one they ask."""


# A merge guard verdict: a deny reason, or a check to run before the call is allowed.
# A `Secret` travels the same way but is reported apart.
Guard = Union[str, Merge, Push, Chdir]
Verdict = tuple[Optional[str], Optional[str], Optional[Guard]]  # (deploy, ask, guard)
NONE: Verdict = (None, None, None)


def _program(word: str) -> str:
    """The program a word names: the base name without .exe/.cmd/.ps1/.bat, lower case."""
    scoped = re.fullmatch(r"@(railway|infisical)/cli(@\S*)?", word, re.IGNORECASE)
    if scoped:  # `npx @railway/cli up`, `npx @infisical/cli export`
        return scoped.group(1).lower()
    base = re.split(r"[\\/]", word)[-1].lower()
    return re.sub(r"\.(exe|cmd|ps1|bat)$", "", base)


def _norm(word: str) -> str:
    """`--Set=FOO` -> `set`: flags compared without dashes, value or case."""
    return word.lower().lstrip("-").split("=", 1)[0]


def _flags(args: list[str]) -> set[str]:
    return {_norm(a) for a in args if a.startswith("-")}


def _positional(args: list[str], value_flags: frozenset[str] = frozenset()) -> list[str]:
    """Words that are not flags, skipping the value of a known `--flag value` pair."""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a.startswith("-"):
            skip = "=" not in a and a in value_flags
        else:
            out.append(a.lower())
    return out


def _deploy(why: str) -> Verdict:
    return why, None, None


def _ask(why: str) -> Verdict:
    return None, why, None


def _guard(guard: Optional[Guard]) -> Verdict:
    return None, None, guard


# --- per-program classifiers: args after the program name -> Verdict ---------------------

# Railway CLI 5.71.0 (`railway <cmd> --help`). Anything not listed here asks.
RAILWAY_VALUE_FLAGS = frozenset({
    "-s", "--service", "-e", "--environment", "-p", "--project", "--port", "-n", "--lines",
    "--tail", "-f", "--filter", "--limit", "-S", "--since", "-U", "--until", "--method",
    "--path", "--set", "--set-from-stdin", "-t", "--template",
})
RAILWAY_ALIASES = {
    "variables": "variable", "vars": "variable", "var": "variable", "deployments": "deployment",
    "ls": "list", "function": "functions", "func": "functions", "fn": "functions",
    "funcs": "functions", "fns": "functions",
}
RAILWAY_READS = {"status", "logs", "metrics", "docs", "whoami", "list"}
# Commands that run something else: a `--help` after them may belong to that program.
RAILWAY_EXEC = {"run", "local", "shell", "ssh", "sandbox", "sandboxes", "sbx", "dev", "develop",
                "connect", "agent", "api", "code", "ca"}
RAILWAY_SERVICE_SUBS = {"list", "ls", "delete", "remove", "rm", "link", "source", "status", "logs",
                        "redeploy", "restart", "scale", "files", "file", "help"}
# GraphQL mutations that deploy: `serviceInstanceDeploy`, `...Redeploy`, variable upserts
# (not the `deployments` query).
GRAPHQL_DEPLOY = re.compile(r"[Dd]eploy(?!ment)|variable(Collection)?Upsert")
RAILWAY_OTHER = "is a Railway command outside the read allowlist (status, logs, list, ...)"


def _railway(args: list[str]) -> Verdict:
    pos = _positional(args, RAILWAY_VALUE_FLAGS)
    flags = _flags(args)
    cmd = [RAILWAY_ALIASES.get(pos[0], pos[0])] + pos[1:] if pos else []
    top, sub = (cmd + ["", ""])[:2]
    if top in ("", "help", "version") or (top not in RAILWAY_EXEC and flags & {"h", "help", "v", "version"}):
        return NONE
    if top in RAILWAY_READS:
        return NONE
    if top in ("up", "redeploy", "deploy"):
        return _deploy("is a Railway deploy")
    if top == "variable":
        if flags & {"set", "set-from-stdin"} or sub in ("set", "edit"):
            if "skip-deploys" in flags:
                return _ask("changes Railway variables (--skip-deploys)")
            return _deploy("changes Railway variables, which redeploys the service")
        if sub in ("", "list", "ls"):  # a listing prints secret values
            return _guard(Secret("lists Railway variables, which prints their values into the transcript"))
        return _ask(RAILWAY_OTHER)
    if top == "deployment":
        if sub in ("up", "deploy", "redeploy"):
            return _deploy("is a Railway deploy")
        return NONE if sub in ("list", "ls") else _ask(RAILWAY_OTHER)
    if top == "service":
        rest = cmd[1:]
        if rest and rest[0] not in RAILWAY_SERVICE_SUBS:
            rest = rest[1:]  # the deprecated `railway service <name> <cmd>` form
        if rest[:1] == ["redeploy"] or rest[:2] == ["source", "connect"]:
            return _deploy("redeploys a Railway service or connects its source")
        return NONE if rest[:1] in (["list"], ["ls"], ["status"], ["logs"]) else _ask(RAILWAY_OTHER)
    if top == "domain":  # bare `railway domain [name]` creates a domain
        return NONE if sub in ("list", "ls", "status") else _ask(RAILWAY_OTHER)
    if top == "functions":
        if sub in ("push", "up", "deploy"):
            return _deploy("pushes a Railway function (a deploy)")
        return NONE if sub in ("list", "ls") else _ask(RAILWAY_OTHER)
    if top == "config":
        if sub == "apply":
            return _deploy("applies Railway config (a deploy)")
        return NONE if sub == "plan" else _ask(RAILWAY_OTHER)
    if top in ("postgres", "mysql", "redis"):  # config changes "commit and deploy by default"
        reads = sub == "history" or cmd[2:3] in (["status"], ["progress"]) or (
            cmd[1:4] in (["pitr", "backup", "list"], ["pitr", "schedule", "list"]))
        return NONE if reads else _deploy("changes a Railway database service (deploys by default)")
    if top == "api" and any(GRAPHQL_DEPLOY.search(a) for a in args):
        return _deploy("calls a Railway API mutation that deploys")
    return _ask(RAILWAY_OTHER)


def railway(args: list[str]) -> Verdict:
    deploy, ask, guard = _railway(args)
    return deploy, Platform(ask) if ask else None, guard


GIT_GLOBAL_VALUE_FLAGS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
# A version: `v2`, `v1.2.3-rc1`, `2026.12.01`, `1.0.0+build.5`; not `v2-docs` or `1.2-hotfix`.
VERSION_SUFFIX = r"(?:rc|alpha|beta|pre|preview|dev|build)(?:\.?\d+)*|\d+(?:\.\d+)*"
GIT_TAG_REF = re.compile(
    rf"refs/tags/.*|release-.*|v\d+(?:\.\d+)*(?:[-+.](?:{VERSION_SUFFIX}))*"
    rf"|\d+\.\d+(?:\.\d+)*(?:[-+](?:{VERSION_SUFFIX}))*", re.IGNORECASE)
GIT_PUSH_VALUE_FLAGS = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})


def _main_ref(ref: str) -> bool:
    """`master`, `main`, `refs/heads/master` (refs are compared in lower case)."""
    return re.sub(r"^refs/heads/", "", ref) in MAIN_BRANCHES


def _push_guard(rest: list[str], refspecs: list[str], dirs: list[str],
                git_dir: Optional[str]) -> Optional[Guard]:
    """Merge guard for `git push <rest>`: the main branch takes no direct pushes."""
    if _flags(rest) & {"all", "branches", "mirror"}:
        return "pushes every branch (--all/--mirror), the main branch included"
    # The destination of `src:dst`, `+src:dst`, `:dst` (a delete) or `name` (same name).
    dests = [spec.lstrip("+").split(":", 1)[-1] for spec in refspecs]
    if any(_main_ref(dst) for dst in dests):
        return "pushes to the main branch (master/main) directly"
    if not refspecs and "tags" in _flags(rest):
        return None  # `git push --tags` pushes tags only, never a branch
    if not refspecs or any(spec.lstrip("+") in ("head", "@") for spec in refspecs):
        return Push(tuple(dirs), git_dir)
    return None


# Aliases hide what a command runs (`git -c alias.x=push x`, `gh alias set m "pr merge"`).
ALIAS_RISK = ("defines a git or gh alias or runs a gh extension, which can hide a merge or "
              "push from the merge guard; run the full command instead")
# `git config` flags that only read or remove (a key with a value after it is otherwise a set).
GIT_CONFIG_READS = {"get", "get-all", "get-regexp", "get-urlmatch", "unset", "unset-all",
                    "l", "list", "name-only", "show-origin", "show-scope"}
GIT_CONFIG_VALUE_FLAGS = frozenset({"-f", "--file", "--blob", "--type", "--default",
                                    "--comment", "--value"})


def _git_config_sets_alias(rest: list[str]) -> bool:
    """`git config [scope] [set|--add|...] alias.<x> <value>`: a set, not a get or list."""
    pos = _positional(rest, GIT_CONFIG_VALUE_FLAGS)
    if pos[:1] == ["set"]:  # git 2.46+: `git config set <key> <value>`
        pos = pos[1:]
    elif pos[:1] and pos[0] in ("get", "unset", "list", "edit", "rename-section", "remove-section"):
        return False
    if _flags(rest) & GIT_CONFIG_READS:
        return False
    return len(pos) >= 2 and pos[0].startswith("alias.")


def git(args: list[str]) -> Verdict:
    i, dirs, git_dir = 0, [], None
    while i < len(args) and args[i].startswith("-"):  # global flags before the subcommand
        value = args[i + 1] if i + 1 < len(args) else ""
        if args[i] == "-C":
            dirs.append(value)
        elif args[i] == "--git-dir" or args[i].startswith("--git-dir="):
            git_dir = args[i].split("=", 1)[1] if "=" in args[i] else value
        elif (args[i] == "-c" and value.lower().startswith("alias.")) or \
                args[i].lower().startswith("--config-env=alias."):
            return _guard(ALIAS_RISK)
        i += 2 if args[i] in GIT_GLOBAL_VALUE_FLAGS else 1
    if args[i:i + 1] == ["config"] and _git_config_sets_alias(args[i + 1:]):
        return _guard(ALIAS_RISK)
    if args[i:i + 1] != ["push"]:
        return NONE
    rest = args[i + 1:]
    refspecs = _positional(rest, GIT_PUSH_VALUE_FLAGS)
    if "repo" not in _flags(rest):  # with --repo every positional may be a refspec
        refspecs = refspecs[1:]
    guard = _push_guard(rest, refspecs, dirs, git_dir)
    if _flags(rest) & {"tags", "follow-tags", "mirror"}:
        return "pushes tags (a release deploy)", None, guard
    if refspecs[:1] == ["tag"] or any(GIT_TAG_REF.fullmatch(side) for spec in refspecs
                                      for side in spec.lstrip("+").split(":") if side):
        return "pushes a tag or release ref (a release deploy)", None, guard
    if any(re.search(r"[$%`]", spec) for spec in refspecs):
        return None, "pushes a ref named by a variable (cannot tell whether it is a tag)", guard
    return _guard(guard)


def _gh_api_writes(args: list[str]) -> bool:
    """`gh api` sends a body with -f/-F/--field/--input (then POST), or a method with -X."""
    for a, nxt in zip(args, args[1:] + [""]):
        if re.fullmatch(r"-[fF].*|--(raw-)?field(=.*)?|--input(=.*)?", a):
            return True
        method = re.fullmatch(r"(?:-X|--method)=?(.*)", a)
        if method and (method.group(1) or nxt).upper() != "GET":
            return True
    return False


# `gh pr merge` flags that take a value (gh 2.x), `-R/--repo` included.
GH_MERGE_VALUE_FLAGS = frozenset({"-b", "--body", "-F", "--body-file", "-t", "--subject",
                                  "-A", "--author-email", "--match-head-commit", "-R", "--repo"})
GH_API_MERGE = re.compile(r"(?:^|/)repos/([^/\s]+)/([^/\s]+)/pulls/([^/\s?]+)/merge/?(?:$|\?)", re.IGNORECASE)
GRAPHQL_MERGE = re.compile(r"mergePullRequest|enablePullRequestAutoMerge", re.IGNORECASE)
AUTO_MERGE = ("uses auto-merge (--auto), which merges later without this guard's check. Wait "
              "for the required check to pass, then merge without --auto")


def _gh_merge(args: list[str]) -> Optional[Guard]:
    """`gh pr merge [<n>|<branch>|<url>] [flags]`: the PR to check, or a deny reason."""
    words, repo, skip = [], None, False
    for k, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a.startswith("-"):
            name, has_value = a.split("=", 1)[0], "=" in a
            if name in ("-R", "--repo"):
                repo = a.split("=", 1)[1] if has_value else (args[k + 1] if k + 1 < len(args) else None)
            skip = not has_value and name in GH_MERGE_VALUE_FLAGS
            continue
        words.append(a)
    flags = _flags(args)
    if "auto" in flags:
        return AUTO_MERGE
    if "disable-auto" in flags:
        return None  # only turns auto-merge off
    pr = words[2] if len(words) > 2 else None  # words: ["pr", "merge", <pr>]
    if pr is not None and re.search(r"[$%`]", pr):
        return "names the PR by a variable (cannot tell which PR); use its number"
    return Merge(pr, repo)


def _gh_api_merge(args: list[str]) -> Optional[Guard]:
    """`gh api` writes to `repos/<o>/<r>/pulls/<n>/merge`, or GraphQL merge mutations."""
    if not _gh_api_writes(args):
        return None
    if GRAPHQL_MERGE.search(" ".join(args)):
        return ("merges or auto-merges a PR through the GraphQL API (cannot check which PR); "
                "use gh pr merge <n>")
    for a in args:
        m = GH_API_MERGE.search(a)
        if m:
            owner, name, number = m.groups()
            if not number.isdigit():
                return "merges a PR named by a variable through the API (cannot check which PR)"
            current = owner.lower() in ("{owner}", ":owner") or name.lower() in ("{repo}", ":repo")
            return Merge(number, None if current else f"{owner}/{name}")
    return None


def gh(args: list[str]) -> Verdict:
    pos = _positional(args, frozenset({"-R", "--repo"}))
    if pos[:2] in (["alias", "set"], ["alias", "import"]) or \
            (pos[:1] in (["extension"], ["extensions"], ["ext"]) and pos[1:2] in (["install"], ["exec"], ["upgrade"])):
        return _guard(ALIAS_RISK)
    if pos[:2] in (["release", "create"], ["release", "edit"], ["workflow", "run"], ["run", "rerun"]):
        return _deploy("creates or edits a release, or runs a workflow (a deploy)")
    if pos[:2] == ["pr", "merge"]:
        return _guard(_gh_merge(args))
    if pos[:1] == ["api"]:
        guard = _gh_api_merge(args)
        text = " ".join(args).lower()
        if "refs/tags" in text or "/dispatches" in text or ("/releases" in text and _gh_api_writes(args)):
            return "calls the GitHub API on tags, releases or dispatches (a deploy)", None, guard
        return _guard(guard)
    return NONE


def docker(args: list[str]) -> Verdict:
    pos = _positional(args, frozenset({"-c", "--context", "-H", "--host", "--config", "-l", "--log-level"}))
    if pos[:1] == ["push"] or pos[:2] == ["image", "push"]:
        return _deploy("pushes an image (a deploy)")
    return NONE


# Infisical CLI, read from its command reference (`infisical <cmd>`, and the same commands
# under `infisical secrets-manager`). Only the words before `--` are its own. A command that
# shows values or a token is denied; one that changes secrets, switches the login or has no
# rule here asks, so a new CLI command fails closed.
INFISICAL_VALUE_FLAGS = frozenset({
    "-e", "--env", "--projectId", "--path", "--token", "--domain", "--profile", "--org", "-t",
    "--tags", "-f", "--format", "-o", "--output", "--output-file", "--type", "-l", "--log-level",
    "--method", "--client-id", "--client-secret", "--watch-interval", "--access-bundle", "--ttl",
    "--proxy", "-c", "--command",
})
INFISICAL_VALUES = "prints secret values from Infisical into the transcript"
INFISICAL_TOKEN = "prints an Infisical token into the transcript"
INFISICAL_CHANGE = ("changes secrets or folders in Infisical (the user does that, so no value "
                    "passes through the session)")
INFISICAL_LOGIN = "changes which Infisical login the session uses"
INFISICAL_OTHER = "is an Infisical command the gate has no rule for (it may show or change secrets)"
INFISICAL_SAFE = {"", "help", "version", "completion", "run", "scan", "init"}


def infisical(args: list[str]) -> Verdict:
    own = args[:args.index("--")] if "--" in args else args
    pos = _positional(own, INFISICAL_VALUE_FLAGS)
    flags = _flags(own)
    if pos[:1] == ["secrets-manager"]:
        pos = pos[1:]
    top, sub, third = (pos + ["", "", ""])[:3]
    if flags & {"profile", "org"}:
        return _ask(INFISICAL_LOGIN)
    if top in INFISICAL_SAFE or flags & {"h", "help"}:
        return NONE  # what `run` runs is read by `_injected`
    if top == "export":
        return _guard(Secret(INFISICAL_VALUES))
    if top == "secrets":
        if sub in ("set", "create", "update"):
            return _guard(Secret(INFISICAL_VALUES)) if "show-values" in flags else _ask(INFISICAL_CHANGE)
        if sub == "delete":
            return _ask(INFISICAL_CHANGE)
        if sub == "folders":
            return NONE if third in ("", "get", "list", "ls") else _ask(INFISICAL_CHANGE)
        return _guard(Secret(INFISICAL_VALUES))  # a listing, `get`, `export`, anything else
    if top == "folders":
        return NONE if sub in ("", "get", "list", "ls") else _ask(INFISICAL_CHANGE)
    if top == "login":
        if "plain" in flags:
            return _guard(Secret(INFISICAL_TOKEN))
        return NONE if sub == "status" else _ask(INFISICAL_LOGIN)
    if [top, sub, third] in (["user", "get", "token"], ["agent-vault", "sessions", "create"]) or top == "bootstrap":
        return _guard(Secret(INFISICAL_TOKEN))
    if [top, sub] == ["dynamic-secrets", "lease"] and third in ("create", "renew"):
        return _guard(Secret("prints a dynamic secret's credentials into the transcript"))
    if top in ("user", "profile", "org", "logout"):
        return _ask(INFISICAL_LOGIN)
    return _ask(INFISICAL_OTHER)


PROGRAMS = {"railway": railway, "git": git, "gh": gh, "docker": docker, "infisical": infisical}
PLATFORM_PROGRAMS = {"railway", "docker"}
# Programs that run another command with secrets in its environment, and the subcommands
# that do it. That command is read as well: `infisical run -- printenv`, `railway ssh env`.
INJECTORS = {"infisical": ({"run"}, INFISICAL_VALUE_FLAGS), "railway": ({"run", "ssh"}, RAILWAY_VALUE_FLAGS)}

# --- commands that print secrets (docs/MODEL.md section 12.3, rule 3) ----------------------
# Kept out of PROGRAMS: these are everyday words (`set`, `head`, `type`), so the backstop
# and the runner shortcuts must not treat a mention of them as a command.

SECRETS_PRINTED = "prints environment variables, which hold secrets, into the transcript"
SECRET_READ = "reads a .env file, which prints its secrets into the transcript"
# `.env`, `.env.local`, `config/.env.prod`; not `.env.example`, `.env.sample`, `.env.template`.
ENV_FILE = re.compile(r"(?:^|[\\/])\.env(?:\.(?!(?:example|sample|template|dist)$)[\w.-]+)?$", re.IGNORECASE)
ENV_DRIVE = re.compile(r"env:", re.IGNORECASE)  # PowerShell `env:`, `env:\`, `env:FOO`
READERS = {"cat", "type", "gc", "get-content", "less", "more", "head", "tail", "bat", "nl", "tac",
           "strings", "od", "xxd", "hexdump", "base64", "sed", "awk", "grep", "egrep", "rg",
           "findstr", "select-string", "sls", "cut", "sort", "uniq", "diff", "column", "jq"}
LISTERS = {"get-childitem", "gci", "ls", "dir", "get-item", "gi", "get-itemproperty", "gp"}


def _printenv(args: list[str]) -> Verdict:
    return _guard(Secret(SECRETS_PRINTED))


def _bare(*allowed: str):
    """`set`, `export`, `declare` with no names print every variable (`-p`/`-x` too)."""
    def classify(args: list[str]) -> Verdict:
        if all(a in allowed for a in args):
            return _guard(Secret(SECRETS_PRINTED))
        return NONE
    return classify


def _reader(args: list[str]) -> Verdict:
    if any(ENV_FILE.search(a) for a in args):
        return _guard(Secret(SECRET_READ))
    if any(ENV_DRIVE.match(a) for a in args):
        return _guard(Secret(SECRETS_PRINTED))
    return NONE


def _lister(args: list[str]) -> Verdict:
    return _guard(Secret(SECRETS_PRINTED)) if any(ENV_DRIVE.match(a) for a in args) else NONE


SECRET_PROGRAMS = {
    "printenv": _printenv, "set": _bare(), "export": _bare("-p"),
    "declare": _bare("-p", "-x", "-px", "-xp"), "typeset": _bare("-p", "-x", "-px", "-xp"),
    **{p: _reader for p in READERS}, **{p: _lister for p in LISTERS},
}
SECRET_API = re.compile(r"GetEnvironmentVariables\s*\(", re.IGNORECASE)
# The whole environment printed by a one-liner: `console.log(process.env)`,
# `print(dict(os.environ))`. One variable (`process.env.PORT`, `os.environ["X"]`) is not it.
SECRET_DUMP = re.compile(r"(?:console\.\w+|print|pprint|JSON\.stringify|json\.dumps)\s*\(\s*(?:dict\s*\(\s*)?"
                         r"(?:process\.env|os\.environ)\s*[),]")

# --- reading a command line ---------------------------------------------------------------

SEPARATORS = "|;&\r\n(){}"
# Bash keywords and prefixes skipped in command position. After `for`, `select` or `case`
# the rest of the segment is a header (`for s in a b`) and runs nothing.
RESERVED = {"if", "then", "elif", "else", "fi", "do", "done", "while", "until", "in", "esac",
            "function", "!", "{", "}", "[[", "]]", "coproc"}
HEADERS = {"for", "select", "case"}
# Launchers that run the program named after them (with the flags that take a value).
WRAPPERS = {
    "sudo": {"-u", "-g", "-h", "-p", "-C"}, "doas": {"-u", "-C"},
    "env": {"-u", "--unset", "-C", "--chdir"}, "command": set(), "exec": {"-a"},
    "nohup": set(), "time": set(), "nice": {"-n"}, "ionice": {"-c", "-n", "-p", "-P", "-u"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"}, "flock": {"-w", "--timeout", "-E"},
    "unbuffer": set(), "stdbuf": {"-i", "-o", "-e"},
    "xargs": {"-I", "-n", "-L", "-P", "-d", "-E", "-s", "-a", "--max-args", "--max-lines",
              "--max-procs", "--delimiter", "--eof", "--max-chars", "--arg-file"},
    "npx": {"-p", "--package"}, "bunx": {"-p", "--package"}, "pnpx": set(),
}
WRAPPER_POSITIONALS = {"timeout": 1, "flock": 1}  # `timeout 5 cmd`, `flock <file> cmd`
# Launcher flags whose value (and the rest of the line) is a string a shell runs.
WRAPPER_STRINGS = {"env": r"(?:-S|--split-string=?)(.*)", "flock": r"(?:-c|--command=?)(.*)"}
RUNNERS = {"pnpm": {"dlx", "exec"}, "yarn": {"dlx", "exec"}, "npm": {"exec", "x"}, "bun": {"x"}}
# Shells that run the word after a flag: (flag, how the string is read). POSIX shells take
# one word; PowerShell and cmd join the rest. cmd is read without escapes, like PowerShell.
POSIX_C, PWSH_C = r"-[a-z]*c[a-z]*|--command", r"-c(o(m(m(a(n(d)?)?)?)?)?)?"
SHELLS = {
    "bash": (POSIX_C, "bash"), "sh": (POSIX_C, "bash"), "zsh": (POSIX_C, "bash"),
    "dash": (POSIX_C, "bash"), "fish": (POSIX_C, "bash"), "su": (POSIX_C, "bash"),
    "script": (POSIX_C, "bash"), "pwsh": (PWSH_C, "powershell"),
    "powershell": (PWSH_C, "powershell"), "cmd": (r"/[ck]", "powershell"),
}
# Shells that also read commands from input (a heredoc, a pipe).
STDIN_SHELLS = {"bash", "sh", "zsh", "dash", "fish", "pwsh", "powershell", "cmd"}
# Programs that run the rest of the line as a string, after flags (those listed take a value).
JOINERS = {
    "eval": ("bash", set()), "watch": ("bash", {"-n", "--interval", "-q", "--equexit"}),
    "iex": ("powershell", set()), "invoke-expression": ("powershell", set()),
}
START_PROCESS = {"start-process", "start", "saps"}
# Directory changes: after one, the session's current branch says nothing (merge guard).
CHDIR_PROGRAMS = {"cd", "pushd", "popd", "chdir", "set-location", "sl", "push-location", "pop-location"}
START_SWITCHES = ("wait", "nonewwindow", "passthru", "usenewenvironment", "loaduserprofile")
HEREDOC = re.compile(r"<<([-~]?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|(\\?)([A-Za-z_][\w.-]*))")
HERE_STRING = re.compile(r"@(['\"])[ \t]*\r?\n")


@dataclass
class Segment:
    words: list[str] = field(default_factory=list)
    bare: list[bool] = field(default_factory=list)  # True: no part of the word was quoted


@dataclass
class Found:
    """What a segment runs. `at` is the command word; with `covered`, every word from `at`
    on has been read as part of it (a string a shell runs, Start-Process arguments)."""
    at: int
    prog: str = ""
    args: list[str] = field(default_factory=list)
    text: Optional[str] = None  # a string a shell runs
    dialect: str = "bash"
    ask: Optional[str] = None  # a form the gate cannot read
    covered: bool = False
    xargs: bool = False  # xargs adds arguments from its input


def _substitutions(text: str, shell: str) -> list[str]:
    """The `$( ... )` (and in Bash backtick) command substitutions inside a string."""
    out, i = [], 0
    while i < len(text):
        if text.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            out.append(text[i + 2:j - 1 if depth == 0 else j])
            i = j
        elif text[i] == "`" and shell == "bash":
            j = text.find("`", i + 1)
            j = len(text) if j < 0 else j
            out.append(text[i + 1:j])
            i = j + 1
        else:
            i += 1
    return out


def _heredoc_bodies(command: str, pos: int, pending: list[tuple[str, bool, bool]],
                    bodies: list[str], nested: list[str]) -> int:
    """Reads the bodies of the heredocs opened on the line that ended at `pos`."""
    for delimiter, strip_tabs, expands in pending:
        lines = []
        while pos < len(command):
            eol = command.find("\n", pos)
            eol = len(command) if eol < 0 else eol
            line = command[pos:eol].rstrip("\r")
            pos = eol + 1
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                break
            lines.append(line)
        bodies.append("\n".join(lines))
        if expands:  # an unquoted delimiter: `$(...)` in the body runs
            nested += _substitutions(bodies[-1], "bash")
    return min(pos, len(command))


def _segments(command: str, shell: str) -> tuple[list[Segment], list[str], list[str]]:
    """(segments, strings that run as commands, heredoc bodies): see the module docstring."""
    esc = "`" if shell == "powershell" else "\\"
    segments: list[Segment] = []
    nested: list[str] = []
    bodies: list[str] = []
    pending: list[tuple[str, bool, bool]] = []  # heredocs whose body starts at the next newline
    seg = Segment()
    word: list[str] = []
    in_word = quoted = False
    i, n = 0, len(command)

    def flush() -> None:
        nonlocal word, in_word, quoted
        if in_word:
            seg.words.append("".join(word))
            seg.bare.append(not quoted)
        word, in_word, quoted = [], False, False

    def cut() -> None:
        nonlocal seg
        flush()
        if seg.words:
            segments.append(seg)
        seg = Segment()

    while i < n:
        c = command[i]
        if c == esc and i + 1 < n:  # escaped character, or a line continuation
            if command[i + 1] not in "\r\n":
                word.append(command[i + 1])
                in_word = True
            i += 2
            continue
        heredoc = HEREDOC.match(command, i) if shell == "bash" and c == "<" else None
        here_string = HERE_STRING.match(command, i) if shell == "powershell" and not in_word else None
        if c == "\n" and pending:
            cut()
            i = _heredoc_bodies(command, i + 1, pending, bodies, nested)
            pending = []
            continue
        if shell == "bash" and command.startswith("<<<", i):  # a here-string, not a heredoc
            word.append("<<<")
            in_word = True
            i += 3
            continue
        if heredoc:
            flush()
            delimiter = heredoc.group(2) or heredoc.group(3) or heredoc.group(5) or ""
            pending.append((delimiter, bool(heredoc.group(1)), bool(heredoc.group(5)) and not heredoc.group(4)))
            i = heredoc.end()
            continue
        if here_string:  # @' ... '@ is one quoted word (its body is not a command)
            close = re.compile(r"(?m)^[ \t]*" + here_string.group(1) + "@").search(command, here_string.end())
            body = command[here_string.end():close.start() if close else n].rstrip("\r\n")
            if here_string.group(1) == '"':
                nested += _substitutions(body, shell)
            word.append(body)
            in_word = quoted = True
            i = close.end() if close else n
            continue
        if c in " \t":
            flush()
        elif c in SEPARATORS or (c == "`" and shell == "bash"):
            cut()
        elif c in "'\"":
            j, text = i + 1, []
            while j < n and command[j] != c:
                if c == '"' and command[j] == esc and j + 1 < n and (
                        shell == "powershell" or command[j + 1] in '"\\$`'):
                    j += 1
                text.append(command[j])
                j += 1
            if c == '"':
                nested += _substitutions(command[i + 1:j], shell)
            word.append("".join(text))
            in_word = quoted = True
            i = j
        else:
            word.append(c)
            in_word = True
        i += 1
    cut()
    return segments, nested, bodies


def _string_flag(prog: str, words: list[str], i: int) -> Optional[str]:
    """`env -S 'cmd'`, `flock f -c 'cmd'`: the string the flag at `i` hands to a shell."""
    m = re.fullmatch(WRAPPER_STRINGS[prog], words[i]) if prog in WRAPPER_STRINGS else None
    return " ".join(([m.group(1)] if m.group(1) else []) + words[i + 1:]) if m else None


def _encoded(word: str) -> bool:
    w = word.lower()
    return w in ("-e", "-ec") or (len(w) >= 3 and "-encodedcommand".startswith(w))


def _shell(prog: str, words: list[str], i: int) -> Found:
    flag, dialect = SHELLS[prog]
    rest = words[i + 1:]
    if prog in ("pwsh", "powershell") and any(_encoded(w) for w in rest):
        return Found(i, ask="runs an encoded PowerShell command (cannot read it)", covered=True)
    for j, w in enumerate(rest):
        if w.startswith("<<<"):  # `bash <<< 'cmd'`
            return Found(i, text=w[3:] or " ".join(rest[j + 1:j + 2]), dialect=dialect, covered=True)
        if re.fullmatch(flag, w, re.IGNORECASE) and j + 1 < len(rest):
            text = rest[j + 1] if dialect == "bash" else " ".join(rest[j + 1:])
            return Found(i, text=text, dialect=dialect, covered=True)
    return Found(i, prog=prog, args=rest)  # a script, or commands from input


def _start_process(args: list[str]) -> list[str]:
    """`Start-Process railway -ArgumentList up,-s,web` -> ["railway", "up", "-s", "web"]."""
    prog, arg_list, positional, i = None, None, [], 0
    while i < len(args):
        name = args[i].lower().lstrip("-") if args[i].startswith("-") else ""
        if name and ("filepath".startswith(name) or name in ("pspath", "path")):
            prog, i = (args[i + 1] if i + 1 < len(args) else None), i + 2
        elif name and ("argumentlist".startswith(name) or name == "args"):
            arg_list, i = [], i + 1
            while i < len(args):  # `-ArgumentList up, -s, web`: a list may span words
                arg_list.append(args[i])
                i += 1
                if not arg_list[-1].endswith(","):
                    break
        elif name:
            i += 1 if any(s.startswith(name) for s in START_SWITCHES) else 2
        else:
            positional.append(args[i])
            i += 1
    if prog is None and positional:
        prog = positional.pop(0)
    rest = arg_list if arg_list is not None else positional
    return [prog] + [w for a in rest for w in re.split(r"[,\s]+", a) if w] if prog else []


def _command(words: list[str]) -> Optional[Found]:
    """What a segment runs, or None when it runs nothing the gate can name."""
    i, via_xargs = 0, False
    at = lambda k: words[k] if k < len(words) else ""  # noqa: E731
    while i < len(words):
        word, prog = words[i], _program(words[i])
        if word.lower() in HEADERS:
            return None
        if word.lower() in RESERVED or re.fullmatch(r"[A-Za-z_]\w*=.*", word):  # or VAR=value
            i += 1
        elif prog in WRAPPERS:
            via_xargs = via_xargs or prog == "xargs"
            i += 1
            while i < len(words) and re.fullmatch(r"-.+|[A-Za-z_]\w*=.*", words[i]):
                text = _string_flag(prog, words, i)
                if text is not None:
                    return Found(i, text=text, covered=True)
                i += 2 if words[i] in WRAPPERS[prog] else 1
            i += WRAPPER_POSITIONALS.get(prog, 0)
            if prog == "env" and i >= len(words):  # a bare `env` lists the environment
                return Found(i - 1, prog="printenv")
            text = _string_flag(prog, words, i) if i < len(words) else None
            if text is not None:
                return Found(i, text=text, covered=True)
        elif prog in RUNNERS and at(i + 1).lower() in RUNNERS[prog]:
            i += 2
            while i < len(words) and words[i].startswith("-"):
                i += 1
        elif prog in ("pnpm", "yarn") and _program(at(i + 1)) in PROGRAMS:
            i += 1  # `pnpm railway up` runs the railway binary
        elif prog in RUNNERS and at(i + 1).lower() == "run" and _program(at(i + 2)) in PROGRAMS:
            i += 2  # `npm run railway`: a script named like a program is treated as it
        elif prog in SHELLS:
            return _shell(prog, words, i)
        elif prog in JOINERS:
            dialect, value_flags = JOINERS[prog]
            j = i + 1
            while j < len(words) and words[j].startswith("-"):
                j += 2 if words[j] in value_flags else 1
            return Found(i, text=" ".join(words[j:]), dialect=dialect, covered=True)
        elif prog in START_PROCESS:
            inner_words = _start_process(words[i + 1:])
            inner = _command(inner_words) if inner_words else None
            if inner:
                inner.at, inner.covered = i, True
            return inner
        else:
            return Found(i, prog=prog, args=words[i + 1:], xargs=via_xargs)
    return None


# Built-in subcommands: anything else may be an alias or extension that hides a merge or push.
# git: `git help -a` (2.53, Windows; guides left out: an alias cannot shadow a built-in).
GIT_BUILTINS = frozenset("""
add am archive backfill bisect branch bundle checkout cherry-pick citool clean clone commit
describe diff fetch format-patch gc gitk grep gui init log maintenance merge mv notes pull push
range-diff rebase reset restore revert rm scalar shortlog show sparse-checkout stash status
submodule survey switch tag worktree config fast-export fast-import filter-branch mergetool
pack-refs prune reflog refs remote repack replace annotate blame bugreport count-objects diagnose
difftool fsck gitweb help instaweb merge-tree rerere show-branch verify-commit verify-tag version
whatchanged archimport cvsexportcommit cvsimport cvsserver imap-send p4 quiltimport request-pull
send-email svn apply checkout-index commit-graph commit-tree hash-object index-pack merge-file
merge-index mktag mktree multi-pack-index pack-objects prune-packed read-tree replay symbolic-ref
unpack-objects update-index update-ref write-tree cat-file cherry diff-files diff-index diff-pairs
diff-tree for-each-ref for-each-repo get-tar-commit-id last-modified ls-files ls-remote ls-tree
merge-base name-rev pack-redundant repo rev-list rev-parse show-index show-ref unpack-file var
verify-pack daemon fetch-pack http-backend send-pack update-server-info check-attr check-ignore
check-mailmap check-ref-format column credential credential-cache credential-store fmt-merge-msg
hook interpret-trailers mailinfo mailsplit merge-one-file patch-id sh-i18n sh-setup stripspace
askpass askyesno credential-helper-selector credential-manager lfs update-git-for-windows
stage init-db upload-pack receive-pack upload-archive
""".split())
# gh 2.89 top-level commands, their built-in short forms and help topics (`gh help`).
GH_BUILTINS = frozenset("""
auth browse codespace cs gist issue org pr project release repo cache run workflow agent-task
agent-tasks agent alias api attestation at completion config copilot extension extensions ext
gpg-key label licenses preview ruleset rs search secret ssh-key status variable help version
accessibility a11y actions environment exit-codes formatting mintty reference
""".split())
UNKNOWN_SUB = "runs `{prog} {sub}`, not a built-in {prog} command: it may be an alias or extension hiding a merge or push"


def _unknown_sub(prog: str, args: list[str]) -> Verdict:
    """Asks for a git/gh subcommand that is not a built-in (in command position only)."""
    if prog == "git":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in GIT_GLOBAL_VALUE_FLAGS else 1
        sub, known = (args[i] if i < len(args) else None), GIT_BUILTINS
    elif prog == "gh":
        pos = _positional(args, frozenset({"-R", "--repo"}))
        sub, known = (pos[0] if pos else None), GH_BUILTINS
    else:
        return NONE
    if sub is None or sub in known:  # exact: `git PUSH` may still run git-push.exe on Windows
        return NONE
    return _ask(UNKNOWN_SUB.format(prog=prog, sub=sub))


def _run(found: Found) -> Verdict:
    if found.prog in SECRET_PROGRAMS:  # judged on its own words; xargs input is not read
        return SECRET_PROGRAMS[found.prog](found.args)
    verdict = PROGRAMS[found.prog](found.args)
    if verdict == NONE:
        verdict = _unknown_sub(found.prog, found.args)
    if not found.xargs:
        return verdict
    deploy, ask, guard = verdict
    if isinstance(guard, Merge):
        guard = f"runs {found.prog} pr merge through xargs (the PR comes from input; cannot check it)"
    elif isinstance(guard, Push):
        guard = None  # the refspecs come from input: the xargs ask below covers it
    if deploy or ask or guard:
        return deploy, ask, guard
    if not _positional(found.args):
        return _deploy(f"runs {found.prog} through xargs with its command from input (treated as a deploy)")
    return _ask(f"runs {found.prog} through xargs with arguments from input")


def _injected(found: Found) -> Optional[str]:
    """The command an injector runs (`infisical run -- <cmd>`, `railway ssh <cmd>`), as text
    for the Bash reader; None when the call runs none."""
    subs, value_flags = INJECTORS[found.prog]
    args, i, seen = found.args, 0, False
    while i < len(args):
        word = args[i]
        if word == "--":
            return shlex.join(args[i + 1:]) or None if seen else None
        if word.startswith("-"):
            m = re.fullmatch(r"(?:-c|--command)(?:=(.*))?", word) if seen and found.prog == "infisical" else None
            if m:  # `infisical run --command "a && b"`: a string a shell runs
                return m.group(1) if m.group(1) is not None else " ".join(args[i + 1:i + 2]) or None
            i += 2 if "=" not in word and word in value_flags else 1
        elif not seen:
            if word.lower() not in subs | {"secrets-manager"}:
                return None
            seen, i = word.lower() in subs, i + 1
        else:
            return shlex.join(args[i:])
    return None


def _backstop(seg: Segment, found: Optional[Found]) -> list[Verdict]:
    """An unquoted program word outside command position (`mywrap railway up`) asks. One
    followed by a path (`grep railway docs/RUNBOOK.md`) is a search term, not a command."""
    for j, (word, bare) in enumerate(zip(seg.words, seg.bare)):
        prog = _program(word)
        if not bare or prog not in PROGRAMS or (found and (j == found.at or (found.covered and j > found.at))):
            continue
        if j + 1 < len(seg.words) and re.search(r"[/\\.]", seg.words[j + 1]):
            continue
        if PROGRAMS[prog](seg.words[j + 1:]) != NONE:
            why = f"mentions {prog} outside a recognised command position"
            return [_ask(Platform(why) if prog in PLATFORM_PROGRAMS else why)]
    return []


def _programs(command: str, shell: str, depth: int = 0) -> list[Verdict]:
    """Verdicts for every program the command line runs, nested strings included."""
    if depth > 5:
        return []
    segments, nested, bodies = _segments(command, shell)
    verdicts: list[Verdict] = []
    shells: list[str] = []  # dialects of the shells in command position (they may read a heredoc)
    for seg in segments:
        found = _command(seg.words)
        if found and found.ask:
            verdicts.append(_ask(found.ask))
        elif found and found.text is not None:
            verdicts += _programs(found.text, found.dialect, depth + 1)
        elif found and (found.prog in PROGRAMS or found.prog in SECRET_PROGRAMS):
            verdicts.append(_run(found))
            inner = _injected(found) if found.prog in INJECTORS and not found.xargs else None
            if inner:
                found.covered = True  # its words are read as a command, not as mentions
                verdicts += _programs(inner, "bash", depth + 1)
        elif found and found.prog in CHDIR_PROGRAMS:
            verdicts.append(_guard(Chdir()))
        elif found and found.prog in STDIN_SHELLS:
            shells.append(SHELLS[found.prog][1])
            if not bodies and not _positional(found.args):
                verdicts.append(_ask(f"runs {found.prog} reading commands from input (cannot tell what)"))
        verdicts += _backstop(seg, found)
    for body in bodies if shells else []:
        verdicts += _programs(body, shells[0], depth + 1)
    for text in nested:
        verdicts += _programs(text, shell, depth + 1)
    return verdicts


# --- whole-command patterns ---------------------------------------------------------------

RAILWAY_API = re.compile(r"backboard\.railway\.(app|com)", re.IGNORECASE)
HTTP_WRITE = re.compile(
    r"(?i:(?<!\S)(-X|--request|--method|-Me(t(h(o(d)?)?)?)?|-CustomMethod)[=:\s'\"]*(POST|PUT|PATCH|DELETE)\b)"
    r"|(?<!\S)(-d|-F|-T|--data\S*|--json\b|--form\S*|--upload-file\b|--post-data\b|--post-file\b)"  # curl: case-sensitive
    r"|(?i:(?<!\S)(-Bo(d(y)?)?|-InF\w*|-Form)(?![\w-]))"  # PowerShell -Body, -InFile, -Form
)
RAILWAY_HOSTS = re.compile(r"rlwy\.net|railway\.internal", re.IGNORECASE)


# Backstop for merge endpoints the parser does not read as `gh api` (curl, `{owner}` cut at
# its braces, GraphQL): a write to one is denied unless it became a checked Merge.
MERGE_ENDPOINT = re.compile(r"pulls/[^\s/'\"]+/merge(?![\w-])", re.IGNORECASE)
GH_API_FIELD = re.compile(r"(?<!\S)(-[fF]|--(raw-)?field|--input)(?![\w-])")


def _classify(command: str, shell: str) -> tuple[list[str], list[str], list[Guard]]:
    verdicts = _programs(command, shell)
    deploys = [d for d, _, _ in verdicts if d]
    asks = [a for _, a, _ in verdicts if a]
    guards = [g for _, _, g in verdicts if g is not None]
    if RAILWAY_API.search(command) and HTTP_WRITE.search(command):
        if GRAPHQL_DEPLOY.search(command):
            deploys.append("calls a Railway API mutation that deploys")
        else:
            asks.append(Platform("writes to the Railway API"))
    writes = HTTP_WRITE.search(command) or GH_API_FIELD.search(command)
    endpoint = MERGE_ENDPOINT.search(command) or (GRAPHQL_MERGE.search(command) and "graphql" in command.lower())
    if endpoint and writes and not any(isinstance(g, Merge) for g in guards):
        guards.append("calls a PR merge API in a form the guard cannot check; use gh pr merge <n>")
    if RAILWAY_HOSTS.search(command):
        asks.append(Platform("connects to a Railway host directly"))
    if SECRET_API.search(command) or SECRET_DUMP.search(command):
        guards.append(Secret(SECRETS_PRINTED))
    return list(dict.fromkeys(deploys)), list(dict.fromkeys(asks)), list(dict.fromkeys(guards))


def classify(command: str, shell: str = "bash") -> tuple[list[str], list[str]]:
    """(deploy reasons, ask reasons) for a command line. `shell` is "bash" or "powershell"."""
    deploys, asks, _ = _classify(command, shell)
    return deploys, asks


# --- merge guard checks ----------------------------------------------------------------------

CHECK_OK = {"SUCCESS", "SKIPPED", "NEUTRAL"}
WHAT_TO_DO = "Wait for CI to finish, or fix the failure and push; then merge."


def merge_problems(view_json: str) -> list[str]:
    """Why a PR may not merge, from `gh pr view --json number,headRefOid,statusCheckRollup`
    (the checks of its head commit). Empty: every check passed and REQUIRED_CHECK succeeded."""
    if not REQUIRED_CHECK:
        return ["has no required check to wait for (`merge.required_check` is not set in the "
                "profile); merge denied"]
    try:
        data = json.loads(view_json)
        rollup = data["statusCheckRollup"]
        if not isinstance(rollup, list) or not all(isinstance(c, dict) for c in rollup):
            raise TypeError("statusCheckRollup is not a list of checks")
        where = f"PR #{data.get('number', '?')} (head {str(data.get('headRefOid') or '?')[:12]})"
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return [f"cannot read the PR's checks from `gh pr view` ({exc!r}); merge denied"]
    failing, pending, ci_ok, ci_seen = [], [], False, False
    for check in rollup:
        kind = check.get("__typename")
        name = str(check.get("name") or check.get("context") or "(unnamed)")
        if kind == "CheckRun":
            status, outcome = str(check.get("status") or "").upper(), str(check.get("conclusion") or "").upper()
            state = outcome if status == "COMPLETED" else "PENDING"
            label = outcome.lower() if status == "COMPLETED" else (status.lower() or "pending")
        elif kind == "StatusContext":
            state = str(check.get("state") or "").upper()
            state = "PENDING" if state in ("PENDING", "EXPECTED") else state
            label = state.lower() or "no state"
        else:
            state, label = "UNKNOWN", f"unknown check type {kind!r}"
        if name.lower() == REQUIRED_CHECK.lower():
            ci_seen, ci_ok = True, ci_ok or state == "SUCCESS"
        if state == "PENDING":
            pending.append(f"{name} ({label})")
        elif state not in CHECK_OK:
            failing.append(f"{name} ({label or 'no conclusion'})")
    problems = []
    if failing:
        problems.append(f"failing checks: {', '.join(failing)}")
    if pending:
        problems.append(f"checks still running: {', '.join(pending)}")
    if not ci_ok:
        problems.append(f"no successful `{REQUIRED_CHECK}` check"
                        + ("" if ci_seen else f" (no check named {REQUIRED_CHECK} has run on the head commit)"))
    return [f"{where} has {'; '.join(problems)}. {WHAT_TO_DO}"] if problems else []


def _tool(cmd: list[str], cwd: str, deadline: float, limit: int) -> tuple[Optional[int], str, str]:
    """(exit code or None if it did not finish, stdout, what went wrong)."""
    remaining = deadline - time.monotonic()
    if remaining < 1:
        return None, "", "the merge guard ran out of time (too many checks in one command)"
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1",
           "GIT_TERMINAL_PROMPT": "0", "NO_COLOR": "1"}
    timeout = min(limit, remaining)
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return None, "", f"timed out after {timeout:.0f} s"
    except OSError as exc:
        return None, "", f"did not run ({exc})"
    first = (out.stderr.strip() or out.stdout.strip()).splitlines()[:2]
    return out.returncode, out.stdout, f"exited {out.returncode}: {' '.join(first) or '(no output)'}"


def _check_merge(merge: Merge, cwd: str, chdir: bool, deadline: float) -> list[str]:
    if merge.pr is None and chdir:
        return ["merges the current branch's PR after a directory change (cannot tell which PR); "
                "name it: gh pr merge <n>"]
    cmd = GH_CMD + ["pr", "view"] + ([merge.pr] if merge.pr else []) + (
        ["-R", merge.repo] if merge.repo else []) + ["--json", "number,headRefOid,statusCheckRollup"]
    code, out, err = _tool(cmd, cwd, deadline, GH_TIMEOUT_S)
    if code != 0:
        return [f"cannot check the PR's CI, so the merge is denied: gh pr view {err}. Check that "
                "gh is installed, logged in (gh auth status) and online, then retry"]
    return merge_problems(out)


def _check_push(push: Push, cwd: str, chdir: bool, deadline: float) -> list[str]:
    if chdir:
        return ["pushes the current branch after a directory change (cannot tell which branch); "
                "name it: git push origin <branch>"]
    base = GIT_CMD + [w for d in push.dirs for w in ("-C", d)] + (
        ["--git-dir", push.git_dir] if push.git_dir else [])
    code, out, err = _tool(base + ["rev-parse", "--abbrev-ref", "HEAD"], cwd, deadline, GIT_TIMEOUT_S)
    if code != 0:
        return [f"pushes the current branch, which the guard cannot read (git rev-parse {err}); "
                "name it: git push origin <branch>"]
    branch = out.strip()
    if branch.lower() in MAIN_BRANCHES:
        return [f"pushes the current branch `{branch}`, the main branch"]
    # Where a bare push goes (push.default, upstream): fails when there is none, which is fine.
    code, out, err = _tool(base + ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}"],
                           cwd, deadline, GIT_TIMEOUT_S)
    if code is None:
        return [f"pushes the current branch, whose push target the guard cannot read ({err})"]
    if code == 0 and out.strip().split("/", 1)[-1].lower() in MAIN_BRANCHES:
        return [f"pushes `{branch}` to `{out.strip()}`, the main branch"]
    return []


def merge_guard(guards: list[Guard], cwd: str) -> list[str]:
    """Deny reasons for the merge guard verdicts of one command line (empty: allowed)."""
    fixed = [g for g in guards if isinstance(g, str)]
    if fixed:
        return fixed  # denied anyway: no need to call gh or git
    deadline = time.monotonic() + GUARD_BUDGET_S
    chdir = any(isinstance(g, Chdir) for g in guards)
    problems: list[str] = []
    for g in guards:
        if isinstance(g, Merge):
            problems += _check_merge(g, cwd, chdir, deadline)
        elif isinstance(g, Push):
            problems += _check_push(g, cwd, chdir, deadline)
    return problems


# --- the decision ---------------------------------------------------------------------------

MERGE_GUARD = ("MERGE GUARD: a main branch takes no direct pushes, and a merge needs every check on "
               "the PR's head commit green, including the required check. This call ")


def _answer(decision: str, reason: str) -> dict:
    return {"permissionDecision": decision, "permissionDecisionReason": reason}


def _decide(event: dict, loaded: athena_profile.Loaded) -> Optional[dict]:
    if event.get("tool_name") not in ("Bash", "PowerShell"):
        return None
    tool_input = event.get("tool_input") or {}
    command = tool_input.get("command", "")
    what = tool_input.get("description") or "(no description given)"
    if loaded.state == "invalid":
        return _answer("ask", (
            f"OPS GATE: the athena-orchestrator profile is broken ({loaded.problem}), so every shell "
            f"call needs review. Fix .claude/orchestration/project.toml. Claude says: {what}"))
    data = loaded.data if loaded.state == "ok" else {}
    configure(data)
    deploys, asks, guards = _classify(command, "powershell" if event["tool_name"] == "PowerShell" else "bash")
    secrets = [g for g in guards if isinstance(g, Secret)]
    guards = [g for g in guards if not isinstance(g, Secret)]

    if loaded.state == "absent":  # not adopted: built-in rules, every opinion asks
        reasons = deploys + asks + [str(g) for g in secrets] + [
            "merges a PR (no profile, so its checks are not verified)" if isinstance(g, Merge)
            else "pushes without naming a branch (no profile, so the branch is not checked)" if isinstance(g, Push)
            else g for g in guards if not isinstance(g, Chdir)]
        if not reasons:
            return None
        return _answer("ask", (f"OPS GATE (no athena-orchestrator profile in this repo) - this call "
                               f"{'; '.join(dict.fromkeys(reasons))}. Claude says: {what}"))

    if secrets:
        return _answer("deny", (
            "SECRETS: this call " + "; ".join(dict.fromkeys(secrets)) + ". Secrets reach "
            "commands through the secrets manager at runtime, never through the session."))
    unsure = [a for a in asks if not isinstance(a, Platform)]  # the gate could not read the command

    # Deploys and platform commands run without a prompt: the agent's credentials reach
    # development only, and the destroy gate stops the few destructive actions that reach
    # beyond it. The merge guard still applies.
    denials = merge_guard(guards, event.get("cwd") or loaded.root)
    if denials:
        return _answer("deny", MERGE_GUARD + "; ".join(dict.fromkeys(denials)))
    if not unsure:
        return None  # no opinion; normal permission flow applies
    return _answer("ask", f"OPS GATE - this call {'; '.join(unsure)}. Claude says: {what}")


BYPASS = ("This session is in bypass-permissions mode, where a question cannot reach the user, "
          "so it is denied. Leave bypass mode to approve it, or the user runs it by hand.")


def _strict(decision: Optional[dict], event: object) -> Optional[dict]:
    """In bypass-permissions mode Claude Code does not show an ask to the user (trial F5),
    so an ask would let the call through: deny it instead."""
    if decision and decision["permissionDecision"] == "ask" and isinstance(event, dict) \
            and event.get("permission_mode") == "bypassPermissions":
        return _answer("deny", decision["permissionDecisionReason"] + " " + BYPASS)
    return decision


def main() -> None:
    event: object = None
    try:
        event = json.load(sys.stdin)
        start = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or "."
        decision = _decide(event, athena_profile.load(start))
    except Exception as exc:  # a broken gate must not wave commands through
        decision = {"permissionDecision": "ask",
                    "permissionDecisionReason": f"OPS GATE crashed ({exc!r}); review this call by hand."}
    decision = _strict(decision, event)
    if decision:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}}))


if __name__ == "__main__":
    main()
