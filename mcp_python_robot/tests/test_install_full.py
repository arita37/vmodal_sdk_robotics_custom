"""Offline installer orchestration tests; no package installs or client writes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'install_full.sh'
BASH = shutil.which('bash')


@unittest.skipUnless(BASH, 'Bash required')
class FullInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='robot install ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        shutil.copy2(SCRIPT, self.root / SCRIPT.name)
        (self.root / 'pyproject.toml').write_text('[project]\nname="vmodal_mcp_robot"\n')
        sample = self.root / 'data/robot/ep_demo1/telemetry.jsonl'
        sample.parent.mkdir(parents=True)
        sample.write_text('{}\n')
        self.log = self.root / 'calls.jsonl'
        self.env = {**os.environ, 'PATH': str(self.bin), 'CALL_LOG': str(self.log),
                    'PYTHON_BIN': str(self.bin / 'python3'), 'FAIL_STAGE': '',
                    'PYTHONPATH': 'must-be-removed', 'PYTHONHOME': 'must-be-removed'}
        for command in ('bash', 'dirname'):
            (self.bin / command).symlink_to(shutil.which(command))
        for command in ('ffmpeg', 'ffprobe'):
            (self.bin / command).write_text('#!/bin/sh\nexit 0\n')
            (self.bin / command).chmod(0o755)
        # This fake Python handles venv/pip and bypasses only the import smoke test.
        # The generated JSON is produced by the real installer Python snippet.
        fake = self.bin / 'python3'
        fake.write_text(f'''#!{sys.executable}
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as f:
    f.write(json.dumps(args) + '\\n')
fail = os.environ['FAIL_STAGE']
if args[:2] == ['-m', 'venv']:
    if fail == 'venv': sys.exit(2)
    dest = pathlib.Path(args[2]); (dest/'bin').mkdir(parents=True)
    (dest/'pyvenv.cfg').write_text('mock')
    shutil.copy2(__file__, dest/'bin/python')
elif args[:2] == ['-m', 'pip']:
    if fail == 'pip' or (fail == 'check' and args[2] == 'check'): sys.exit(3)
elif args == ['-']:
    code = sys.stdin.read()
    if 'from src.mcp_server' in code:
        if fail == 'smoke': sys.exit(4)
    else:
        if fail == 'config': sys.exit(5)
        exec(code)
elif args[:1] == ['-c']:
    if fail == 'version': sys.exit(1)
else:
    sys.exit('Unexpected fake Python args: ' + repr(args))
''')
        fake.chmod(0o755)
        (self.root / 'install.sh').write_text('''#!/bin/bash
[ "$1" = install ] || exit 10
[ "$PYTHON_BIN" = "$PWD/.venv-robot/bin/python" ] || exit 11
[ -z "${PYTHONPATH:-}" ] || exit 12
[ -z "${PYTHONHOME:-}" ] || exit 13
[ "$FAIL_STAGE" != install ] || exit 14
''')

    def run_install(self, *args):
        return subprocess.run([BASH, str(self.root / SCRIPT.name), *args],
                              env=self.env, cwd='/', text=True, capture_output=True, timeout=20)

    def test_success_repeat_and_paths_with_spaces(self):
        for _ in range(2):
            result = self.run_install()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Installed successfully', result.stdout)
            config = json.loads((self.root / '.venv-robot/mcp-config.json').read_text())
            self.assertEqual(config['mcpServers']['vmodal-robot']['command'],
                             str(self.root / '.venv-robot/bin/python'))
            self.assertNotIn('api_key', json.dumps(config))
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(sum(call[:2] == ['-m', 'venv'] for call in calls), 1)

    def test_missing_python(self):
        self.env['PYTHON_BIN'] = '/missing/python'
        r = self.run_install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Python was not found', r.stderr)

    def test_missing_ffprobe(self):
        (self.bin / 'ffprobe').unlink()
        r = self.run_install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Missing ffprobe', r.stderr)
        self.assertFalse((self.root / '.venv-robot').exists())

    def test_broken_ffmpeg(self):
        (self.bin / 'ffmpeg').write_text('#!/bin/sh\nexit 1\n')
        r = self.run_install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('cannot run', r.stderr)

    def test_failures_do_not_report_success(self):
        for stage in ('version', 'venv', 'pip', 'install', 'check', 'smoke', 'config'):
            with self.subTest(stage=stage):
                shutil.rmtree(self.root / '.venv-robot', ignore_errors=True)
                self.env['FAIL_STAGE'] = stage
                r = self.run_install()
                self.assertNotEqual(r.returncode, 0)
                self.assertNotIn('Installed successfully', r.stdout)
                self.assertFalse((self.root / '.venv-robot/mcp-config.json').exists())

    def test_existing_directory_is_preserved(self):
        venv = self.root / '.venv-robot'
        venv.mkdir()
        keep = venv / 'important.txt'
        keep.write_text('keep me')
        r = self.run_install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Nothing was deleted', r.stderr)
        self.assertEqual(keep.read_text(), 'keep me')

    def test_symlink_is_refused(self):
        (self.root / '.venv-robot').symlink_to(self.bin, target_is_directory=True)
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertTrue((self.bin / 'python3').exists())

    def test_help_and_unknown_arguments(self):
        self.assertEqual(self.run_install('--help').returncode, 0)
        self.assertNotEqual(self.run_install('--bad').returncode, 0)
        self.assertFalse((self.root / '.venv-robot').exists())

    def test_incomplete_checkout(self):
        (self.root / 'pyproject.toml').unlink()
        r = self.run_install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('Incomplete checkout', r.stderr)


if __name__ == '__main__':
    unittest.main()
