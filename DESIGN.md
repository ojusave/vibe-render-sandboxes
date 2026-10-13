# Design and existing integrations

Checked October 13, 2026. This is a community development preview. It is not an official Mistral or Render product announcement.

## Job and acceptance standard

A developer asks Vibe to fix code, and receives a reviewable patch supported by real execution evidence. The original project stays unchanged, model and Render credentials stay on the host, and paid sandboxes are terminated after use. Success requires both a real Vibe tool loop in Render and independent checks of the patch, not just a model's completion message.

## What already exists

| Existing work | What it provides | Why this implementation is distinct |
| --- | --- | --- |
| [Docker's Mistral Vibe Sandbox guide](https://docs.docker.com/guides/mistral-vibe-sandbox/) | Runs Vibe within Docker's sandbox environment. | This adapter keeps the model process on the host and routes the child Vibe's coding tools to Render. |
| [Pixelstrudel/mistral-vibe-sandbox](https://github.com/Pixelstrudel/mistral-vibe-sandbox) | A Podman-based Vibe environment with project mounts. | This plugin copies a project to managed remote compute and returns a patch. |
| [VibePod CLI](https://github.com/VibePod/vibepod-cli) | Local container wrappers for coding agents, including Vibe. | Different runtime/provider mechanism; it does not supply this Render connection. |
| Existing Render sandbox helpers | CLI skills, generic execution helpers, and other framework adapters. | Reuse their Render lifecycle knowledge and process supervisor, but implement Vibe's actual protocol and native plugin entry point. |

Scoped GitHub and web searches did not identify a maintained Render-specific Vibe plugin. This does not establish that none exists. The small `jenperson/mistral-vibe-in-sandbox` repository was also found, but its fetched page had no explanatory README, so no detailed capability comparison is claimed.

## Why a native plugin plus a child session

The [Vibe 2.26.1 source](https://github.com/mistralai/mistral-vibe/tree/v2.26.1) defines a native Agent Plugins manifest, but no manifest field selects a sandbox provider for an already-running conversation. Its documented [experimental agent socket](https://github.com/mistralai/mistral-vibe/blob/v2.26.1/README.md#agent-socket---agent-socket-experimental) is available to programmatic sessions.

The plugin therefore exposes three task tools through MCP. A user-invoked skill starts a bounded child Vibe session and polls its receipt. That child receives only built-in coding tools, uses a fresh host configuration, and sends shell/file operations through a private Unix socket to the Render adapter. The original conversation remains an ordinary Vibe session.

The connection implements protocol 2: `agent/initialize`, `sandbox/execute`, and `sandbox/readFile`. It validates the Vibe version, handles concurrent requests, preserves nonzero exit codes and separate output streams, returns binary file contents as encoded data, stops work when its caller disconnects, and never falls back to local execution.

The command supervisor is adapted from the same author's Pydantic sandbox adapter. It uses separate output pipes and process-group registration to stop a command even when the original execution stream fails. Control frames carry unique command IDs and encoded output, rather than treating arbitrary program output as control instructions. It is process management within a sandbox, not an isolation boundary between hostile processes in that same sandbox.

## Product decisions and limits

- Project-bound installation prevents task arguments from choosing arbitrary host directories. Git history and conventional secret files are not uploaded. The source manifest records exactly which files were copied and their hashes.
- The host credentials file is chosen during installation. This is necessary because Vibe's MCP launcher does not inherit arbitrary shell environment variables. Only recognized provider settings are read; values are not copied into plugin manifests.
- Tasks return a patch rather than applying edits. Git's private exclude file suppresses generated caches and conventional secrets in normal exports. Patches are untrusted data and must be reviewed before application.
- Task duration, token count, command output, upload size and sandbox lifetime are bounded. One task per project can run at a time. Receipts retain cleanup failures and sandbox IDs.
- Both [Render Sandboxes](https://render.com/docs/sandboxes) and Vibe's socket are evolving interfaces. Direct Mistral API authentication and the OpenRouter route both passed live validation. Prepared snapshots, Windows support, public app previews and production recovery still require additional validation or implementation as documented in the README.

The next useful validation is a real developer's small repository using its normal test command and dependency snapshot. The adoption measure is whether that developer can review and accept a useful patch without repairing the environment manually. Fixture validation does not establish workflow adoption, official partnership status, or production readiness.
