"""Agent files: valid frontmatter, and the shared blocks identical in every agent that has them.

The rubric, the safety rules and the reviewer modes are the invariant core (docs/MODEL.md
sections 5.2 to 5.4). They are copied into each agent so a cold subagent has them, and this
test keeps the copies from drifting. Change one, change all.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parent.parent / "plugins" / "orchestrator" / "agents"
REVIEWERS = ["review-spec", "review-correctness", "review-reliability", "review-security",
             "review-tests", "review-ops", "review-ux", "review-combined"]
EXPECTED = set(REVIEWERS) | {"implementer", "finding-verifier"}
MODELS = {"inherit", "sonnet", "opus", "haiku", "fable"}
DEEP = {"implementer", "finding-verifier", "review-correctness", "review-reliability"}
# Section name -> agents that must carry an identical copy.
SHARED = {
    "Modes": REVIEWERS,
    "Rubric": REVIEWERS + ["finding-verifier"],
    "Safety": REVIEWERS + ["finding-verifier"],
}


def parse(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        raise AssertionError(f"{path.name}: no frontmatter")
    meta = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, m.group(2)


def section(body: str, name: str) -> str:
    m = re.search(rf"^## {re.escape(name)}\n(.*?)(?=^## |\Z)", body, re.DOTALL | re.MULTILINE)
    if not m:
        raise AssertionError(f"no '## {name}' section")
    return m.group(1).strip()


class AgentFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.files = {p.stem: p for p in AGENTS.glob("*.md")}

    def test_expected_set(self) -> None:
        self.assertEqual(set(self.files), EXPECTED)

    def test_frontmatter(self) -> None:
        for stem, path in self.files.items():
            with self.subTest(agent=stem):
                meta, _ = parse(path)
                self.assertEqual(meta.get("name"), stem)
                self.assertNotIn(":", meta["name"])
                self.assertGreater(len(meta.get("description", "")), 40)
                self.assertIn(meta.get("model"), MODELS)
                self.assertEqual(meta["model"] == "inherit", stem in DEEP,
                                 "deep roles inherit the strongest model; checklist lenses use sonnet")
                tools = {t.strip() for t in meta.get("tools", "").split(",")}
                self.assertTrue({"Read", "Grep", "Glob", "Bash"} <= tools)
                if stem != "implementer":
                    self.assertNotIn("Edit", tools, "reviewers and the verifier are read-only")

    def test_shared_sections_identical(self) -> None:
        for name, agents in SHARED.items():
            copies = {a: section(parse(self.files[a])[1], name) for a in agents}
            reference = copies[agents[0]]
            for agent, text in copies.items():
                with self.subTest(section=name, agent=agent):
                    self.assertEqual(text, reference, f"'## {name}' in {agent} differs from {agents[0]}")

    def test_reviewers_read_profile_and_report_lens_file(self) -> None:
        for stem in REVIEWERS + ["finding-verifier", "implementer"]:
            with self.subTest(agent=stem):
                body = parse(self.files[stem])[1]
                self.assertIn(".claude/orchestration/project.toml", body)
                self.assertIn(".claude/orchestration/lenses/", body)
        for stem in REVIEWERS:
            with self.subTest(agent=stem):
                self.assertIn("LENS FILE:", section(parse(self.files[stem])[1], "Report"))


if __name__ == "__main__":
    unittest.main()
