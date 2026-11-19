"""The push_secrets.py template, run against a fake `op` and a fake `railway`: nothing is executed."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

PATH = Path(__file__).resolve().parent.parent / "plugins" / "orchestrator" / "templates" / "push_secrets.py"
SPEC = importlib.util.spec_from_file_location("push_secrets", PATH)
push_secrets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(push_secrets)

ITEM = {"fields": [
    {"label": "BOT_TOKEN", "value": "tok-123456"}, {"label": "API_KEY", "value": "key-abcdef"},
    {"label": "SHEET_ID", "value": "sheet-1"}, {"label": "notesPlain", "value": "a note"},
    {"label": "EMPTY", "value": ""},
]}


class Fake:
    def __init__(self, railway: dict[str, str], fail_set: bool = False) -> None:
        self.railway, self.fail_set, self.calls = railway, fail_set, []

    def __call__(self, cmd: list[str], stdin: str | None = None):
        self.calls.append((cmd, stdin))
        out, code, err = "", 0, ""
        if cmd[:3] == ["op", "item", "get"]:
            out = json.dumps(ITEM)
        elif cmd[:3] == ["railway", "variable", "list"]:
            out = json.dumps(self.railway)
        elif cmd[:3] == ["railway", "variable", "set"] and self.fail_set:
            code, err = 1, f"invalid value {stdin}"
        return mock.Mock(returncode=code, stdout=out, stderr=err)

    def sets(self) -> list[list[str]]:
        return [c for c, _ in self.calls if c[:3] == ["railway", "variable", "set"]]


def run(argv: list[str], fake: Fake, tty: bool = False, answer: str = "production",
        env: dict[str, str] | None = None) -> tuple[int, str]:
    out = io.StringIO()
    with mock.patch.object(push_secrets, "run", fake), mock.patch.object(push_secrets, "SERVICES", ["web"]), \
            mock.patch.object(push_secrets.sys.stdin, "isatty", return_value=tty), \
            mock.patch("builtins.input", return_value=answer), mock.patch.dict(os.environ, env or {}, clear=False), \
            redirect_stdout(out), redirect_stderr(out):
        if env is None:
            os.environ.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
        code = push_secrets.main(argv)
    return code, out.getvalue()


VALUES = ("tok-123456", "key-abcdef", "sheet-1", "old-value", "set-by-railway")


class PushSecrets(unittest.TestCase):
    def railway(self) -> dict[str, str]:
        return {"BOT_TOKEN": "tok-123456", "API_KEY": "old-value", "HAND_MADE": "x1",
                "RAILWAY_PUBLIC_DOMAIN": "set-by-railway"}

    def assertNoValues(self, text: str) -> None:
        for v in VALUES:
            self.assertNotIn(v, text)

    def test_development_sets_what_differs_with_one_deploy(self) -> None:
        fake = Fake(self.railway())
        code, out = run(["development"], fake)
        self.assertEqual(code, 0, out)
        sets = fake.sets()
        self.assertEqual([c[3] for c in sets], ["API_KEY", "SHEET_ID"])
        self.assertIn("--skip-deploys", sets[0])
        self.assertNotIn("--skip-deploys", sets[1], "the last change deploys development once")
        self.assertTrue(all("--stdin" in c for c in sets))
        self.assertEqual([s for c, s in fake.calls if c[:3] == ["railway", "variable", "set"]], ["key-abcdef", "sheet-1"])
        self.assertIn("HAND_MADE", out)
        self.assertNotIn("RAILWAY_PUBLIC_DOMAIN", out)
        self.assertNotIn("notesPlain", out)
        self.assertNoValues(out)
        for cmd, _ in fake.calls:
            self.assertNoValues(" ".join(cmd))

    def test_check_changes_nothing(self) -> None:
        fake = Fake(self.railway())
        code, out = run(["development", "--check"], fake)
        self.assertEqual(code, 0, out)
        self.assertEqual(fake.sets(), [])
        self.assertIn("to set: API_KEY, SHEET_ID", out)
        self.assertNoValues(out)

    def test_nothing_to_change_deploys_nothing(self) -> None:
        fake = Fake({"BOT_TOKEN": "tok-123456", "API_KEY": "key-abcdef", "SHEET_ID": "sheet-1"})
        code, _ = run(["development"], fake)
        self.assertEqual((code, fake.sets()), (0, []))

    def test_production_never_redeploys(self) -> None:
        fake = Fake(self.railway())
        code, out = run(["production"], fake, tty=True)
        self.assertEqual(code, 0, out)
        self.assertTrue(fake.sets())
        self.assertTrue(all("--skip-deploys" in c for c in fake.sets()))
        self.assertIn("deploy it from the Railway dashboard", out)

    def test_production_needs_you_at_a_terminal(self) -> None:
        for kw, why in [({"tty": False}, "terminal"), ({"tty": True, "answer": "yes"}, "not confirmed"),
                        ({"tty": True, "env": {"OP_SERVICE_ACCOUNT_TOKEN": "ops_x"}}, "service account")]:
            with self.subTest(why=why):
                fake = Fake(self.railway())
                code, out = run(["production"], fake, **kw)
                self.assertEqual(code, 1)
                self.assertIn(why, out)
                self.assertEqual(fake.calls, [], "nothing is read before production is confirmed")

    def test_a_failure_blanks_the_values(self) -> None:
        code, out = run(["development"], Fake(self.railway(), fail_set=True))
        self.assertEqual(code, 1)
        self.assertIn("invalid value ***", out)
        self.assertNoValues(out)

    def test_usage(self) -> None:
        for argv in ([], ["staging"], ["development", "production"]):
            with self.subTest(argv=argv):
                self.assertEqual(run(argv, Fake({}))[0], 2)


if __name__ == "__main__":
    unittest.main()
