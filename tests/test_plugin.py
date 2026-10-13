"""Exercise native plugin validation, credential boundaries and the real MCP transport."""

# Vibe's validator and MCP's client catch integration mistakes that manifest-only tests miss.
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from vibe_render.cli import install
from vibe_render.session import child_config


def test_plugin_native_validator(tmp_path):
    """Vibe must recognize both the plugin manifest and its user-invoked skill."""
    from vibe.core.plugins.inspection import inspect_plugin

    plugin = install(tmp_path)
    inspection = inspect_plugin(plugin)
    assert inspection.valid, inspection.to_json()
    assert inspection.plugin.namespace == "renderSandbox"
    assert any(skill.source_name == "code" for skill in inspection.skills)
    # An existing plugin is preserved instead of being silently overwritten.
    with pytest.raises(ValueError, match="already exists"):
        install(tmp_path)
    assert str(Path(sys.executable)) in (plugin / "run-server").read_text()


def test_child_has_no_render_credentials_or_parent_settings(tmp_path, monkeypatch):
    """Only the selected model key reaches Vibe; all keys stay out of its configuration file."""
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-model-key")
    monkeypatch.setenv("RENDER_API_KEY", "fake-render-key")
    monkeypatch.setenv("OTHER_PRIVATE_KEY", "fake-other-key")
    monkeypatch.delenv("VIBE_RENDER_PROVIDER", raising=False)
    env = child_config(tmp_path / "home")
    assert env["MISTRAL_API_KEY"] == "fake-model-key"
    assert "RENDER_API_KEY" not in env and "OTHER_PRIVATE_KEY" not in env
    assert "fake-model-key" not in (tmp_path / "home" / "config.toml").read_text()


async def test_mcp_real_transport_lists_tools_and_rejects_host_path(tmp_path):
    """Launch the installed entry point and use MCP messages, without creating paid resources."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "vibe_render.cli", "serve", "--project", str(tmp_path)],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
        await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert names == {"start_task", "task_status", "cancel_task"}
        result = await session.call_tool("task_status", {"run_id": "../../outside"})
        assert result.isError
        result = await session.call_tool("start_task", {"task": ""})
        assert result.isError
        # The task input intentionally has no path or shell-command options for host execution.
        schema = next(
            tool.inputSchema
            for tool in (await session.list_tools()).tools
            if tool.name == "start_task"
        )
        assert set(schema["properties"]) == {"task"}


async def test_readiness_failure_still_terminates_created_sandbox(tmp_path, monkeypatch):
    """A failure before Vibe starts must still retain the sandbox ID and confirm cleanup."""
    import subprocess
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import vibe_render.session as runner

    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)  # noqa: ASYNC221 - tiny test setup
    (project / "app.py").write_text("print('fixture')\n")
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-only")
    monkeypatch.delenv("VIBE_RENDER_PROVIDER", raising=False)
    create = AsyncMock(return_value=SimpleNamespace(id="sbx-fixture"))
    client = SimpleNamespace(experimental=SimpleNamespace(sandboxes=SimpleNamespace(create=create)))
    monkeypatch.setattr(runner, "render_client", lambda: client)
    monkeypatch.setattr(runner, "wait_ready", AsyncMock(side_effect=RuntimeError("not ready")))
    cleanup = AsyncMock()
    monkeypatch.setattr(runner, "terminate", cleanup)
    with pytest.raises(RuntimeError, match="not ready"):
        await runner.run_task(project, "Fix fixture", run_id="a" * 32)
    cleanup.assert_awaited_once_with(client, "sbx-fixture")
    receipt = json.loads((project / ".vibe-render/runs" / ("a" * 32) / "receipt.json").read_text())
    assert receipt["state"] == "failed" and receipt["cleanup"] == "terminated"
    assert receipt["sandbox_id"] == "sbx-fixture"
