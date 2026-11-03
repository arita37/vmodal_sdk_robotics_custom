#!/usr/bin/env bash
help='
## Usage:
  bash start.sh local [--transport stdio|http] [--port 8199]
  bash start.sh prd [--transport stdio|http] [--port 8199]
'
set -euo pipefail
cd "$(dirname "$0")"

mcp_start() {
  local mode="$1"
  shift
  local transport="stdio"
  local port=8199
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --transport)
        transport="${2:-stdio}"
        shift 2
        ;;
      --transport=*)
        transport="${1#*=}"
        shift
        ;;
      --port)
        port="${2:-8199}"
        shift 2
        ;;
      --port=*)
        port="${1#*=}"
        shift
        ;;
      *)
        shift
        ;;
    esac
  done

  source env.sh "$mode"
  python -m src.mcp_server.main_mcp run --transport "$transport" --port "$port"
}

case "${1:-local}" in
  local|prd)
    mcp_start "$1" "${@:2}"
    ;;
  help|--help|-h)
    echo "$help"
    ;;
  *)
    echo "$help"
    exit 1
    ;;
esac
