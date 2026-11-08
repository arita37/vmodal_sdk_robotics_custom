"""Local skill entry points must work in the installed robot interpreter."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SkillInstallationTests(unittest.TestCase):
    def test_runtime_dependencies_import(self):
        # Run outside the checkout without PYTHONPATH to test the installed package,
        # rather than accidentally finding a source checkout or scratch environment.
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        result = subprocess.run(
            [sys.executable, '-c',
             'import numpy, fire, filelock, PIL, vmodal; '
             'from src.mcp_server.robot_format import telemetry_check, spec_validate'],
            cwd=tempfile.gettempdir(), env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_local_skill_entry_points(self):
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        for tree in ('skills', '.claude/skills'):
            for skill, script in (
                ('format-review', 'format_review'),
                ('failure-screen', 'failure_screen'),
                ('telemetry-repair', 'telemetry_repair'),
                ('sync-audit', 'sync_audit'),
                ('norm-stats', 'norm_stats'),
                ('qc-batch', 'qc_batch'),
                ('staged-upload', 'staged_upload'),
            ):
                path = ROOT / tree / f'vmodal-robot-{skill}/scripts/{script}.py'
                with self.subTest(path=path):
                    result = subprocess.run([sys.executable, str(path), '--help'],
                                            cwd=ROOT, env=env, capture_output=True,
                                            text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('usage:', result.stdout.lower())

    def test_readme_installs_maintained_branch(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertIn('git clone --branch main --single-branch ', readme)
        self.assertNotIn('--branch docs/robot-mcp-beginner-readme', readme)

    def test_documented_interpreter_matches_installer(self):
        for tree in ('skills', '.claude/skills'):
            for path in (ROOT / tree).rglob('*'):
                if path.suffix in ('.md', '.py'):
                    with self.subTest(path=path):
                        self.assertNotIn('.venv/bin/python', path.read_text())
        self.assertIn('VENV="$ROOT/.venv-robot"', (ROOT / 'install_full.sh').read_text())


if __name__ == '__main__':
    unittest.main()
