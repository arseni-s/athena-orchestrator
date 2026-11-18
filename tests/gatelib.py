"""Shared helpers for the gate tests: import the gates, build profiles, fake `gh` and `git`.

The gates are imported and fed command strings. Nothing dangerous is ever executed: `gh`
and `git` are replaced by a fake script, and the freeze check by a stub or a tiny Python.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "orchestrator"
SCRIPTS = PLUGIN / "scripts"
sys.path.insert(0, str(SCRIPTS))
# The plugin folder is what a marketplace copies when it installs the plugin: keep bytecode out.
sys.dont_write_bytecode = True

import athena_lock  # noqa: E402
import athena_profile  # noqa: E402
import destroy_gate  # noqa: E402
import docs_gate  # noqa: E402
import ops_gate  # noqa: E402

PY = sys.executable.replace("\\", "/")

BASE: dict[str, Any] = {
    "schema": 1,
    "project": {"name": "Sample", "summary": "A sample project for gate tests."},
    "rubric": {"user_visible": "a wrong total on a page", "conditions": ["restart"]},
    "deploy": {"test": "the test environment", "prod": "the production environment",
               "freeze_check": "fake-freeze-check"},
    "merge": {"required_check": "ci"},
    "access": {"phase": "development"},
    "repo": {"main": "main", "gates": ["true"]},
    "docs": {"code": ["apps/", "packages/", "db/", "scripts/", ".claude/hooks/",
                      ".claude/settings.json", "package.json", "Dockerfile"],
             "docs": ["docs/**/*.md", "README.md", "CLAUDE.md", "AGENTS.md", "packages/*/README.md"],
             "hint": "Update the matching docs/features/*.md file."},
}


DROP = object()  # raw(deploy={"freeze_check": DROP}) removes that key


def raw(**changes: Any) -> dict[str, Any]:
    """A copy of BASE with top-level tables replaced or merged: raw(deploy={...}).
    None removes a whole table; DROP inside a table removes one key."""
    out = copy.deepcopy(BASE)
    for key, value in changes.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            merged = {**out[key], **value}
            out[key] = {k: v for k, v in merged.items() if v is not DROP}
        else:
            out[key] = value
    return out


def loaded(state: str = "ok", root: str = ".", **changes: Any) -> athena_profile.Loaded:
    if state != "ok":
        return athena_profile.Loaded(state, root, problems=["broken for the test"] if state == "invalid" else [])
    data, problems = athena_profile.check(raw(**changes))
    assert not problems, problems
    return athena_profile.Loaded("ok", root, data)


def toml(value: Any) -> str:
    """Enough TOML for test profiles: tables, arrays of tables, strings, lists, bools, dates."""
    def scalar(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int,)) or hasattr(v, "isoformat"):
            return str(v) if not hasattr(v, "isoformat") else v.isoformat()
        if isinstance(v, list):
            return "[" + ", ".join(scalar(x) for x in v) + "]"
        return json.dumps(v)

    lines: list[str] = []

    def emit(table: dict[str, Any], prefix: str) -> None:
        for k, v in table.items():
            if not isinstance(v, dict) and not (isinstance(v, list) and v and isinstance(v[0], dict)):
                lines.append(f"{k} = {scalar(v)}")
        for k, v in table.items():
            if isinstance(v, dict):
                lines.append(f"\n[{prefix}{k}]")
                emit(v, f"{prefix}{k}.")
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                for item in v:
                    lines.append(f"\n[[{prefix}{k}]]")
                    emit(item, f"{prefix}{k}.")
    emit(value, "")
    return "\n".join(lines) + "\n"


class TempDirs:
    """Temp folders removed at the end of a test class (tearDownClass)."""

    def __init__(self) -> None:
        self.dirs: list[str] = []

    def make(self, prefix: str = "athena-") -> str:
        d = tempfile.mkdtemp(prefix=prefix)
        self.dirs.append(d)
        return d

    def cleanup(self) -> None:
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)


def git(cwd: str, *args: str) -> str:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True,
                          encoding="utf-8").stdout


def make_repo(path: str, profile: Optional[str] = None) -> str:
    """A git repo with one commit (README.md, and the profile text if given)."""
    os.makedirs(path, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@example.org"), ("user.name", "t"), ("core.autocrlf", "false"),
                 ("commit.gpgsign", "false")):
        git(path, "config", k, v)
    write(path, "README.md")
    if profile is not None:
        write(path, ".claude/orchestration/project.toml", profile)
    git(path, "add", "-A")
    git(path, "commit", "-qm", "init")
    return path


def write(root: str, rel: str, text: str = "x\n") -> None:
    p = Path(root, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


FAKE = """import json, sys, time
spec, args = sys.argv[1], sys.argv[2:]
with open(spec + '.log', 'a', encoding='utf-8') as f: f.write(json.dumps(args) + '\\n')
for rule in json.load(open(spec, encoding='utf-8')):
    if rule.get('match') is None or rule['match'] in args:
        time.sleep(rule.get('sleep', 0))
        sys.stdout.write(rule.get('stdout', '')); sys.stderr.write(rule.get('stderr', ''))
        sys.exit(rule.get('exit', 0))
sys.exit(97)
"""


class Fakes:
    """A fake `gh`/`git`: the first rule whose `match` is one of its arguments answers."""

    def __init__(self, work: str) -> None:
        self.work = work
        self.n = 0
        self.script = os.path.join(work, "fake.py")
        Path(self.script).write_text(FAKE, encoding="utf-8")

    def make(self, rules: list[dict[str, Any]]) -> tuple[list[str], "callable"]:
        spec = os.path.join(self.work, f"spec-{self.n}.json")
        self.n += 1
        Path(spec).write_text(json.dumps(rules), encoding="utf-8")

        def calls() -> list[list[str]]:
            log = Path(spec + ".log")
            return [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        return [sys.executable, "-B", self.script, spec], calls

    def command(self, rules: list[dict[str, Any]]) -> tuple[str, "callable"]:
        """The same fake as a command line, for `deploy.freeze_check` (forward slashes)."""
        cmd, calls = self.make(rules)
        return " ".join(f"'{a.replace(chr(92), '/')}'" for a in cmd), calls


def bash(command: str, **extra: Any) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command, **extra}}


def powershell(command: str) -> dict[str, Any]:
    return {"tool_name": "PowerShell", "tool_input": {"command": command}}


def git_bash() -> Optional[str]:
    """Git Bash on Windows (what Claude Code runs hook commands with), else `bash`."""
    if os.name != "nt":
        return shutil.which("bash")
    candidates = [os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")]
    try:
        exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True).stdout.strip()
        candidates.append(str(Path(exec_path).parents[2] / "bin" / "bash.exe"))
    except OSError:
        pass
    return next((c for c in candidates if c and os.path.exists(c)), None)


def on_ci() -> bool:
    return os.environ.get("CI", "").lower() not in ("", "0", "false")
