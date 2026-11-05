"""Offline guards for the checkout's runnable tests and skill documentation."""
import re
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[3]


class CheckoutContractTests(unittest.TestCase):
    def test_runner_targets_exist(self):
        runner = (PACKAGE / "test.sh").read_text()
        targets = re.findall(r"^\s*python (\S+\.py)(?:\s|$)", runner, re.MULTILINE)
        targets += ["tests/" + name for name in re.findall(
            r"python -m unittest discover -s tests -p (\S+\.py)", runner
        )]
        self.assertTrue(targets)
        for target in targets:
            with self.subTest(target=target):
                self.assertTrue((PACKAGE / target).is_file(), target)

    def test_skill_links_resolve(self):
        for doc in (PACKAGE / "skills").rglob("*.md"):
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", doc.read_text()):
                if "://" in target or target.startswith("#"):
                    continue
                with self.subTest(doc=str(doc.relative_to(PACKAGE)), target=target):
                    self.assertTrue((doc.parent / target.split("#", 1)[0]).exists())

    def test_documented_skill_scripts_exist(self):
        docs = [PACKAGE / "README.md", *(PACKAGE / "docs").rglob("*.md"),
                *(PACKAGE / "skills").rglob("*.md")]
        for doc in docs:
            for target in re.findall(
                r"(?:skills/)?(vmodal-[\w-]+/(?:scripts|tests)/[\w.-]+\.(?:sh|py))",
                doc.read_text(),
            ):
                with self.subTest(doc=str(doc.relative_to(PACKAGE)), target=target):
                    self.assertTrue((PACKAGE / "skills" / target).is_file(), target)


if __name__ == "__main__":
    unittest.main()
