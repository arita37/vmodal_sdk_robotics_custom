#!/usr/bin/env bash
help='
## Usage:
  bash cli.sh mcp_run [--transport stdio|http] [--port 8199]
  bash cli.sh mcp_dev
  bash cli.sh mcp_test
'
CMD="${1:-help}"
shift || true

mcp_run() {
  local help='
  ## Usage:
    bash cli.sh mcp_run --transport stdio
    bash cli.sh mcp_run --transport http --port 8199
  '
  local transport="stdio"
  local port=8199
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --transport)
        transport="${2:-}"
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
  python -m src.mcp_server.main_mcp run --transport "$transport" --port "$port"
}

mcp_dev() {
  local help='
  ## Usage:
    bash cli.sh mcp_dev
  '
  mcp dev src/mcp_server/main_mcp.py
}

mcp_test() {
  local help='
  ## Usage:
    bash cli.sh mcp_test
  '
  python tests/test_main_mcp.py test_all
}

case "$CMD" in
  mcp_run)
    mcp_run "$@"
    ;;
  mcp_dev)
    mcp_dev "$@"
    ;;
  mcp_test)
    mcp_test "$@"
    ;;
  help|--help|-h)
    echo "$help"
    ;;
  *)
    echo "$help"
    exit 1
    ;;
esac
