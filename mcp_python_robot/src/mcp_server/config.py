from typing import List, Dict, Tuple, Optional, Any, Union
from dataclasses import dataclass
import os,sys
import fire
from src.utils.util_log import log_info, log_error, log_trace, log_warning
from vmodal.config import SdkConfig

PUBLIC_API_KEY_ENV = "api_key"


def str_or_default(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text if text else default


def int_or_default(value: Any, default: int) -> int:
    try:
        return max(1, int(float(value)))
    except Exception:
        return default


@dataclass
class McpConfig:
    sdk: SdkConfig
    image_dir: str
    transport: str
    upload_max_mb: int
    cfg_error: str
    tool_timeout: float
    robot_dir: str = ""

    @classmethod
    def from_env(cls, **kw) -> "McpConfig":
        sdk_kw = dict(kw)
        public_key = os.environ.get(PUBLIC_API_KEY_ENV, "").strip()
        if public_key and not sdk_kw.get("token"):
            sdk_kw["token"] = public_key
        env_key = os.environ.get("VMODAL_API_KEY", "").strip()
        if os.environ.get("VMODAL_ENV", "").strip():
            env_key = env_key or os.environ.get("VMODAL_API_TOKEN", "").strip()
            env_key = env_key or os.environ.get("TEST_CLIENT_CLERK_USER_API_TOKEN", "").strip()
            env_key = env_key or os.environ.get("TEST_CLIENT_USER_TOKEN", "").strip()
        missing_key = not sdk_kw.get("token") and not env_key
        if missing_key:
            sdk_kw["token"] = "missing"
            sdk_kw["resolve_identity"] = False
        cfg_error = ""
        try:
            sdk = SdkConfig.from_env(**sdk_kw)
            if missing_key:
                sdk.token = ""
                cfg_error = "API key required: set api_key in the MCP server environment"
        except Exception as exc:
            # Keep the MCP server alive so tool calls can return a readable auth
            # error instead of making the client see "server disconnected".
            base_url = str(sdk_kw.get("base_url") or os.environ.get("TEST_CLIENT_SERVER_API_URL", "") or "").strip()
            mode = str(sdk_kw.get("mode") or ("gateway" if base_url else "direct")).strip() or "direct"
            sdk = SdkConfig(base_url=base_url, user_id="", token="", mode=mode)
            cfg_error = f"Bearer identity resolution failed: {exc}"
        image_dir = str_or_default(kw.get("image_dir") or os.environ.get("MCP_IMAGE_DIR"), "ztmp/mcp_images")
        transport = str_or_default(kw.get("transport") or os.environ.get("MCP_TRANSPORT"), "stdio").lower()
        if transport not in ("stdio", "http"):
            transport = "stdio"
        upload_max_mb = int_or_default(kw.get("upload_max_mb") or os.environ.get("MCP_UPLOAD_MAX_MB"), 5120)
        if not cfg_error and not sdk.token:
            cfg_error = "API key required: set api_key in the MCP server environment"
        # outer MCP guard, derived from SDK budget unless overridden
        derived = sdk.timeout * (sdk.max_retries + 1) + 10
        tool_timeout = float(os.environ.get("MCP_TOOL_TIMEOUT") or derived)
        return cls(
            sdk=sdk,
            image_dir=image_dir,
            transport=transport,
            upload_max_mb=upload_max_mb,
            cfg_error=cfg_error,
            tool_timeout=tool_timeout,
            robot_dir=str(kw.get("robot_dir") or os.environ.get("MCP_ROBOT_DIR") or os.path.join(os.path.dirname(image_dir), "mcp_robot")),
        )


def main() -> McpConfig:
    return McpConfig.from_env()
