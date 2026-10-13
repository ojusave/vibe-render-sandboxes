"""Read host credentials without putting them into a sandbox or plugin manifest."""

# Environment variables are process settings; paths and URL parsing validate saved logins.
import os
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from render import RenderAsync


def render_client() -> RenderAsync:
    """Use an explicit workspace and either an API key or an opted-in CLI login."""
    owner = os.environ.get("RENDER_WORKSPACE_ID", "")
    if not owner.startswith("tea-"):
        raise ValueError("Set RENDER_WORKSPACE_ID to the intended tea-... workspace")
    token = os.environ.get("RENDER_API_KEY")
    if not token and os.environ.get("VIBE_RENDER_USE_CLI_LOGIN") == "1":
        # A matching workspace and official API host prevent sending a saved key elsewhere.
        path = Path(os.environ.get("RENDER_CLI_CONFIG_PATH", "~/.render/cli.yaml")).expanduser()
        saved = yaml.safe_load(path.read_text())
        host = urlsplit(saved["api"].get("host") or "https://api.render.com")
        if saved.get("workspace") != owner or not (
            host.scheme == "https"
            and host.netloc == "api.render.com"
            and host.path in {"", "/", "/v1", "/v1/"}
            and not host.query
            and not host.fragment
        ):
            raise ValueError("Saved Render login must match the workspace and official API host")
        token = saved["api"]["key"]
    if not token:
        raise ValueError("Set RENDER_API_KEY, or VIBE_RENDER_USE_CLI_LOGIN=1 for your saved login")
    return RenderAsync(token=token, owner_id=owner, region="oregon")
