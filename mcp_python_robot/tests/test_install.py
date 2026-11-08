"""Offline installer regression tests; all external CLI calls are mocked.

Run with: python -m unittest discover -s tests -p test_install.py
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
BASH = shutil.which("bash")


@unittest.skipUnless(BASH, "installer requires bash")
class ClaudeInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.log = root / "claude.jsonl"
        claude = root / "claude"
        claude.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "with open(os.environ['CLAUDE_TEST_LOG'], 'a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        )
        claude.chmod(0o755)
        # Installation entry points must never invoke pip or a real Python CLI.
        for name in ("mock-python", "py"):
            command = root / name
            command.write_text("#!/bin/sh\nexit 0\n")
            command.chmod(0o755)
        self.env = {
            "PATH": str(root) + os.pathsep + os.defpath,
            "HOME": str(root),
            "CLAUDE_TEST_LOG": str(self.log),
            "PYTHON_BIN": str(root / "mock-python"),
        }

    def run_installer(self, *args):
        result = subprocess.run(
            [BASH, str(INSTALLER), *args],
            env=self.env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def expected_python(self):
        command = self.env["PYTHON_BIN"]
        return [command, "-3"] if command == "py" else [command]

    def assert_registration(self, action, scope, launcher):
        self.env["PYTHON_BIN"] = launcher
        # A value containing spaces also catches accidental shell word splitting.
        key = "fake test key=not-a-credential"
        self.run_installer(action, key)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(calls, [
            ["mcp", "add", "vmodal-robot", "--scope", scope, "--env", f"api_key={key}",
             "--", *self.expected_python(), "-m", "src.mcp_server.main_mcp",
             "run", "--transport", "stdio"],
            ["mcp", "list"],
        ])
        self.log.unlink()

    def test_local_registration_name_precedes_variadic_env(self):
        for launcher in (self.env["PYTHON_BIN"], "py"):
            with self.subTest(launcher=launcher):
                self.assert_registration("register_claude_local", "local", launcher)

    def test_install_and_register_user_name_precedes_variadic_env(self):
        for launcher in (self.env["PYTHON_BIN"], "py"):
            with self.subTest(launcher=launcher):
                self.assert_registration("claude_code", "user", launcher)

    def test_printed_commands_have_server_name_first(self):
        for launcher in (self.env["PYTHON_BIN"], "py"):
            with self.subTest(launcher=launcher):
                self.env["PYTHON_BIN"] = launcher
                lines = self.run_installer("print_claude").splitlines()
                self.assertEqual(shlex.split(lines[0]), [
                    "claude", "mcp", "add", "vmodal-robot", "--scope", "local", "-e",
                    "api_key=PUT_API_KEY_HERE", "--", *self.expected_python(),
                    "-m", "src.mcp_server.main_mcp", "run", "--transport", "stdio",
                ])
                self.assertEqual(lines[1:], ["claude mcp list"])
                self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
