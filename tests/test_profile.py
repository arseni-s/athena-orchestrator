"""The profile loader: checking, defaults, path patterns, the command line."""
from __future__ import annotations

import io
import os
import shutil
import unittest
from contextlib import redirect_stdout

from gatelib import DROP, ROOT, TempDirs, athena_profile, git, make_repo, raw, toml

SAMPLE = ROOT / "examples" / "sample-profile" / ".claude" / "orchestration" / "project.toml"


def problems(data: dict) -> list[str]:
    return athena_profile.check(data)[1]


class Check(unittest.TestCase):
    def test_base_is_valid_with_defaults(self) -> None:
        data, found = athena_profile.check(raw())
        self.assertEqual(found, [])
        self.assertEqual(data["plan"]["plan"], "docs/IMPLEMENTATION_PLAN.md")
        self.assertEqual(data["repo"]["setup"], [])
        self.assertEqual(data["paths"]["ux"], [])
        self.assertEqual(data["deploy"], {"dev": "the development environment", "prod": "the production environment"})

    def test_required(self) -> None:
        cases = {
            "schema": raw(schema=None),
            "project": raw(project={"summary": ""}),
            "deploy.dev": raw(deploy={"dev": DROP}),
            "rubric": raw(rubric=None),
            "deploy": raw(deploy={"prod": ""}),
            "merge": raw(merge={"required_check": ""}),
            "repo": raw(repo=None),
            "repo.gates": raw(repo={"gates": []}),
            "repo.main": raw(repo={"main": DROP}),
            "docs": raw(docs=None),
            "docs.code": raw(docs={"code": []}),
        }
        for name, data in cases.items():
            with self.subTest(missing=name):
                found = problems(data)
                self.assertTrue(any(name in p for p in found), found)

    def test_types_and_values(self) -> None:
        cases = {
            "schema": raw(schema=2),
            "conditions": raw(rubric={"conditions": "restart"}),
            "panel.full": raw(panel={"full": "K1"}),
            "paths.ops": raw(paths={"ops": "scripts/"}),
            "gates": raw(repo={"gates": "pytest"}),
            "project is not a table": raw(project="Sample"),
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                self.assertNotEqual(problems(data), [])

    def test_unknown_settings_are_errors(self) -> None:
        cases = {
            "schedule": raw(schedule={"freeze": "2027-01-01"}),
            "lanes": raw(lanes=[{"id": "A"}]),
            "access": raw(access={"phase": "development"}),
            "deploy.test": raw(deploy={"test": "the old name for deploy.dev"}),
            "deploy.freeze_check": raw(deploy={"freeze_check": "scripts/freeze"}),
            "plan.human_lane": raw(plan={"human_lane": "You"}),
            "deploy.freeze_date": raw(deploy={"freeze_date": "2027-01-01"}),
        }
        for name, data in cases.items():
            with self.subTest(setting=name):
                self.assertIn(f"`{name}` is not a profile setting", problems(data))

    def test_removed_settings_are_errors(self) -> None:
        """The access phases and the freeze check were removed on 19 Nov 2026 (MODEL.md 12)."""
        found = problems(raw(access={"phase": "observe"}))
        self.assertIn("`access` is not a profile setting", found)


class Patterns(unittest.TestCase):
    def test_matches(self) -> None:
        yes = [("db/", "db/migrations/001.sql"), ("Dockerfile", "Dockerfile"),
               ("railway.*", "railway.json"), ("docs/**/*.md", "docs/a.md"),
               ("docs/**/*.md", "docs/features/x/y.md"), ("packages/*/README.md", "packages/env/README.md"),
               (".claude/", ".claude\\settings.json")]
        no = [("db/", "dbx/a.sql"), ("db/", "src/db/a.sql"), ("Dockerfile", "app/Dockerfile"),
              ("railway.*", "deploy/railway.json"), ("docs/**/*.md", "docs/a.txt"),
              ("packages/*/README.md", "packages/a/b/README.md"), ("README.md", "docs/README.md")]
        for pattern, path in yes:
            with self.subTest(pattern=pattern, path=path):
                self.assertTrue(athena_profile.matches(pattern, path))
        for pattern, path in no:
            with self.subTest(pattern=pattern, path=path):
                self.assertFalse(athena_profile.matches(pattern, path))


class Load(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempDirs()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_states(self) -> None:
        parent = self.tmp.make()
        absent = make_repo(os.path.join(parent, "absent"))
        self.assertEqual(athena_profile.load(absent).state, "absent")
        broken = make_repo(os.path.join(parent, "broken"), "schema = 1\n[project\n")
        self.assertEqual(athena_profile.load(broken).state, "invalid")
        incomplete = make_repo(os.path.join(parent, "incomplete"), "schema = 1\n")
        self.assertIn("project", athena_profile.load(incomplete).problem)
        good = make_repo(os.path.join(parent, "app"), toml(raw()))
        sub = os.path.join(good, "apps", "web")
        os.makedirs(sub)
        result = athena_profile.load(sub)  # found from a subfolder of the repo
        self.assertEqual((result.state, os.path.normcase(result.root)), ("ok", os.path.normcase(good)))

    def test_a_worktree_reads_its_own_copy(self) -> None:
        parent = self.tmp.make()
        main = make_repo(os.path.join(parent, "app"), toml(raw()))
        wt = os.path.join(parent, "app-wp-x1")
        git(main, "worktree", "add", "-q", wt, "-b", "wp/x1")
        result = athena_profile.load(wt)
        self.assertEqual((result.state, os.path.normcase(result.root)), ("ok", os.path.normcase(wt)))

    def test_sample_profile_is_valid(self) -> None:
        repo = make_repo(os.path.join(self.tmp.make(), "harbormaster"))
        os.makedirs(os.path.join(repo, ".claude", "orchestration"))
        shutil.copy(SAMPLE, os.path.join(repo, ".claude", "orchestration", "project.toml"))
        result = athena_profile.load(repo)
        self.assertEqual(result.state, "ok", result.problem)

    def test_command_line(self) -> None:
        parent = self.tmp.make()
        good = make_repo(os.path.join(parent, "app"), toml(raw()))
        cases = [(good, 0, "profile ok: Sample (main branch: main"),
                 (make_repo(os.path.join(parent, "none")), 2, "no profile"),
                 (make_repo(os.path.join(parent, "bad"), "schema = 1\n"), 1, "invalid profile")]
        for repo, code, text in cases:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(athena_profile.main(["check", repo]), code)
            self.assertIn(text, out.getvalue())


if __name__ == "__main__":
    unittest.main()
