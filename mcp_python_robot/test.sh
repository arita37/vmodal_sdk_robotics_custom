#!/usr/bin/env bash
help='
GitHub Actions MCP test runner using TEST_CLIENT_CLERK_USER_API_TOKEN.

## Usage:
  bash test.sh test
  bash test.sh live
  bash test.sh live_mcp
  bash test.sh initial
  bash test.sh robot_live
'
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"
export VMODAL_AUTH_CACHE_DIR="${VMODAL_AUTH_CACHE_DIR:-ztmp/vmodal_auth}"
export VMODAL_LIVE_GROUP_NAME="${VMODAL_LIVE_GROUP_NAME:-newsalien2}"
export VMODAL_LIVE_STREAM_NAME="${VMODAL_LIVE_STREAM_NAME-astream}"

if [ -d "vmodal" ] && [ ! -f "vmodal/__init__.py" ]; then
  rm -rf "vmodal"
fi

mcp_ci_env() {
  local help='
  ## Usage:
    mcp_ci_env
  '
  if [ -f "../../ztmp/env_gitignore.sh" ]; then
    source ../../ztmp/env_gitignore.sh
  fi
  if [ -z "${api_key:-}" ] && [ -n "${TEST_CLIENT_CLERK_USER_API_TOKEN:-}" ]; then
    export api_key="$TEST_CLIENT_CLERK_USER_API_TOKEN"
  fi
}

mcp_test_unit() {
  local help='
  ## Usage:
    bash test.sh test
  '
  python tests/test_utils.py test_all
  python tests/test_main_mcp.py test_all
  python tests/test_cli.py test_all
  python tests/test_robot_format.py test_all
  python tests/test_robot.py test_all
  python tests/test_robot_similar.py test_all
  python tests/test_robot_mcp.py test_all
  python skills/vmodal-robot-similar/tests/test_telemetry_scan.py test_all
  python skills/vmodal-trend-radar/tests/test_trend_matrix.py test_all
}

mcp_test_live() {
  local help='
  ## Usage:
    bash test.sh live
  '
  mcp_ci_env
  python tests/test_main_mcp.py test7
}

mcp_test_live_mcp() {
  local help='
  ## Usage:
    bash test.sh live_mcp
  '
  mcp_ci_env
  python tests/test_main_mcp.py test8
}

mcp_test_initial() {
  local help='
  ## Usage:
    bash test.sh initial
  '
  mcp_ci_env
  python tests/test_cli.py test3
}

mcp_test_robot_live() {
  local help='
  ## Usage:
    bash test.sh robot_live
  '
  mcp_ci_env
  python tests/test_robot_live.py test_all
}

cmd="${1:-test}"
case "$cmd" in
  test) mcp_test_unit ;;
  live) mcp_test_live ;;
  live_mcp) mcp_test_live_mcp ;;
  initial) mcp_test_initial ;;
  robot_live) mcp_test_robot_live ;;
  help|-h|--help) echo "$help" ;;
  *) mcp_test_unit "$@" ;;
esac
