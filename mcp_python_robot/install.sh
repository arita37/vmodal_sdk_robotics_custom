#!/usr/bin/env bash
help='
## Usage:
  bash install.sh install
  bash install.sh install_user
  bash install.sh claude_code API_KEY
  bash install.sh codex API_KEY
  bash install.sh cursor API_KEY
  bash install.sh github_copilot API_KEY
  bash install.sh doctor
  bash install.sh print_claude
  bash install.sh print_codex
  bash install.sh print_copilot
  bash install.sh print_copilot_vscode
  bash install.sh print_cursor
  bash install.sh register_claude_local API_KEY
  bash install.sh register_codex API_KEY
  bash install.sh register_copilot API_KEY
  bash install.sh register_copilot_vscode

## Examples:
  bash install.sh install
  bash install.sh claude_code PUT_API_KEY_HERE
  bash install.sh codex PUT_API_KEY_HERE
  bash install.sh cursor PUT_API_KEY_HERE
  bash install.sh github_copilot PUT_API_KEY_HERE
  bash install.sh doctor
  bash install.sh print_claude
  bash install.sh print_codex
  bash install.sh print_copilot
  bash install.sh print_copilot_vscode
  bash install.sh print_cursor
'
set -euo pipefail
cd "$(dirname "$0")"

mcp_py() {
  local help='
  ## Usage:
    mcp_py -m pip --version
  '
  if [ -n "${PYTHON_BIN:-}" ]; then
    "$PYTHON_BIN" "$@"
  elif command -v python >/dev/null 2>&1; then
    python "$@"
  elif command -v python3 >/dev/null 2>&1; then
    python3 "$@"
  elif command -v py >/dev/null 2>&1; then
    py -3 "$@"
  else
    echo "Error: python was not found. Install Python 3.10+ and re-run." >&2
    return 1
  fi
}

mcp_py_bin() {
  local help='
  ## Usage:
    mcp_py_bin
  '
  if [ -n "${PYTHON_BIN:-}" ]; then
    printf '%s\n' "$PYTHON_BIN"
  elif command -v python >/dev/null 2>&1; then
    command -v python
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v py >/dev/null 2>&1; then
    printf '%s\n' "py"
  else
    echo "Error: python was not found. Install Python 3.10+ and re-run." >&2
    return 1
  fi
}

mcp_install() {
  local help='
  ## Usage:
    bash install.sh install
  '
  if [ -f pyproject.toml ] && grep -q 'name = "vmodal_mcp_robot"' pyproject.toml; then
    mcp_py -m pip install "fire>=0.6.0"
    if [ -f ../sdk_python/src/vmodal/__init__.py ]; then
      mcp_py utils.py sdk_version_sync --check=true
    fi
    mcp_py -m pip install -e .
  else
    echo "Run install.sh from the robot MCP source distribution." >&2
    return 1
  fi
}

mcp_install_user() {
  local help='
  ## Usage:
    bash install.sh install_user
  '
  if [ -f pyproject.toml ] && grep -q 'name = "vmodal_mcp_robot"' pyproject.toml; then
    mcp_py -m pip install --user "fire>=0.6.0"
    if [ -f ../sdk_python/src/vmodal/__init__.py ]; then
      mcp_py utils.py sdk_version_sync --check=true
    fi
    mcp_py -m pip install --user -e .
  else
    echo "Run install.sh from the robot MCP source distribution." >&2
    return 1
  fi
}

mcp_api_key() {
  local help='
  ## Usage:
    mcp_api_key API_KEY
  '
  local key="${1:-${api_key:-}}"
  if [ -z "$key" ] || [ "$key" = "PUT_API_KEY_HERE" ]; then
    echo "Error: provide the vmodal API key as the second argument or api_key environment variable." >&2
    return 1
  fi
  printf '%s\n' "$key"
}

mcp_doctor() {
  local help='
  ## Usage:
    bash install.sh doctor
  '
  mcp_py --version
  mcp_py -m pip show vmodal-mcp-robot
  if command -v vmodal-mcp-robot >/dev/null 2>&1; then
    command -v vmodal-mcp-robot
  else
    echo "Warning: vmodal-mcp-robot is installed but not on PATH." >&2
    echo "Add your Python scripts directory to PATH or use python -m src.mcp_server.main_mcp." >&2
  fi
}

mcp_print_claude() {
  local help='
  ## Usage:
    bash install.sh print_claude
  '
  local pycmd
  pycmd="$(mcp_py_bin)"
  if [ "$pycmd" = "py" ]; then
    printf '%s\n' 'claude mcp add vmodal --scope local -e api_key=PUT_API_KEY_HERE -- py -3 -m src.mcp_server.main_mcp run --transport stdio'
  else
    printf 'claude mcp add vmodal --scope local -e api_key=PUT_API_KEY_HERE -- %s -m src.mcp_server.main_mcp run --transport stdio\n' "$pycmd"
  fi
  printf '%s\n' 'claude mcp list'
}

mcp_print_codex() {
  local help='
  ## Usage:
    bash install.sh print_codex
  '
  local pycmd
  pycmd="$(mcp_py_bin)"
  if [ "$pycmd" = "py" ]; then
    printf '%s\n' 'codex mcp add --env api_key=PUT_API_KEY_HERE vmodal -- py -3 -m src.mcp_server.main_mcp run --transport stdio'
  else
    printf 'codex mcp add --env api_key=PUT_API_KEY_HERE vmodal -- %s -m src.mcp_server.main_mcp run --transport stdio\n' "$pycmd"
  fi
  printf '%s\n' 'codex mcp list'
}

mcp_print_copilot() {
  local help='
  ## Usage:
    bash install.sh print_copilot
  '
  local pycmd
  pycmd="$(mcp_py_bin)"
  if [ "$pycmd" = "py" ]; then
    printf '%s\n' 'copilot mcp add vmodal --env api_key=PUT_API_KEY_HERE -- py -3 -m src.mcp_server.main_mcp run --transport stdio'
  else
    printf 'copilot mcp add vmodal --env api_key=PUT_API_KEY_HERE -- %s -m src.mcp_server.main_mcp run --transport stdio\n' "$pycmd"
  fi
  printf '%s\n' 'copilot mcp list'
}

mcp_print_copilot_vscode() {
  local help='
  ## Usage:
    bash install.sh print_copilot_vscode
  '
  local pycmd
  pycmd="$(mcp_py_bin)"
  if [ "$pycmd" = "py" ]; then
    printf '%s\n' "code --add-mcp '{\"name\":\"vmodal\",\"command\":\"py\",\"args\":[\"-3\",\"-m\",\"src.mcp_server.main_mcp\",\"run\",\"--transport\",\"stdio\"],\"env\":{\"api_key\":\"PUT_API_KEY_HERE\"}}'"
  else
    printf "code --add-mcp '{\"name\":\"vmodal\",\"command\":\"%s\",\"args\":[\"-m\",\"src.mcp_server.main_mcp\",\"run\",\"--transport\",\"stdio\"],\"env\":{\"api_key\":\"PUT_API_KEY_HERE\"}}'\n" "$pycmd"
  fi
  printf '%s\n' 'Use “MCP: List Servers” in VS Code to verify it for GitHub Copilot.'
}

mcp_print_cursor() {
  local help='
  ## Usage:
    bash install.sh print_cursor
  '
  local pycmd
  pycmd="$(mcp_py_bin)"
  printf '%s\n' 'Save this as .cursor/mcp.json for project scope or ~/.cursor/mcp.json for global scope:'
  if [ "$pycmd" = "py" ]; then
    printf '%s\n' '{"mcpServers":{"vmodal":{"command":"py","args":["-3","-m","src.mcp_server.main_mcp","run","--transport","stdio"],"env":{"api_key":"PUT_API_KEY_HERE"}}}}'
  else
    printf '{"mcpServers":{"vmodal":{"command":"%s","args":["-m","src.mcp_server.main_mcp","run","--transport","stdio"],"env":{"api_key":"PUT_API_KEY_HERE"}}}}\n' "$pycmd"
  fi
}

mcp_register_claude_local() {
  local help='
  ## Usage:
    bash install.sh register_claude_local API_KEY
  '
  if ! command -v claude >/dev/null 2>&1; then
    echo "Error: claude CLI was not found." >&2
    return 1
  fi
  local pycmd key scope
  key="$(mcp_api_key "${1:-}")"
  scope="${2:-local}"
  pycmd="$(mcp_py_bin)"
  if [ "$pycmd" = "py" ]; then
    claude mcp add vmodal --scope "$scope" --env "api_key=$key" -- py -3 -m src.mcp_server.main_mcp run --transport stdio
  else
    claude mcp add vmodal --scope "$scope" --env "api_key=$key" -- "$pycmd" -m src.mcp_server.main_mcp run --transport stdio
  fi
  claude mcp list
}

mcp_register_codex() {
  local help='
  ## Usage:
    bash install.sh register_codex API_KEY
  '
  if ! command -v codex >/dev/null 2>&1; then
    echo "Error: codex CLI was not found." >&2
    return 1
  fi
  local pycmd key
  key="$(mcp_api_key "${1:-}")"
  pycmd="$(mcp_py_bin)"
  if [ "$pycmd" = "py" ]; then
    codex mcp add --env "api_key=$key" vmodal -- py -3 -m src.mcp_server.main_mcp run --transport stdio
  else
    codex mcp add --env "api_key=$key" vmodal -- "$pycmd" -m src.mcp_server.main_mcp run --transport stdio
  fi
  codex mcp list
}

mcp_register_copilot() {
  local help='
  ## Usage:
    bash install.sh register_copilot API_KEY
  '
  if ! command -v copilot >/dev/null 2>&1; then
    echo "Error: GitHub Copilot CLI was not found." >&2
    return 1
  fi
  local pycmd key
  key="$(mcp_api_key "${1:-}")"
  pycmd="$(mcp_py_bin)"
  if [ "$pycmd" = "py" ]; then
    copilot mcp add vmodal --env "api_key=$key" -- py -3 -m src.mcp_server.main_mcp run --transport stdio
  else
    copilot mcp add vmodal --env "api_key=$key" -- "$pycmd" -m src.mcp_server.main_mcp run --transport stdio
  fi
  copilot mcp list
}

mcp_register_copilot_vscode() {
  local help='
  ## Usage:
    bash install.sh register_copilot_vscode
  '
  if ! command -v code >/dev/null 2>&1; then
    echo "Error: VS Code CLI was not found." >&2
    return 1
  fi
  local pycmd config
  pycmd="$(mcp_py_bin)"
  if [ "$pycmd" = "py" ]; then
    config='{"name":"vmodal","command":"py","args":["-3","-m","src.mcp_server.main_mcp","run","--transport","stdio"]}'
  else
    printf -v config '{"name":"vmodal","command":"%s","args":["-m","src.mcp_server.main_mcp","run","--transport","stdio"]}' "$pycmd"
  fi
  code --add-mcp "$config"
}

mcp_claude_code() {
  local help='
  ## Usage:
    bash install.sh claude_code API_KEY
  '
  local key
  key="$(mcp_api_key "${1:-}")"
  mcp_install
  mcp_register_claude_local "$key" user
}

mcp_codex() {
  local help='
  ## Usage:
    bash install.sh codex API_KEY
  '
  local key
  key="$(mcp_api_key "${1:-}")"
  mcp_install
  mcp_register_codex "$key"
}

mcp_cursor() {
  local help='
  ## Usage:
    bash install.sh cursor API_KEY
  '
  local key pycmd config encoded url
  key="$(mcp_api_key "${1:-}")"
  if ! command -v openssl >/dev/null 2>&1; then
    echo "Error: openssl is required to generate the Cursor install link." >&2
    return 1
  fi
  mcp_install
  pycmd="$(mcp_py_bin)"
  if [ "$pycmd" = "py" ]; then
    config="{\"command\":\"py\",\"args\":[\"-3\",\"-m\",\"src.mcp_server.main_mcp\",\"run\",\"--transport\",\"stdio\"],\"env\":{\"api_key\":\"$key\"}}"
  else
    config="{\"command\":\"$pycmd\",\"args\":[\"-m\",\"src.mcp_server.main_mcp\",\"run\",\"--transport\",\"stdio\"],\"env\":{\"api_key\":\"$key\"}}"
  fi
  encoded="$(printf '%s' "$config" | openssl base64 -A)"
  encoded="${encoded//+/%2B}"
  encoded="${encoded//\//%2F}"
  encoded="${encoded//=/%3D}"
  url="https://cursor.com/en/install-mcp?name=vmodal&config=$encoded"
  mcp_py -m webbrowser "$url"
}

mcp_github_copilot() {
  local help='
  ## Usage:
    bash install.sh github_copilot API_KEY
  '
  local key
  key="$(mcp_api_key "${1:-}")"
  mcp_install
  mcp_register_copilot "$key"
}

cmd="${1:-install}"
if [ "$#" -gt 0 ]; then
  shift
fi
case "$cmd" in
  install) mcp_install ;;
  install_user) mcp_install_user ;;
  claude_code) mcp_claude_code "$@" ;;
  codex) mcp_codex "$@" ;;
  cursor) mcp_cursor "$@" ;;
  github_copilot) mcp_github_copilot "$@" ;;
  doctor) mcp_doctor ;;
  print_claude) mcp_print_claude ;;
  print_codex) mcp_print_codex ;;
  print_copilot) mcp_print_copilot ;;
  print_copilot_vscode) mcp_print_copilot_vscode ;;
  print_cursor) mcp_print_cursor ;;
  register_claude_local) mcp_register_claude_local "$@" ;;
  register_codex) mcp_register_codex "$@" ;;
  register_copilot) mcp_register_copilot "$@" ;;
  register_copilot_vscode) mcp_register_copilot_vscode ;;
  help|-h|--help) echo "$help" ;;
  *) echo "$help"; exit 1 ;;
esac
