"""Regression coverage for report issue 1, without touching real client settings."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")


@unittest.skipUnless(BASH, "installer requires bash")
class RegistrationNameTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.log = root / "calls.jsonl"
        for name in ("claude", "codex", "copilot", "code", "mock-python", "py"):
            executable = root / name
            executable.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "with open(os.environ['TEST_CALLS'], 'a') as log:\n"
                "    log.write(json.dumps(sys.argv) + '\\n')\n"
            )
            executable.chmod(0o755)
        self.env = {
            "PATH": str(root) + os.pathsep + os.defpath,
            "HOME": str(root),
            "TEST_CALLS": str(self.log),
            "PYTHON_BIN": str(root / "mock-python"),
            "api_key": "fake-offline-test-key",
        }

    def run_script(self, script, action):
        self.log.unlink(missing_ok=True)
        result = subprocess.run(
            [BASH, str(ROOT / script), action], env=self.env,
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result.stdout, calls

    def test_wrapper_registers_only_robot_name_for_every_client(self):
        for launcher in (self.env["PYTHON_BIN"], "py"):
            self.env["PYTHON_BIN"] = launcher
            for client in ("claude", "codex", "copilot", "cursor"):
                with self.subTest(client=client, launcher=launcher):
                    if client == "cursor" and not shutil.which("openssl", path=self.env["PATH"]):
                        continue
                    _, calls = self.run_script("install_mcp.sh", client)
                    if client == "cursor":
                        browser = [call for call in calls if "webbrowser" in call]
                        self.assertEqual(len(browser), 1)
                        query = parse_qs(urlparse(browser[0][-1]).query)
                        self.assertEqual(query["name"], ["vmodal-robot"])
                    else:
                        client_calls = [call[1:] for call in calls if Path(call[0]).name == client]
                        self.assertEqual(len(client_calls), 2)
                        registration, listing = client_calls
                        self.assertEqual(registration[:2], ["mcp", "add"])
                        self.assertIn("vmodal-robot", registration)
                        self.assertNotIn("vmodal", registration)
                        self.assertEqual(listing, ["mcp", "list"])
                    # No remove/edit operations against a potentially unrelated generic server.
                    self.assertFalse(any("remove" in call or "delete" in call for call in calls))

    def test_vscode_registration_and_all_printed_configs(self):
        for launcher in (self.env["PYTHON_BIN"], "py"):
            self.env["PYTHON_BIN"] = launcher
            with self.subTest(launcher=launcher):
                _, calls = self.run_script("install.sh", "register_copilot_vscode")
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][1], "--add-mcp")
                self.assertEqual(json.loads(calls[0][2])["name"], "vmodal-robot")
                for client in ("claude", "codex", "copilot"):
                    output, calls = self.run_script("install.sh", "print_" + client)
                    self.assertFalse(calls)
                    command = shlex.split(output.splitlines()[0])
                    self.assertIn("vmodal-robot", command)
                    self.assertNotIn("vmodal", command)
                output, _ = self.run_script("install.sh", "print_cursor")
                config = json.loads(output.splitlines()[-1])
                self.assertEqual(list(config["mcpServers"]), ["vmodal-robot"])
                output, _ = self.run_script("install.sh", "print_copilot_vscode")
                config = json.loads(shlex.split(output.splitlines()[0])[-1])
                self.assertEqual(config["name"], "vmodal-robot")


if __name__ == "__main__":
    unittest.main()
