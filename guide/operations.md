# Operate the Vibe plugin

Use these instructions after the <a href="README.md" target="_blank" rel="noopener noreferrer">walkthrough</a> succeeds. Commands run on your computer. Replace example paths and resource IDs with your own values.

## Reuse a Render CLI login

The Render command-line program (CLI) can authenticate through your browser. Install <a href="https://render.com/docs/cli" target="_blank" rel="noopener noreferrer">Render CLI</a> 2.28.0 or later and run:

```shell
# Open the browser login and select the workspace where sandboxes should run.
render login
render workspace set tea-your-workspace
```

In your private `.vibe/render.env`, remove the `RENDER_API_KEY` placeholder and add `VIBE_RENDER_USE_CLI_LOGIN=1`. Keep `RENDER_WORKSPACE_ID` set to the same selected workspace. The plugin reads `~/.render/cli.yaml` and checks the workspace and official API host before using that saved login. This option avoids copying the CLI token into another file.

## Model selection and OpenRouter

The Mistral API key authorizes model calls; `VIBE_RENDER_MODEL` selects the model. If your account reports that `mistral-medium-3-5` is unavailable, choose a tool-capable model listed for your account. This release does not automatically switch providers or models after an error.

To use the tested OpenRouter route, add `OPENROUTER_API_KEY` from <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">OpenRouter's key page</a>, change `VIBE_RENDER_MODEL` to `mistralai/devstral-2512`, and use `--provider openrouter` when running the guide or installing the plugin. OpenRouter and its selected model provider then receive the model requests and supplied source instead of the direct Mistral endpoint. That key stays on the host as well.

## Run without an outer chat

The terminal command below starts the same child coding session directly. Run it from the downloaded plugin folder. It prints a receipt when the task and cleanup end; progress is also saved in the project's `.vibe-render/runs/` directory.

```shell
# Choose the project and host-only credential file; replace the task and tests as needed.
.venv/bin/vibe-render run --project /absolute/path/to/your/project \
  --env-file /absolute/path/to/vibe-render-sandboxes/.vibe/render.env \
  --provider mistral \
  --task "Fix the median function, preserve input, and run python3 -m unittest -v."
```

A successful model run has `state: finished`, a patch path, and `cleanup: terminated`. This command does not add the guide's independent verification step for arbitrary projects. Read the retained test output and check important behavior separately.

## Review and apply a patch

A patch records proposed changes relative to the source copied for that run, including any uncommitted local edits present then. It is untrusted model output. First read it, then check whether it still fits your current files. Run these commands from the original project's root:

```shell
# Display the proposed changes without executing them. Press q to leave the viewer.
less /absolute/path/to/changes.patch
# Check compatibility without modifying files. Silence means this check passed.
git apply --check /absolute/path/to/changes.patch
```

If the patch fits and you decide to accept it, apply it:

```shell
# This changes the original project's source files. Run only after reviewing the patch.
git apply /absolute/path/to/changes.patch
```

Run your own acceptance tests in an appropriate test environment. A clean patch application does not prove correctness. Local edits made after the upload may prevent clean application; there is no automatic merge.

## Dependencies and limits

The sandbox denies outbound network access. The sample uses Python's built-in libraries, so no package downloads are needed. For a different project, `VIBE_RENDER_SNAPSHOT` can select a trusted, available <a href="https://render.com/docs/sandboxes#snapshots" target="_blank" rel="noopener noreferrer">prepared filesystem snapshot</a> containing its dependencies. The adapter replaces `/workspace/project` inside that sandbox with the uploaded source. Snapshot restoration is implemented but untested in the live evidence, so it is not part of the verified setup path.

| Limit | Behavior |
| --- | --- |
| Coding deadline | 300 seconds by default; direct CLI permits 30 to 600 seconds |
| Model work | At most 20 turns and 100,000 tokens |
| Individual command | At most 120 seconds |
| Source upload | At most 5,000 files and 50 MiB |
| File reads and patch export | At most 8 MiB each |
| Concurrent task | One active task per installed project |
| Coding sandbox lifetime | Coding deadline plus 240 seconds |

Git history, Git-ignored files, local Vibe settings, conventional secret files, and common build/cache directories are excluded. Source exclusions also apply to tracked files; the source manifest records which files were copied or excluded. Symbolic links and Git submodules are rejected. The exclusions are not a general secret scanner.

There are no public app preview URLs, persistent interactive sessions, Windows support, package-download allowlists, or automatic patch application in this release. Model cost exports are not billed-cost measurements because provider prices are not configured here.

## Cleanup and recovery

Normal completion downloads the patch before terminating the coding sandbox. Cancellation stops the child model process and attempts sandbox termination. `cleanup: terminated` means the adapter found the exact sandbox ID in Render's terminated list.

If a receipt reports `cleanup_failed`, keep its `sandbox_id` and use the intended workspace. Install the <a href="https://render.com/docs/cli" target="_blank" rel="noopener noreferrer">Render CLI</a> if needed, then:

```shell
# Select the workspace that owns the recorded sandbox.
render workspace set tea-your-workspace
# Stop only the sandbox whose exact ID appears in the receipt.
render ea sandboxes stop sbx-your-sandbox --confirm
# Verify that exact ID appears as terminated; use the CLI's paging options if needed.
render ea sandboxes list --status terminated
```

> [!WARNING]
> Stopping a sandbox destroys its filesystem. Preserve wanted files first if normal patch export failed. Stopping one sandbox does not terminate other runs, delete snapshots, or remove local credentials and logs.

A lost create response may leave an uncertain outcome before an ID is available. The adapter does not retry creation automatically. Every created coding sandbox has a finite lifetime, which provides a fallback if the host process disappears. A forced host shutdown can leave a stale receipt until you inspect Render directly; an unfinished local receipt is not confirmation that cleanup failed or succeeded.

The command supervisor stops ordinary child processes after a command timeout. A process group is not a protection boundary against hostile code deliberately creating another group; terminating the sandbox is the whole-environment cleanup mechanism.

## When a run fails

| Symptom | Next action |
| --- | --- |
| Setup error before a sandbox ID exists | Check the selected project, private settings file, workspace access, and model key |
| Model exit or outcome is not successful | Read `vibe.stderr.log` and the saved Vibe output in the run folder; verify model access and task size |
| Package installation fails inside the sandbox | Outbound networking is denied; use a prepared dependency environment or the dependency-free sample |
| Independent checks fail | Read `independent-checks.log` and the patch; do not apply the change solely because Vibe finished |
| Another task is already active | Check its receipt or use `task_status`; do not start a duplicate task |
| Cleanup is unconfirmed | Retain the sandbox ID and follow cleanup and recovery above |
| Installed plugin path no longer works | Restore the recorded Python environment, or reinstall after the old task has finished |

The guide keeps raw evidence locally. Logs, prompts, and copied source can contain project information, so review and redact them before sharing a report.

## Remove the project installation

Finish or cancel active tasks and verify cleanup first. Then remove only `<project>/.vibe/plugins/render-sandboxes` using your file manager. Reload Vibe with `/reload`. This removes this project's plugin registration; it does not delete evidence, credentials, or remote resources. If you later reinstall, run the installer from the plugin environment you intend to keep.
