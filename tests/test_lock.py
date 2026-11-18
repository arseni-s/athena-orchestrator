"""Orchestrator lock: one orchestrator per repository, shared by every worktree.

The lock functions are imported and called with session ids and process ids. A "gone"
holder is a real process that has already exited; nothing else is run.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from gatelib import TempDirs, athena_lock, destroy_gate, git, loaded, make_repo, ops_gate

LIVE = str(os.getpid())


def dead_pid() -> str:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return str(proc.pid)


class Lock(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempDirs()
        self.path = os.path.join(self.tmp.make("athena-lock-"), athena_lock.NAME)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_first_claim_takes_it_and_another_live_holder_is_refused(self) -> None:
        ok, record = athena_lock.claim(self.path, "session-a", LIVE)
        self.assertTrue(ok)
        self.assertEqual((record["session"], record["pid"]), ("session-a", LIVE))
        ok, holder = athena_lock.claim(self.path, "session-b", "1")
        self.assertFalse(ok)
        self.assertEqual(holder["session"], "session-a")

    def test_same_session_or_process_renews(self) -> None:
        _, first = athena_lock.claim(self.path, "session-a", LIVE)
        ok, again = athena_lock.claim(self.path, "session-a", LIVE)
        self.assertTrue(ok)
        self.assertEqual(again["since"], first["since"])
        ok, cleared = athena_lock.claim(self.path, "session-after-clear", LIVE)  # /clear: same process
        self.assertTrue(ok)
        self.assertNotIn("took_over", cleared)

    def test_holder_whose_process_ended_is_taken_over(self) -> None:
        athena_lock.claim(self.path, "session-a", dead_pid())
        ok, record = athena_lock.claim(self.path, "session-b", LIVE)
        self.assertTrue(ok)
        self.assertEqual(record["session"], "session-b")
        self.assertEqual(record["took_over"]["session"], "session-a")

    def test_holder_with_unknown_process_counts_as_live(self) -> None:
        athena_lock.claim(self.path, "session-a", None)
        self.assertFalse(athena_lock.claim(self.path, "session-b", LIVE)[0])
        self.assertIsNone(athena_lock.alive(None))
        self.assertIsNone(athena_lock.alive("not a pid"))

    def test_release(self) -> None:
        self.assertEqual(athena_lock.release(self.path, "session-a", LIVE), "free")
        athena_lock.claim(self.path, "session-a", LIVE)
        self.assertEqual(athena_lock.release(self.path, "session-b", "1"), "not yours")
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(athena_lock.release(self.path, "session-b", "1", force=True), "released")
        self.assertFalse(os.path.exists(self.path))
        athena_lock.claim(self.path, "session-a", LIVE)
        self.assertEqual(athena_lock.release(self.path, "session-a", LIVE), "released")

    def test_fails_closed(self) -> None:
        Path(self.path).write_text("not json", encoding="utf-8")
        with self.assertRaises(athena_lock.LockError):
            athena_lock.claim(self.path, "session-a", LIVE)
        Path(self.path).write_text("[]", encoding="utf-8")
        with self.assertRaises(athena_lock.LockError):
            athena_lock.claim(self.path, "session-a", LIVE)

    def test_stuck_mutex_is_broken_and_a_fresh_one_waits(self) -> None:
        mutex = self.path + ".mutex"
        Path(mutex).write_text("", encoding="utf-8")
        os.utime(mutex, (0, 0))  # left by a crash long ago
        self.assertTrue(athena_lock.claim(self.path, "session-a", LIVE)[0])
        self.assertFalse(os.path.exists(mutex))
        Path(mutex).write_text("", encoding="utf-8")  # held right now by another claim
        with mock.patch.object(athena_lock.time, "sleep"), \
                mock.patch.object(athena_lock.time, "time", side_effect=[0.0, 1.0, 6.0]):
            with self.assertRaises(athena_lock.LockError):
                athena_lock.claim(self.path, "session-b", LIVE)


class Repo(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempDirs()
        base = cls.tmp.make("athena-lock-repo-")
        cls.repo = make_repo(os.path.join(base, "repo"))
        cls.worktree = os.path.join(base, "repo-wp-a1")
        git(cls.repo, "worktree", "add", "-q", cls.worktree, "-b", "wp/a1-x")
        cls.outside = cls.tmp.make("athena-not-a-repo-")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_main(self, cwd: str, args: list[str], session: str, pid: str) -> tuple[int, str]:
        out, here = io.StringIO(), os.getcwd()
        env = {"CLAUDE_CODE_SESSION_ID": session, "CLAUDE_PID": pid}
        try:
            os.chdir(cwd)
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
                code = athena_lock.main(args)
        finally:
            os.chdir(here)
        return code, out.getvalue()

    def test_main_checkout_and_worktree_share_one_lock(self) -> None:
        main_lock = athena_lock.lock_path(self.repo)
        self.assertEqual(os.path.normcase(main_lock), os.path.normcase(athena_lock.lock_path(self.worktree)))
        self.assertEqual(os.path.normcase(os.path.dirname(main_lock)),
                         os.path.normcase(os.path.join(self.repo, ".git")))

    def test_cli(self) -> None:
        code, text = self.run_main(self.repo, ["claim"], "session-a", LIVE)
        self.assertEqual(code, 0, text)
        code, text = self.run_main(self.worktree, ["claim"], "session-b", "1")
        self.assertEqual(code, 1)
        self.assertIn("another orchestrator is running", text)
        self.assertIn("release --force", text)
        code, text = self.run_main(self.worktree, ["status"], "session-b", "1")
        self.assertEqual(code, 0)
        self.assertIn("held: session session-", text)
        self.assertEqual(self.run_main(self.repo, ["release"], "session-b", "1")[0], 1)
        self.assertEqual(self.run_main(self.repo, ["release"], "session-a", LIVE), (0, "released\n"))
        self.assertEqual(self.run_main(self.repo, ["status"], "session-a", LIVE)[1],
                         "free: no orchestrator holds this repository\n")

    def test_cli_outside_a_repo_or_misused(self) -> None:
        code, text = self.run_main(self.outside, ["claim"], "session-a", LIVE)
        self.assertEqual(code, 2)
        self.assertIn("not in a git repository", text)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for args in ([], ["take"], ["claim", "--force"], ["release", "--all"]):
                with self.subTest(args=args):
                    self.assertEqual(athena_lock.main(args), 64)


class Gates(unittest.TestCase):
    """The skill's own lock commands must pass the gates it runs under."""

    def test_lock_commands_pass(self) -> None:
        script = str(Path(athena_lock.__file__)).replace("\\", "/")
        for action in ("claim", "status", "release"):
            command = f'python "{script}" {action}'
            event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": os.getcwd()}
            for phase in ("development", "observe"):
                with self.subTest(action=action, phase=phase):
                    self.assertIsNone(destroy_gate.decide(event))
                    self.assertIsNone(ops_gate._decide(event, loaded(access={"phase": phase})))


if __name__ == "__main__":
    unittest.main()
