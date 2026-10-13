"""Terminal entry points for installation, direct tasks and Vibe's plugin server."""

# Argument parsing turns terminal text into named settings; shell quoting protects installed paths.
import argparse
import asyncio
import json
import os
import shlex
import shutil
import sys
from importlib.resources import files
from pathlib import Path

from .session import run_task


def install(project: Path, *, env_file: Path | None = None, provider: str = "mistral") -> Path:
    """Add a native project plugin without changing Vibe's global settings or storing keys."""
    project = project.resolve(strict=True)
    if env_file is not None:
        env_file = env_file.resolve(strict=True)
    destination = project / ".vibe" / "plugins" / "render-sandboxes"
    if destination.exists():
        raise ValueError(f"Plugin already exists at {destination}; inspect it before replacing")
    shutil.copytree(str(files("vibe_render").joinpath("plugin")), destination)
    # Vibe permits a plugin-relative executable. The wrapper uses this installed Python environment.
    wrapper = destination / "run-server"
    command = [
        sys.executable,
        "-m",
        "vibe_render.cli",
        "serve",
        "--project",
        str(project),
        "--provider",
        provider,
    ]
    if env_file:
        command.extend(["--env-file", str(env_file)])
    wrapper.write_text(
        "#!/bin/sh\n# Launch this project's adapter; credentials are read from the host at runtime.\nexec "
        + shlex.join(command)
        + "\n"
    )
    wrapper.chmod(0o755)
    return destination


def main():
    """Choose a single operation; no arbitrary Vibe flags can bypass the sandbox connection."""
    parser = argparse.ArgumentParser(description="Run Vibe coding tasks in Render Sandboxes")
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("install", "run", "serve"):
        action = actions.add_parser(name)
        action.add_argument("--project", type=Path, required=True, help="Absolute Git project root")
        action.add_argument(
            "--env-file", type=Path, help="Host-only credentials file; values are not copied"
        )
        action.add_argument("--provider", choices=["mistral", "openrouter"], default=None)
        if name == "run":
            action.add_argument(
                "--task", required=True, help="Coding request and acceptance checks"
            )
            action.add_argument("--time-limit", type=int, default=300)
    args = parser.parse_args()
    try:
        if args.action != "install" and args.env_file:
            # MCP deliberately does not inherit arbitrary shell settings. Read only known settings
            # from the file the user selected during installation, never from a model-supplied path.
            from dotenv import dotenv_values

            allowed = {
                "MISTRAL_API_KEY",
                "OPENROUTER_API_KEY",
                "RENDER_API_KEY",
                "RENDER_WORKSPACE_ID",
                "VIBE_RENDER_USE_CLI_LOGIN",
                "RENDER_CLI_CONFIG_PATH",
                "VIBE_RENDER_MODEL",
                "VIBE_RENDER_SNAPSHOT",
                "VIBE_RENDER_PROVIDER",
            }
            for key, value in dotenv_values(
                args.env_file.resolve(strict=True), interpolate=False
            ).items():
                if key in allowed and value:
                    os.environ[key] = value
        if args.provider:
            os.environ["VIBE_RENDER_PROVIDER"] = args.provider
        if args.action == "install":
            print(
                f"Installed {install(args.project, env_file=args.env_file, provider=args.provider or 'mistral')}\nOpen Vibe in this project, trust it, and use /reload."
            )
        elif args.action == "serve":
            from .mcp_server import make_server

            make_server(args.project).run(transport="stdio")
        else:
            result = asyncio.run(run_task(args.project, args.task, time_limit=args.time_limit))
            print(json.dumps(result, indent=2))
            if result["state"] != "finished" or result["cleanup"] != "terminated":
                raise SystemExit(1)
    except (ValueError, FileNotFoundError) as error:
        parser.exit(2, f"Setup error: {error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Task interrupted; inspect the saved receipt for cleanup status.\n")
    except Exception as error:  # noqa: BLE001 - sanitize external error data
        # SDK messages may contain request information, so the terminal gets only their category.
        parser.exit(
            1, f"Task failed ({type(error).__name__}); inspect .vibe-render/runs/*/receipt.json\n"
        )


if __name__ == "__main__":
    main()
