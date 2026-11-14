"""Docs gate: splits code from docs by the profile, recognises commits, finds their repo."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from typing import Any, Optional

from gatelib import BASE, TempDirs, bash, docs_gate, git, make_repo, powershell, raw, toml, write

CODE = BASE["docs"]["code"]
DOCS = BASE["docs"]["docs"]
STOP = {"hook_event_name": "Stop", "stop_hook_active": False}
PROFILE = toml(raw())
SERVER = "apps/web/src/server.ts"


def gate(cwd: str, event: dict, project_dir: Optional[str] = None) -> Optional[dict]:
    """The hook as Claude Code runs it: event JSON on stdin, `cwd` in the event."""
    out, real = io.StringIO(), sys.stdin
    sys.stdin = io.StringIO(json.dumps({"cwd": cwd, **event}))
    old = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = project_dir or cwd
    try:
        with redirect_stdout(out):
            docs_gate.main()
    finally:
        sys.stdin = real
        if old is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old
    text = out.getvalue().strip()
    return json.loads(text) if text else None


def denied(out: Optional[dict]) -> bool:
    return bool(out) and out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


class Split(unittest.TestCase):
    def test_split(self) -> None:
        code = [SERVER, "packages/env/src/index.ts", "db/migrations/001_init.sql", "scripts/freeze.ts",
                ".claude/hooks/x.py", ".claude/settings.json", "package.json", "Dockerfile"]
        not_code = ["tests/docs.test.ts", "docs/notes.txt", ".claude/rules/sse.md", "apps.md"]
        docs = ["docs/features/development.md", "docs/decisions/0018-x.md", "README.md", "CLAUDE.md",
                "AGENTS.md", "packages/env/README.md"]
        for p in code:
            with self.subTest(code=p):
                self.assertEqual(docs_gate.split({p}, CODE, DOCS), ([p], False))
        for p in not_code:
            with self.subTest(not_code=p):
                self.assertEqual(docs_gate.split({p}, CODE, DOCS), ([], False))
        for p in docs:
            with self.subTest(docs=p):
                self.assertEqual(docs_gate.split({SERVER, p}, CODE, DOCS), ([SERVER], True))
        self.assertEqual(docs_gate.split({"packages/env/README.md"}, CODE, DOCS), ([], True))


class IsCommit(unittest.TestCase):
    def test_commits(self) -> None:
        for c in ["git commit -m x", 'git -c "user.name=A B" commit -m x', 'git -c user.name="A B" commit -m x',
                  "git.exe commit -m x", "git --no-pager commit -m x", 'git -C "C:/a b/wt" commit -m x',
                  "cd wt && git commit -m x", "git commit -m @'\nchange\n'@"]:
            with self.subTest(c):
                self.assertTrue(docs_gate.is_commit(c))
        for c in ["git commit-tree x", "git log --grep commit", "git status && git log --oneline -1", "echo committed"]:
            with self.subTest(c):
                self.assertFalse(docs_gate.is_commit(c))


class CommitRoot(unittest.TestCase):
    def test_cd_then_dash_c(self) -> None:
        base = os.path.join(tempfile.gettempdir(), "athena gate", "main")
        wt = os.path.join(tempfile.gettempdir(), "athena gate", "wt")
        cases = [("git commit -m x", base), (f'git -C "{wt}" commit -m x', wt), ("git -C ../wt commit -m x", wt),
                 (f'cd "{wt}" && git commit -m x', wt), ("cd ../wt && git commit -m x", wt),
                 (f'Set-Location "{wt}"; git commit -m x', wt), (f'Set-Location -Path "{wt}"; git commit -m x', wt),
                 (f"Push-Location '{wt}'; git commit -m x", wt), ("cd .. && cd wt && git commit -m x", wt),
                 ("cd .. && git -C wt commit -m x", wt), ("git -C .. -C wt commit -m x", wt),
                 ("git status && git commit -m x", base)]
        if os.name == "nt":
            cases.append((f'cd "/{wt[0].lower()}{wt[2:].replace(chr(92), "/")}" && git commit -m x', wt))
        norm = lambda p: os.path.normcase(os.path.abspath(p))  # noqa: E731
        for command, want in cases:
            with self.subTest(command):
                self.assertEqual(norm(docs_gate.commit_root(command, base)), norm(want))


class RealRepo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempDirs()
        self.repo = make_repo(os.path.join(self.tmp.make(), "app"), PROFILE)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def g(self, event: dict) -> Optional[dict]:
        return gate(self.repo, event)

    def test_stop_bounces_once_then_passes(self) -> None:
        write(self.repo, SERVER)
        out = self.g(STOP)
        self.assertRegex(out["reason"], r"DOCS GATE.*apps/web/src/server\.ts.*docs/features")
        self.assertIsNone(self.g({**STOP, "stop_hook_active": True}))

    def test_stop_passes_clean_and_with_docs(self) -> None:
        self.assertIsNone(self.g(STOP))
        write(self.repo, SERVER)
        write(self.repo, "docs/features/x.md")
        self.assertIsNone(self.g(STOP))

    def test_commits(self) -> None:
        write(self.repo, SERVER)
        git(self.repo, "add", "-A")
        self.assertTrue(denied(self.g(bash('git commit -m "change"'))))
        self.assertIsNone(self.g(bash('git commit -m "refactor [no-docs]"')))
        self.assertTrue(denied(self.g(bash(f"git -C {self.repo} commit -m x"))))
        self.assertTrue(denied(self.g(powershell("git commit -m @'\nchange\n'@"))))
        write(self.repo, "docs/features/x.md")
        git(self.repo, "add", "-A")
        self.assertIsNone(self.g(bash('git commit -m "change"')))

    def test_working_tree_counts_for_add_and_commit_dash_a(self) -> None:
        write(self.repo, SERVER)
        self.assertTrue(denied(self.g(bash('git add -A && git commit -m "change"'))))
        self.assertTrue(denied(self.g(bash('git commit -am "change"'))))
        self.assertTrue(denied(self.g(powershell("git add .; git commit -m change"))))

    def test_commit_all_and_not_without_it(self) -> None:
        write(self.repo, SERVER)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "code")
        write(self.repo, SERVER, "changed\n")
        self.assertIsNone(self.g(bash("git commit -m change")))
        self.assertTrue(denied(self.g(bash("git commit --all -m change"))))

    def test_ignores_non_commits(self) -> None:
        write(self.repo, SERVER)
        git(self.repo, "add", "-A")
        self.assertIsNone(self.g(bash("git status && git log --oneline -1")))
        self.assertIsNone(self.g(bash("echo committed")))
        self.assertIsNone(self.g({"tool_name": "Read", "tool_input": {"file_path": "x"}}))


class ProfileStates(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempDirs()
        self.parent = self.tmp.make()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_no_profile_is_off(self) -> None:
        repo = make_repo(os.path.join(self.parent, "plain"))
        write(repo, SERVER)
        git(repo, "add", "-A")
        self.assertIsNone(gate(repo, bash("git commit -m x")))
        self.assertIsNone(gate(repo, STOP))

    def test_broken_profile_denies_commits_and_bounces_stop_once(self) -> None:
        repo = make_repo(os.path.join(self.parent, "broken"), "schema = 1\n")
        out = gate(repo, bash("git commit -m x"))
        self.assertTrue(denied(out))
        self.assertIn("profile is broken", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(gate(repo, STOP)["decision"], "block")
        self.assertIsNone(gate(repo, {**STOP, "stop_hook_active": True}))

    def test_profile_patterns_decide(self) -> None:
        docs = {"code": ["src/"], "docs": ["notes/*.txt"], "hint": "See notes/."}
        repo = make_repo(os.path.join(self.parent, "app"), toml(raw(docs=docs)))
        write(repo, "src/a.py")
        git(repo, "add", "-A")
        out = gate(repo, bash("git commit -m x"))
        self.assertIn("See notes/.", out["hookSpecificOutput"]["permissionDecisionReason"])
        write(repo, "notes/a.txt")
        git(repo, "add", "-A")
        self.assertIsNone(gate(repo, bash("git commit -m x")))


class Worktrees(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempDirs()
        self.parent = self.tmp.make()
        self.main = make_repo(os.path.join(self.parent, "app"), PROFILE)
        self.wt = os.path.join(self.parent, "app-wp-x1")
        git(self.main, "worktree", "add", "-q", self.wt, "-b", "wp/x1")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_checks_the_worktree_the_commit_runs_in(self) -> None:
        write(self.wt, SERVER)
        git(self.wt, "add", "-A")
        self.assertIsNone(gate(self.main, bash("git commit -m x")))  # main itself is clean
        commands = [bash(f'git -C "{self.wt}" commit -m x'), bash("git -C ../app-wp-x1 commit -m x"),
                    bash(f'cd "{self.wt}" && git commit -m x'), powershell(f'Set-Location "{self.wt}"; git commit -m x'),
                    bash(f'cd "{self.parent}" && cd app-wp-x1 && git commit -m x')]
        for event in commands:
            with self.subTest(event["tool_input"]["command"]):
                self.assertTrue(denied(gate(self.main, event)))

    def test_documented_worktree_commit_and_every_commit_checked(self) -> None:
        write(self.wt, SERVER)
        write(self.wt, "docs/features/x.md")
        git(self.wt, "add", "-A")
        write(self.main, SERVER)
        git(self.main, "add", "-A")
        self.assertIsNone(gate(self.main, bash(f'git -C "{self.wt}" commit -m x')))
        self.assertTrue(denied(gate(self.main, bash(f'git -C "{self.wt}" commit -m a && git -C "{self.main}" commit -m b'))))

    def test_stop_checks_the_event_cwd(self) -> None:
        write(self.main, SERVER)
        self.assertEqual(gate(self.main, STOP, project_dir=self.wt)["decision"], "block")
        self.assertIsNone(gate(self.wt, STOP, project_dir=self.main))


if __name__ == "__main__":
    unittest.main()
