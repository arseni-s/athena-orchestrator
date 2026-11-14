"""Loads and checks a project's orchestration profile (docs/PROFILE.md in athena-orchestrator).

Used by the gates (imported) and by the orchestrator (`python athena_profile.py check [dir]`).
Standard library only; Python 3.11+ for `tomllib`.

    load(start) -> Loaded: state "absent", "invalid" or "ok", with the checked data
    match_any(patterns, path) -> whether a repo-relative path matches a profile pattern
"""
from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from typing import Any

PROFILE = os.path.join(".claude", "orchestration", "project.toml")
SCHEMA = 1
PHASES = ("development", "observe")
KNOWN = {
    "project": {"name", "summary"},
    "access": {"phase"},
    "repo": {"main", "setup", "gates", "architecture"},
    "plan": {"plan", "process", "specs", "adrs", "log", "read_at_start"},
    "rubric": {"user_visible", "conditions"},
    "deploy": {"test", "prod", "freeze_check"},
    "merge": {"required_check"},
    "panel": {"full"},
    "paths": {"full_panel", "design_review", "ops", "security", "ux"},
    "docs": {"code", "docs", "hint"},
}


@dataclass
class Loaded:
    state: str  # "absent" | "invalid" | "ok"
    root: str  # the repo folder the profile was looked for in
    data: dict[str, Any] = field(default_factory=dict)  # checked, with defaults (state "ok")
    problems: list[str] = field(default_factory=list)  # why it is invalid

    @property
    def problem(self) -> str:
        return "; ".join(self.problems)


def repo_root(start: str) -> str:
    """The nearest folder at or above `start` that holds `.git` (a folder, or a worktree's
    file). No subprocess: the gates run on every tool call. Falls back to `start`."""
    here = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return os.path.abspath(start)
        here = parent


def load(start: str) -> Loaded:
    root = repo_root(start)
    path = os.path.join(root, PROFILE)
    if not os.path.exists(path):
        return Loaded("absent", root)
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return Loaded("invalid", root, problems=[f"{PROFILE} cannot be read: {exc}"])
    data, problems = check(raw)
    return Loaded("invalid", root, problems=problems) if problems else Loaded("ok", root, data)


class _Checker:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.problems: list[str] = []

    def table(self, name: str, required: bool = True) -> dict:
        if name not in self.raw:
            if required:
                self.problems.append(f"`[{name}]` is required")
            return {}
        if not isinstance(self.raw[name], dict):
            self.problems.append(f"`{name}` must be a table")
            return {}
        return self.raw[name]

    def get(self, table: dict, key: str, kind: type, where: str,
            default: Any = ..., nonempty: bool = False) -> Any:
        name = f"{where}.{key}" if where else key
        if key not in table:
            if default is ...:
                self.problems.append(f"`{name}` is required")
                return None
            return default
        value = table[key]
        if kind is list:
            ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
        else:
            ok = isinstance(value, kind) and not isinstance(value, bool)
        if not ok:
            want = {list: "a list of strings", str: "a string", int: "an integer"}[kind]
            self.problems.append(f"`{name}` must be {want}")
            return None
        if nonempty and not value:
            self.problems.append(f"`{name}` must not be empty")
            return None
        return value


def check(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """(data with defaults, problems). Data is complete only when there are no problems."""
    c = _Checker(raw)
    if c.get(raw, "schema", int, "") not in (None, SCHEMA):
        c.problems.append(f"`schema` must be {SCHEMA}")
    # A setting the engine does not know is an error: a typo, or one that no longer exists,
    # must not look as if it were enforced.
    for name, value in raw.items():
        if name == "schema":
            continue
        if name not in KNOWN:
            c.problems.append(f"`{name}` is not a profile setting")
        elif isinstance(value, dict):
            c.problems += [f"`{name}.{k}` is not a profile setting" for k in value if k not in KNOWN[name]]
    project, access, repo = c.table("project"), c.table("access"), c.table("repo")
    plan, rubric, deploy = c.table("plan", False), c.table("rubric"), c.table("deploy")
    merge, panel, paths, docs = c.table("merge"), c.table("panel", False), c.table("paths", False), c.table("docs")
    data: dict[str, Any] = {"schema": SCHEMA}
    data["project"] = {"name": c.get(project, "name", str, "project", nonempty=True),
                       "summary": c.get(project, "summary", str, "project", nonempty=True)}
    data["access"] = {"phase": c.get(access, "phase", str, "access")}
    if data["access"]["phase"] not in (None, *PHASES):
        c.problems.append(f"`access.phase` must be one of: {', '.join(PHASES)}")
    data["repo"] = {
        "main": c.get(repo, "main", str, "repo", nonempty=True),
        "setup": c.get(repo, "setup", list, "repo", []),
        "gates": c.get(repo, "gates", list, "repo", nonempty=True),
        "architecture": c.get(repo, "architecture", list, "repo", []),
    }
    data["plan"] = {
        "plan": c.get(plan, "plan", str, "plan", "docs/IMPLEMENTATION_PLAN.md"),
        "process": c.get(plan, "process", str, "plan", "docs/PROCESS.md"),
        "specs": c.get(plan, "specs", str, "plan", "docs/work"),
        "adrs": c.get(plan, "adrs", str, "plan", "docs/decisions"),
        "log": c.get(plan, "log", str, "plan", "docs/decisions/log"),
        "read_at_start": c.get(plan, "read_at_start", list, "plan", []),
    }
    data["rubric"] = {"user_visible": c.get(rubric, "user_visible", str, "rubric", nonempty=True),
                      "conditions": c.get(rubric, "conditions", list, "rubric", nonempty=True)}
    data["deploy"] = {"test": c.get(deploy, "test", str, "deploy", nonempty=True),
                      "prod": c.get(deploy, "prod", str, "deploy", nonempty=True),
                      "freeze_check": c.get(deploy, "freeze_check", str, "deploy", None)}
    data["merge"] = {"required_check": c.get(merge, "required_check", str, "merge", nonempty=True)}
    data["panel"] = {"full": c.get(panel, "full", list, "panel", [])}
    data["paths"] = {k: c.get(paths, k, list, "paths", [])
                     for k in ("full_panel", "design_review", "ops", "security", "ux")}
    data["docs"] = {"code": c.get(docs, "code", list, "docs", nonempty=True),
                    "docs": c.get(docs, "docs", list, "docs", nonempty=True),
                    "hint": c.get(docs, "hint", str, "docs", "")}
    return data, c.problems


# --- path patterns ----------------------------------------------------------------------

def _pattern(pattern: str) -> re.Pattern[str]:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    if pattern.endswith("/"):
        out.append(".*")
    return re.compile("".join(out))


def matches(pattern: str, path: str) -> bool:
    """A profile path pattern against a repo-relative path (docs/PROFILE.md section 2)."""
    return bool(_pattern(pattern).fullmatch(path.replace("\\", "/")))


def match_any(patterns: list[str], path: str) -> bool:
    return any(matches(p, path) for p in patterns)


# --- command line -----------------------------------------------------------------------

def main(argv: list[str]) -> int:
    """`athena_profile.py check [dir]`: exit 0 valid, 1 invalid, 2 absent; prints the result."""
    if len(argv) < 1 or argv[0] != "check":
        print("usage: athena_profile.py check [dir]", file=sys.stderr)
        return 64
    loaded = load(argv[1] if len(argv) > 1 else os.getcwd())
    if loaded.state == "absent":
        print(f"no profile: {os.path.join(loaded.root, PROFILE)} does not exist")
        return 2
    if loaded.state == "invalid":
        print(f"invalid profile ({os.path.join(loaded.root, PROFILE)}):")
        for p in loaded.problems:
            print(f"  - {p}")
        return 1
    d = loaded.data
    print(f"profile ok: {d['project']['name']} (phase: {d['access']['phase']}, main branch: {d['repo']['main']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
