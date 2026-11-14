"""Boundary test: no client-specific content in the engine (CLAUDE.md hard rule).

Everything specific to one project belongs in that project's profile. If this fails, move
the text to a profile or an example, or generalise it.

The forbidden words name real clients, so they are not published: they live in
`tests/client_terms.txt`, which is gitignored (one regex per line, `#` for comments).
Without that file the test is skipped, so a public clone runs it as a no-op.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "plugins"
TERMS = Path(__file__).resolve().parent / "client_terms.txt"
TEXT = {".md", ".py", ".json", ".toml", ".txt", ".yml", ".yaml", ".sql", ".sh"}


def forbidden() -> re.Pattern[str] | None:
    if not TERMS.is_file():
        return None
    terms = [
        line.strip()
        for line in TERMS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not terms:
        return None
    return re.compile(r"\b(" + "|".join(terms) + r")\b", re.IGNORECASE)


class NoClientContent(unittest.TestCase):
    def test_engine_is_generic(self) -> None:
        pattern = forbidden()
        if pattern is None:
            self.skipTest("no tests/client_terms.txt (private; kept out of the public repo)")
        hits = []
        for path in ENGINE.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT:
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    for m in pattern.finditer(line):
                        hits.append(f"{path.relative_to(ENGINE)}:{n}: {m.group(0)}")
        self.assertEqual(hits, [], "client-specific words in the engine:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
