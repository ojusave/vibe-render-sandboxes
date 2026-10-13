"""Own a Render sandbox and translate Vibe's file and shell requests into remote work."""

# Async timers bound remote work; JSON and base64 carry binary file bytes without corruption.
import asyncio
import base64
import json
from dataclasses import asdict
from pathlib import PurePosixPath

from .commands import run_command
from .types import WorkspaceOutputLimitError, WorkspaceTimeoutError

# A fresh sandbox always uses the same remote project location. No host path is mounted.
WORKSPACE = "/workspace/project"
MAX_READ = 8 * 1024 * 1024

# This small program runs inside Render. Opening without blocking avoids hanging on named pipes.
READ_PROGRAM = """import os, stat, json, base64, sys
try:
 fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NONBLOCK)
 with os.fdopen(fd, "rb") as stream:
  data = stream.read(int(sys.argv[2])) if stat.S_ISREG(os.fstat(stream.fileno()).st_mode) else None
except OSError:
 data = None
print(json.dumps({"contentBase64": None if data is None else base64.b64encode(data).decode()}))
"""


class Remote:
    """The host owns the credentials; this object sends only commands and source files."""

    def __init__(self, client, sandbox_id: str, *, command_limit: float = 120):
        self.client, self.id = client, sandbox_id
        self.command_limit = command_limit
        self.failed = False
        self.counts = {"execute": 0, "readFile": 0, "timeouts": 0}

    async def execute(self, command: str, cwd: str, timeout: float | None) -> dict:
        """Run a command once, stopping its process group when its time expires."""
        if self.failed:
            raise RuntimeError("Sandbox connection failed; start a new task")
        self.counts["execute"] += 1
        limit = min(timeout, self.command_limit) if timeout is not None else self.command_limit
        try:
            result = await run_command(
                self.client,
                self.id,
                command,
                working_dir=cwd,
                timeout=limit,
                max_output_bytes=8 * 1024 * 1024,
            )
        except WorkspaceTimeoutError as error:
            # An unconfirmed stop or overflowing output makes further use unsafe or unreliable.
            if isinstance(error, WorkspaceOutputLimitError) or getattr(error, "__notes__", []):
                self.failed = True
                raise RuntimeError("Remote command failed; sandbox will be terminated") from error
            self.counts["timeouts"] += 1
            raise
        except BaseException:
            self.failed = True
            raise
        output = asdict(result)
        output["exitCode"] = output.pop("exit_code")
        return output

    async def read_file(self, path: str, max_bytes: int) -> dict:
        """Read only remote bytes. A missing file returns null, not a host-file fallback."""
        if not PurePosixPath(path).is_absolute() or "\0" in path:
            raise ValueError("The remote file path must be absolute")
        if type(max_bytes) is not int or not 0 <= max_bytes <= MAX_READ:
            raise ValueError("File reads must be between 0 and 8 MiB")
        if self.failed:
            raise RuntimeError("Sandbox connection failed; start a new task")
        self.counts["readFile"] += 1
        result = await run_command(
            self.client,
            self.id,
            ["python3", "-c", READ_PROGRAM, path, str(max_bytes)],
            working_dir="/",
            timeout=30,
            max_output_bytes=12 * 1024 * 1024,
        )
        if result.exit_code:
            raise RuntimeError("Remote file read failed")
        return json.loads(result.stdout)

    async def patch(self) -> bytes:
        """Export additions, edits and deletions as data. Never apply them on the host."""
        # Git runs only in Render here. Disabling hooks and external diff tools gives a plain patch.
        result = await self.execute(
            "git -c core.hooksPath=/dev/null -c core.fsmonitor=false add -A -- . && "
            "git -c core.hooksPath=/dev/null -c core.fsmonitor=false diff --cached "
            "--binary --no-ext-diff --no-textconv > /tmp/vibe-render.patch && "
            "test $(wc -c < /tmp/vibe-render.patch) -le 8388608",
            WORKSPACE,
            30,
        )
        if result["exitCode"]:
            raise RuntimeError("Patch export failed or exceeded 8 MiB")
        record = await self.read_file("/tmp/vibe-render.patch", MAX_READ)
        if record["contentBase64"] is None:
            raise RuntimeError("Patch export is missing")
        return base64.b64decode(record["contentBase64"], validate=True)


async def wait_ready(client, sandbox_id: str) -> None:
    """Creation starts a machine; wait up to 90 seconds before sending it work."""
    async with asyncio.timeout(90):
        while True:
            status = (await client.experimental.sandboxes.from_id(sandbox_id)).status
            if status == "running":
                return
            if status in {"errored", "terminated"}:
                raise RuntimeError(f"Sandbox became {status}")
            await asyncio.sleep(1.5)


async def terminate(client, sandbox_id: str) -> None:
    """Confirm this exact machine is terminated, including when get no longer returns it."""
    async with asyncio.timeout(60):
        await client.experimental.sandboxes.terminate(sandbox_id)
        while True:
            # Terminated sandboxes remain visible in this filtered, paginated collection.
            cursor = None
            while True:
                page = await client.experimental.sandboxes.list(status="terminated", cursor=cursor)
                if any(item.id == sandbox_id for item in page.sandboxes):
                    return
                cursor = page.next_cursor
                if not cursor:
                    break
            await asyncio.sleep(2)
