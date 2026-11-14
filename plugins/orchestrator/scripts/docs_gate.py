"""Docs gate (athena-orchestrator): code and docs change together.

Two hook events, one rule: a change to code needs a change to docs. What counts as code and
as docs comes from `[docs]` in the project profile (docs/PROFILE.md).

    Stop        Code files differ from HEAD but no doc file does: Claude is sent back once
                to update the docs (the profile's hint says where), or to say why the change
                needs none. A second stop in the same turn passes.
    PreToolUse  A `git commit` whose files include code but no docs is denied, unless the
                command carries `[no-docs]` (a pure refactor or test-only change), so the
                exception is visible in the history.

No profile: the gate is off (the project has not adopted the plugin). A profile that cannot
be read: commits are denied and a stop is sent back once, with
the reason.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import athena_profile  # noqa: E402

OPT_OUT = "[no-docs]"
_PATH = r"""(?:"[^"]*"|'[^']*'|[^\s;&|]+)"""
_CVAL = r"""(?:[^\s;&|"']*(?:"[^"]*"|'[^']*')|[^\s;&|]+)"""  # k=v, "k=A B", k="A B"
# `git [global options] commit`: -C <path>, -c k=v, --flag, --flag=value; not `commit-tree`.
COMMIT = re.compile(r"\bgit(?:\.exe)?((?:\s+(?:-C\s+" + _PATH + r"|-c\s+" + _CVAL
                    + r"|--[\w-]+(?:=\S+)?))*)\s+commit(?![-\w])")
DASH_C = re.compile(r"-C\s+(" + _PATH + r")")
# A `cd` / `Set-Location` / `Push-Location` at the start of a command segment.
CD = re.compile(r"(?:^|[;&|\n])\s*(?:cd|pushd|Set-Location|Push-Location|sl)"
                r"(?:\s+-(?:Literal)?Path)?\s+(" + _PATH + r")", re.IGNORECASE)


def _git(root: str, *args: str) -> list[str]:
    out = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=10)
    return [line for line in out.stdout.splitlines() if line.strip()]


def _working_tree(root: str) -> set[str]:
    paths = set()
    for line in _git(root, "status", "--porcelain", "-uall"):
        path = line[3:].split(" -> ")[-1].strip('"')
        paths.add(path)
    return paths


def split(paths: set[str], code: list[str], docs: list[str]) -> tuple[list[str], bool]:
    """Code paths (sorted) and whether any doc changed. A path matching both is docs."""
    is_doc = lambda p: athena_profile.match_any(docs, p)  # noqa: E731
    found = sorted(p for p in paths if athena_profile.match_any(code, p) and not is_doc(p))
    return found, any(is_doc(p) for p in paths)


def is_commit(command: str) -> bool:
    return bool(COMMIT.search(command))


def _resolve(base: str, path: str) -> str:
    path = path.strip("\"'")
    path = re.sub(r"^/([a-zA-Z])(?=/|$)", r"\1:", path)  # Git Bash /c/... -> c:...
    return os.path.normpath(os.path.join(base, os.path.expanduser(path)))


def _toplevel(path: str) -> str:
    top = _git(path, "rev-parse", "--show-toplevel")
    return top[0] if top else path


def _root_at(command: str, m: re.Match[str], base: str) -> str:
    """The folder the commit matched by `m` runs in: every `cd` before it, then its own -C."""
    root = base
    for path in CD.findall(command[:m.start()]):
        root = _resolve(root, path)  # each cd is relative to the one before
    for path in DASH_C.findall(m.group(1)):
        root = _resolve(root, path)  # several -C options are cumulative, as in git
    return root


def commit_root(command: str, base: str) -> str:
    """The repo the first commit runs in: its `-C <path>`, after every `cd` before it, else base."""
    m = COMMIT.search(command)
    return _root_at(command, m, base) if m else base


def _rules(root: str) -> tuple[str, object]:
    """("off", None) without a profile; ("broken", reason); or ("on", the profile's docs table)."""
    loaded = athena_profile.load(root)
    if loaded.state == "absent":
        return "off", None
    if loaded.state == "invalid":
        return "broken", f"the athena-orchestrator profile is broken ({loaded.problem})"
    return "on", loaded.data["docs"]


def _on_stop(root: str, event: dict) -> None:
    if event.get("stop_hook_active"):
        return  # already sent back once this turn; Claude has answered
    mode, rules = _rules(root)
    if mode == "off":
        return
    if mode == "broken":
        print(json.dumps({"decision": "block", "reason": (
            f"DOCS GATE: {rules}, so it cannot check this change. Fix "
            ".claude/orchestration/project.toml, or tell the user it is broken.")}))
        return
    code, docs = split(_working_tree(root), rules["code"], rules["docs"])
    if code and not docs:
        hint = f" {rules['hint']}" if rules["hint"] else ""
        print(json.dumps({"decision": "block", "reason": (
            "DOCS GATE: code changed without any documentation change: "
            + ", ".join(code[:10]) + (" ..." if len(code) > 10 else "") + "."
            + hint + " Keep it lean. If the change truly alters no documented behaviour, "
            "say so in one line and stop.")}))


def _on_commit(base: str, command: str) -> None:
    if OPT_OUT in command:
        return
    wide = re.search(r"\bgit\s+add\b|\bcommit\b[^|;&]*\s(?:-[a-zA-Z]*a|--all\b)", command)
    for m in COMMIT.finditer(command):  # every commit in the command, each in its own repo
        root = _toplevel(_root_at(command, m, base))
        mode, rules = _rules(root)
        if mode == "off":
            continue
        if mode == "broken":
            _deny(f"DOCS GATE: {rules}, so commits are denied until it is fixed "
                  "(.claude/orchestration/project.toml).")
            return
        files = set(_git(root, "diff", "--cached", "--name-only"))
        if wide:
            files |= _working_tree(root)  # `git add ... && git commit`, `commit -a` / `--all`
        code, docs = split(files, rules["code"], rules["docs"])
        if code and not docs:
            hint = f" {rules['hint']}" if rules["hint"] else ""
            _deny("DOCS GATE: this commit changes code (" + ", ".join(code[:10]) + ") but no "
                  "documentation." + hint + f" Include the docs in the commit, or put {OPT_OUT} "
                  "in the commit message if no documented behaviour changed.")
            return


def _deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))


def main() -> None:
    event = json.load(sys.stdin)
    # The session's directory first: in worktree mode it is not CLAUDE_PROJECT_DIR.
    base = event.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or "."
    try:
        if event.get("hook_event_name") == "Stop":
            _on_stop(base, event)  # only the session's own tree, never another package's worktree
        elif event.get("tool_name") in ("Bash", "PowerShell"):
            command = (event.get("tool_input") or {}).get("command", "")
            _on_commit(base, command)
    except Exception as exc:  # a broken gate must not wave a commit through
        if event.get("hook_event_name") == "Stop":
            if not event.get("stop_hook_active"):
                print(json.dumps({"decision": "block",
                                  "reason": f"DOCS GATE crashed ({exc!r}); check the docs by hand."}))
        elif is_commit((event.get("tool_input") or {}).get("command", "")):
            _deny(f"DOCS GATE crashed ({exc!r}); commit denied. Check the docs by hand, then retry.")


if __name__ == "__main__":
    main()
