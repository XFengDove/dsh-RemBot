"""Telemetry configuration for blender_mcp.

The upstream plugin source shipped without this module, which makes
`blender_mcp.telemetry` fail at import time with:

    No module named 'blender_mcp.config'

`safe_mode.py` / `telemetry.py` only read the handful of attributes below, so a
plain dataclass is enough.  Telemetry defaults to OFF here: this harness does
not send usage data anywhere, and the Supabase coordinates are left empty so no
endpoint is ever contacted.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TelemetryConfig:
    # Master switch. TelemetryCollector.__init__ may flip this to False when a
    # DISABLE_TELEMETRY / BLENDER_MCP_DISABLE_TELEMETRY / MCP_DISABLE_TELEMETRY
    # environment variable is set; we start from False anyway.
    enabled: bool = False

    # Longest prompt prefix captured before truncation.
    max_prompt_length: int = 500

    # Network settings for the opt-in uploader. Intentionally empty: with no
    # url/key nothing can be uploaded even if `enabled` were turned on.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_bucket: str = ""

    # HTTP timeout in seconds for the uploader.
    timeout: float = 10.0


telemetry_config = TelemetryConfig()

__all__ = ["TelemetryConfig", "telemetry_config"]
