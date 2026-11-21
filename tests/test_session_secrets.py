"""session_secrets.py: the session-start loader of a project's development tokens, and the
merge guard's own GH_TOKEN. `op` is a fake and the credential store is patched: no
1Password, no Windows Credential Manager, and no real token anywhere.
"""
from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest import mock

from gatelib import Fakes, TempDirs, make_repo, ops_gate, write

import session_secrets as ss  # noqa: E402  (gatelib puts the scripts folder on sys.path)

VAULT = "sample-dev"
SECRET = "ghp_not_a_real_value_123"
SA = "ops_not_a_real_service_account"
ITEMS = [
    {"id": "abc123", "title": "GitHub - sample token", "category": "API_CREDENTIAL"},
    {"id": "def456", "title": "railway-development", "category": "SECURE_NOTE"},
    {"id": "ghi789", "title": "Railway project token", "category": "API_CREDENTIAL"},
]


def config(**changes: Any) -> str:
    cfg = {"credential": "claude-project-secrets/sample", "vault": VAULT,
           "export_service_account_token": True,
           "env": {"GH_TOKEN": f"op://{VAULT}/abc123/credential"}}
    cfg.update(changes)
    return json.dumps(cfg)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempDirs()
        self.work = self.tmp.make("athena-secrets-")
        self.repo = make_repo(os.path.join(self.work, "app"))
        self.env_file = os.path.join(self.work, "env.sh")
        self.fakes = Fakes(self.work)
        self.stored: dict[str, str] = {"claude-project-secrets/sample": SA}
        patches = [mock.patch.object(ss, "read_stored", lambda name: self.stored.get(name)),
                   mock.patch.dict(os.environ, {"CLAUDE_ENV_FILE": self.env_file})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr, ss, "OP_CMD", None)

    def op(self, vaults: Optional[list[str]] = None, read: Optional[dict] = None) -> "callable":
        rules = [{"match": "item", "stdout": json.dumps(ITEMS)},
                 {"match": "vault", "stdout": json.dumps([{"id": "v", "name": n} for n in (vaults or [VAULT])])},
                 read or {"match": "read", "stdout": SECRET}]
        ss.OP_CMD, calls = self.fakes.make(rules)
        return calls

    def exported(self) -> str:
        return Path(self.env_file).read_text(encoding="utf-8") if os.path.exists(self.env_file) else ""


class Load(Base):
    def test_loads_names_only(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config())
        calls = self.op()
        msg = ss.load(self.repo)
        self.assertIn("OP_SERVICE_ACCOUNT_TOKEN, GH_TOKEN", msg)
        self.assertNotIn(SECRET, msg)
        self.assertNotIn(SA, msg)
        self.assertEqual(self.exported(), f"export OP_SERVICE_ACCOUNT_TOKEN='{SA}'\nexport GH_TOKEN='{SECRET}'\n")
        self.assertIn(["read", "--no-newline", f"op://{VAULT}/abc123/credential"], calls())

    def test_refuses_a_service_account_that_opens_more(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config())
        calls = self.op(vaults=[VAULT, "sample-prod"])
        msg = ss.load(self.repo)
        self.assertIn("not only 'sample-dev'", msg)
        self.assertEqual(self.exported(), "")
        self.assertFalse([c for c in calls() if c[0] == "read"])

    def test_refuses_another_vault(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config())
        self.op(vaults=["other-dev"])
        self.assertIn("nothing loaded", ss.load(self.repo))
        self.assertEqual(self.exported(), "")

    def test_failed_read_is_named_without_a_value(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config(export_service_account_token=False))
        self.op(read={"match": "read", "exit": 1, "stderr": "item not found\n"})
        msg = ss.load(self.repo)
        self.assertIn("Loaded for this session (names only): none", msg)
        self.assertIn("Could not read: GH_TOKEN", msg)
        self.assertEqual(self.exported(), "")

    def test_quotes_a_value_for_bash(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config(export_service_account_token=False))
        self.op(read={"match": "read", "stdout": "it's"})
        ss.load(self.repo)
        self.assertEqual(self.exported(), "export GH_TOKEN='it'\\''s'\n")

    def test_project_without_config_is_silent(self) -> None:
        self.assertEqual(ss.load(self.repo), "")

    def test_stored_token_without_config_says_setup(self) -> None:
        self.stored[ss.default_credential(Path(self.repo))] = SA
        self.assertIn("setup", ss.load(self.repo))

    def test_no_stored_token_says_how(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config(credential="claude-project-secrets/none"))
        msg = ss.load(self.repo)
        self.assertIn("no token stored as 'claude-project-secrets/none'", msg)
        self.assertIn("setup", msg)

    def test_bad_config(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config(env={"BAD NAME": "op://x/y/z"}))
        self.assertIn("not valid", ss.load(self.repo))
        write(self.repo, ".claude/session-secrets.json", "{not json")
        self.assertIn("cannot be read", ss.load(self.repo))

    def test_hook_entry_never_fails(self) -> None:
        with mock.patch.object(ss, "load", side_effect=RuntimeError(SECRET)), \
                mock.patch("sys.stdin") as stdin, mock.patch("builtins.print") as out:
            stdin.isatty.return_value, stdin.buffer.read.return_value = False, json.dumps({"cwd": self.repo}).encode()
            self.assertEqual(ss.main([]), 0)
        self.assertNotIn(SECRET, str(out.call_args))  # the exception text is not printed
        self.assertIn("RuntimeError", str(out.call_args))

    def test_hook_reads_an_event_with_a_bom(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config())
        self.op()
        event = b"\xef\xbb\xbf" + json.dumps({"cwd": self.repo}).encode()
        with mock.patch.dict(os.environ), mock.patch("sys.stdin") as stdin, \
                mock.patch("builtins.print") as out:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            stdin.isatty.return_value, stdin.buffer.read.return_value = False, event
            self.assertEqual(ss.main([]), 0)
        self.assertIn("names only): OP_SERVICE_ACCOUNT_TOKEN, GH_TOKEN", str(out.call_args))

    def test_op_answering_nonsense_is_a_problem(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config())
        ss.OP_CMD, _ = self.fakes.make([{"match": "vault", "stdout": "<html>"}])
        self.assertIn("did not answer JSON", ss.load(self.repo))


class Discover(Base):
    def test_finds_the_agent_tokens(self) -> None:
        self.op()
        self.assertEqual(ss.find_tokens(VAULT, SA), {
            "GH_TOKEN": f"op://{VAULT}/abc123/credential",
            "RAILWAY_TOKEN": f"op://{VAULT}/ghi789/credential"})  # not the secure note

    def test_two_candidates_are_left_to_the_user(self) -> None:
        two = ITEMS + [{"id": "zzz", "title": "github old", "category": "API_CREDENTIAL"}]
        ss.OP_CMD, _ = self.fakes.make([{"match": "item", "stdout": json.dumps(two)}])
        self.assertNotIn("GH_TOKEN", ss.find_tokens(VAULT, SA))

    def test_default_credential_name(self) -> None:
        self.assertEqual(ss.default_credential(Path("/x/My Project")), "claude-project-secrets/my-project")


class Setup(Base):
    def run_setup(self, answers: list[str], clipboard: str = SA) -> list[str]:
        with mock.patch("builtins.input", side_effect=answers), \
                mock.patch.object(ss, "_clipboard_token", return_value=clipboard), \
                mock.patch.object(ss, "write_stored", lambda n, t: self.stored.__setitem__(n, t)):
            return ss.setup(self.repo)

    def test_writes_the_config_from_what_the_token_opens(self) -> None:
        self.op()
        lines = self.run_setup([])
        name = ss.default_credential(Path(self.repo))
        self.assertEqual(self.stored[name], SA)
        cfg = json.loads(Path(self.repo, ".claude/session-secrets.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg, {"credential": name, "vault": VAULT, "export_service_account_token": True,
                               "env": {"GH_TOKEN": f"op://{VAULT}/abc123/credential",
                                       "RAILWAY_TOKEN": f"op://{VAULT}/ghi789/credential"}})
        self.assertNotIn(SA, "\n".join(lines))

    def test_keeps_the_stored_token_and_existing_entries(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config(env={"GH_TOKEN": "op://sample-dev/mine/credential"}))
        self.op()
        with mock.patch.object(ss, "_clipboard_token", side_effect=AssertionError("asked")):
            self.run_setup([""])
        cfg = json.loads(Path(self.repo, ".claude/session-secrets.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["env"]["GH_TOKEN"], "op://sample-dev/mine/credential")
        self.assertEqual(cfg["credential"], "claude-project-secrets/sample")

    def test_refuses_more_than_one_vault(self) -> None:
        self.op(vaults=[VAULT, "sample-prod"])
        with self.assertRaisesRegex(ss.Problem, "exactly one"):
            self.run_setup([])
        self.assertFalse(Path(self.repo, ".claude/session-secrets.json").exists())

    def test_refuses_something_else_on_the_clipboard(self) -> None:
        with self.assertRaisesRegex(ss.Problem, "ops_"):
            self.run_setup([], clipboard="hello")


class MergeGuardToken(Base):
    def test_env_values(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config())
        self.op()
        self.assertEqual(ss.env_values(self.repo, ["GH_TOKEN", "OTHER"]), {"GH_TOKEN": SECRET})
        self.stored.clear()
        self.assertEqual(ss.env_values(self.repo, ["GH_TOKEN"]), {})

    def test_gh_token_prefers_the_process_environment(self) -> None:
        with mock.patch.dict(os.environ, {"GH_TOKEN": "x"}), \
                mock.patch.object(ss, "env_values", side_effect=AssertionError("read")):
            self.assertEqual(ops_gate.gh_token(self.repo, time.monotonic() + 20), ({}, ""))

    def test_gh_token_from_the_project(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config())
        self.op()
        with mock.patch.dict(os.environ), mock.patch.object(ops_gate.session_secrets, "read_stored",
                                                            lambda n: self.stored.get(n)):
            os.environ.pop("GH_TOKEN", None), os.environ.pop("GITHUB_TOKEN", None)
            self.assertEqual(ops_gate.gh_token(self.repo, time.monotonic() + 20), ({"GH_TOKEN": SECRET}, ""))

    def test_a_failed_read_denies_the_merge(self) -> None:
        write(self.repo, ".claude/session-secrets.json", config())
        self.op(read={"match": "read", "exit": 1, "stderr": "service account deleted\n"})
        with mock.patch.dict(os.environ):
            os.environ.pop("GH_TOKEN", None), os.environ.pop("GITHUB_TOKEN", None)
            problems = ops_gate._check_merge(ops_gate.Merge(pr="5"), self.repo, False, time.monotonic() + 20)
        self.assertEqual(len(problems), 1)
        self.assertIn("cannot read GH_TOKEN", problems[0])
        self.assertIn("service account deleted", problems[0])


if __name__ == "__main__":
    unittest.main()
