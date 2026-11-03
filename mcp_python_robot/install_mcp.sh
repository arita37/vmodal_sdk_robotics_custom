#!/usr/bin/env bash
help='
Register the robot MCP from this source checkout using the active Python installation.
## Usage:
  bash install_mcp.sh claude API_KEY
  bash install_mcp.sh codex API_KEY
  bash install_mcp.sh cursor API_KEY
  bash install_mcp.sh copilot API_KEY
'
set -euo pipefail
cd "$(dirname "$0")"

robot_install() {
  local help='
  ## Usage:
    robot_install claude API_KEY
  '
  local client="${1:-help}"
  if [ "$#" -gt 0 ]; then shift; fi
  case "$client" in
    claude) bash install.sh claude_code "$@" ;;
    codex) bash install.sh codex "$@" ;;
    cursor) bash install.sh cursor "$@" ;;
    copilot) bash install.sh github_copilot "$@" ;;
    help|-h|--help) echo "$help" ;;
    *) echo "$help" >&2; return 1 ;;
  esac
}

robot_install "$@"
