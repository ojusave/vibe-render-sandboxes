"""Command execution for the Vibe sandbox connection.

Only Render's public asynchronous exec API is used. A small remote supervisor
supplies process-group identity, byte-preserving output and direct-child exit
semantics that are not exposed by Render's streaming endpoint itself.
"""

from __future__ import annotations

# Async tasks, byte encoding, and shell quoting keep remote execution bounded and transport-safe.
import asyncio

# These standard-library modules manage remote processes, pipes, locks, and encoded output.
import base64
import binascii
import json
import math
import shlex
import uuid
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from importlib.resources import files
from typing import cast

import anyio
from render import RenderAsync
from render.experimental.sandbox import SandboxExecExit, SandboxExecOutput

from .types import (
    CommandResult,
    WorkspaceCommand,
    WorkspaceError,
    WorkspaceOutputLimitError,
    WorkspaceTimeoutError,
)

_CLAIM_ROOT = "/tmp"
_MAX_FRAME_CHARS = 131_072
# Linux limits each exec argument (including Render's bash -c argument). The raw
# JSON payload avoids another base64 expansion of Workspace's file-write chunks.
_MAX_LAUNCH_BYTES = 126_000


def _positive(value: object, name: str) -> float:
    """Reject zero, negative, boolean, or infinite limits before starting any remote work."""
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be positive and finite")  # noqa: TRY004
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return float(value)


def _argv(command: object) -> list[str]:
    """Convert shell text or literal arguments into the remote program and its input arguments."""
    if isinstance(command, str):
        values = ["/bin/sh", "-c", command]
    elif isinstance(command, Sequence) and not isinstance(command, (bytes, bytearray)):
        elements = list(cast(Sequence[object], command))
        if any(not isinstance(value, str) for value in elements):
            raise TypeError("command arguments must be strings")
        values = cast(list[str], elements)
        if not values:
            raise ValueError("command argv cannot be empty")
    else:
        raise TypeError("command must be text or a sequence of arguments")
    if any(type(value) is not str for value in values):
        raise TypeError("command arguments must be strings")
    if any("\0" in value for value in values):
        raise ValueError("command arguments cannot contain NUL")
    return values


def _launch(source: str, operation: str, config: Mapping[str, object]) -> str:
    """Quote the remote Python program and its settings so shell punctuation stays ordinary data."""
    payload = json.dumps(dict(config), separators=(",", ":"), ensure_ascii=True)
    command = shlex.join(["python3", "-c", source, operation, payload])
    if len(command.encode()) > _MAX_LAUNCH_BYTES:
        raise ValueError("Command and environment exceed the remote exec argument limit")
    return command


def _object(value: object) -> dict[str, object]:
    """Require a JSON object before reading named fields from a remote control message."""
    if not isinstance(value, dict):
        raise WorkspaceError("Invalid command supervisor frame")
    return cast(dict[str, object], value)


@dataclass
class _Capture:
    nonce: str
    limit: int
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    buffer: str = ""
    terminal: str | None = None
    exit_code: int | None = None

    def text(self) -> tuple[str, str]:
        """Decode captured bytes for Vibe; replace invalid text bytes instead of losing the whole result."""
        return self.stdout.decode("utf-8", errors="replace"), self.stderr.decode(
            "utf-8", errors="replace"
        )

    def overflow(self) -> WorkspaceOutputLimitError:
        """Preserve the captured output when reporting that the configured byte limit was exceeded."""
        stdout, stderr = self.text()
        return WorkspaceOutputLimitError(
            "Command output exceeded max_output_bytes; redirect output to a file",
            limit=self.limit,
            stdout=stdout,
            stderr=stderr,
        )

    def feed(self, data: str) -> None:
        """Reassemble newline-delimited control messages when network chunks split a message in two."""
        pieces = data.split("\n")
        for index, piece in enumerate(pieces):
            self.buffer += piece
            if len(self.buffer) > _MAX_FRAME_CHARS:
                raise WorkspaceError("Command supervisor frame exceeded its bound")
            if index < len(pieces) - 1:
                line, self.buffer = self.buffer, ""
                if line:
                    try:
                        parsed: object = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise WorkspaceError("Invalid command supervisor JSON") from exc
                    self.frame(_object(parsed))

    def frame(self, frame: dict[str, object]) -> None:
        """Validate the unique command ID and message order before accepting output or completion."""
        if frame.get("nonce") != self.nonce:
            raise WorkspaceError("Command supervisor identity does not match")
        kind = frame.get("kind")
        if self.terminal is not None:
            raise WorkspaceError("Command supervisor sent data after its terminal frame")
        if kind == "started":
            return
        if kind == "output":
            stream, encoded = frame.get("stream"), frame.get("data")
            if stream not in ("stdout", "stderr") or not isinstance(encoded, str):
                raise WorkspaceError("Invalid command output frame")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise WorkspaceError("Invalid base64 command output") from exc
            remaining = max(0, self.limit - len(self.stdout) - len(self.stderr))
            (self.stdout if stream == "stdout" else self.stderr).extend(data[:remaining])
            if len(data) > remaining:
                raise self.overflow()
            return
        if kind in ("exit", "limit", "timeout", "stopped", "fenced"):
            self.terminal = cast(str, kind)
            if kind == "exit":
                code = frame.get("code")
                if type(code) is not int:
                    raise WorkspaceError("Missing direct command exit code")
                self.exit_code = code
            return
        if kind == "error":
            raise WorkspaceError("Remote command supervisor failed")
        raise WorkspaceError("Unknown command supervisor frame")


async def _consume(client: RenderAsync, sandbox_id: str, launch: str, capture: _Capture) -> None:
    """Read Render output events and require both a complete supervisor result and a successful stream exit."""
    stream = client.experimental.sandboxes.exec(sandbox_id, launch)
    sdk_exit: int | None = None
    async with AsyncExitStack() as stack:
        if isinstance(stream, AsyncGenerator):
            stack.push_async_callback(stream.aclose)
        async for event in stream:
            if isinstance(event, SandboxExecOutput):
                if sdk_exit is not None:
                    raise WorkspaceError("Render output followed its terminal exit")
                if event.stream != "stdout":
                    # The supervisor reserves stderr for interpreter-level failures.
                    raise WorkspaceError("Command supervisor emitted unexpected stderr")
                capture.feed(event.data)
            elif type(event) is SandboxExecExit:
                if sdk_exit is not None or type(event.exit_code) is not int:
                    raise WorkspaceError("Invalid Render exec terminal event")
                sdk_exit = event.exit_code
            else:
                raise WorkspaceError("Invalid Render exec event")
    if sdk_exit != 0 or capture.buffer or capture.terminal is None:
        raise WorkspaceError("Command supervisor stream ended without a complete result")


async def _stop_shielded(
    client: RenderAsync, sandbox_id: str, launch: str, nonce: str, stop_timeout: float
) -> asyncio.CancelledError | None:
    """Send an independent stop request that remains alive while its caller is being cancelled."""

    async def stop() -> None:
        async with asyncio.timeout(stop_timeout):
            capture = _Capture(nonce, 4096)
            await _consume(client, sandbox_id, launch, capture)
            if capture.terminal != "stopped":
                raise WorkspaceError("Command stop did not acknowledge its fence")

    # The child task owns the timeout. Neither AnyIO level cancellation nor
    # repeated native Task.cancel calls may abandon an already-dispatched stop.
    task = asyncio.create_task(stop())
    interrupted: asyncio.CancelledError | None = None
    with anyio.CancelScope(shield=True):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                interrupted = exc
            except Exception:  # noqa: BLE001 - rethrown by task.result below
                break
    try:
        task.result()
    except BaseException as error:
        if interrupted is not None:
            interrupted.add_note("Command stop also failed; inspect the retained sandbox reference")
            raise interrupted from error
        raise
    return interrupted


async def run_command(
    client: RenderAsync,
    sandbox_id: str,
    command: WorkspaceCommand,
    *,
    working_dir: str,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    max_output_bytes: int = 1_048_576,
    stop_timeout: float = 12.0,
) -> CommandResult:
    """Run once, preserving the sandbox on timeout, cancellation or stream failure.

    Strings run with /bin/sh -c; sequences are literal argv. The backend owns
    argument-form validation and environment-state translation. Exceptions from
    Render propagate unchanged, including after an uncertain start. No command
    is replayed. Stop failures remain explicit in exception notes and causes.
    """
    argv = _argv(command)
    if timeout is not None:
        timeout = _positive(timeout, "timeout")
    stop_timeout = _positive(stop_timeout, "stop_timeout")
    if type(max_output_bytes) is not int or max_output_bytes < 1:
        raise ValueError("max_output_bytes must be a positive integer")
    if not working_dir.startswith("/") or "\0" in working_dir:
        raise ValueError("working_dir must be an absolute path without NUL")
    environment = dict(env or {})
    if any(type(key) is not str or type(value) is not str for key, value in environment.items()):
        raise TypeError("env must map strings to strings")
    if any(
        not key or "=" in key or "\0" in key or "\0" in value for key, value in environment.items()
    ):
        raise ValueError("env contains an invalid name or NUL")
    nonce = uuid.uuid4().hex
    claim = f"{_CLAIM_ROOT}/vibe-render-command-{nonce}"
    source = files("vibe_render").joinpath("_command_runner.py").read_text()
    config: dict[str, object] = {
        "claim": claim,
        "nonce": nonce,
        "argv": argv,
        "cwd": working_dir,
        "env": environment,
        "timeout": timeout,
        "limit": max_output_bytes,
    }
    launch = _launch(source, "run", config)
    stop = _launch(source, "stop", {"claim": claim, "nonce": nonce})
    capture = _Capture(nonce, max_output_bytes)
    try:
        deadline = asyncio.timeout(timeout)
        try:
            async with deadline:
                await _consume(client, sandbox_id, launch, capture)
        except TimeoutError as exc:
            if not deadline.expired():
                raise  # A provider TimeoutError retains its original identity.
            stdout, stderr = capture.text()
            raise WorkspaceTimeoutError(
                "Command deadline exceeded", stdout=stdout, stderr=stderr
            ) from exc
        stdout, stderr = capture.text()
        if capture.terminal == "limit":
            raise capture.overflow()
        if capture.terminal == "timeout":
            raise WorkspaceTimeoutError("Command deadline exceeded", stdout=stdout, stderr=stderr)
        if capture.terminal != "exit" or capture.exit_code is None:
            raise WorkspaceError("Command was fenced before it could start")
        return CommandResult(exit_code=capture.exit_code, stdout=stdout, stderr=stderr)
    except BaseException as original:
        try:
            interrupted = await _stop_shielded(client, sandbox_id, stop, nonce, stop_timeout)
        except BaseException as stop_error:
            if isinstance(stop_error, asyncio.CancelledError) and not isinstance(
                original, asyncio.CancelledError
            ):
                # A new cancellation during failure cleanup still takes priority.
                raise stop_error from original
            original.add_note(
                f"Command stop was not confirmed in sandbox {sandbox_id}; "
                "retain its reference for inspection or explicit disposal"
            )
            # Preserve cancellation and provider exception identity. Frameworks
            # may overwrite implicit __context__, so make cleanup evidence explicit.
            raise original from stop_error
        if interrupted is not None and not isinstance(original, asyncio.CancelledError):
            raise interrupted from original
        raise
