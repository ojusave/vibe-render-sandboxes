# Render Sandboxes for Mistral Vibe

Ask Vibe to fix code, let it edit and test a copy in Render, then review the returned changes. The original project stays unchanged. This community plugin is a development preview, pinned to **Mistral Vibe 2.26.1** and **Render Python SDK 1.2.0**.

**[Follow the step-by-step guide](guide/README.md)** to install it, run a real repair, independently verify the answer, and confirm cleanup.

## What it does

- Adds `/renderSandbox:code` to one Vibe project, with `start_task`, `task_status`, and `cancel_task` tools.
- Starts a separate Vibe coding session on your computer. Its file and shell actions run against a project copy in a temporary Render sandbox.
- Saves a reviewable `changes.patch`, execution logs, source manifest, and cleanup receipt under the project's `.vibe-render/runs/` folder.
- Keeps Render and model credentials on the host. Neither is injected into the sandbox. Source and tool results are sent to the selected model service.

Only the child coding task uses Render. The outer Vibe chat and its other tools retain their usual host access. The plugin does not apply changes automatically.

## Install

You need macOS or Linux, Git, Python 3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/), [Render Sandboxes access](https://render.com/docs/sandboxes), and model API access. Render compute and model requests incur charges.

```shell
# Download this plugin and install the library versions tested together.
git clone https://github.com/ojusave/vibe-render-sandboxes.git
cd vibe-render-sandboxes
uv sync --python 3.12 --locked
```

Follow the guide's [credential setup](guide/README.md#2-configure-access) and [project installation](guide/README.md#5-use-the-plugin-in-your-project). The tested direct Mistral model is `mistral-medium-3-5`; the tested OpenRouter option is `mistralai/devstral-2512`.

## Scope and limits

Tasks default to five minutes, 20 model turns, and 100,000 tokens. Source uploads are capped at 5,000 files and 50 MiB. Outbound sandbox network access is denied. Projects needing extra packages require a trusted prepared dependency snapshot; that optional path has not been live-validated.

Render Sandboxes is in early access and Vibe's agent socket is experimental. Website previews, persistent sessions, Windows, and automatic merges are outside this release. The time and token limits do not promise an exact dollar cost.

## Tests and design

[VALIDATION.md](VALIDATION.md) records local tests, real Mistral and OpenRouter runs, independent checks, and remaining gaps. [DESIGN.md](DESIGN.md) explains the connection and existing alternatives. [Operations](guide/operations.md) covers limits, patch review, and recovery.

```shell
# Keep test-only Vibe settings separate from your normal profile.
mkdir -p artifacts/test-home
VIBE_HOME="$PWD/artifacts/test-home" .venv/bin/pytest -q --basetemp=artifacts/unit
# Check Python code and build an installable package.
.venv/bin/ruff check src tests examples guide
.venv/bin/python -m build
```

The guide's paid test invokes the installed plugin through real tool messages, runs a Mistral coding session in Render, then checks the patch in a second Render sandbox. Ordinary unit tests require no account keys.

This is an independent integration example, not an official Mistral or Render product.
