---
name: code
description: Run a coding task in this project's temporary Render sandbox and return a patch for review. Use when the user asks to code, fix, refactor, or test in Render.
---

Use this plugin's `start_task`, `task_status`, and `cancel_task` tools. The tools are bound to the project selected at installation. They cannot select an arbitrary host directory.

1. Turn the user's request into one concrete coding task with observable acceptance checks. Preserve constraints and ask only for a missing requirement that changes the implementation.
2. Call `start_task` once. Include the requested tests in the task. It starts a child Vibe session whose file and shell tools run in Render. A task uses paid compute, a 300-second coding deadline, at most 20 model turns and 100,000 model tokens. The sandbox denies outbound network access; dependencies must already exist in a prepared snapshot.
3. Show the returned run ID. Poll `task_status` at reasonable intervals until the state is terminal. Never start a duplicate task because a response is delayed. Use `cancel_task` only when the user asks to stop.
4. Report the actual Vibe outcome, patch path, and cleanup status. A model saying it finished does not prove tests passed. Read the retained Vibe output for checks actually run, and distinguish those from independent verification.
5. Offer the patch for review. Never apply it automatically. It is relative to the uploaded source snapshot, including any existing uncommitted edits. Before a user chooses to apply it, use `git apply --check` from the project root. Applying a patch changes their source files and requires their instruction.

Do not claim the outer Vibe chat, its other plugins, or its host tools are sandboxed. Only the child coding task uses Render. The native connection is experimental and pinned to Vibe 2.26.1. On `cleanup_failed`, surface the sandbox ID and the need to retry termination. Never report resource cleanup as confirmed without `cleanup: terminated`.
