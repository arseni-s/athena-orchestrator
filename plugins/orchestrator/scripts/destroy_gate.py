"""PreToolUse hook: destruction that reaches beyond development is a hard no
(athena-orchestrator, docs/MODEL.md 12.2, layer 5).

Needs no profile. Python 3 standard library only: no subprocess, no network.

The agent's credentials reach development only, so destroying things there is allowed: SQL
of any kind, and deleting Railway services, volumes, variables, domains and deployments.
This gate denies what can reach production or what every environment shares:

    deny   Deleting or transferring a Railway project, or deleting an environment (or a
           workspace or team), by CLI, GraphQL or HTTP DELETE; GitHub repository delete,
           archive, rename, transfer or visibility change, and release, secret and variable
           deletes; Infisical secret and folder deletes (a sync carries the delete to every
           environment); a force push or delete of a main branch; a force push that does not
           name its branch; the same actions through an MCP tool; a file write that holds a
           Railway project or environment delete mutation; a script written or run that
           holds any of these (`sh x`, `bash x`, `source x`, `./x`, `pwsh -File x`; written:
           shell and PowerShell scripts, batch files, YAML, Makefile, justfile, Procfile,
           package.json, and any file starting with `#!`). Denied even with approval: the
           user runs it in their own terminal.
    ask    Edits of the project profile (`.claude/orchestration/project.toml`) or of
           `.claude/settings*.json`, so a session cannot quietly switch a gate off. In
           bypass-permissions mode an ask cannot reach the user, so it is denied instead.

It is a text scan, not a shell parser, and independent of the other gates on purpose. The
text is normalised (lower case; `"`, `'`, backtick and `^` deleted; `,` read as a space),
then cut into segments at `;`, `&`, `|`, newlines and brackets, ignoring quotes. Segment
rules look inside one segment; SQL, GraphQL and HTTP rules look at the whole command.
It over-matches on purpose and fails closed: bad input, a crash or a referenced file that
cannot be read (or is over 1 MB) denies.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Optional

MAX_FILE_BYTES = 1_000_000
SHELL_TOOLS = {"Bash", "PowerShell"}
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

DENY_TAIL = ("Destructive operations never run from Claude, even with approval: the user runs "
             "this in their own terminal.")
ASK_TAIL = "This can switch off a gate: check it by hand."
ERROR_TAIL = "The gate fails closed: the user runs this in their own terminal."
BYPASS_TAIL = ("This session is in bypass-permissions mode, where a question cannot reach the "
               "user, so it is denied. Leave bypass mode to approve it, or the user does it by hand.")

Verdict = Optional[tuple[str, str]]  # (decision, reason)


class GateError(Exception):
    """Something the gate cannot check: it denies."""


# --- text helpers ----------------------------------------------------------------------

def strip(text: str) -> str:
    """Quotes, backticks and `^` deleted, `,` read as a space; case kept (for paths)."""
    return re.sub(r"[\"'`^]", "", text).replace(",", " ")


def segments(norm: str) -> list[str]:
    return [s.strip() for s in re.split(r"[;&|\n\r(){}]", norm) if s.strip()]


def word(*words: str) -> str:
    """A whole word: not glued to a letter, digit, `_` or `-`."""
    return r"(?<![\w-])(?:" + "|".join(words) + r")(?![\w-])"


def program(name: str) -> re.Pattern[str]:
    """A program word, also as a path or `name.exe`; `railway.json` is not one."""
    return re.compile(r"(?<![\w-])" + name + r"(?:\.exe|\.cmd|\.ps1|\.bat)?(?![\w.-])")


def after(seg: str, prog: re.Pattern[str], what: re.Pattern[str]) -> bool:
    """`what` comes after `prog` in the segment."""
    m = prog.search(seg)
    return bool(m and what.search(seg, m.end()))


def strings(value: object) -> list[str]:
    """Every string inside a JSON value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def read_file(path: str, cwd: str) -> str:
    full = os.path.expanduser(path)
    if not os.path.isabs(full):
        full = os.path.join(cwd, full)
    try:
        if os.path.getsize(full) > MAX_FILE_BYTES:
            raise GateError(f"{path} is over 1 MB, so it cannot be checked")
        with open(full, "rb") as f:
            data = f.read(MAX_FILE_BYTES + 1)
    except OSError as e:
        raise GateError(f"cannot read {path} ({type(e).__name__}), so it cannot be checked")
    if len(data) > MAX_FILE_BYTES:
        raise GateError(f"{path} is over 1 MB, so it cannot be checked")
    return data.decode("utf-8", errors="replace").lower()


PATH = r"([^\s;&|(){}<>]+)"
BODY_FILES = [
    re.compile(r"(?:(?<!\S)|(?<==)|(?<=-d))@(?!railway/cli)" + PATH, re.IGNORECASE),
    re.compile(r"(?<![\w-])--input(?:\s*=\s*|\s+)" + PATH, re.IGNORECASE),
    re.compile(r"(?<![\w-])-infile(?:\s*:\s*|\s+)" + PATH, re.IGNORECASE),
]


def files(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    found = [m.group(1) for p in patterns for m in p.finditer(text)]
    # `where n < 5` and `curl -f https://...` name no file
    return [f for f in found if not re.fullmatch(r"[\d.]+|\w+://.*", f)]


# --- patterns --------------------------------------------------------------------------

RAILWAY = program(r"railway")
GIT = program(r"git")
GH = program(r"gh")
INFISICAL = program(r"infisical")

# Railway: what the agent's development-scoped token reaches is allowed; a project,
# environment, workspace or team holds production too, so deleting one is denied.
RAILWAY_DELETE_WORDS = {"delete", "remove", "rm", "destroy", "purge"}
RAILWAY_SCOPES = {"project", "projects", "environment", "environments", "env", "workspace", "team"}
API_WORD = re.compile(word("api"))
# GraphQL names such as projectDelete, environmentDelete, projectTransfer.
SHARED_DESTROY = re.compile(r"(?:project|environment|workspace|team)\w*(?:delete|remove|destroy|purge|transfer)"
                            r"|\w*transfer\w*", re.IGNORECASE)
HTTP_DELETE = re.compile(
    r"(?:(?<![\w-])-x\s*|(?<![\w-])--request(?:\s*=\s*|\s+)|(?<![\w-])--method(?:\s*=\s*|\s+)"
    r"|(?<![\w-])-me\w*(?:\s*:\s*|\s+))delete(?![\w-])")
HTTP_DELETE_HOSTS = re.compile(r"backboard\.railway|api\.github\.com")

# MCP: GitHub and Infisical are shared by every environment, so any destructive tool is
# denied; on Railway only the tools that act on a project, environment, workspace or team.
MCP_SHARED = ("github", "infisical")
MCP_DESTROY = ("delete", "remove", "destroy", "drop", "truncate", "purge", "restore", "transfer")

GIT_PUSH = re.compile(word("push"))
GIT_MAIN = re.compile(r"(?<![\w.-])(?:master|main)(?![\w/.-])")
GIT_VALUE_OPTS = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}

GH_REPO = re.compile(word("repo"))
GH_REPO_DESTROY = re.compile(word("delete", "archive", "rename", "transfer"))
GH_REPO_EDIT = re.compile(word("edit"))
GH_VISIBILITY = re.compile(r"(?<![\w-])--visibility(?![\w-])")
GH_STORE = re.compile(word("release", "secret", "variable"))
GH_STORE_DELETE = re.compile(r"(?<![\w-])(?:delete[\w-]*|remove)(?![\w-])")
GH_GRAPHQL = re.compile(word("graphql"))

WRITE_NAMES = re.compile(r"(?:project|environment|workspace|team)(?:delete|transfer)"
                         r"|project\w*transfer", re.IGNORECASE)
MAX_SCRIPT_DEPTH = 3
WRAPPERS = {"sudo", "exec", "nohup", "time", "env", "command", "builtin", "call"}
SH_FAMILY = {"sh", "bash", "zsh", "dash", "ksh"}
SCRIPT_RUN_EXT = re.compile(r"\.(?:sh|bash|zsh|ksh|ps1)$")
# Files whose text a shell runs. Their content gets the shell rules when written; other
# code (an app that builds SQL, a test of a gate) does not, so it is not over-matched.
SCRIPT_FILE = re.compile(
    r"\.(?:sh|bash|zsh|ksh|ps1|psm1|cmd|bat|ya?ml)$|(?:^|/)(?:makefile|justfile|procfile|package\.json)$")
PROTECTED = (".claude/orchestration/project.toml", ".claude/settings.json", ".claude/settings.local.json")
GATE_MENTION = re.compile(r"\.claude[\\/]+(?:settings|orchestration[\\/]+project\.toml)")
SHELL_WRITE = re.compile(
    r">>?\s*(?!(?:/dev/null|\$null|nul)(?![\w/.]))[^\s>]"
    r"|" + word("set-content", "out-file", "add-content", "rm", "remove-item", "mv", "move-item",
                "cp", "copy-item", "checkout", "restore", "tee", "tee-object", "del", "erase",
                "ri", "rmdir", "ren", "rename-item", "mi", "move", "copy", "cpi", "clear-content",
                "clc", "new-item", "ni", "unlink", "truncate", "sc", "ac")
    + r"|" + word("sed") + r".*" + word(r"-i\w*", "--in-place"))


# --- rules: each returns (rule, what) or None -------------------------------------------

def script_path(seg: str) -> Optional[tuple[str, bool]]:
    """The script a segment runs, and whether it must be readable (an interpreter was named).

    `sh x`, `bash -e x`, `source x`, `. x`, `pwsh -File x`, `./x`, `x.sh`. A `-c` or
    `-Command` string is not a file: its text is already in the command."""
    tokens = seg.split()
    while tokens and (tokens[0].lower() in WRAPPERS or re.fullmatch(r"\w+=\S*", tokens[0])):
        tokens = tokens[1:]
    if not tokens:
        return None
    name = re.sub(r"\.exe$", "", re.split(r"[\\/]", tokens[0])[-1].lower())
    rest = tokens[1:]
    if name in SH_FAMILY:
        while rest and rest[0].startswith("-"):
            if re.fullmatch(r"-[a-z]*c[a-z]*", rest[0].lower()):
                return None
            rest = rest[1:]
        if rest and rest[0] == "<":
            rest = rest[1:]
        return (rest[0], True) if rest else None
    if name in ("source", "."):
        return (rest[0], True) if rest else None
    if name in ("pwsh", "powershell"):
        for i, tok in enumerate(rest):
            low = tok.lower()
            if re.fullmatch(r"-(?:c|co|com|comm|comma|comman|command|encodedcommand|e|ec)", low):
                return None
            if re.fullmatch(r"-f(?:i|il|ile)?", low) and i + 1 < len(rest):
                return rest[i + 1], True
            if not low.startswith("-") and SCRIPT_RUN_EXT.search(low):
                return tok, True
        return None
    first = tokens[0]
    if re.match(r"\.{1,2}[\\/]", first) or SCRIPT_RUN_EXT.search(first.lower()):
        return first, False
    return None


def script_text(path: str, cwd: str, strict: bool) -> Optional[str]:
    """The script's text. A file run directly (`./x`) may be a program: missing, too big or
    binary, it is skipped. Named to an interpreter, it must be readable, or the gate denies."""
    try:
        text = read_file(path, cwd)
    except GateError:
        if strict:
            raise
        return None
    if "\x00" in text:
        if strict:
            raise GateError(f"{path} is not a text file, so it cannot be checked")
        return None
    return text


def shell_denies(command: str, cwd: Optional[str], depth: int = 0) -> Optional[tuple[str, str]]:
    """The first deny rule a command (or a script's text) breaks. `cwd` None: the text is a
    file being written, so no file it names is read."""
    kept = strip(command)
    norm = kept.lower()
    segs = segments(norm)

    def read(path: str) -> str:
        return read_file(path, cwd) if cwd is not None else ""

    for seg in segs:
        if railway_shared_delete(seg):
            return "railway-delete", ("deletes or transfers a Railway project, or deletes an environment, "
                                      "workspace or team (they hold production too)")

    # HTTP DELETE first: `-X DELETE` to backboard is not a GraphQL name (railway-api).
    if HTTP_DELETE.search(norm) and HTTP_DELETE_HOSTS.search(norm):
        return "http-delete", "sends an HTTP DELETE to the Railway or GitHub API"

    if "backboard.railway" in norm or any(after(s, RAILWAY, API_WORD) for s in segs):
        bodies = [norm] + [read(f) for f in files(kept, BODY_FILES)]
        if any(SHARED_DESTROY.search(b) for b in bodies):
            return "railway-api", ("calls a Railway GraphQL mutation that deletes or transfers a project, "
                                   "environment, workspace or team")

    for seg in segs:
        found = git_push(seg)
        if found:
            return found

    for seg in segs:
        found = gh_destroy(seg, norm)
        if found:
            return "gh-destroy", found

    if any(infisical_delete(seg) for seg in segs):
        return "infisical-delete", "deletes a secret or folder in Infisical"

    # A script it runs is read and checked too, so writing one first does not get round
    # these rules. Nested scripts are followed to MAX_SCRIPT_DEPTH.
    if cwd is not None and depth < MAX_SCRIPT_DEPTH:
        for seg in segments(kept):
            run = script_path(seg)
            if not run:
                continue
            text = script_text(run[0], cwd, strict=run[1])
            inner = shell_denies(text, cwd, depth + 1) if text is not None else None
            if inner:
                return "script-run", f"runs {run[0]}, which {inner[1]} ({inner[0]})"
    return None


def railway_shared_delete(seg: str) -> bool:
    """`railway delete` (the project), `railway environment delete x`, `railway project
    transfer`: yes. `railway service delete web -e dev`, `railway down`: no, the agent's
    token reaches development only. Scopes count as words, not flag values, so
    `--environment dev` on a service delete is not an environment delete."""
    m = RAILWAY.search(seg)
    if not m:
        return False
    rest = re.sub(r"^/cli(?:@\S*)?", "", seg[m.end():])  # `npx @railway/cli@latest delete`
    words = [t for t in rest.split() if not t.startswith("-")]
    if "transfer" in words:
        return True
    if not any(w in RAILWAY_DELETE_WORDS for w in words):
        return False
    return words[0] in RAILWAY_DELETE_WORDS or any(w in RAILWAY_SCOPES for w in words)


def git_push(seg: str) -> Optional[tuple[str, str]]:
    g = GIT.search(seg)
    p = GIT_PUSH.search(seg, g.end()) if g else None
    if not p:
        return None
    flags, positional, skip = [], [], False
    for tok in seg[p.end():].split():
        if skip:
            skip = False
        elif tok in GIT_VALUE_OPTS or re.fullmatch(r"\d*>>?|<", tok):
            skip = True
        elif re.match(r"\d*>|<", tok):
            continue
        elif tok.startswith("-"):
            flags.append(tok)
        else:
            positional.append(tok)
    refspecs = positional[1:]
    force = any(f in ("--force", "--force-with-lease", "--force-if-includes")
                or f.startswith("--force-with-lease=") or re.fullmatch(r"-[a-z]*f[a-z]*", f)
                for f in flags) or any(r.startswith("+") for r in refspecs)
    delete = any(f == "--delete" or re.fullmatch(r"-[a-z]*d[a-z]*", f) for f in flags) or any(
        r.startswith(":") for r in refspecs)
    if (force or delete) and any(GIT_MAIN.search(t) for t in positional):
        return "git-main", "force-pushes or deletes a main branch"
    if force and all(r.lstrip("+") in ("head", "@") for r in refspecs):
        return "git-force-unnamed", "force-pushes without naming its branch (a force push must name it)"
    return None


def gh_destroy(seg: str, norm: str) -> Optional[str]:
    g = GH.search(seg)
    if not g:
        return None
    rest = seg[g.end():]
    repo = GH_REPO.search(rest)
    if repo and GH_REPO_DESTROY.search(rest, repo.end()):
        return "deletes, archives, renames or transfers a GitHub repository"
    if repo and GH_REPO_EDIT.search(rest, repo.end()) and GH_VISIBILITY.search(rest):
        return "changes a GitHub repository's visibility"
    store = GH_STORE.search(rest)
    if store and GH_STORE_DELETE.search(rest, store.end()):
        return "deletes a GitHub release, secret or variable"
    api = API_WORD.search(rest)
    if api and HTTP_DELETE.search(rest):
        return "sends a DELETE to the GitHub API"
    if api and GH_GRAPHQL.search(rest) and "mutation" in norm and re.search(r"\w*delete\w*", norm):
        return "runs a GitHub GraphQL delete mutation"
    return None


def infisical_delete(seg: str) -> bool:
    """`infisical secrets delete X`, `infisical secrets-manager folders delete x`. Only the
    CLI's own words count: what `infisical run` runs (`... -- psql -c 'delete from t where
    ...'`) is another program's business."""
    for m in INFISICAL.finditer(seg):  # every mention: `infisical run -- infisical secrets delete X`
        own = seg[m.end():].split()
        own = own[:own.index("--")] if "--" in own else own
        pos = [t for t in own if not t.startswith("-") and t != "secrets-manager"]
        if pos[:1] != ["run"] and "delete" in pos:
            return True
    return False


def shell_asks(command: str) -> Optional[tuple[str, str]]:
    for seg in segments(strip(command).lower()):
        if GATE_MENTION.search(seg) and SHELL_WRITE.search(seg):
            return "gate-edit", "changes the project profile or .claude/settings*.json from the shell"
    return None


def norm_path(path: str) -> str:
    return path.replace("\\", "/").lower().rstrip("/")


def edit_verdict(tool: str, ti: dict) -> Verdict:
    path = ti.get("file_path", ti.get("notebook_path", ""))
    if not isinstance(path, str):
        raise GateError(f"{tool} path is not a string")
    p = norm_path(path)
    texts = [v for k in ("content", "new_string", "new_source") if isinstance(v := ti.get(k), str)]
    if tool == "MultiEdit":
        edits = ti.get("edits", [])
        if not isinstance(edits, list):
            raise GateError("MultiEdit edits is not a list")
        texts += strings(edits)
    if not p.endswith(".md"):  # docs may name the mutations they warn about
        for text in texts:
            if WRITE_NAMES.search(text) or (
                    re.search(r"backboard\.railway", text, re.IGNORECASE)
                    and SHARED_DESTROY.search(text)):
                return deny("write-mutation", "writes a Railway project or environment delete mutation into a file")
        if SCRIPT_FILE.search(p) or any(t.startswith("#!") for t in texts):
            for text in texts:
                found = shell_denies(text, None)
                if found:
                    return deny("write-script", f"writes a script that {found[1]} ({found[0]})")
    if any(p.endswith("/" + t) or p == t for t in PROTECTED):
        return ask("gate-edit", "edits the project profile or .claude/settings*.json")
    return None


def mcp_verdict(name: str, ti: object) -> Verdict:
    server, _, tool = name[len("mcp__"):].lower().partition("__")
    destroys = any(w in tool for w in MCP_DESTROY)
    if destroys and any(s in server for s in MCP_SHARED):
        return deny("mcp-delete", f"is a destructive {server} MCP tool (shared by every environment)")
    if "railway" in server and (SHARED_DESTROY.search(tool) or (
            destroys and re.search(r"project|environment|workspace|team", tool))):
        return deny("mcp-delete", f"is a {server} MCP tool that deletes or transfers a project, "
                                  "environment, workspace or team")
    return None


# --- decision ---------------------------------------------------------------------------

def deny(rule: str, what: str) -> Verdict:
    return "deny", f"DESTROY GATE: {rule}: this {what}. {DENY_TAIL}"


def ask(rule: str, what: str) -> Verdict:
    return "ask", f"DESTROY GATE: {rule}: this {what}. {ASK_TAIL}"


def decide(event: object) -> Verdict:
    if not isinstance(event, dict):
        raise GateError("the event is not a JSON object")
    tool = event.get("tool_name")
    if not isinstance(tool, str):
        raise GateError("the event has no tool_name")
    ti = event.get("tool_input")
    if tool.startswith("mcp__"):
        return mcp_verdict(tool, ti)
    if tool not in SHELL_TOOLS | EDIT_TOOLS:
        return None
    if not isinstance(ti, dict):
        raise GateError(f"{tool} tool_input is not an object")
    if tool in SHELL_TOOLS:
        command = ti.get("command")
        if not isinstance(command, str):
            raise GateError(f"{tool} command is not a string")
        cwd = event.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        found = shell_denies(command, cwd)
        if found:
            return deny(*found)
        found = shell_asks(command)
        return ask(*found) if found else None
    return edit_verdict(tool, ti)


def strict(verdict: Verdict, event: object) -> Verdict:
    """In bypass-permissions mode Claude Code does not show an ask to the user (trial F5),
    so an ask would let the call through: deny it instead."""
    if verdict and verdict[0] == "ask" and isinstance(event, dict) \
            and event.get("permission_mode") == "bypassPermissions":
        return "deny", f"{verdict[1]} {BYPASS_TAIL}"
    return verdict


def main() -> int:
    event: object = None
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        try:
            event = json.loads(raw)
        except ValueError:
            raise GateError("stdin is not valid JSON")
        verdict = strict(decide(event), event)
    except GateError as e:
        verdict = ("deny", f"DESTROY GATE: gate error, {e}. {ERROR_TAIL}")
    except BaseException as e:  # noqa: BLE001 - any crash denies
        verdict = ("deny", f"DESTROY GATE: gate error, the gate crashed ({type(e).__name__}). {ERROR_TAIL}")
    if verdict:
        decision, reason = verdict
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
