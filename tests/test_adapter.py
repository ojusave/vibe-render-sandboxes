"""Behavioral checks for the actual socket client, process deadlines, and source boundaries."""

# Tests use real local processes as a stand-in for Render's stream; live tests separately use Render.
import asyncio
import base64
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from render.experimental.sandbox import SandboxExecExit, SandboxExecOutput

from vibe_render.commands import _Capture, run_command
from vibe_render.project import snapshot
from vibe_render.remote import Remote
from vibe_render.socket_server import AgentSocket
from vibe_render.types import WorkspaceError, WorkspaceOutputLimitError, WorkspaceTimeoutError


class LocalStream:
    """Match the SDK's output events while running the same supervisor in a test directory."""

    def __init__(self):
        # Drains keep cancelled subprocess transports alive until their stop request completes.
        self.drains = []

    async def exec(self, _sandbox, command):
        # Use the test interpreter explicitly; Render resolves python3 inside its Linux image.
        arguments = shlex.split(command)
        arguments = [sys.executable, "-m", "vibe_render._command_runner", *arguments[3:]]
        process = await asyncio.create_subprocess_exec(
            *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            while data := await process.stdout.readline():
                yield SandboxExecOutput(stream="stdout", data=data.decode())
            stderr = await process.stderr.read()
            if stderr:
                yield SandboxExecOutput(stream="stderr", data=stderr.decode())
            code = await process.wait()
            yield SandboxExecExit(exit_code=code)
        finally:
            # Cancellation leaves the supervisor running briefly so the separate stop request works.
            if process.returncode is None:
                self.drains.append(asyncio.create_task(process.communicate()))


@pytest.fixture
async def client():
    """Supply the SDK surface, then join test-process drains before closing the event loop."""
    stream = LocalStream()
    yield SimpleNamespace(experimental=SimpleNamespace(sandboxes=stream))
    await asyncio.gather(*stream.drains)


async def test_output_exit_and_binary_read(client, tmp_path):
    """Preserve stdout, stderr and nonzero exit codes, then read binary bytes with a byte limit."""
    remote = Remote(client, "local")
    result = await remote.execute("printf hello; printf trouble >&2; exit 7", str(tmp_path), 5)
    assert result == {"exitCode": 7, "stdout": "hello", "stderr": "trouble"}
    binary = tmp_path / "binary"
    binary.write_bytes(b"\x00\xffabc")
    read = await remote.read_file(str(binary), 3)
    assert base64.b64decode(read["contentBase64"]) == b"\x00\xffa"
    assert await remote.read_file(str(tmp_path / "missing"), 4) == {"contentBase64": None}
    assert await remote.read_file(str(tmp_path), 4) == {"contentBase64": None}


async def test_fifo_does_not_block(client, tmp_path):
    """A special file cannot trap a file-read request indefinitely."""
    path = tmp_path / "pipe"
    os.mkfifo(path)
    assert await Remote(client, "local").read_file(str(path), 5) == {"contentBase64": None}


async def test_deadline_stops_delayed_side_effect(client, tmp_path):
    """A timed-out shell's child must not write a marker after the caller has returned."""
    marker = tmp_path / "should-not-exist"
    with pytest.raises(WorkspaceTimeoutError):
        await run_command(
            client,
            "local",
            f"(sleep 1; touch {shlex.quote(str(marker))}) & wait",
            working_dir=str(tmp_path),
            timeout=0.3,
        )
    await asyncio.sleep(1.2)
    assert not marker.exists()
    # A safely stopped command does not prevent the next command from succeeding.
    assert (
        await run_command(client, "local", "printf recovered", working_dir=str(tmp_path), timeout=5)
    ).stdout == "recovered"


async def test_output_bound_stops_command(client, tmp_path):
    """An unlimited-output process is stopped rather than exhausting host memory."""
    with pytest.raises(WorkspaceOutputLimitError):
        await run_command(
            client, "local", "yes large", working_dir=str(tmp_path), timeout=5, max_output_bytes=100
        )


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf")])
async def test_invalid_deadlines_rejected_before_execution(client, tmp_path, timeout):
    """Invalid settings cannot silently remove the time bound."""
    with pytest.raises(ValueError):
        await run_command(client, "local", "exit 0", working_dir=str(tmp_path), timeout=timeout)


def test_untrusted_output_cannot_forge_control_frames():
    """A mismatched command identity is a protocol failure, never a success result."""
    with pytest.raises(WorkspaceError):
        _Capture("expected", 100).feed('{"nonce":"other","kind":"exit","code":0}\n')


@pytest.fixture
def repo(tmp_path):
    """Create an isolated Git project; no tests operate on the user's actual repository."""
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "app.py").write_text("print('original')\n")
    return root


def test_snapshot_excludes_secrets_and_includes_dirty_files(repo, tmp_path):
    """Even tracked environment files are excluded; current source contents are retained."""
    (repo / ".env").write_text("FAKE_SECRET=do-not-upload")
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "ignored.txt").write_text("ignored")
    subprocess.run(["git", "-C", str(repo), "add", "app.py", ".env"], check=True)
    (repo / "app.py").write_text("print('dirty')\n")
    output = tmp_path / "snapshot"
    manifest = snapshot(repo, output)
    assert (output / "app.py").read_text() == "print('dirty')\n"
    assert ".env" in manifest["excluded"]
    assert not (output / ".env").exists() and not (output / "ignored.txt").exists()
    assert not (output / ".git").exists()


def test_snapshot_refuses_symlink(repo, tmp_path):
    """A repository symlink cannot upload an unrelated host file."""
    secret = tmp_path / "outside"
    secret.write_text("fake-secret")
    (repo / "leak").symlink_to(secret)
    with pytest.raises(ValueError, match="symbolic links"):
        snapshot(repo, tmp_path / "snapshot")


async def test_actual_vibe_client_handshake_and_timeout(client, tmp_path):
    """Use the installed Vibe client's parser, rather than a hand-written approximation."""
    from mistralai_vibe_local_harness.vibe import SandboxCommandTimeoutError
    from vibe.cli.agent_socket import connect_agent_socket

    with tempfile.TemporaryDirectory(prefix="vr-test-", dir="/tmp") as directory:
        socket = Path(directory) / "agent.sock"
        async with AgentSocket(Remote(client, "local", command_limit=0.3), socket):
            connection = await connect_agent_socket(socket)
            assert connection.sandbox is not None
            assert connection.sandbox.workspace == "/workspace/project"
            assert socket.stat().st_mode & 0o777 == 0o600
            result = await connection.sandbox.execute("printf remote", str(tmp_path), 10)
            assert result.stdout == "remote"
            with pytest.raises(SandboxCommandTimeoutError):
                await connection.sandbox.execute("sleep 10", str(tmp_path), 10)


async def test_socket_concurrency_and_invalid_version(client, tmp_path):
    """A long command must not block a separate request, and unsupported versions must fail."""

    async def rpc(path, method, params):
        reader, writer = await asyncio.open_unix_connection(path)
        writer.write(
            (
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}) + "\n"
            ).encode()
        )
        await writer.drain()
        result = json.loads(await reader.readline())
        writer.close()
        await writer.wait_closed()
        return result

    with tempfile.TemporaryDirectory(prefix="vr-test-", dir="/tmp") as directory:
        path = Path(directory) / "socket"
        async with AgentSocket(Remote(client, "local"), path):
            invalid = await rpc(
                path, "agent/initialize", {"protocolVersion": 1, "vibeVersion": "old"}
            )
            assert invalid["error"]["code"] == -32602
            await rpc(path, "agent/initialize", {"protocolVersion": 2, "vibeVersion": "2.26.1"})
            slow = asyncio.create_task(
                rpc(
                    path,
                    "sandbox/execute",
                    {"command": "sleep 1", "cwd": str(tmp_path), "timeout": 4},
                )
            )
            result = await asyncio.wait_for(rpc(path, "unknown", {}), 0.5)
            assert result["error"]["code"] == -32601
            assert not slow.done()
            answer = await slow
            assert answer.get("result", {}).get("exitCode") == 0, answer


async def test_disconnection_stops_active_command(client, tmp_path):
    """Closing a socket must cancel its command instead of leaving remote work running."""
    marker = tmp_path / "disconnected-child"
    with tempfile.TemporaryDirectory(prefix="vr-test-", dir="/tmp") as directory:
        path = Path(directory) / "socket"
        remote = Remote(client, "local")
        async with AgentSocket(remote, path) as server:
            await server.dispatch(
                "agent/initialize", {"protocolVersion": 2, "vibeVersion": "2.26.1"}
            )
            _reader, writer = await asyncio.open_unix_connection(path)
            request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "sandbox/execute",
                "params": {
                    "command": f"(sleep 2; touch {shlex.quote(str(marker))}) & wait",
                    "cwd": str(tmp_path),
                    "timeout": 10,
                },
            }
            writer.write((json.dumps(request) + "\n").encode())
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(2.3)
            assert not marker.exists()
            assert remote.failed  # A disconnected session must not silently resume commands.


async def test_transport_failure_has_no_local_fallback(tmp_path):
    """An unavailable Render stream must never run the requested shell command on the host."""

    class BrokenStream:
        async def exec(self, *_):
            raise ConnectionError("simulated unavailable Render")
            yield  # This method deliberately has the same async-iterator shape as the SDK.

    client = SimpleNamespace(experimental=SimpleNamespace(sandboxes=BrokenStream()))
    marker = tmp_path / "host-must-stay-clean"
    remote = Remote(client, "broken")
    with pytest.raises(ConnectionError):
        await remote.execute(f"touch {shlex.quote(str(marker))}", str(tmp_path), 5)
    assert remote.failed
    assert not marker.exists()
