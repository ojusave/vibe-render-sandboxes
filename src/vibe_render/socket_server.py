"""A private local socket lets Vibe ask the host to operate its remote sandbox."""

# Each connection contains one JSON request and response. Concurrent connections remain independent.
import asyncio
import json
import math
from pathlib import Path

from .remote import WORKSPACE
from .types import WorkspaceTimeoutError


class AgentSocket:
    """Implement Vibe 2.26.1's experimental protocol, with no local execution fallback."""

    def __init__(self, remote, path: Path):
        self.remote, self.path = remote, path
        self.tasks = set()
        self.server = None
        self.initialized = False

    async def __aenter__(self):
        """Restrict the socket to this OS user before starting the Vibe process."""
        self.path.parent.chmod(0o700)
        self.server = await asyncio.start_unix_server(
            self.handle, path=self.path, limit=16 * 1024 * 1024
        )
        self.path.chmod(0o600)
        return self

    async def __aexit__(self, *_):
        """Stop accepting requests and cancel active commands before sandbox termination."""
        self.server.close()
        await self.server.wait_closed()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.path.unlink(missing_ok=True)

    async def dispatch(self, method: str, params: dict) -> dict:
        """Validate the protocol at its boundary, before any remote operation."""
        if method == "agent/initialize":
            if params.get("protocolVersion") != 2 or params.get("vibeVersion") != "2.26.1":
                raise ValueError("This plugin requires Vibe 2.26.1 and agent protocol 2")
            self.initialized = True
            return {"protocolVersion": 2, "workspace": WORKSPACE, "python": "python3"}
        if not self.initialized:
            raise ValueError("Initialize the agent connection first")
        if method == "sandbox/execute":
            command, cwd, timeout = params.get("command"), params.get("cwd"), params.get("timeout")
            if not isinstance(command, str) or not isinstance(cwd, str) or not cwd.startswith("/"):
                raise ValueError("Commands need text and an absolute remote working directory")
            if timeout is not None and (
                type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0
            ):
                raise ValueError("Command timeout must be positive and finite")
            return await self.remote.execute(command, cwd, timeout)
        if method == "sandbox/readFile":
            path = params.get("path")
            if not isinstance(path, str):
                raise ValueError("Remote file path must be text")
            return await self.remote.read_file(path, params.get("maxBytes"))
        raise LookupError("Unknown agent-socket method")

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Reply safely, and stop a command if Vibe disconnects while it is running."""
        task = asyncio.current_task()
        self.tasks.add(task)
        operation = disconnected = None
        request_id = None
        try:
            line = await asyncio.wait_for(reader.readline(), 10)
            request = json.loads(line)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError("Expected a JSON-RPC 2.0 request")
            request_id = request.get("id")
            if type(request_id) not in {str, int} or not isinstance(
                request.get("params", {}), dict
            ):
                raise ValueError("Request needs an ID and object parameters")
            operation = asyncio.create_task(
                self.dispatch(request.get("method"), request.get("params", {}))
            )
            disconnected = asyncio.create_task(reader.read(1))
            done, _ = await asyncio.wait(
                {operation, disconnected}, return_when=asyncio.FIRST_COMPLETED
            )
            if disconnected in done:
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
                return
            result = await operation
            reply = {"result": result}
        except WorkspaceTimeoutError:
            reply = {
                "error": {
                    "code": -32001,
                    "message": "Remote command deadline exceeded",
                    "data": {
                        "timeoutSeconds": min(
                            request.get("params", {}).get("timeout") or self.remote.command_limit,
                            self.remote.command_limit,
                        )
                    },
                }
            }
        except LookupError:
            reply = {"error": {"code": -32601, "message": "Unknown method"}}
        except (ValueError, TypeError):
            reply = {
                "error": {"code": -32602, "message": "Invalid agent-socket request or version"}
            }
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - preserve cleanup and redact external errors
            # Do not put credentials, source text, or SDK response bodies in model-visible errors.
            reply = {
                "error": {
                    "code": -32002,
                    "message": "Render connection failed; inspect the task receipt",
                }
            }
        finally:
            for pending in (operation, disconnected):
                if pending and not pending.done():
                    pending.cancel()
            await asyncio.gather(
                *(p for p in (operation, disconnected) if p), return_exceptions=True
            )
            self.tasks.discard(task)
            if task.cancelling() or (
                disconnected
                and disconnected.done()
                and not disconnected.cancelled()
                and operation
                and operation.cancelled()
            ):
                writer.close()
                await writer.wait_closed()
        try:
            writer.write(
                (json.dumps({"jsonrpc": "2.0", "id": request_id, **reply}) + "\n").encode()
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
