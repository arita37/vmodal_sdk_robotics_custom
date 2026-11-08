"""Check dry-run output ignores without changing the checkout or its index."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("git"), "git is required")
class DryRunGitignoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "--quiet")
        self.package = self.repo / "mcp_python_robot"
        self.package.mkdir()
        # Stage a pre-existing fixture before installing the new ignore rule.
        self.fixture = "mcp_python_robot/ztmp/mcp_robot/robot_demo/fixture.json"
        self.write(self.fixture, "{}\n")
        self.git("add", self.fixture)
        shutil.copyfile(ROOT / ".gitignore", self.package / ".gitignore")
        self.git("add", "mcp_python_robot/.gitignore")

    def git(self, *args, check=True):
        return subprocess.run(
            ["git", "-c", "core.excludesFile=/dev/null", *args],
            cwd=self.repo, check=check, capture_output=True, text=True,
        )

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_new_dry_run_artifacts_are_ignored(self):
        artifacts = [
            "mcp_python_robot/ztmp/mcp_robot/robot_demo/new_episode/check.json",
            "mcp_python_robot/ztmp/mcp_robot/formats/new_format.json",
        ]
        for path in artifacts:
            self.write(path, "{}\n")
            with self.subTest(path=path):
                self.assertEqual(self.git("check-ignore", path).stdout.strip(), path)
                self.assertEqual(
                    self.git("status", "--porcelain", "--untracked-files=all", "--", path).stdout,
                    "",
                )

    def test_tracked_fixture_remains_visible(self):
        self.write(self.fixture, '{"changed": true}\n')
        self.assertEqual(self.git("check-ignore", self.fixture, check=False).returncode, 1)
        self.assertEqual(self.git("ls-files", "--", self.fixture).stdout.strip(), self.fixture)
        self.assertEqual(
            self.git("status", "--porcelain", "--", self.fixture).stdout,
            "AM " + self.fixture + "\n",
        )

    def test_source_and_non_scratch_fixtures_remain_visible(self):
        paths = [
            "mcp_python_robot/src/new_source.py",
            "mcp_python_robot/data/new_fixture.json",
            "mcp_python_robot/src/ztmp/new_source.py",
        ]
        for path in paths:
            self.write(path, "\n")
            with self.subTest(path=path):
                self.assertEqual(self.git("check-ignore", path, check=False).returncode, 1)
                self.assertEqual(
                    self.git("status", "--porcelain", "--untracked-files=all", "--", path).stdout,
                    "?? " + path + "\n",
                )


if __name__ == "__main__":
    unittest.main()
