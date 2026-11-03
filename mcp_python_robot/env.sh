#!/usr/bin/env bash
help='
## Usage:
  source env.sh dev
  source env.sh prd
'

setup_env_dev() {
  local help='
  ## Usage:
    source env.sh dev
  '
  export VMODAL_ENV="dev"
  export VMODAL_BASE_URL="http://127.0.0.1:3099"
  export VMODAL_MODE="gateway"
  export MCP_IMAGE_DIR="${MCP_IMAGE_DIR:-ztmp/mcp_images}"
  # Robot artifacts and immutable telemetry specifications (derived default).
  export MCP_ROBOT_DIR="${MCP_ROBOT_DIR:-$(dirname "$MCP_IMAGE_DIR")/mcp_robot}"
  export VMODAL_AUTH_CACHE_DIR="${VMODAL_AUTH_CACHE_DIR:-ztmp/vmodal_auth}"
  export MCP_TRANSPORT="${MCP_TRANSPORT:-stdio}"
}

setup_env_prd() {
  local help='
  ## Usage:
    source env.sh prd
  '
  export VMODAL_ENV="prd"
  export VMODAL_BASE_URL="https://searchapi-test.v-modal.com"
  export VMODAL_MODE="gateway"
  export MCP_IMAGE_DIR="${MCP_IMAGE_DIR:-ztmp/mcp_images}"
  export MCP_ROBOT_DIR="${MCP_ROBOT_DIR:-$(dirname "$MCP_IMAGE_DIR")/mcp_robot}"
  export VMODAL_AUTH_CACHE_DIR="${VMODAL_AUTH_CACHE_DIR:-ztmp/vmodal_auth}"
  export MCP_TRANSPORT="${MCP_TRANSPORT:-stdio}"
}

cmd="${1:-dev}"
case "$cmd" in
  dev) setup_env_dev ;;
  prd) setup_env_prd ;;
  *) echo "$help"; return 1 2>/dev/null || exit 1 ;;
esac
