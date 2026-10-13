# Render Sandboxes for Mistral Vibe

[![Checks](https://github.com/ojusave/vibe-render-sandboxes/actions/workflows/checks.yml/badge.svg)](https://github.com/ojusave/vibe-render-sandboxes/actions/workflows/checks.yml)

Let [Mistral Vibe](https://github.com/mistralai/mistral-vibe), the terminal coding assistant, edit and test a copy of your project in a temporary [Render Sandbox](https://render.com/docs/sandboxes). Get the proposed changes back for review. Your original source files stay unchanged until you apply them.

[Walkthrough](guide/README.md) · [Operations](guide/operations.md) · [Test results](VALIDATION.md) · [Design](DESIGN.md)

After installation, ask Vibe:

```text
/renderSandbox:code Fix the median bug in stats.py and run the tests.
```

The plugin returns `changes.patch`, a file describing the edits, plus execution logs and a record of whether the sandbox was stopped. You can inspect and test the changes before accepting them.

## Get started

### Prerequisites

You need macOS or Linux, [Git](https://git-scm.com/install/), [uv](https://docs.astral.sh/uv/getting-started/installation/) to install Python and its libraries, a [Render workspace with Sandboxes enabled](https://render.com/docs/sandboxes#1-confirm-access), and Mistral model access. An API key is a secret that authorizes software to make requests to your account. The [credential table](guide/README.md#prerequisites) explains which keys and workspace identifier to supply.

Render compute and model requests incur charges. The repair example creates two temporary sandboxes, one for coding and one for independent verification.

### Set up with your coding assistant

Open your coding assistant in the Git project you want to work on and paste this prompt. It sets up the plugin; the paid example is a separate step.

```text
Set up the Render Sandboxes plugin for Mistral Vibe in this Git project.
Use https://github.com/ojusave/vibe-render-sandboxes and its guide/README.md.

1. Inspect this project. Reuse an existing plugin checkout or clone it
   into a separate folder. Install the versions pinned in uv.lock.
2. Follow the guide's credential setup, preserving existing settings.
   Have me enter missing secrets in a local editor. Never print keys.
3. Follow "Use the plugin in your project", including the ignore rules.
   Inspect an existing installation instead of overwriting it.
4. Run the local checks in guide/operations.md. Verify this project's
   plugin points to the intended Python environment and settings file.
5. Report what passed, any blocked step, and the exact command to open
   the installed Vibe in this project. Include a sample sandbox task.

Stop after setup. Do not start paid tasks or apply source patches.
Report installation and local checks separately from live testing.
If setup fails, name the failing step and next action.
```

### Set up manually

In a terminal, enter the folder where you keep projects, then run:

```shell
# Download the plugin and enter its folder.
git clone https://github.com/ojusave/vibe-render-sandboxes.git
cd vibe-render-sandboxes
# Install Python 3.12, the plugin, and the supported Vibe version.
uv sync --python 3.12 --locked
```

[Configure your private settings file](guide/README.md#2-configure-access), then choose [the repair example below](#try-the-repair-example) or [install into your own project](guide/README.md#5-use-the-plugin-in-your-project).

## Try the repair example

From the configured `vibe-render-sandboxes` folder, run:

```shell
# Ask Vibe to repair the sample in Render, then independently test its patch.
.venv/bin/python guide/run_example.py --env-file "$PWD/.vibe/render.env"
```

The sample's median function returns **3 instead of 2.5** for `[4, 1, 3, 2]`. The helper installs the plugin into a disposable sample project, asks Vibe to fix it, and checks the changes in a fresh sandbox using protected tests and additional cases.

Successful output, excerpted from the recorded live run:

```text
Independent verification: passed
Original project: unchanged
Coding and verification sandboxes: terminated
```

The command prints an `Evidence:` folder with the patch and test results. Startup can be quiet; wait for verification to finish. See [result inspection and cleanup](guide/README.md#4-inspect-the-result-and-cleanup) for the files to check.

## How it works

1. The plugin copies your project to Render and starts a separate Vibe coding session on your computer.
2. That session requests model responses from your computer. Its file edits and commands execute in the sandbox.
3. The plugin downloads a patch, attempts sandbox termination, and saves the cleanup result alongside the logs.

Account keys remain on your computer. Source contents and tool results go to the selected model service. Only the separate coding task uses Render; the outer Vibe chat retains its normal access to your computer. The guide includes an [architecture diagram](guide/README.md#how-it-works).

## Status and limits

Community development preview, pinned to **Vibe 2.26.1** and **Render's Python library 1.2.0**. Render Sandboxes is in early access, and Vibe's remote execution connection is experimental.

Outbound networking is denied, so projects need dependencies already available in the sandbox. There are no public app previews or persistent coding sessions. See [dependencies and limits](guide/operations.md#dependencies-and-limits) for supported project sizes, task deadlines, and the optional snapshot path.

[Recorded verification](VALIDATION.md) includes 20 automated tests and live coding runs with direct Mistral and OpenRouter, independent patch checks, and confirmed cleanup. The outer interactive Vibe chat and prepared dependency snapshots have not been live-tested.

For development, run the [local checks](guide/operations.md#development-checks). For returned changes, follow [patch review and application](guide/operations.md#review-and-apply-a-patch).

[MIT licensed](LICENSE). This is an independent integration example, not an official Mistral or Render product.
