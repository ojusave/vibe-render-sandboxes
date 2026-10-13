"""Run one bounded coding task and preserve its evidence before destroying the sandbox."""

# These host-only helpers manage processes, private directories, locks, and reproducible receipts.
import asyncio
import fcntl
import json
import os
import shlex
import shutil
import signal
import sys
import tempfile
import time
import uuid
from contextlib import suppress
from importlib.metadata import version
from pathlib import Path

from .config import render_client
from .project import SKIP_DIRS, SKIP_NAMES, snapshot
from .remote import WORKSPACE, Remote, terminate, wait_ready
from .socket_server import AgentSocket


def write_json(path: Path, value: dict) -> None:
    """Replace a receipt atomically so a polling reader never sees half-written JSON."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def child_config(home: Path) -> dict[str, str]:
    """Create a clean Vibe configuration with one model provider and no host extensions."""
    provider = os.environ.get("VIBE_RENDER_PROVIDER", "mistral")
    if provider == "mistral":
        key, url, model, backend = (
            "MISTRAL_API_KEY",
            "https://api.mistral.ai/v1",
            "devstral-latest",
            "mistral",
        )
    elif provider == "openrouter":
        key, url, model, backend = (
            "OPENROUTER_API_KEY",
            "https://openrouter.ai/api/v1",
            "mistralai/devstral-2512",
            "generic",
        )
    else:
        raise ValueError("VIBE_RENDER_PROVIDER must be mistral or openrouter")
    if not os.environ.get(key):
        raise ValueError(f"Set {key} on the host before starting a task")
    model = os.environ.get("VIBE_RENDER_MODEL", model)
    # JSON-quoted strings are valid TOML strings, including escaping a supplied model name.
    home.mkdir(mode=0o700)
    config = [
        'active_model = "render-task"',
        "enable_update_checks = false",
        "enable_telemetry = false",
        "disable_welcome_banner_animation = true",
        "[[providers]]",
        f"name = {json.dumps(provider)}",
        f"api_base = {json.dumps(url)}",
        f"api_key_env_var = {json.dumps(key)}",
        f"backend = {json.dumps(backend)}",
        "[[models]]",
        f"name = {json.dumps(model)}",
        f"provider = {json.dumps(provider)}",
        'alias = "render-task"',
        "max_context_length = 200000",
        "max_output_tokens = 8192",
    ]
    (home / "config.toml").write_text("\n".join(config) + "\n")
    # Deliberately forward only the model credential. Render keys never enter the child or sandbox.
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "VIBE_HOME": str(home),
        key: os.environ[key],
        "NO_COLOR": "1",
        "TERM": "dumb",
    }


async def stop_child(process) -> None:
    """Stop Vibe and its own helper processes if the task is cancelled or exceeds its deadline."""
    if process and process.returncode is None:
        # The child may finish between the return-code check and the signal.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), 10)
        except TimeoutError:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


async def run_task(
    project: Path, task: str, *, run_id: str | None = None, time_limit: int = 300
) -> dict:
    """Copy source, start Vibe against Render, export a patch, and always attempt cleanup."""
    if not task.strip() or len(task) > 32000:
        raise ValueError("A task must contain 1 to 32000 characters")
    if not 30 <= time_limit <= 600:
        raise ValueError("Task time limit must be between 30 and 600 seconds")
    if version("mistral-vibe") != "2.26.1":
        raise ValueError("This release requires mistral-vibe 2.26.1")
    project = project.resolve(strict=True)
    root = project / ".vibe-render"
    root.mkdir(mode=0o700, exist_ok=True)
    # The lock prevents separate plugin or CLI processes from creating overlapping paid tasks.
    lock = (root / "active.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError("A Render task is already active for this project") from None
    run_id = run_id or uuid.uuid4().hex
    run = root / "runs" / run_id
    run.mkdir(parents=True, mode=0o700)
    receipt = {
        "run_id": run_id,
        "state": "preparing",
        "sandbox_id": None,
        "cleanup": "not_created",
        "project": str(project),
        "directory": str(run),
        "vibe_version": "2.26.1",
        "render_sdk": "1.2.0",
        "started_at": time.time(),
    }
    client = remote = process = None
    socket_dir = None
    try:
        # Validate credentials and source before allocating paid compute.
        env = child_config(run / "home")
        client = render_client()
        manifest = snapshot(project, run / "source")
        write_json(run / "source-manifest.json", manifest)
        (run / "task.txt").write_text(task)
        receipt["state"] = "creating"
        write_json(run / "receipt.json", receipt)
        options = {"timeout_seconds": time_limit + 240, "network_policy": "deny-all"}
        if os.environ.get("VIBE_RENDER_SNAPSHOT"):
            options["snapshot_id"] = os.environ["VIBE_RENDER_SNAPSHOT"]
        # Shield creation so cancellation does not lose a newly allocated sandbox's identity.
        creation = asyncio.create_task(client.experimental.sandboxes.create(**options))
        try:
            sandbox = await asyncio.shield(creation)
        except asyncio.CancelledError:
            sandbox = await creation
            receipt.update(sandbox_id=sandbox.id, cleanup="pending")
            raise
        receipt.update(sandbox_id=sandbox.id, cleanup="pending", state="starting")
        write_json(run / "receipt.json", receipt)
        await wait_ready(client, sandbox.id)
        remote = Remote(client, sandbox.id)
        # Clear only the fixed project folder inside Render when starting from a prepared image.
        reset = await remote.execute(
            "rm -rf /workspace/project && mkdir -p /workspace/project", "/", 30
        )
        if reset["exitCode"]:
            raise RuntimeError("Could not prepare a clean sandbox project directory")
        # Only the sanitized source directory is uploaded, never Git history, local settings, or keys.
        await client.experimental.sandboxes.copy_to(sandbox.id, run / "source", WORKSPACE)
        # Git's private exclude file keeps caches and conventional secrets out of the returned patch.
        ignores = (
            "\n".join(
                [
                    *(name + "/" for name in sorted(SKIP_DIRS)),
                    *sorted(SKIP_NAMES),
                    ".env*",
                    "*.pem",
                    "*.key",
                    "*.p12",
                    "*.pfx",
                ]
            )
            + "\n"
        )
        init = await remote.execute(
            "git init -q && printf %s " + shlex.quote(ignores) + " > .git/info/exclude && "
            "git -c core.hooksPath=/dev/null add -A && "
            "git -c core.hooksPath=/dev/null -c user.name=VibeRender "
            "-c user.email=local@example.invalid commit -q -m baseline",
            WORKSPACE,
            30,
        )
        if init["exitCode"]:
            raise RuntimeError("Could not prepare the sandbox's patch baseline")
        # A short path fits macOS's Unix-socket length limit. This temporary directory stores no code.
        socket_dir = Path(tempfile.mkdtemp(prefix="vr-", dir="/tmp"))
        socket_path = socket_dir / "agent.sock"
        async with AgentSocket(remote, socket_path):
            command = [
                str(Path(sys.executable).with_name("vibe")),
                "--prompt-file",
                str(run / "task.txt"),
                "--agent-socket",
                str(socket_path),
                "--auto-approve",
                "--max-turns",
                "20",
                "--max-tokens",
                "100000",
                "--time-limit",
                str(time_limit),
                "--output",
                "json",
                "--output-dir",
                str(run / "vibe"),
            ]
            # Allow only built-in coding tools. No web tools, subagents, host MCP servers, or hooks.
            for tool in ("bash", "read_file", "write_file", "edit", "grep"):
                command.extend(["--enabled-tools", tool])
            receipt["state"] = "coding"
            write_json(run / "receipt.json", receipt)
            with (
                (run / "vibe.stdout.log").open("wb") as stdout,
                (run / "vibe.stderr.log").open("wb") as stderr,
            ):
                process = await asyncio.create_subprocess_exec(
                    *command, cwd=run, env=env, stdout=stdout, stderr=stderr, start_new_session=True
                )
                try:
                    await asyncio.wait_for(process.wait(), time_limit + 45)
                finally:
                    await stop_child(process)
            receipt["vibe_exit_code"] = process.returncode
        # A stopped or failed model can still leave useful work. Label the outcome and retain it.
        exported = run / "vibe" / "export.json"
        if exported.exists():
            data = json.loads(exported.read_text())
            receipt["vibe_outcome"] = data.get("outcome")
        if not remote.failed:
            patch = await remote.patch()
            (run / "changes.patch").write_bytes(patch)
            receipt.update(patch=str(run / "changes.patch"), patch_bytes=len(patch))
        receipt["state"] = "finished" if process.returncode == 0 else "incomplete"
    except asyncio.CancelledError:
        receipt["state"] = "cancelled"
        raise
    except Exception as error:
        # Keep actionable setup errors, but redact SDK exception bodies that can include request data.
        receipt.update(state="failed", error_type=type(error).__name__)
        if isinstance(error, ValueError):
            receipt["error"] = str(error)
        raise
    finally:

        async def cleanup():
            try:
                await stop_child(process)
            except Exception:  # noqa: BLE001 - still terminate Render if the host child fails to stop
                receipt["child_stop"] = "unconfirmed"
                receipt["state"] = "cleanup_failed"
            if receipt["sandbox_id"] and client:
                try:
                    await terminate(client, receipt["sandbox_id"])
                    receipt["cleanup"] = "terminated"
                except Exception:  # noqa: BLE001 - preserve cleanup and redact external errors
                    receipt["cleanup"] = "unconfirmed"
                    receipt["state"] = "cleanup_failed"

        # Keep cleanup alive through cancellation, including a second stop request.
        cleanup_task = asyncio.create_task(cleanup())
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                continue
        cleanup_task.result()
        if remote:
            receipt["operations"] = remote.counts
        receipt["ended_at"] = time.time()
        write_json(run / "receipt.json", receipt)
        if socket_dir:
            shutil.rmtree(socket_dir)
        lock.close()
    return receipt
