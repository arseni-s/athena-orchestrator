"""Destroy gate: destruction that reaches beyond development is denied.

The cases live in destroy_gate_cases.json (tool, input, expect, rule, optional fixture
files). Each is passed to the imported gate as an event; nothing is executed.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from pathlib import Path

from gatelib import TempDirs, destroy_gate

CASES = json.loads((Path(__file__).parent / "destroy_gate_cases.json").read_text(encoding="utf-8"))


class Cases(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempDirs()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_case(self, case: dict) -> tuple[str, str]:
        folder = self.tmp.make("athena-dg-")
        for name, body in (case.get("files") or {}).items():
            Path(folder, name).write_text(body, encoding="utf-8")
        text = json.dumps(case["input"]).replace("{{DIR}}", folder.replace("\\", "/"))
        event = {"tool_name": case["tool"], "tool_input": json.loads(text), "cwd": folder}
        try:
            verdict = destroy_gate.decide(event)
        except destroy_gate.GateError as exc:
            return "deny", f"gate error, {exc}"
        return verdict or ("none", "")

    def test_cases(self) -> None:
        self.assertGreater(len(CASES), 150)
        for n, case in enumerate(CASES):
            with self.subTest(n=n, tool=case["tool"], input=json.dumps(case["input"])[:120], note=case.get("note")):
                decision, reason = self.run_case(case)
                self.assertEqual(decision, case["expect"], reason)
                if case.get("rule"):
                    self.assertIn(case["rule"], reason)

    def test_every_rule_has_cases(self) -> None:
        rules = {c["rule"] for c in CASES if c.get("rule")}
        self.assertEqual(rules, {"railway-delete", "railway-api", "http-delete", "git-main",
                                 "git-force-unnamed", "gh-destroy", "infisical-delete", "op-delete", "mcp-delete", "write-mutation",
                                 "write-script", "script-run", "gate-edit", "gate error"})

    def test_bypass_turns_ask_into_deny(self) -> None:
        ask = ("ask", "DESTROY GATE: gate-edit: ...")
        bypass = {"permission_mode": "bypassPermissions"}
        self.assertEqual(destroy_gate.strict(ask, bypass)[0], "deny")
        self.assertIn("bypass-permissions", destroy_gate.strict(ask, bypass)[1])
        for mode in ("default", "acceptEdits", "plan", None):
            self.assertEqual(destroy_gate.strict(ask, {"permission_mode": mode}), ask)
        self.assertEqual(destroy_gate.strict(ask, None), ask)
        self.assertIsNone(destroy_gate.strict(None, bypass))
        deny = ("deny", "x")
        self.assertEqual(destroy_gate.strict(deny, bypass), deny)


class FailsClosed(unittest.TestCase):
    def main_with(self, raw: bytes) -> dict:
        out, real_in, real_out = io.StringIO(), sys.stdin, sys.stdout
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
        sys.stdout = out
        try:
            self.assertEqual(destroy_gate.main(), 0)
        finally:
            sys.stdin, sys.stdout = real_in, real_out
        return json.loads(out.getvalue())["hookSpecificOutput"] if out.getvalue() else {}

    def test_bad_input_denies(self) -> None:
        for raw in (b"not json", b"[]", b'{"tool_input": {}}', b'{"tool_name": "Bash", "tool_input": null}',
                    b'{"tool_name": "Bash", "tool_input": {"command": 5}}'):
            with self.subTest(raw=raw):
                result = self.main_with(raw)
                self.assertEqual(result["permissionDecision"], "deny")
                self.assertIn("gate error", result["permissionDecisionReason"])

    def test_big_file_denies(self) -> None:
        tmp = TempDirs()
        try:
            folder = tmp.make()
            Path(folder, "big.sh").write_text("echo hello\n" * 100_001, encoding="utf-8")
            event = {"tool_name": "Bash", "cwd": folder,
                     "tool_input": {"command": f'bash {folder.replace(os.sep, "/")}/big.sh'}}
            result = self.main_with(json.dumps(event).encode())
            self.assertEqual(result["permissionDecision"], "deny")
            self.assertIn("over 1 MB", result["permissionDecisionReason"])
        finally:
            tmp.cleanup()

    def test_other_tools_have_no_opinion(self) -> None:
        self.assertEqual(self.main_with(b'{"tool_name": "WebFetch", "tool_input": {"url": "https://example.org"}}'), {})


if __name__ == "__main__":
    unittest.main()
