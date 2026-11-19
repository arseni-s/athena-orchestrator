"""Templates: listed, their placeholders documented, and consistent with the skill and the profile schema."""
from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

from gatelib import athena_profile

PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "orchestrator"
TEMPLATES = PLUGIN / "templates"
README = (TEMPLATES / "README.md").read_text(encoding="utf-8")
SKILL = (PLUGIN / "skills" / "orchestrate" / "SKILL.md").read_text(encoding="utf-8")
SKILL_FLAT = re.sub(r"\s+", " ", SKILL)
# `{{name}}`, but not GitHub's `${{ expression }}`.
PLACEHOLDER = re.compile(r"(?<!\$)\{\{([a-z_]+)\}\}")


def text(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def section(markdown: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", markdown, re.MULTILINE | re.DOTALL)
    if not m:
        raise AssertionError(f"no section {heading!r}")
    return m.group(1)


class Listing(unittest.TestCase):
    def test_every_template_is_listed_and_exists(self) -> None:
        table = section(README, "Templates") if "## Templates" in README else README.split("## Placeholders")[0]
        listed = set(re.findall(r"^\| `([^`]+)` \|", table, re.MULTILINE))
        present = {p.name for p in TEMPLATES.iterdir() if p.is_file() and p.name != "README.md"}
        self.assertEqual(listed, present)

    def test_no_file_named_claude_md(self) -> None:
        # Claude Code would load it as memory for anyone working in the plugin.
        self.assertEqual([p for p in PLUGIN.rglob("CLAUDE.md")], [])


class Placeholders(unittest.TestCase):
    def test_documented_both_ways(self) -> None:
        used = set()
        for path in TEMPLATES.iterdir():
            if path.is_file() and path.name != "README.md":
                used |= set(PLACEHOLDER.findall(path.read_text(encoding="utf-8")))
        rows = [l for l in section(README, "Placeholders").splitlines() if l.startswith("| `")]
        documented = set(PLACEHOLDER.findall("\n".join(rows)))
        self.assertEqual(used - documented, set(), "used but not documented")
        self.assertEqual(documented - used, set(), "documented but never used")


class Profile(unittest.TestCase):
    def test_filled_profile_is_valid(self) -> None:
        filled = PLACEHOLDER.sub(lambda m: f"sample {m.group(1)}", text("project.toml"))
        data, problems = athena_profile.check(tomllib.loads(filled))
        self.assertEqual(problems, [])
        self.assertEqual(data["deploy"]["dev"], "sample deploy_dev")


class MatchesTheSkill(unittest.TestCase):
    def test_plan_has_the_tables_the_skill_reads(self) -> None:
        plan = text("IMPLEMENTATION_PLAN.md")
        for heading in ("Status", "Open questions", "Follow-up register", "Access inventory", "Safeguards"):
            with self.subTest(heading=heading):
                self.assertIn(f"\n## {heading}\n", plan)
                if heading != "Status":
                    self.assertIn(heading, SKILL_FLAT)

    def test_pr_template_has_the_skill_pr_body(self) -> None:
        body = re.search(r"## 9\..*?```markdown\n(.*?)```", SKILL, re.DOTALL).group(1)
        headings = re.findall(r"^### (.+)$", body, re.MULTILINE)
        self.assertGreater(len(headings), 4)
        template = re.findall(r"^### (.+)$", text("pull_request_template.md"), re.MULTILINE)
        self.assertEqual(template[: len(headings)], headings)

    def test_statuses_match(self) -> None:
        statuses = re.search(r"## 4\. Statuses\n\n(.*?)\n\n", SKILL, re.DOTALL).group(1)
        plan = text("IMPLEMENTATION_PLAN.md")
        for status in re.findall(r"`([a-z ]+)", statuses):
            with self.subTest(status=status):
                self.assertIn(f"`{status}", plan)

    def test_ci_job_is_the_required_check(self) -> None:
        self.assertRegex(text("ci.yml"), r"\njobs:\n  \{\{required_check\}\}:\n")


if __name__ == "__main__":
    unittest.main()
