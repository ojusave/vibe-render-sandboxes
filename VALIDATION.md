# Validation record

Validated October 13, 2026. Result: development preview verified, including a real Mistral coding task through the installed plugin. This is not a production-readiness certification.

## Versions and entry point

- Python 3.12.13 on macOS; Mistral Vibe 2.26.1, upstream reference commit `4ae5c5955da8e761318916bdb1a7f46f0b50c7d0`.
- Render Python SDK 1.2.0; MCP 1.28.1. Dependency versions are captured in `uv.lock`.
- Real model: `mistralai/devstral-2512` through OpenRouter. Availability and tool support were checked against OpenRouter's model catalog before the run. A subsequent direct Mistral API run with `mistral-medium-3-5` also passed; see the direct-provider evidence below.
- Native plugin format validated using Vibe's own inspector. A real MCP client invoked the installed plugin's `run-server` executable using the restricted environment supplied by Vibe-style plugin launchers. The credential file was read on the host at runtime.

## Automated checks

**20 tests pass**, covering separate stdout/stderr and nonzero exits; binary and missing-file reads; nonblocking handling of special files; deadlines and child-process termination; output limits; invalid timeout values; forged result rejection; source exclusions and dirty-file contents; symlink rejection; the actual installed Vibe client's handshake and timeout parsing; concurrent socket requests; client-disconnect cancellation; no local fallback after transport failure; native plugin validation; credential separation; real MCP tool discovery and argument boundaries; and cleanup after a readiness failure.

`ruff check src tests examples` passes. The documented `uv sync --python 3.12 --locked` installation was exercised. Unit results are retained in `artifacts/unit-results.xml`. The source archive and installable wheel both built successfully. After installing the wheel, imports resolved from its installed package rather than the editable source, and all 20 tests passed again (`artifacts/wheel-results.xml`). Archive inspection confirmed the native plugin files were included and credentials, local environments, and run artifacts were excluded.

The local stream fixture launches the packaged command supervisor as a subprocess. It does not claim to reproduce Render's infrastructure. The production inline-supervisor path was separately exercised in the live checks below.

## Final live evidence

Evidence directory: `artifacts/live-20261013-010921/`.

| Check | Result and retained identity |
| --- | --- |
| Render execution smoke test | `sbx-18p4gdb6uec8u01pc73bl3olg`: separate output streams and exit 7 preserved; Render and model credentials absent from sandbox environment; a timed-out shell's child could not create a delayed marker; subsequent commands succeeded; missing file returned null. Cleanup confirmed terminated. |
| Native plugin coding task | Run `212854a837264ee2aeb6f49cf2d0f215`, sandbox `sbx-18p4gdb6uef49v7es739rtuhg`: Devstral repaired the median function through the real Vibe agent socket. Vibe exited 0 with outcome `finished`; 18 execute operations and two file reads were recorded, including adapter setup/export operations. |
| Reviewable output | Returned a 944-byte patch changing `stats.py`. Generated Python cache files were excluded. The original source and test file were byte-for-byte unchanged. The patch applied to a disposable review copy. |
| Independent verification | Fresh sandbox `sbx-18p4gdb6uem0n74is7393fdi0` ran the preserved four original tests plus six additional numeric cases, input-preservation checks and empty-input handling. The extra checks were held back from the coding model. All passed, and the verifier sandbox was confirmed terminated. |
| User cancellation | Run `cca32b8095ea4be09269b025b736e771`, sandbox `sbx-18p4gdb6v724s728c73ctlvrg`: started through the same installed plugin, cancelled after reaching the coding stage, ended `cancelled` with cleanup `terminated`. |

All four sandboxes in the final validation sequence were confirmed terminated by exact ID. The coding task's sandbox was terminated before independent validation began. Raw receipts are `render-smoke.json`, `plugin-receipt.json`, and `cancellation-receipt.json`; test output is `independent-checks.log`. Source, prompt, Vibe export, and logs remain under the fixture project's `.vibe-render/runs/` directories and are excluded from distribution.

An earlier exploratory run also completed and cleaned up its two sandboxes (`sbx-18p4gdb6u3sc9v7es739qrl1g`, `sbx-18p4gdb6u3vd9fdbs73ecevu0`). Its patch included generated cache files, which prompted the export fix. The final evidence above supersedes that run for patch-quality and isolated-verification claims.

## Direct Mistral follow-up

An authenticated request to `https://api.mistral.ai/v1/models` returned HTTP 200. The account exposed `mistral-medium-3-5` with chat and function-calling support; `devstral-latest` was not listed, so the private host configuration explicitly selects the available Medium model. The key is stored in a mode-0600, Git-ignored host settings file, not in plugin manifests or sandbox environments.

The installed plugin then completed run `92ee16899df94be8b05fda624ff2977f` using Mistral directly. Coding sandbox `sbx-18p4gdb6vbd3l550s73a8gssg` returned a 929-byte source patch, Vibe exit 0 and outcome `finished`, with 18 execute operations and two reads including adapter setup/export. Original source and tests remained byte-for-byte unchanged.

Fresh verification sandbox `sbx-18p4gdb6vbjrl550s73a8hj30` passed the four preserved original tests, six hidden numeric cases, input-preservation checks and empty-input handling. Both exact sandbox IDs were confirmed terminated. Evidence is in `artifacts/mistral-direct-20261013-021114/plugin-receipt.json` and `independent-checks.log`. This closes the earlier direct-authentication validation gap; it does not imply deployment of an always-on Render service.

## Review findings and remaining limits

The review fixed native plugin credential loading, generated-cache export, a cancellation-test transport mismatch, and a host-child exit race that could otherwise interfere with cleanup. Model-generated code still had harmless trailing whitespace, which `git apply` reported; the adapter preserves generated content for review rather than silently rewriting it.

No browser-driven outer Vibe UI session was exercised. The actual native plugin inspector, installed MCP executable, Vibe child CLI and socket client were tested. Public preview URLs, Windows, prepared dependency snapshots, large repositories, resuming coding sessions and adversarial process escape were not validated. The plugin has no automatic patch application.

The finite sandbox lifetime is a recovery fallback, not proof of immediate cleanup after a forcibly killed host process or a lost create response. Vibe's cost export is not a billed-cost measurement because provider prices are not configured in this prototype. Render and Vibe both expose evolving interfaces; versions are pinned accordingly.

Next practical validation: install into one real small project with its normal dependency snapshot and test command, then have a developer review and accept a useful patch. That would validate workflow adoption beyond this reproducible fixture.

## Published walkthrough preparation

The separate `guide/` follows the existing OpenAI Agents and OpenRouter guide structure. Its `run_example.py` uses the installed native plugin through the same real MCP check as development. The guide was executed on October 13, 2026 with direct Mistral `mistral-medium-3-5` and the explicitly enabled Render CLI login option. The default Render API-key option is supported by the SDK; this run used the saved CLI credential.

Run `d6d2f93d35634b1f973a7fb5f1cdba4c` reproduced the original failing tests, returned a 1261-byte patch, preserved the original source and tests, passed independent verification in a fresh Render sandbox, and confirmed both exact sandbox IDs terminated. Local evidence is retained under `artifacts/guide-20261013-022833/`; raw evidence and credentials are excluded from the public repository.

All 20 unit tests, Ruff, source archive construction, and wheel construction passed after adding the guide helper. The public repository includes a GitHub Actions workflow for these credential-free checks. A passing workflow does not stand in for the paid live run.

## GitHub source verification

Published source revision: [`c38be771f6bc2fa6b7481c1ff8e4bbbfb992f858`](https://github.com/ojusave/vibe-render-sandboxes/commit/c38be771f6bc2fa6b7481c1ff8e4bbbfb992f858). Downloaded the source archive from GitHub into a disposable installation folder and compared all 31 files byte-for-byte with the reviewed commit. A separate `uv sync --python 3.12 --locked` environment installed successfully. The documented `guide/run_example.py` then ran against real Mistral and Render services using the existing private credential file.

Coding run `0a0973e463084335b325b8f9cb7c7e7a` produced a 940-byte patch. The original failing tests were reproduced, original project files remained unchanged, the four preserved tests and independent cases passed, and both sandbox IDs were confirmed terminated. This was a new live run from the published source, not a replay of the earlier receipts. The GitHub source download and installation were tested; the clone URL was verified against the published repository without creating a second working clone.

GitHub's [Linux test and build workflow](https://github.com/ojusave/vibe-render-sandboxes/actions/runs/38377038805) passed all 20 tests, Ruff, and both package builds. The guide and Mermaid diagram were rendered at desktop and narrow widths locally and inspected on GitHub. Local relative links were checked. Authored guide links specify safe new-tab attributes; GitHub strips those attributes and controls navigation on its rendered pages.

The staged files and built archives were scanned against the actual credentials used for validation, with zero matches. Private settings, raw runs, environments, and cache files were excluded. A final portability adjustment makes the guide's trusted before-state check use its selected Python interpreter instead of assuming a global `python3` command; this does not change the remote coding or verification path.
