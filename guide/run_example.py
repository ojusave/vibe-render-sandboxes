"""Run the guide's real installed-plugin exercise and independent Render verification."""

# These standard Python helpers read terminal options, locate files, and start async work.
# Async work lets this host program wait for Render and model responses without blocking tools.
import argparse
import asyncio
import os
import runpy
import time
from pathlib import Path

# Read key=value settings as data; never execute the credentials file as shell commands.
from dotenv import dotenv_values


def main():
    """Load a selected private file and reuse the same integration check as development."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--provider", choices=["mistral", "openrouter"], default="mistral")
    args = parser.parse_args()
    credentials = args.env_file.expanduser().resolve(strict=True)
    # The verifier needs Render access. Model settings are also read by the installed plugin.
    # Ignore unrelated settings so this file cannot choose a Python import path or executable.
    allowed = {
        "RENDER_API_KEY", "RENDER_WORKSPACE_ID", "RENDER_CLI_CONFIG_PATH",
        "VIBE_RENDER_USE_CLI_LOGIN", "MISTRAL_API_KEY", "OPENROUTER_API_KEY",
        "VIBE_RENDER_MODEL",
    }
    for key, value in dotenv_values(credentials, interpolate=False).items():
        if key in allowed and value:
            os.environ[key] = value
    os.environ["VIBE_RENDER_PROVIDER"] = args.provider
    os.environ["VIBE_RENDER_ENV_FILE"] = str(credentials)
    # Reject an unfinished template before allocating paid resources. A CLI login is optional.
    workspace = os.environ.get("RENDER_WORKSPACE_ID", "")
    model_key = "MISTRAL_API_KEY" if args.provider == "mistral" else "OPENROUTER_API_KEY"
    if not workspace.startswith("tea-") or "replace_me" in workspace:
        parser.error("Set RENDER_WORKSPACE_ID in the private settings file")
    if not os.environ.get(model_key) or "replace_me" in os.environ[model_key]:
        parser.error(f"Set {model_key} in the private settings file")
    # Each run gets its own private folder. Existing evidence is never overwritten.
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts" / ("guide-" + time.strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True, mode=0o700)
    print(f"Evidence: {output}", flush=True)
    # Loading this checked-in helper defines its functions without executing its paid main().
    # Reusing it ensures the guide tests the same installed MCP entry point as development.
    checks = runpy.run_path(str(root / "tests" / "live_check.py"))
    try:
        asyncio.run(checks["plugin_run"](output))
    except Exception as error:  # noqa: BLE001 - sanitize provider request details
        # Provider errors can contain request data. Report the category and private evidence path.
        print(f"Verification failed ({type(error).__name__}). Inspect {output}", flush=True)
        raise SystemExit(1) from None
    print("Independent verification: passed", flush=True)
    print("Original project: unchanged", flush=True)
    print("Coding and verification sandboxes: terminated", flush=True)


if __name__ == "__main__":
    # Importing this file does not start a paid test; running it explicitly does.
    main()
