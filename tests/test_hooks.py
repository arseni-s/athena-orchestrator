"""hooks/hooks.json and the project fallback stub, run the way Claude Code runs them (Git Bash
on Windows, `bash` elsewhere). Without a shell these tests skip, except on CI, where they fail.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from typing import Optional

from gatelib import PLUGIN, TempDirs, git_bash, make_repo, on_ci, raw, toml, write

HOOKS = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
STUB = json.loads((PLUGIN / "templates" / "settings.json").read_text(encoding="utf-8"))
SHELL = git_bash()


def commands(event: str) -> list[str]:
    return [h["command"] for entry in HOOKS.get(event, []) for h in entry["hooks"]]


class Registration(unittest.TestCase):
    def test_events_and_matchers(self) -> None:
        self.assertEqual(sorted(HOOKS), ["PreToolUse", "Stop"])
        by_gate = {gate: e["matcher"] for e in HOOKS["PreToolUse"] for h in e["hooks"]
                   for gate in ("destroy_gate", "ops_gate", "docs_gate") if f"{gate}.py" in h["command"]}
        self.assertEqual(by_gate, {
            "destroy_gate": "Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit|mcp__.*",
            "ops_gate": "Bash|PowerShell", "docs_gate": "Bash|PowerShell"})
        pre, stop = commands("PreToolUse"), commands("Stop")
        self.assertEqual(len(pre), 3)
        self.assertTrue(all("docs_gate.py" in c for c in stop) and stop)

    def test_every_command_has_a_fallback(self) -> None:
        for c in commands("PreToolUse"):
            # ask, or deny in bypass-permissions mode, where an ask never reaches the user
            self.assertRegex(c, r"\|\| \{ grep -qE .*bypassPermissions.* && d=deny \|\| d=ask; echo .*permissionDecision")
        for c in commands("Stop"):
            self.assertIn("|| echo", c)
            self.assertIn("systemMessage", c)  # never a block: a blocking fallback could loop

    def test_timeouts_inside_limits(self) -> None:
        for entry in HOOKS["PreToolUse"]:
            for h in entry["hooks"]:
                self.assertLessEqual(h["timeout"], 30)


@unittest.skipIf(not SHELL and not on_ci(), "Git Bash / bash not found")
class RunThroughTheShell(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not SHELL:
            raise AssertionError("Git Bash / bash not found (required on CI)")
        cls.tmp = TempDirs()
        cls.repo = make_repo(os.path.join(cls.tmp.make(), "app"), toml(raw()))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_hook(self, command: str, event: dict, plugin_root: str, home: Optional[str] = None) -> tuple[int, str]:
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root), "CLAUDE_PROJECT_DIR": self.repo}
        if home:
            env["HOME"] = home
            env.pop("CLAUDE_CODE_PLUGIN_CACHE_DIR", None)
        r = subprocess.run([SHELL, "-c", command], input=json.dumps({**event, "cwd": self.repo}),
                           capture_output=True, text=True, env=env, timeout=60)
        return r.returncode, r.stdout.strip()

    def decision(self, stdout: str) -> str:
        return json.loads(stdout)["hookSpecificOutput"]["permissionDecision"] if stdout else "none"

    def test_ops_gate_runs(self) -> None:
        ops = next(c for c in commands("PreToolUse") if "ops_gate.py" in c)
        code, out = self.run_hook(ops, {"tool_name": "Bash", "tool_input": {"command": "printenv"}}, PLUGIN)
        self.assertEqual((code, self.decision(out)), (0, "deny"))
        code, out = self.run_hook(ops, {"tool_name": "Bash", "tool_input": {"command": "ls"}}, PLUGIN)
        self.assertEqual((code, out), (0, ""))

    def test_destroy_gate_runs(self) -> None:
        destroy = next(c for c in commands("PreToolUse") if "destroy_gate.py" in c)
        code, out = self.run_hook(destroy, {"tool_name": "Bash", "tool_input": {"command": "railway delete --yes"}}, PLUGIN)
        self.assertEqual((code, self.decision(out)), (0, "deny"))
        edit = {"tool_name": "Edit", "tool_input": {"file_path": ".claude/orchestration/project.toml",
                                                    "old_string": "observe", "new_string": "development"}}
        code, out = self.run_hook(destroy, edit, PLUGIN)
        self.assertEqual((code, self.decision(out)), (0, "ask"))
        code, out = self.run_hook(destroy, {**edit, "permission_mode": "bypassPermissions"}, PLUGIN)
        self.assertEqual((code, self.decision(out)), (0, "deny"))
        self.assertIn("bypass-permissions", out)
        code, out = self.run_hook(destroy, {"tool_name": "Bash", "tool_input": {"command": "railway up"}}, PLUGIN)
        self.assertEqual((code, out), (0, ""))

    def test_missing_scripts_fail_closed(self) -> None:
        missing = os.path.join(self.tmp.make(), "no-plugin")
        for c in commands("PreToolUse"):
            with self.subTest(c[:60]):
                code, out = self.run_hook(c, {"tool_name": "Bash", "tool_input": {"command": "ls"}}, missing)
                self.assertEqual((code, self.decision(out)), (0, "ask"))
                code, out = self.run_hook(c, {"tool_name": "Bash", "tool_input": {"command": "ls"},
                                              "permission_mode": "bypassPermissions"}, missing)
                self.assertEqual((code, self.decision(out)), (0, "deny"))
        for c in commands("Stop"):
            code, out = self.run_hook(c, {"hook_event_name": "Stop", "stop_hook_active": False}, missing)
            self.assertEqual(code, 0)
            self.assertIn("systemMessage", json.loads(out))

    def test_docs_gate_stop_runs(self) -> None:
        write(self.repo, "apps/x.ts")
        try:
            code, out = self.run_hook(commands("Stop")[0], {"hook_event_name": "Stop", "stop_hook_active": False}, PLUGIN)
            self.assertEqual((code, json.loads(out)["decision"]), (0, "block"))
        finally:
            os.remove(os.path.join(self.repo, "apps", "x.ts"))

    def test_fallback_stub(self) -> None:
        stub = STUB["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        event = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        home = self.tmp.make()
        code, out = self.run_hook(stub, event, PLUGIN, home=home)  # no plugins at all
        self.assertEqual((code, self.decision(out)), (0, "ask"))
        self.assertIn("GATES MISSING", out)
        code, out = self.run_hook(stub, {**event, "permission_mode": "bypassPermissions"}, PLUGIN, home=home)
        self.assertEqual((code, self.decision(out)), (0, "deny"))
        write(home, ".claude/plugins/installed_plugins.json",
              json.dumps({"plugins": {"athena-orchestrator@athena-orchestrator": [{"scope": "project"}]}}))
        self.assertEqual(self.run_hook(stub, event, PLUGIN, home=home), (0, ""))
        self.assertEqual(STUB["enabledPlugins"], {"athena-orchestrator@athena-orchestrator": True})


if __name__ == "__main__":
    unittest.main()
