# Render Sandboxes for Mistral Vibe

[![Checks](https://github.com/ojusave/vibe-render-sandboxes/actions/workflows/checks.yml/badge.svg)](https://github.com/ojusave/vibe-render-sandboxes/actions/workflows/checks.yml)

Give [Mistral Vibe](https://github.com/mistralai/mistral-vibe), the terminal coding assistant, a separate place to edit and run code. This plugin copies your project into a temporary [Render Sandbox](https://render.com/docs/sandboxes), runs a Vibe coding task there, and returns the proposed changes for review.

For example, after installation, enter this in Vibe:

```text
/renderSandbox:code Fix the median calculation in stats.py. Preserve the input list and run python3 -m unittest -v.
```

Vibe can read files, make edits, and run tests against the copy. The plugin saves the changes in `changes.patch`, a file describing the edits, along with execution logs and the sandbox's cleanup status. **Your original source files stay unchanged until you choose to apply the patch.**

Start with the quickstart below, or follow the [full walkthrough](guide/README.md) for the architecture diagram, captured output, and troubleshooting.

## How it works

1. **Start a task from Vibe.** The `/renderSandbox:code` skill starts a separate Vibe session on your computer and copies the selected project's source to Render.
2. **Edit and test in Render.** That session calls the model from your computer, while its file and shell actions execute in the sandbox. Results return to Vibe so it can inspect failures and try again.
3. **Review the result.** The plugin downloads a patch and attempts sandbox termination. It saves a run record, called a receipt, with the outcome, patch path, and confirmed cleanup status.

The plugin provides `start_task`, `task_status`, and `cancel_task` through the Model Context Protocol (MCP), the interface Vibe uses to discover and call tools. The installed skill uses those tools to start work and check progress. Ask it to cancel when you want an active task stopped.

Render and model credentials are read on your computer and are not injected into the sandbox. Source contents and tool results are sent to the selected model service. **Only the separate coding task uses Render.** The outer Vibe chat and its other tools retain their normal access to your computer.

## Prerequisites

- **macOS or Linux**, [Git](https://git-scm.com/install/), and [uv](https://docs.astral.sh/uv/getting-started/installation/). The installation command uses uv to install Python 3.12 and the required libraries.
- **A Render workspace with Sandboxes enabled.** Check for **Sandbox Group** in the Dashboard's **+ New** menu. See [access requirements](https://render.com/docs/sandboxes#1-confirm-access).
- **Mistral API access** to a model that can request tools. The sample uses `mistral-medium-3-5`, which passed the recorded live tests.

Render compute and model requests incur charges. The example below creates two temporary sandboxes: one for coding and one for independent verification.

> [!NOTE]
> This is a community development preview, pinned to **Mistral Vibe 2.26.1** and **Render's Python SDK 1.2.0**. The SDK is the library the plugin uses to communicate with Render. Render Sandboxes is in early access, and Vibe's remote execution connection is experimental.

## Quickstart

Run these commands in a terminal on your computer.

### 1. Install the plugin's environment

```shell
# Download the repository and enter its folder.
git clone https://github.com/ojusave/vibe-render-sandboxes.git
cd vibe-render-sandboxes
# Install the tested library versions into the local .venv folder.
uv sync --python 3.12 --locked
```

The `.venv` folder is a Python virtual environment: it holds this plugin's Python executable and libraries. It includes the supported Vibe version, so a separate global Vibe installation is unnecessary.

### 2. Configure access

Create a private settings file. These commands are silent on success:

```shell
# Keep local settings in a folder excluded from Git and sandbox uploads.
mkdir -p .vibe
# Copy the template without overwriting an existing settings file.
cp -n .env.example .vibe/render.env
# Allow only your computer's user account to read or change the file.
chmod 600 .vibe/render.env
```

Open `.vibe/render.env` in your editor and replace the placeholders. An API key is a secret that authorizes software to send requests to a service's application programming interface (API).

| Setting | Where to get it | What it does |
| --- | --- | --- |
| `RENDER_API_KEY` | [Render Account Settings](https://render.com/docs/api#1-create-an-api-key) | Authorizes sandbox operations in a workspace your account can access |
| `RENDER_WORKSPACE_ID` | Workspace **Settings** in the [Render Dashboard](https://dashboard.render.com/) | Selects where sandboxes run; this `tea-...` identifier is not a secret |
| `MISTRAL_API_KEY` | [Mistral's API key page](https://console.mistral.ai/api-keys) | Authorizes the model requests made by Vibe |
| `VIBE_RENDER_MODEL` | Leave `mistral-medium-3-5` if available to your account | Selects the model used for the coding task |

The plugin reads this file directly; you do not need to put keys into terminal commands. Keep it private and out of commits. If you already use the Render command-line program, you can [reuse its saved login](guide/operations.md#reuse-a-render-cli-login) instead of setting `RENDER_API_KEY`.

### 3. Try the repair example

From the `vibe-render-sandboxes` folder, run:

```shell
# Run a real coding task through the installed plugin and independently check its patch.
.venv/bin/python guide/run_example.py --env-file "$PWD/.vibe/render.env"
```

The helper installs the plugin into a disposable copy of [the sample project](examples/tiny-calc). Its broken median function returns **3 instead of 2.5** for `[4, 1, 3, 2]`. It also changes the input list and mishandles empty input.

Vibe repairs the function in Render. The helper applies the returned patch to a separate review copy, then runs the protected original tests and additional cases in a fresh Render sandbox. It checks the result independently of Vibe's completion message.

A successful run ends with these lines, captured from the published-source test:

```text
Independent verification: passed
Original project: unchanged
Coding and verification sandboxes: terminated
```

The terminal prints an `Evidence:` folder containing the patch location, test results, and both sandbox cleanup results. Startup and model responses can take time; keep the command running until verification finishes. See the [walkthrough's output explanation](guide/README.md#4-inspect-the-result-and-cleanup) if a check fails.

## Use it in your project

Start with a small Git project whose dependencies are already available in the sandbox. **Outbound network access is denied**, so commands cannot download packages. The sample above only needs Python's built-in libraries.

From the downloaded `vibe-render-sandboxes` folder, install into your project's root:

```shell
# Replace this with the absolute path to your Git project.
PROJECT=/absolute/path/to/your/project
# Register the plugin for this project using your private settings file.
.venv/bin/vibe-render install --project "$PROJECT" \
  --env-file "$PWD/.vibe/render.env" --provider mistral
```

The installer prints `Installed .../.vibe/plugins/render-sandboxes`. It preserves an existing installation by refusing to overwrite it. Keep this downloaded folder and `.venv` in place because the installed plugin points to their absolute paths.

Add `.vibe/` and `.vibe-render/` to the target project's `.gitignore` file. This keeps local settings, copied source, prompts, and run logs out of commits. Review the source you intend to upload: common secret filenames are excluded, but a secret embedded in an ordinary source file can still be copied.

Open the supported Vibe executable in that project:

```shell
# Save the executable's location before changing folders.
VIBE_EXECUTABLE="$PWD/.venv/bin/vibe"
cd "$PROJECT"
# Start Vibe in the project where the plugin is installed.
"$VIBE_EXECUTABLE"
```

Complete Vibe's normal login and trust prompt if needed. The outer chat uses its own model settings; `.vibe/render.env` configures the separate plugin task. If Vibe was already open, use `/reload`, then enter `/renderSandbox:code` followed by your task and test command.

Each run saves its patch, source manifest, logs, and `receipt.json` under `<project>/.vibe-render/runs/<run-id>/`. A receipt with `cleanup: terminated` confirms that exact sandbox ID was found in Render's terminated list. Review the patch and test output before applying it. The [operations guide](guide/operations.md#review-and-apply-a-patch) includes the review, application, and cleanup commands.

## Compatibility and limits

| Area | Current support |
| --- | --- |
| Models tested | Direct Mistral: `mistral-medium-3-5`; [OpenRouter option](guide/operations.md#model-selection-and-openrouter): `mistralai/devstral-2512` |
| Task limits | Five-minute coding deadline by default, at most 20 model turns and 100,000 tokens |
| Project size | At most 5,000 files and 50 MiB; symbolic links and Git submodules are rejected |
| Dependencies | A trusted prepared snapshot can supply installed packages; this optional path has not been live-validated |
| Execution scope | One active task per project; no public app previews, persistent sessions, Windows support, or automatic patch application |

The time and token limits do not guarantee a dollar cost. If the host disappears, a finite sandbox lifetime provides a cleanup fallback. Check the receipt and follow [recovery instructions](guide/operations.md#cleanup-and-recovery) when termination is unconfirmed.

## Verification and development

[VALIDATION.md](VALIDATION.md) records **20 passing automated tests**, live coding runs through both model routes, an additional run from the published GitHub source, independent patch checks, and confirmed cleanup. The outer interactive Vibe chat has not been automated in those tests; the native plugin inspector, installed tool server, and actual child Vibe session have been exercised.

To run the checks that require no account keys, return to the downloaded plugin folder:

```shell
# Keep test-only Vibe settings separate from your normal profile.
mkdir -p artifacts/test-home
VIBE_HOME="$PWD/artifacts/test-home" .venv/bin/pytest -q --basetemp=artifacts/unit
# Check the Python files and build the installable package.
.venv/bin/ruff check src tests examples guide
.venv/bin/python -m build
```

The [GitHub workflow](.github/workflows/checks.yml) runs these checks on Linux. The paid walkthrough adds real model and Render calls. For implementation details and existing alternatives, read [DESIGN.md](DESIGN.md).

[MIT licensed](LICENSE). This is an independent integration example, not an official Mistral or Render product.
