"""Skill files: valid frontmatter, and every agent or skill they name exists in the plugin."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "orchestrator"
AGENTS = {p.stem for p in (PLUGIN / "agents").glob("*.md")}
SKILLS = {p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md")}
# `athena-orchestrator:<name>`, or a bare agent-shaped name in backticks.
SCOPED = re.compile(r"athena-orchestrator:([a-z][a-z-]*[a-z])(?![-<\w])")  # not `review-<lens>`
# Skills from later build steps that are already referenced. Remove each one when it lands.
PLANNED: set[str] = set()
BARE = re.compile(r"`((?:review-[a-z]+)|implementer|finding-verifier)`")


def frontmatter(path: Path) -> dict[str, str]:
    m = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
    if not m:
        raise AssertionError(f"{path}: no frontmatter")
    return {k.strip(): v.strip() for k, _, v in (l.partition(":") for l in m.group(1).splitlines())}


class SkillFiles(unittest.TestCase):
    def test_frontmatter(self) -> None:
        for path in (PLUGIN / "skills").glob("*/SKILL.md"):
            with self.subTest(skill=path.parent.name):
                meta = frontmatter(path)
                self.assertEqual(meta.get("name"), path.parent.name)
                self.assertGreater(len(meta.get("description", "")), 40)

    def test_names_resolve(self) -> None:
        for path in (PLUGIN / "skills").glob("*/SKILL.md"):
            text = path.read_text(encoding="utf-8")
            for name in SCOPED.findall(text):
                with self.subTest(skill=path.parent.name, name=name):
                    self.assertIn(name, AGENTS | SKILLS | PLANNED)
            for name in BARE.findall(text):
                with self.subTest(skill=path.parent.name, name=name):
                    self.assertIn(name, AGENTS)

    def test_shim(self) -> None:
        # adopt recognises its own shim by this description prefix, and never touches another.
        path = PLUGIN / "shim" / "athena" / "SKILL.md"
        meta = frontmatter(path)
        self.assertEqual(meta.get("name"), "athena")
        self.assertTrue(meta.get("description", "").startswith("athena-orchestrator shortcut"))
        text = path.read_text(encoding="utf-8")
        self.assertIn("athena-orchestrator:orchestrate", text)
        self.assertIn("$ARGUMENTS", text)
        self.assertIn("athena-orchestrator shortcut", (PLUGIN / "skills" / "adopt" / "SKILL.md").read_text(encoding="utf-8"))

    def test_planned_not_built_yet(self) -> None:
        self.assertEqual(PLANNED & SKILLS, set(), "a planned skill exists now: remove it from PLANNED")


if __name__ == "__main__":
    unittest.main()
