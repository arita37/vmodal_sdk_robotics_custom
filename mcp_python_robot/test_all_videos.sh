#!/usr/bin/env bash
help='
Local MCP test runner using a custom API key.

The default fixture is collection city, stream astream.

## Usage:
  bash test_all_videos.sh test --api-key "$API_KEY"
  API_KEY="$API_KEY" bash test_all_videos.sh test
  bash test_all_videos.sh live --api-key "$API_KEY"
  bash test_all_videos.sh visual --api-key "$API_KEY"
  bash test_all_videos.sh all --api-key "$API_KEY"

The all command also runs the upload/index/search integration flow.
'
set -euo pipefail
dir_script="$(cd "$(dirname "$0")" && pwd)"
cd "$dir_script"

mcp_custom_key() {
  local help='
  ## Usage:
    mcp_custom_key --api-key "$API_KEY"
  '
  local key="${API_KEY:-}"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --api-key)
        key="${2:-}"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done
  if [ -f "ztmp/env.sh" ]; then
    source ztmp/env.sh
  fi
  key="${key:-${VMODAL_API_KEY:-}}"
  if [ -z "$key" ]; then
    echo "Missing custom API key: pass --api-key, set API_KEY, or set VMODAL_API_KEY in ztmp/env.sh" >&2
    return 1
  fi
  export api_key="$key"
  export VMODAL_API_KEY="$key"
}

mcp_local_setup() {
  local help='
  ## Usage:
    mcp_local_setup --api-key "$API_KEY"
  '
  local repo_root
  repo_root="$(cd ../.. && pwd)"
  source "$repo_root/isetup_env.sh"
  cd "$dir_script"
  export PYTHONPATH="$(pwd):${PYTHONPATH:-}"
  export VMODAL_LIVE_GROUP_NAME="${VMODAL_LIVE_GROUP_NAME:-city}"
  export VMODAL_LIVE_STREAM_NAME="${VMODAL_LIVE_STREAM_NAME:-astream}"
  mcp_custom_key "$@"
}

mcp_local_test() {
  local help='
  ## Usage:
    bash test_all_videos.sh test --api-key "$API_KEY"
  '
  shift || true
  mcp_local_setup "$@"
  bash test.sh test
  VMODAL_LIVE_STREAM_NAME="" bash test.sh live_mcp
  mcp_visual_all
}

mcp_local_live() {
  local help='
  ## Usage:
    bash test_all_videos.sh live --api-key "$API_KEY"
  '
  shift || true
  mcp_local_setup "$@"
  bash test.sh live
  VMODAL_LIVE_STREAM_NAME="" bash test.sh live_mcp
}

mcp_local_all() {
  local help='
  ## Usage:
    bash test_all_videos.sh all --api-key "$API_KEY"
  '
  shift || true
  mcp_local_setup "$@"
  bash test.sh test
  VMODAL_LIVE_STREAM_NAME="" bash test.sh live_mcp
  mcp_visual_all
  bash test.sh initial
}

mcp_visual_search() {
  local help='
  ## Usage:
    mcp_visual_search "a red car"
  '
  local query_text="$1"
  VMODAL_LIVE_QUERY_TEXT="$query_text" VMODAL_LIVE_STREAM_NAME="" python tests/test_main_mcp.py test8
}

mcp_visual_test1() {
  local help='
  ## Usage:
    mcp_visual_test1
  '
  mcp_visual_search "a red car"
}

mcp_visual_test2() {
  local help='
  ## Usage:
    mcp_visual_test2
  '
  mcp_visual_search "a gray car parked on a street"
}

mcp_visual_test3() {
  local help='
  ## Usage:
    mcp_visual_test3
  '
  mcp_visual_search "people standing beside a stone wall"
}

mcp_visual_test4() {
  local help='
  ## Usage:
    mcp_visual_test4
  '
  mcp_visual_search "trees shading a city street"
}

mcp_visual_test5() {
  local help='
  ## Usage:
    mcp_visual_test5
  '
  mcp_visual_search "a historic castle or large stone building"
}

mcp_visual_all() {
  local help='
  ## Usage:
    mcp_visual_all
  '
  mcp_visual_test1
  mcp_visual_test2
  mcp_visual_test3
  mcp_visual_test4
  mcp_visual_test5
}

mcp_local_visual() {
  local help='
  ## Usage:
    bash test_all_videos.sh visual --api-key "$API_KEY"
  '
  shift || true
  mcp_local_setup "$@"
  mcp_visual_all
}

cmd="${1:-test}"
case "$cmd" in
  test) mcp_local_test "$@" ;;
  live) mcp_local_live "$@" ;;
  visual) mcp_local_visual "$@" ;;
  all) mcp_local_all "$@" ;;
  help|-h|--help) echo "$help" ;;
  *) echo "$help"; exit 2 ;;
esac
