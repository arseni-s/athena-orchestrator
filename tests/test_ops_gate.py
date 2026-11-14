"""Ops gate: phases, the freeze check, secrets, and commands it cannot read.

Commands are passed as strings to the imported gate; none is executed. The freeze check is
a stub here, except in FreezeStatus, which runs tiny Python commands.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import contextmanager, redirect_stdout
from typing import Any, Iterator, Optional

from gatelib import DROP, PY, bash, loaded, ops_gate, powershell

CLEAR = (0, "CLEAR: nothing scheduled")
FROZEN = (1, "FROZEN: release window")
OBSERVE = {"phase": "observe"}
FREEZE_CALLS: list[str] = []  # the freeze-check commands the last decide() ran


@contextmanager
def patched(**attrs: Any) -> Iterator[None]:
    old = {k: getattr(ops_gate, k) for k in attrs}
    for k, v in attrs.items():
        setattr(ops_gate, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(ops_gate, k, v)


def decide(event: dict, freeze: tuple = CLEAR, state: str = "ok", **changes: Any) -> tuple[str, str]:
    FREEZE_CALLS.clear()

    def stub(root: str, command: Optional[str]) -> tuple:
        FREEZE_CALLS.append(command or "")
        return freeze if command else (0, ops_gate.NO_CHECK)
    with patched(freeze_status=stub, GH_CMD=["gh-must-not-be-called"], GIT_CMD=["git-must-not-be-called"]):
        out = ops_gate._decide(event, loaded(state, **changes)) or {}
    return out.get("permissionDecision", "none"), out.get("permissionDecisionReason", "")


def decision(event: dict, **kw: Any) -> str:
    return decide(event, **kw)[0]


# Railway commands outside the read allowlist, API writes and direct hosts: platform work.
PLATFORM = [
    "railway variables --set A=1 --skip-deploys", "railway variable set A=1 --skip-deploys",
    "railway restart", "railway service source disconnect --service web", "railway domain",
    "railway domain app.example.org", "railway cdn disable", "railway waf under-attack enable",
    "railway bucket rename a b", "railway sandbox exec -- ls", "railway volume attach",
    'railway agent -p "deploy everything --help"', "railway run -- pnpm x --help",
    "railway run pnpm db:migrate", "railway connect postgres", "railway shell", "railway ssh",
    "railway add --database postgres", "railway link", "railway service restart",
    "curl -X POST https://backboard.railway.com/graphql/v2 -d '{\"query\":\"query { deployments { edges { node { id } } } }\"}'",
    "psql postgresql://u:p@monorail.proxy.rlwy.net:5432/railway",
    "psql postgres://u:p@postgres.railway.internal:5432/railway",
    "mywrap railway up", "echo railway up", 'bash -c "echo railway up"', "ssh host docker push x",
    "find . -exec railway up ;",
]
HARMLESS = [
    "railway --help", "railway --version", "railway status", "railway logs",
    "railway logs --service sync", "railway deployment list", "railway metrics", "railway whoami",
    "railway list", "railway up --help", "railway domain list", "railway postgres pitr status",
    "railway postgres -s pg ha status", "grep railway docs/RUNBOOK.md", "cat railway.json",
    "curl -d x https://example.org/", "cat docs/production.md", 'psql "$PROD_DATABASE_URL" -c "select 1"',
    "git push origin wp/x1-gates", "gh pr create --fill", "gh release list", "gh api repos/o/r/pulls",
    "gh api repos/o/r/releases", "bash -c \"echo 'railway up'\"", "grep railway README.md",
    'git commit -m "fix $(date)"', "docker build .", "pnpm test", "terraform plan",
]
MENTIONS = [
    'git commit -m "push 3 fixes to names page"', 'git commit -m "docs: railway deploy notes"',
    'git commit -m "K8: docker push step documented"', "git push -u origin 42-fix-heartbeat",
    'echo "see railway up in RUNBOOK"', 'git commit -m "fix"', "grep -rn railway docs",
    'git commit -m "a; railway up && docker push x"', 'echo "x | railway up"',
    'git commit -m "railway up"', "git push origin v2-docs", "git push origin 2.0-prep",
    "git push origin v2-redesign", "git push origin 1.2-hotfix",
]
BODY = "X1: fix\n\nrailway up now asks; it's fine"
BODIES = [
    (f"git commit -m \"$(cat <<'EOF'\n{BODY}\nEOF\n)\"", bash),
    (f"gh pr create --title x --body \"$(cat <<'EOF'\n{BODY}\nEOF\n)\"", bash),
    (f"cat <<-EOF > notes.txt\n\t{BODY}\n\tEOF", bash),
    ("git commit -m @'\nX1: it's done; docker push is a deploy\n'@", powershell),
]
DEPLOYS = [
    "railway up --service web", "railway redeploy", "railway deploy -t postgres", "railway service redeploy",
    "railway service web redeploy", "railway deployment redeploy", "railway deployment up",
    "railway variables set FOO=bar", "railway variables --set FOO=bar", "railway variable --set=FOO=bar",
    "railway variable --set-from-stdin APP_KEY", "railway variable edit --yes", "railway config apply --yes",
    "railway postgres ha convert --service pg --replicas 2", "railway postgres ha switchover --to r1",
    "railway postgres pgbouncer configure --max-client-conn 200",
    "railway functions push", "railway service source connect --repo o/r --service web",
    "railway api 'mutation { deploymentRedeploy(id: \"x\") }'", "railway.cmd up",
    "& 'C:\\Users\\me\\AppData\\Roaming\\npm\\railway.ps1' up", "./node_modules/.bin/railway up",
    "npx @railway/cli up", "npx -y @railway/cli@latest redeploy", "pnpm dlx @railway/cli up",
    'bash -c "railway up"', "railway status && railway up", "echo x | railway up", "(railway up)",
    'echo "$(railway up)"', "pwsh -NoProfile -Command railway up", "cmd /c railway up", 'iex "railway up"',
    "sudo env FOO=1 railway up",
    "curl -X POST https://backboard.railway.app/graphql/v2 -d '{\"query\":\"mutation { serviceInstanceRedeploy }\"}'",
    "git push origin release-2026-12", "git push --tags", "git push --follow-tags origin main",
    "git push --mirror backup", "git push origin v1.2", "git push origin 1.0.0",
    "git push origin refs/tags/app-2026", "git push origin HEAD:refs/tags/x", "git -C ../app push origin v2.0.0",
    "git -c user.name=x push origin v2", "git push origin tag app-2026", "gh release create v1.0.0",
    "gh -R o/app release create v1.0.0", "gh api repos/o/r/git/refs -f ref=refs/tags/v1 -f sha=abc",
    "gh workflow run deploy.yml", "gh run rerun 123", "gh release edit v1.0.0 --draft=false",
    "gh api -X POST repos/o/r/releases -f tag_name=v1", "gh api repos/o/r/dispatches -f event_type=deploy",
    "docker push registry.example.org/app/live:latest", "docker image push registry.example.org/app/live:latest",
]
TO_MAIN = {"git push --follow-tags origin main", "git push --mirror backup"}
FORMS = [
    ("for s in web worker; do railway up -s $s; done", bash), ("if git diff --quiet; then git push --tags; fi", bash),
    ("if railway up; then echo ok; fi", bash), ("until railway up; do sleep 1; done", bash),
    ("while true; do railway up; done", bash), ("case $x in a) railway up;; esac", bash), ("! railway up", bash),
    ("[[ -n $x ]] && railway up", bash), ("xargs railway up", bash), ("xargs -n 1 railway up", bash),
    ("echo up | xargs railway", bash), ("eval railway up", bash), ("eval 'railway up'", bash),
    ("watch railway up", bash), ("watch -n 5 railway up", bash), ("exec railway up", bash), ("doas railway up", bash),
    ("nice -n 5 railway up", bash), ("ionice -c 3 railway up", bash), ("flock /tmp/app.lock railway up", bash),
    ("flock /tmp/app.lock -c 'railway up'", bash), ("timeout 30s railway up", bash), ("nohup railway up", bash),
    ("unbuffer railway up", bash), ("stdbuf -oL railway up", bash), ("su -c 'railway up' deploy", bash),
    ("fish -c 'railway up'", bash), ("script -q -c 'railway up' /dev/null", bash), ("env -S 'railway up'", bash),
    ("bash <<< 'railway up'", bash), ("pnpm railway up", bash), ("yarn railway up", bash),
    ("npm run railway up", bash), ("bun run railway up", bash), ("bash <<'EOF'\nrailway up\nEOF", bash),
    ("cat <<'EOF' | sh\nrailway up\nEOF", bash), ("cat <<EOF > notes.txt\n$(railway up)\nEOF", bash),
    ("cat <<'EOF' > notes.txt\nfine\nEOF\nrailway up", bash), ("Start-Process railway -ArgumentList up", powershell),
    ("Start-Process -FilePath railway -ArgumentList 'up','-s','web'", powershell),
    ("Start-Process -Wait railway -ArgumentList up, -s, web", powershell), ("start railway up", powershell),
    ("saps railway -ArgumentList up", powershell), ("iex -Command 'railway up'", powershell),
    ("Invoke-Expression -Command 'railway up'", powershell), ('git commit -m "$(railway up)"', powershell),
]
# The gate cannot read these well enough to rule out a hidden merge, push or deploy.
CANNOT_TELL = [
    ("pwsh -EncodedCommand cgBhAGkAbAB3AGEAeQAgAHUAcAA=", powershell, "encoded PowerShell"),
    ("powershell -enc cgBhAGkAbAB3AGEAeQAgAHUAcAA=", powershell, "encoded PowerShell"),
    ("echo 'railway up' | bash", bash, "reading commands from input"),
    ("git push origin $TAG", bash, "variable"), ("git push origin $env:TAG", powershell, "variable"),
    ("git push origin %TAG%", bash, "variable"), ("git ls-files | xargs git push origin", bash, "xargs"),
    ("git frobnicate", bash, "not a built-in git command"), ("gh m 5", bash, "not a built-in gh command"),
]
TAGS = ["git push origin 2026.12.01", "git push origin v1.2.3-rc1", "git push --repo=origin v1.2.3",
        "git push --repo origin v1.2.3", "git push origin v1.0.0+build.5"]


class Bypass(unittest.TestCase):
    """Trial F5: in bypass-permissions mode an ask never reaches the user, so it is denied."""

    def test_ask_becomes_deny(self) -> None:
        ask = {"permissionDecision": "ask", "permissionDecisionReason": "OPS GATE: x"}
        out = ops_gate._strict(ask, {"permission_mode": "bypassPermissions"})
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("bypass-permissions", out["permissionDecisionReason"])
        for mode in ("default", "acceptEdits", "plan", None):
            self.assertEqual(ops_gate._strict(ask, {"permission_mode": mode}), ask)
        self.assertEqual(ops_gate._strict(ask, None), ask)
        self.assertIsNone(ops_gate._strict(None, {"permission_mode": "bypassPermissions"}))


class Development(unittest.TestCase):
    """Deploys and platform commands run without a prompt; the freeze check still applies."""

    def test_platform_commands_run(self) -> None:
        for command in PLATFORM:
            with self.subTest(command=command):
                self.assertEqual(decision(bash(command), freeze=FROZEN), "none")

    def test_deploys_run_when_clear(self) -> None:
        for command in DEPLOYS:
            if command in TO_MAIN:
                continue
            with self.subTest(command=command):
                self.assertEqual(decision(bash(command)), "none")
                self.assertEqual(len(FREEZE_CALLS), 1, "the freeze check runs once per deploy")

    def test_deploys_denied_while_frozen(self) -> None:
        for command in DEPLOYS:
            with self.subTest(command=command):
                d, reason = decide(powershell(command), freeze=FROZEN)
                self.assertEqual(d, "deny")
                self.assertRegex(reason, "^DEPLOY FREEZE")
                self.assertIn("FROZEN: release window", reason)

    def test_forms_denied_while_frozen_run_when_clear(self) -> None:
        for command, shell in FORMS:
            with self.subTest(command=command):
                self.assertEqual(decision(shell(command), freeze=FROZEN), "deny")
                self.assertEqual(decision(shell(command)), "none")

    def test_tag_pushes_are_deploys(self) -> None:
        for command in TAGS:
            with self.subTest(command=command):
                self.assertEqual(decision(bash(command), freeze=FROZEN), "deny")

    def test_pushes_to_main_are_denied_by_the_merge_guard(self) -> None:
        for command in TO_MAIN:
            with self.subTest(command=command):
                d, reason = decide(bash(command))
                self.assertEqual(d, "deny")
                self.assertRegex(reason, "^MERGE GUARD")

    def test_freeze_check_that_cannot_decide_denies(self) -> None:
        for status in [(None, "FROZEN (cannot check): did not run"), (2, "no answer"), (127, "x")]:
            with self.subTest(status=status):
                self.assertEqual(decision(bash("railway up"), freeze=status), "deny")

    def test_no_freeze_check_configured(self) -> None:
        self.assertEqual(decision(bash("railway up"), freeze=FROZEN, deploy={"freeze_check": DROP}), "none")

    def test_non_deploys_do_not_run_the_check(self) -> None:
        self.assertEqual(decision(bash("railway restart"), freeze=FROZEN), "none")
        self.assertEqual(FREEZE_CALLS, [])


class Observe(unittest.TestCase):
    """After close-out: nothing deploys, merges or changes a platform."""

    def test_platform_commands_and_deploys_denied(self) -> None:
        for command in PLATFORM + DEPLOYS + ["gh pr merge 5 --squash"]:
            with self.subTest(command=command):
                d, reason = decide(bash(command), access=OBSERVE)
                self.assertEqual(d, "deny")
                self.assertRegex(reason, "^OBSERVE PHASE")
                self.assertEqual(FREEZE_CALLS, [], "denied before the freeze check or gh is called")

    def test_forms_denied(self) -> None:
        for command, shell in FORMS:
            with self.subTest(command=command):
                self.assertEqual(decision(shell(command), access=OBSERVE), "deny")

    def test_reading_and_local_work_stay_open(self) -> None:
        for command in HARMLESS + ["railway logs --service web", "git push -u origin wp/x1"]:
            with self.subTest(command=command):
                self.assertEqual(decision(bash(command), access=OBSERVE), "none")


class BothPhases(unittest.TestCase):
    PHASES = ({"phase": "development"}, OBSERVE)

    def test_harmless(self) -> None:
        for access in self.PHASES:
            for command in HARMLESS:
                with self.subTest(command=command, phase=access["phase"]):
                    self.assertEqual(decision(bash(command), freeze=FROZEN, access=access), "none")

    def test_mentions_in_both_shells(self) -> None:
        for command in MENTIONS:
            for shell in (bash, powershell):
                with self.subTest(command=command, shell=shell.__name__):
                    self.assertEqual(decision(shell(command), freeze=FROZEN, access=OBSERVE), "none")

    def test_heredoc_and_here_string_bodies_are_data(self) -> None:
        for command, shell in BODIES:
            with self.subTest(command=command):
                self.assertEqual(decision(shell(command), freeze=FROZEN, access=OBSERVE), "none")

    def test_cannot_tell_asks(self) -> None:
        for access in self.PHASES:
            for command, shell, why in CANNOT_TELL:
                with self.subTest(command=command, phase=access["phase"]):
                    d, reason = decide(shell(command), access=access)
                    self.assertEqual(d, "ask")
                    self.assertIn(why, reason)

    def test_ask_shows_the_description(self) -> None:
        _, reason = decide(bash("git frobnicate", description="Tidy refs"))
        self.assertRegex(reason, r"OPS GATE.*not a built-in git command.*Tidy refs")

    def test_other_tools(self) -> None:
        self.assertEqual(decision({"tool_name": "Read", "tool_input": {"file_path": "railway up"}}), "none")


class Secrets(unittest.TestCase):
    DENIED = [
        ("printenv", bash), ("printenv DATABASE_URL", bash), ("env", bash), ("env -0", bash),
        ("env FOO=1", bash), ("set", bash), ("export", bash), ("export -p", bash), ("declare -p", bash),
        ("declare -x", bash), ("cat .env", bash), ("cat ./config/.env.local", bash), ("type .env", powershell),
        ("Get-Content .env", powershell), ("gc .env.production", powershell), ("grep KEY .env", bash),
        ("head -n 3 .env", bash), ("Get-ChildItem env:", powershell), ("gci Env:\\", powershell),
        ("ls env:", powershell), ("dir env:", powershell), ("Get-Item env:DATABASE_URL", powershell),
        ("[Environment]::GetEnvironmentVariables()", powershell), ('bash -c "printenv"', bash),
        ("sudo cat .env", bash), ("git status && env", bash), ("railway variables", bash),
        ("railway vars ls -s web", bash), ("railway variables list", bash),
    ]
    ALLOWED = [
        "cat .env.example", "cp .env.example .env", "set -euo pipefail", "export FOO=1",
        "env FOO=1 pnpm test", "echo set", "ls -la", "git diff .env.example", "grep -r env src/",
        "echo $env:PATH", "declare -a list", "cat README.md", "Get-Content docs/env.md",
        "infisical run -- pnpm db:migrate",
    ]

    def test_denied_in_both_phases(self) -> None:
        for access in ({"phase": "development"}, OBSERVE):
            for command, shell in self.DENIED:
                with self.subTest(command=command, phase=access["phase"]):
                    d, reason = decide(shell(command), access=access)
                    self.assertEqual(d, "deny")
                    self.assertRegex(reason, "^SECRETS: ")

    def test_allowed(self) -> None:
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertEqual(decision(bash(command)), "none")
                self.assertEqual(decision(powershell(command)), "none")


class ProfileStates(unittest.TestCase):
    def test_no_profile_turns_every_opinion_into_ask(self) -> None:
        for command in ["railway up", "railway restart", "printenv", "gh pr merge 5", "git push origin main",
                        "git push", "docker push x/y", "mywrap railway up"]:
            with self.subTest(command=command):
                d, reason = decide(bash(command), state="absent", freeze=FROZEN)
                self.assertEqual(d, "ask")
                self.assertIn("no athena-orchestrator profile", reason)
                self.assertEqual(FREEZE_CALLS, [])

    def test_no_profile_leaves_harmless_commands_alone(self) -> None:
        for command in ["ls", "pnpm test", "cd ..", "git status", "railway logs"]:
            with self.subTest(command=command):
                self.assertEqual(decision(bash(command), state="absent"), "none")

    def test_broken_profile_asks_for_everything(self) -> None:
        d, reason = decide(bash("ls"), state="invalid")
        self.assertEqual(d, "ask")
        self.assertIn("profile is broken (broken for the test)", reason)


class FreezeStatus(unittest.TestCase):
    """The real freeze check: tiny Python commands, never a deploy."""

    def run_check(self, code: str, timeout: Optional[int] = None) -> tuple:
        with patched(FREEZE_TIMEOUT_S=timeout or ops_gate.FREEZE_TIMEOUT_S):
            return ops_gate.freeze_status(".", f"'{PY}' -c \"{code}\"")

    def test_exit_codes(self) -> None:
        self.assertEqual(self.run_check("print('CLEAR')")[0], 0)
        status = self.run_check("import sys; print('FROZEN: window'); sys.exit(1)")
        self.assertEqual(status, (1, "FROZEN: window"))
        self.assertEqual(self.run_check("import sys; sys.exit(2)")[0], 2)

    def test_not_configured(self) -> None:
        self.assertEqual(ops_gate.freeze_status(".", None), (0, ops_gate.NO_CHECK))

    def test_missing_program(self) -> None:
        code, report = ops_gate.freeze_status(".", "athena-no-such-freeze-binary")
        self.assertIsNone(code)
        self.assertIn("did not run", report)

    def test_timeout_keeps_partial_output(self) -> None:
        code, report = self.run_check("import time; print('partial line', flush=True); time.sleep(10)", timeout=2)
        self.assertIsNone(code)
        self.assertRegex(report, r"^FROZEN \(cannot check\): the freeze check timed out after 2 s")
        self.assertIn("partial line", report)


class Robustness(unittest.TestCase):
    def test_null_tool_input(self) -> None:
        self.assertEqual(decision({"tool_name": "Bash", "tool_input": None}), "none")

    def test_crash_asks(self) -> None:
        out = io.StringIO()
        real = sys.stdin
        sys.stdin = io.StringIO("[]")  # not an object: _decide raises
        try:
            with redirect_stdout(out):
                ops_gate.main()
        finally:
            sys.stdin = real
        result = json.loads(out.getvalue())["hookSpecificOutput"]
        self.assertEqual(result["permissionDecision"], "ask")
        self.assertIn("OPS GATE crashed", result["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
