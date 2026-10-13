"""Expose short-lived tool calls while a longer coding task runs in the background."""

# The Model Context Protocol (MCP) lets Vibe discover these named tools through standard input/output.
import asyncio
import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .session import run_task


def make_server(project: Path) -> FastMCP:
    """Bind all task tools to one project so model arguments cannot choose host paths."""
    project = project.resolve(strict=True)
    jobs, errors = {}, {}

    @asynccontextmanager
    async def lifespan(_server):
        """Closing Vibe cancels unfinished tasks, which run their sandbox cleanup."""
        try:
            yield {}
        finally:
            for job in jobs.values():
                if not job.done():
                    job.cancel()
            await asyncio.gather(*jobs.values(), return_exceptions=True)

    server = FastMCP("Render coding tasks", lifespan=lifespan, log_level="WARNING")

    @server.tool()
    async def start_task(task: str) -> dict:
        """Start one coding task in Render; return immediately with an ID to poll."""
        if any(not job.done() for job in jobs.values()):
            raise ValueError("A coding task is already running; use task_status")
        if not task.strip() or len(task) > 32000:
            raise ValueError("Task must contain 1 to 32000 characters")
        run_id = uuid.uuid4().hex

        async def work():
            try:
                await run_task(project, task, run_id=run_id)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - sanitize external error data
                # Store only the category here; setup detail, if safe, is in the persisted receipt.
                errors[run_id] = type(error).__name__

        jobs[run_id] = asyncio.create_task(work())
        return {"run_id": run_id, "state": "queued", "project": str(project)}

    @server.tool()
    async def task_status(run_id: str) -> dict:
        """Read progress, outcome, patch location and confirmed cleanup for a task."""
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid run ID")
        receipt = project / ".vibe-render" / "runs" / run_id / "receipt.json"
        if receipt.is_file():
            return json.loads(receipt.read_text())
        if run_id in errors:
            return {"run_id": run_id, "state": "failed", "error_type": errors[run_id]}
        if run_id in jobs:
            if jobs[run_id].cancelled():
                return {"run_id": run_id, "state": "cancelled", "cleanup": "not_created"}
            return {"run_id": run_id, "state": "queued"}
        raise ValueError("No such task for this project")

    @server.tool()
    async def cancel_task(run_id: str) -> dict:
        """Request cancellation; poll task_status until sandbox cleanup is confirmed."""
        if run_id not in jobs:
            raise ValueError("No active task with that ID")
        if not jobs[run_id].done():
            jobs[run_id].cancel()
        return {"run_id": run_id, "state": "cancellation_requested"}

    return server
