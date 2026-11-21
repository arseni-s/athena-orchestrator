"""Merge guard (in ops_gate): `gh pr merge` needs green checks with the required check on the
PR head; no direct pushes to a main branch; aliases and extensions. `gh` and `git` are fakes:
no network, no GitHub.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from typing import Any, Optional

from gatelib import SCRIPTS, Fakes, TempDirs, bash, loaded, make_repo, ops_gate, powershell, raw, toml
from test_ops_gate import patched

MERGE = "gh pr merge 5 --squash --delete-branch"
JSON = ["--json", "number,headRefOid,statusCheckRollup"]


def run(name: str, conclusion: str, status: str = "COMPLETED") -> dict:
    return {"__typename": "CheckRun", "name": name, "status": status,
            "conclusion": conclusion if status == "COMPLETED" else "", "workflowName": "ci"}


def ctx(context: str, state: str) -> dict:
    return {"__typename": "StatusContext", "context": context, "state": state}


GREEN = [run("ci", "SUCCESS"), run("optional", "SKIPPED"), run("info", "NEUTRAL"), ctx("docs", "SUCCESS")]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempDirs()
        cls.work = cls.tmp.make("athena-merge-guard-")
        cls.fakes = Fakes(cls.work)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def view(self, rollup: list) -> tuple:
        return self.fakes.make([{"stdout": json.dumps(
            {"number": 5, "headRefOid": "0123456789abcdef0123", "statusCheckRollup": rollup})}])

    def decide(self, event: dict, gh: Optional[list] = None, git: Optional[list] = None,
               gh_timeout: Optional[int] = None, **changes: Any) -> tuple[str, str]:
        """Runs `_decide` with fakes."""
        attrs: dict[str, Any] = {"GH_CMD": gh or ["gh-must-not-be-called"],
                                 "GIT_CMD": git or ["git-must-not-be-called"],
                                 "GH_TIMEOUT_S": gh_timeout or ops_gate.GH_TIMEOUT_S}
        with patched(**attrs):
            out = ops_gate._decide({**event, "cwd": self.work},
                                   loaded("ok", root=self.work, **changes)) or {}
        return out.get("permissionDecision", "none"), out.get("permissionDecisionReason", "")


class GhPrMerge(Base):
    def test_green_has_no_opinion(self) -> None:
        gh, calls = self.view(GREEN)
        self.assertEqual(self.decide(bash(MERGE), gh=gh)[0], "none")
        self.assertEqual(calls(), [["pr", "view", "5", *JSON]])

    DENIED = [
        ("red ci", [run("ci", "FAILURE"), ctx("docs", "SUCCESS")], r"failing checks: ci \(failure\)"),
        ("another check red", [run("ci", "SUCCESS"), run("lint", "CANCELLED")], r"failing checks: lint \(cancelled\)"),
        ("timed out check", [run("ci", "SUCCESS"), run("e2e", "TIMED_OUT")], r"e2e \(timed_out\)"),
        ("status context error", [run("ci", "SUCCESS"), ctx("deploy", "ERROR")], r"deploy \(error\)"),
        ("ci pending", [run("ci", "", "IN_PROGRESS")], r"still running: ci \(in_progress\)"),
        ("ci queued", [run("ci", "", "QUEUED")], r"still running: ci \(queued\)"),
        ("status context pending", [run("ci", "SUCCESS"), ctx("docs", "PENDING")], r"still running: docs \(pending\)"),
        ("no checks at all", [], r"no successful `ci` check \(no check named ci"),
        ("no ci check", [run("lint", "SUCCESS")], r"no successful `ci` check \(no check named ci"),
        ("ci skipped, not succeeded", [run("ci", "SKIPPED")], r"no successful `ci` check\."),
        ("unknown check type", [run("ci", "SUCCESS"), {"__typename": "Mystery", "name": "x"}], "unknown check type"),
    ]

    def test_denied_naming_checks(self) -> None:
        for label, rollup, why in self.DENIED:
            with self.subTest(label):
                d, reason = self.decide(bash("gh pr merge 5 --squash"), gh=self.view(rollup)[0])
                self.assertEqual(d, "deny")
                self.assertRegex(reason, "^MERGE GUARD")
                self.assertRegex(reason, why)
                self.assertRegex(reason, r"PR #5 \(head 0123456789ab\)")
                self.assertIn("Wait for CI to finish, or fix the failure and push", reason)

    def test_required_check_comes_from_the_profile(self) -> None:
        d, reason = self.decide(bash(MERGE), gh=self.view(GREEN)[0], merge={"required_check": "build"})
        self.assertEqual(d, "deny")
        self.assertIn("no successful `build` check (no check named build", reason)
        gh = self.view([run("Build", "SUCCESS")])[0]
        self.assertEqual(self.decide(bash(MERGE), gh=gh, merge={"required_check": "build"})[0], "none")

    def test_broken_gh_fails_closed(self) -> None:
        cases = [
            ("gh missing", {"gh": ["athena-no-such-gh-binary"]}, "did not run"),
            ("not logged in", {"gh": self.fakes.make([{"exit": 4, "stderr": "please run:  gh auth login"}])[0]}, "exited 4"),
            ("offline", {"gh": self.fakes.make([{"exit": 1, "stderr": "error connecting to api.github.com"}])[0]}, "error connecting"),
            ("times out", {"gh": self.fakes.make([{"sleep": 5}])[0], "gh_timeout": 1}, "timed out after 1 s"),
            ("not JSON", {"gh": self.fakes.make([{"stdout": "<html>"}])[0]}, "cannot read the PR's checks"),
            ("rollup missing", {"gh": self.fakes.make([{"stdout": '{"number": 5}'}])[0]}, "cannot read the PR's checks"),
            ("rollup not a list", {"gh": self.fakes.make([{"stdout": '{"statusCheckRollup": {"a": 1}}'}])[0]}, "cannot read"),
        ]
        for label, opts, why in cases:
            with self.subTest(label):
                d, reason = self.decide(bash("gh pr merge 5"), **opts)
                self.assertEqual(d, "deny")
                self.assertIn(why, reason)

    def test_selectors_passed_as_given(self) -> None:
        gh, calls = self.view(GREEN)
        for command in ["gh pr merge", "gh pr merge wp/x1-gates --squash", "gh pr merge https://github.com/o/app/pull/12",
                        "gh pr merge 7 -R o/app -b body", "gh -R o/app pr merge 8"]:
            self.assertEqual(self.decide(bash(command), gh=gh)[0], "none")
        self.assertEqual(calls(), [["pr", "view", *JSON], ["pr", "view", "wp/x1-gates", *JSON],
                                   ["pr", "view", "https://github.com/o/app/pull/12", *JSON],
                                   ["pr", "view", "7", "-R", "o/app", *JSON], ["pr", "view", "8", "-R", "o/app", *JSON]])

    OUTRIGHT = [
        ("gh pr merge 5 --auto --squash", "--auto"), ("gh pr merge --auto", "auto-merge"),
        ("echo 5 | xargs gh pr merge", "through xargs"), ("gh pr merge $PR", "variable"),
        ("cd ../app-wp-x2 && gh pr merge --squash", "directory change"),
        ('gh api graphql -f query="mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }"', "GraphQL"),
        ("gh api repos/{owner}/{repo}/pulls/5/merge -f merge_method=squash", "cannot check"),
        ("gh api -X PUT repos/o/r/pulls/$N/merge", "cannot check"),
        ("curl -X PUT -H 'Authorization: token x' https://api.github.com/repos/o/r/pulls/5/merge", "cannot check"),
    ]

    def test_denied_without_calling_gh(self) -> None:
        for command, why in self.OUTRIGHT:
            with self.subTest(command=command):
                gh, calls = self.view(GREEN)
                d, reason = self.decide(bash(command), gh=gh)
                self.assertEqual(d, "deny")
                self.assertRegex(reason, why.replace("$", r"\$") if why != "cannot check" else "cannot check|variable")
                self.assertEqual(calls(), [])

    def test_api_merge_endpoints_are_checked(self) -> None:
        gh, calls = self.view([run("ci", "FAILURE")])
        self.assertEqual(self.decide(bash("gh api -X PUT repos/o/app/pulls/5/merge"), gh=gh)[0], "deny")
        self.assertEqual(calls(), [["pr", "view", "5", "-R", "o/app", *JSON]])
        gh = self.view(GREEN)[0]
        self.assertEqual(self.decide(bash("gh api --method PUT /repos/o/r/pulls/6/merge -f merge_method=squash"), gh=gh)[0], "none")

    def test_untouched(self) -> None:
        for command in ["gh pr merge 5 --disable-auto", "gh api repos/o/r/pulls/5/merge", "gh pr view 5 --json statusCheckRollup",
                        "gh pr checks 5", 'git commit -m "gh pr merge 5 --auto"']:
            with self.subTest(command=command):
                self.assertEqual(self.decide(bash(command))[0], "none")

    FORMS = [('bash -c "gh pr merge 5 --squash"', bash), ("sh -c 'gh pr merge 5'", bash), ("sudo gh pr merge 5", bash),
             ("env GH_REPO=o/r gh pr merge 5", bash), ("timeout 60 gh pr merge 5", bash), ("npx gh pr merge 5", bash),
             ("if true; then gh pr merge 5; fi", bash), ("git fetch && gh pr merge 5 --squash", bash),
             ('echo "$(gh pr merge 5)"', bash), ("eval 'gh pr merge 5'", bash), ("bash <<'EOF'\ngh pr merge 5\nEOF", bash),
             ("gh.exe pr merge 5", powershell), ("& 'C:\\Program Files\\GitHub CLI\\gh.exe' pr merge 5", powershell),
             ("pwsh -NoProfile -Command gh pr merge 5", powershell), ("cmd /c gh pr merge 5", powershell),
             ("iex 'gh pr merge 5'", powershell), ("Start-Process gh -ArgumentList pr,merge,5", powershell)]

    def test_forms_denied_when_red_none_when_green(self) -> None:
        for command, shell in self.FORMS:
            with self.subTest(command=command):
                red, calls = self.view([run("ci", "FAILURE")])
                self.assertEqual(self.decide(shell(command), gh=red)[0], "deny")
                self.assertEqual([c[:3] for c in calls()], [["pr", "view", "5"]])
                self.assertEqual(self.decide(shell(command), gh=self.view(GREEN)[0])[0], "none")


class MergeAndDeploy(Base):
    def test_green_merge_passes_in_both_shells(self) -> None:
        for shell in (bash, powershell):
            self.assertEqual(self.decide(shell(MERGE), gh=self.view(GREEN)[0])[0], "none")

    def test_red_or_unreadable_pr_denied(self) -> None:
        for gh in (self.view([run("ci", "FAILURE")])[0], self.fakes.make([{"exit": 1, "stderr": "offline"}])[0]):
            d, reason = self.decide(bash(MERGE), gh=gh)
            self.assertEqual(d, "deny")
            self.assertRegex(reason, "^MERGE GUARD: a main branch takes no direct pushes")

    def test_merge_and_release_in_one_line(self) -> None:
        command = "gh pr merge 5 --squash && gh release create v1.2.3"
        self.assertEqual(self.decide(bash(command), gh=self.view(GREEN)[0])[0], "none")
        self.assertEqual(self.decide(bash(command), gh=self.view([run("ci", "FAILURE")])[0])[0], "deny")


class GitPush(Base):
    TO_MAIN = ["git push origin master", "git push origin main", "git push -u origin master", "git push origin HEAD:master",
               "git push origin HEAD:refs/heads/main", "git push origin wp/x1:master", "git push origin +master",
               "git push --force origin master", "git push -f origin main", "git push --force-with-lease origin master",
               "git push origin refs/heads/master", "git push origin :master", "git push origin --delete master",
               "git push backup master", "git push --all", "git push --all origin", "git push --branches origin",
               "git push --mirror backup", "git -C ../app push origin master", "git push origin wp/a master",
               "git push --repo=origin master", "git.exe push origin master", 'bash -c "git push origin master"',
               "sudo git push origin master", "pwsh -Command git push origin master", "cmd /c git push origin master",
               "if true; then git push origin master; fi", "git add . && git commit -m x && git push origin master"]
    ALLOWED = ["git push -u origin wp/x1-gates", "git push origin plan/X1", "git push origin wp/x:wp/x",
               "git push origin master:wp/backup-of-master", "git push origin --delete wp/old",
               "git push origin mastery main-docs", "git push --force-with-lease origin wp/x",
               "git -C C:/DEV/app-wp-X1 push -u origin wp/X1-gates"]

    def test_to_main_denied_without_calling_git(self) -> None:
        for command in self.TO_MAIN:
            for shell in (bash, powershell):
                with self.subTest(command=command, shell=shell.__name__):
                    d, reason = self.decide(shell(command))
                    self.assertEqual(d, "deny")
                    self.assertRegex(reason, r"(?s)^MERGE GUARD.*(main branch|every branch)")

    def test_profile_main_branch_is_protected(self) -> None:
        trunk = {"main": "trunk"}
        self.assertEqual(self.decide(bash("git push origin trunk"), repo=trunk)[0], "deny")
        self.assertEqual(self.decide(bash("git push origin main"), repo=trunk)[0], "deny")
        self.assertEqual(self.decide(bash("git push origin trunk"))[0], "none")

    def test_allowed(self) -> None:
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertEqual(self.decide(bash(command))[0], "none")

    def test_tags_only_is_a_deploy_not_a_push_to_main(self) -> None:
        self.assertEqual(self.decide(bash("git push --tags"))[0], "none")

    def branch(self, name: str, push: Optional[dict] = None) -> tuple:
        return self.fakes.make([{"match": "@{push}", **(push or {"exit": 128, "stderr": "fatal: no upstream"})},
                                {"match": "HEAD", "stdout": f"{name}\n"}])

    def test_bare_push(self) -> None:
        self.assertEqual(self.decide(bash("git push"), git=self.branch("master")[0])[0], "deny")
        self.assertEqual(self.decide(powershell("git push --force"), git=self.branch("main")[0])[0], "deny")
        self.assertEqual(self.decide(bash("git push origin"), git=self.branch("master")[0])[0], "deny")
        self.assertEqual(self.decide(bash("git push origin HEAD"), git=self.branch("main")[0])[0], "deny")
        self.assertEqual(self.decide(bash("git push -u origin HEAD"), git=self.branch("wp/x")[0])[0], "none")
        self.assertEqual(self.decide(bash("git push"), git=self.branch("wp/x", {"stdout": "origin/wp/x\n"})[0])[0], "none")
        d, reason = self.decide(bash("git push"), git=self.branch("wp/x", {"stdout": "origin/master\n"})[0])
        self.assertEqual(d, "deny")
        self.assertIn("pushes `wp/x` to `origin/master`", reason)

    def test_reads_the_branch_in_the_dash_c_directory(self) -> None:
        git, calls = self.branch("wp/x")
        self.decide(bash("git -C ../app-wp-X2 push"), git=git)
        self.assertEqual(calls()[0], ["-C", "../app-wp-X2", "rev-parse", "--abbrev-ref", "HEAD"])

    def test_unreadable_branch_denied(self) -> None:
        for label, git, why in [("git fails", self.fakes.make([{"exit": 128, "stderr": "fatal: not a git repository"}])[0],
                                 "not a git repository"), ("git missing", ["athena-no-such-git-binary"], "did not run")]:
            with self.subTest(label):
                d, reason = self.decide(bash("git push"), git=git)
                self.assertEqual(d, "deny")
                self.assertIn(why, reason)

    def test_bare_push_after_cd_denied(self) -> None:
        git, calls = self.branch("wp/x")
        self.assertEqual(self.decide(bash("cd ../app && git push"), git=git)[0], "deny")
        self.assertEqual(self.decide(powershell("Set-Location ..\\app; git push"), git=git)[0], "deny")
        self.assertEqual(calls(), [])
        self.assertEqual(self.decide(bash("cd ../app-wp-X2 && git push -u origin wp/X2-rules"))[0], "none")


class Aliases(Base):
    DENIED = ['gh alias set m "pr merge"', "gh alias import aliases.yml", "gh extension install x/y", "gh ext install x/y",
              "gh extension exec merge-it 5", "gh extension upgrade --all", "git -c alias.x=push x origin HEAD:master",
              "git -C ../app -c Alias.x=push x", "git config alias.p push", "git config --global alias.p push",
              "git config set alias.p push", "git config --add alias.p push"]
    ASKED = ["gh m 5", "git x origin HEAD:master", "git frobnicate", "git PUSH origin master"]
    UNTOUCHED = ["gh alias list", "gh extension list", "git config --get alias.p", "git config alias.p", "git config --list",
                 "git status", "git log --oneline", "git worktree add ../app-wp-X2 -b wp/X2-rules", "git push -u origin wp/x",
                 "gh pr view 5", "gh pr checks 5", "gh run list", "gh api repos/o/r/pulls/5", "gh secret list",
                 "git --version", "gh --version"]

    def test_all(self) -> None:
        for shell in (bash, powershell):
            for command in self.DENIED:
                with self.subTest(command=command, shell=shell.__name__):
                    d, reason = self.decide(shell(command))
                    self.assertEqual(d, "deny")
                    self.assertRegex(reason, r"(?s)^MERGE GUARD.*alias or runs a gh extension")
            for command in self.ASKED:
                with self.subTest(command=command, shell=shell.__name__):
                    d, reason = self.decide(shell(command))
                    self.assertEqual(d, "ask")
                    self.assertRegex(reason, r"not a built-in (gh|git) command: it may be an alias or extension")
            for command in self.UNTOUCHED:
                with self.subTest(command=command, shell=shell.__name__):
                    self.assertEqual(self.decide(shell(command))[0], "none")


class EndToEnd(unittest.TestCase):
    """Through the real entry point, with real git in a temp repo that has a profile."""

    def test_bare_push_on_main_and_on_a_branch(self) -> None:
        tmp = TempDirs()
        try:
            repo = make_repo(os.path.join(tmp.make(), "app"), toml(raw()))

            def permission(command: str) -> str:
                event = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": repo})
                out = subprocess.run([sys.executable, "-B", str(SCRIPTS / "ops_gate.py")], input=event,
                                     capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": repo})
                self.assertEqual(out.returncode, 0, out.stderr)
                return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] if out.stdout.strip() else "none"
            self.assertEqual(permission("git push"), "deny")
            subprocess.run(["git", "-C", repo, "checkout", "-q", "-b", "wp/x"], check=True)
            self.assertEqual(permission("git push"), "none")
            self.assertEqual(permission("git push origin main"), "deny")
        finally:
            tmp.cleanup()


SHA = "0123456789abcdef0123456789abcdef01234567"
RUNS = f"repos/{{owner}}/{{repo}}/actions/runs?head_sha={SHA}&per_page=100"
STATUS = f"repos/{{owner}}/{{repo}}/commits/{SHA}/status"


class FineGrainedToken(Base):
    """A fine-grained token cannot read check runs; the guard rebuilds them from Actions jobs."""

    def gh(self, jobs: list[dict], statuses: Optional[list] = None, runs_exit: int = 0) -> tuple:
        return self.fakes.make([
            {"match": "number,headRefOid,statusCheckRollup", "exit": 1,
             "stderr": "GraphQL: Resource not accessible by personal access token (repository.pullRequest)\n"},
            {"match": "number,headRefOid", "stdout": json.dumps({"number": 5, "headRefOid": SHA})},
            {"match": RUNS, "exit": runs_exit, "stdout": json.dumps({"workflow_runs": [{"id": 77}]}),
             "stderr": "HTTP 403\n" if runs_exit else ""},
            {"match": "repos/{owner}/{repo}/actions/runs/77/jobs?per_page=100", "stdout": json.dumps({"jobs": jobs})},
            {"match": STATUS, "stdout": json.dumps({"statuses": statuses or []})},
        ])

    def test_green_jobs_allow_the_merge(self) -> None:
        gh, calls = self.gh([{"name": "ci", "status": "completed", "conclusion": "success"},
                             {"name": "lint", "status": "completed", "conclusion": "skipped"}],
                            [{"context": "docs", "state": "success"}])
        self.assertEqual(self.decide(bash(MERGE), gh=gh)[0], "none")
        self.assertEqual([c[:2] for c in calls()], [["pr", "view"], ["pr", "view"], ["api", RUNS],
                                                   ["api", "repos/{owner}/{repo}/actions/runs/77/jobs?per_page=100"],
                                                   ["api", STATUS]])

    def test_red_or_running_jobs_deny(self) -> None:
        for label, jobs, why in [
            ("red", [{"name": "ci", "status": "completed", "conclusion": "failure"}], r"failing checks: ci \(failure\)"),
            ("running", [{"name": "ci", "status": "in_progress", "conclusion": None}], r"still running: ci"),
            ("no ci job", [{"name": "lint", "status": "completed", "conclusion": "success"}], r"no check named ci"),
        ]:
            with self.subTest(label):
                d, reason = self.decide(bash(MERGE), gh=self.gh(jobs)[0])
                self.assertEqual(d, "deny")
                self.assertRegex(reason, why)

    def test_a_failing_status_denies(self) -> None:
        gh = self.gh([{"name": "ci", "status": "completed", "conclusion": "success"}],
                     [{"context": "deploy", "state": "failure"}])[0]
        self.assertRegex(self.decide(bash(MERGE), gh=gh)[1], r"failing checks: deploy \(failure\)")

    def test_actions_unreadable_fails_closed(self) -> None:
        d, reason = self.decide(bash(MERGE), gh=self.gh([], runs_exit=1)[0])
        self.assertEqual(d, "deny")
        self.assertIn("then from GitHub Actions: gh api actions/runs exited 1", reason)


if __name__ == "__main__":
    unittest.main()
