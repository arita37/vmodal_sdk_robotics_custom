#!/usr/bin/env bash
# Source-checkout installer. Never runs sudo or changes an assistant's settings.
set -Eeuo pipefail

stage='checking arguments'
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
trap 'rc=$?; printf "Installation failed while %s (exit %s). Fix the error above and rerun bash install_full.sh. No client settings were changed.\n" "$stage" "$rc" >&2; exit "$rc"' ERR

case "${1:-}" in
  -h|--help) echo 'Usage: bash install_full.sh [--help]
Installs into .venv-robot, verifies dependencies and the local sample, and writes
.venv-robot/mcp-config.json for import into your assistant. Requires Python 3.10+,
FFmpeg and ffprobe. Set PYTHON_BIN to select a Python executable. No API key needed.'; exit 0 ;;
  '') ;;
  *) fail 'Unknown argument. Use bash install_full.sh --help.' ;;
esac
[ "$#" -le 1 ] || fail 'Too many arguments. Use bash install_full.sh --help.'

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
ROOT="$(pwd -P)"
[ -f "$ROOT/pyproject.toml" ] && [ -f "$ROOT/data/robot/ep_demo1/telemetry.jsonl" ] ||
  fail 'Incomplete checkout. Clone the whole repository, not just this script.'

# Ignore Python overrides that could mix the generic and robot 'src' packages.
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
stage='checking system dependencies'
PY="${PYTHON_BIN:-python3}"
command -v "$PY" >/dev/null 2>&1 || fail 'Python was not found. Install Python 3.10+ or set PYTHON_BIN to its executable.'
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' ||
  fail 'Python 3.10+ is required. Select it with PYTHON_BIN=/path/to/python3.'
for cmd in ffmpeg ffprobe; do
  command -v "$cmd" >/dev/null 2>&1 || fail "Missing $cmd. Install FFmpeg first (macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt-get install ffmpeg), then rerun. No system packages are installed automatically."
  "$cmd" -version >/dev/null 2>&1 || fail "$cmd was found but cannot run. Repair your FFmpeg installation."
done

VENV="$ROOT/.venv-robot"
stage='preparing the dedicated virtual environment'
if [ -e "$VENV" ] || [ -L "$VENV" ]; then
  [ ! -L "$VENV" ] && [ -f "$VENV/pyvenv.cfg" ] && [ -x "$VENV/bin/python" ] ||
    fail '.venv-robot exists but is not a usable local venv. Move it aside manually after checking its contents, then rerun. Nothing was deleted.'
else
  "$PY" -m venv "$VENV" || fail 'Could not create .venv-robot. Ensure venv/ensurepip is installed (Debian/Ubuntu: python3-venv), and check disk space and permissions. Move an incomplete .venv-robot aside before retrying.'
fi
PY="$VENV/bin/python"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) and sys.prefix != sys.base_prefix else 1)' ||
  fail '.venv-robot must be a Python 3.10+ virtual environment. Move an outdated/broken environment aside and rerun.'
"$PY" -m pip --version >/dev/null 2>&1 || fail 'pip is missing in .venv-robot. Repair it with .venv-robot/bin/python -m ensurepip --upgrade, then rerun.'

stage='installing Python dependencies (network access required)'
# Use the existing package installer, including its SDK compatibility check.
PYTHON_BIN="$PY" bash "$ROOT/install.sh" install
"$PY" -m pip check

stage='checking the local robot MCP tool without uploading'
"$PY" - <<'PY'
from src.mcp_server.main_mcp import cli
from src.mcp_server.robot_format import telemetry_format_draft_from_file
draft = telemetry_format_draft_from_file(None, 'data/robot/ep_demo1/telemetry.jsonl')
assert draft['output_path'] is None, 'Smoke test unexpectedly wrote a format file'
print('Local telemetry smoke test passed.')

# Exercise the local skill imports as well: the telemetry-only smoke test does not
# load NumPy or the repair script's validator dependency chain.
import subprocess
import sys
for skill, script in (
    ('format-review', 'format_review'),
    ('failure-screen', 'failure_screen'),
    ('telemetry-repair', 'telemetry_repair'),
):
    subprocess.run([
        sys.executable, f'skills/vmodal-robot-{skill}/scripts/{script}.py', '--help',
    ], check=True, stdout=subprocess.DEVNULL)
print('Local review, failure-screen and repair skill smoke tests passed.')
PY

stage='generating credential-free MCP configuration'
"$PY" - <<'PY'
import json
import tempfile
from pathlib import Path
root = Path.cwd()
venv = root / '.venv-robot'
config = {'mcpServers': {'vmodal-robot': {
    'command': str(venv / 'bin/python'),
    'args': ['-m', 'src.mcp_server.main_mcp', 'run', '--transport', 'stdio'],
}}}
destination = venv / 'mcp-config.json'
with tempfile.NamedTemporaryFile(mode='w', dir=venv, delete=False) as stream:
    temporary = Path(stream.name)
    stream.write(json.dumps(config, indent=2) + '\n')
temporary.replace(destination)
print(f'Installed successfully. Import/merge this MCP configuration into your assistant:\n{destination}')
print(json.dumps(config, indent=2))
print('Reconnect the MCP server, then ask your assistant:\n'
      'Use telemetry_format_draft_from_file to inspect ' +
      str(root / 'data/robot/ep_demo1/telemetry.jsonl') +
      '. Do not write a file, register a format, or upload anything. '
      'Show the fields, shapes, sampling rate, and unresolved ? values.')
PY
printf '%s\n' 'No API key is needed for this local test. No assistant configuration was overwritten.'
