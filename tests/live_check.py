"""Opt-in paid verification of Render and the installed plugin with a real Mistral model."""

# Nothing runs during ordinary pytest. The explicit entry point requires host credentials.
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from vibe_render.cli import install
from vibe_render.config import render_client
from vibe_render.remote import Remote, terminate, wait_ready
from vibe_render.session import write_json
from vibe_render.types import WorkspaceTimeoutError

# These extra cases stay on the host until after the model finishes and its patch is downloaded.
HIDDEN_CHECKS = """import unittest
from stats import median
class IndependentChecks(unittest.TestCase):
 def test_cases(self):
  for values, expected in [([1],1),([0,10],5),([-8,-2,-4],-4),([-5,-1],-3),([2,2,2,2],2),([0.1,0.3],0.2)]:
   with self.subTest(values=values):
    original=values.copy()
    self.assertAlmostEqual(median(values),expected)
    self.assertEqual(values,original)
 def test_empty(self):
  with self.assertRaises(ValueError): median([])
unittest.main()
"""


async def smoke(output):
    """Exercise the real SDK, including command cancellation and exact-ID cleanup."""
    client = render_client()
    sandbox = await client.experimental.sandboxes.create(
        timeout_seconds=240, network_policy="deny-all"
    )
    evidence = {"sandbox_id": sandbox.id, "cleanup": "pending"}
    write_json(output / "render-smoke.json", evidence)
    try:
        await wait_ready(client, sandbox.id)
        remote = Remote(client, sandbox.id)
        result = await remote.execute("printf hello; printf error >&2; exit 7", "/tmp", 20)
        assert result == {"stdout": "hello", "stderr": "error", "exitCode": 7}
        evidence["exit_and_streams"] = "passed"
        # The sandbox receives no account credentials, even though the host can use both providers.
        result = await remote.execute(
            'python3 -c \'import os; assert not any(k in os.environ for k in ["RENDER_API_KEY","MISTRAL_API_KEY","OPENROUTER_API_KEY"]); print("keys absent")\'',
            "/tmp",
            20,
        )
        assert result["exitCode"] == 0
        evidence["sandbox_credentials_absent"] = True
        # An independent later read catches a child that was left running after a timeout.
        try:
            await remote.execute("(sleep 4; touch /tmp/leaked-child) & wait", "/tmp", 1)
            raise AssertionError("Expected a timeout")
        except WorkspaceTimeoutError:
            evidence["timeout"] = "raised"
        await asyncio.sleep(4.5)
        assert (
            await remote.execute("test ! -e /tmp/leaked-child && printf recovered", "/tmp", 20)
        )["stdout"] == "recovered"
        evidence["timed_out_child_stopped"] = True
        assert await remote.read_file("/tmp/no-such-file", 10) == {"contentBase64": None}
        evidence["missing_file"] = "passed"
    finally:
        await terminate(client, sandbox.id)
        evidence["cleanup"] = "terminated"
        write_json(output / "render-smoke.json", evidence)
    print(json.dumps(evidence), flush=True)


async def plugin_run(output):
    """Use the plugin's installed executable and real MCP messages to start a real coding task."""
    project = output / "project"
    shutil.copytree(Path(__file__).parents[1] / "examples" / "tiny-calc", project)
    await asyncio.to_thread(subprocess.run, ["git", "init", "-q", str(project)], check=True)
    baseline = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "unittest", "-v"],
        cwd=project, capture_output=True, text=True, check=False,
    )
    (output / "baseline-tests.log").write_text(baseline.stdout + baseline.stderr)
    assert baseline.returncode != 0, "The fixture must reproduce the bug before asking for a fix"
    print("Original tests: expected failure reproduced", flush=True)
    original = (project / "stats.py").read_bytes()
    visible_tests = (project / "test_stats.py").read_bytes()
    plugin = install(
        project,
        env_file=Path(os.environ["VIBE_RENDER_ENV_FILE"]),
        provider=os.environ.get("VIBE_RENDER_PROVIDER", "mistral"),
    )
    # Use the same wrapper Vibe loads from mcp.json. No bypass of the installed plugin entry point.
    params = StdioServerParameters(
        command=str(plugin / "run-server"), env={"PLUGIN_ROOT": str(plugin)}
    )
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
        await session.initialize()
        task = "Fix median in stats.py. Handle odd and even lists, negatives, a single value and duplicates. Empty input must raise ValueError. Do not mutate the input list. Keep the public function name. Add clear plain-language code comments. Do not modify test_stats.py. Run python3 -m unittest -v to verify. Work only in the supplied sandbox project."
        started = await session.call_tool("start_task", {"task": task})
        assert not started.isError, started
        run_id = json.loads(started.content[0].text)["run_id"]
        print(f"Started plugin task {run_id}", flush=True)
        last_state = None
        async with asyncio.timeout(480):
            while True:
                result = await session.call_tool("task_status", {"run_id": run_id})
                receipt = json.loads(result.content[0].text)
                if receipt["state"] != last_state:
                    print(f"Task state: {receipt['state']}", flush=True)
                    last_state = receipt["state"]
                if (
                    receipt["state"]
                    in {"finished", "failed", "incomplete", "cancelled", "cleanup_failed"}
                    and receipt.get("cleanup") != "pending"
                ):
                    break
                await asyncio.sleep(3)
    write_json(output / "plugin-receipt.json", receipt)
    assert receipt["state"] == "finished", receipt
    assert receipt["cleanup"] == "terminated", receipt
    assert receipt["patch_bytes"] > 0, receipt
    assert b"__pycache__" not in Path(receipt["patch"]).read_bytes()
    assert (project / "stats.py").read_bytes() == original, "Original source changed"
    assert (project / "test_stats.py").read_bytes() == visible_tests
    # Apply the untrusted patch only to a disposable review copy, never the original project.
    review = output / "review-copy"
    shutil.copytree(project, review, ignore=shutil.ignore_patterns(".vibe", ".vibe-render", ".git"))
    await asyncio.to_thread(subprocess.run, ["git", "init", "-q", str(review)], check=True)
    await asyncio.to_thread(
        subprocess.run, ["git", "-C", str(review), "apply", "--check", receipt["patch"]], check=True
    )
    await asyncio.to_thread(
        subprocess.run, ["git", "-C", str(review), "apply", receipt["patch"]], check=True
    )
    assert (review / "test_stats.py").read_bytes() == visible_tests, (
        "Model modified protected tests"
    )
    (review / "independent_checks.py").write_text(HIDDEN_CHECKS)
    # Execute generated code only in a fresh Render sandbox, with host-held checks added afterward.
    client = render_client()
    verifier = await client.experimental.sandboxes.create(
        timeout_seconds=120, network_policy="deny-all"
    )
    receipt["verification_sandbox_id"] = verifier.id
    write_json(output / "plugin-receipt.json", receipt)
    try:
        await wait_ready(client, verifier.id)
        await client.experimental.sandboxes.copy_to(verifier.id, review, "/workspace/verify")
        checks = await Remote(client, verifier.id).execute(
            "python3 -m unittest -v test_stats && python3 independent_checks.py",
            "/workspace/verify",
            30,
        )
        (output / "independent-checks.log").write_text(checks["stdout"] + checks["stderr"])
        assert checks["exitCode"] == 0, checks
    finally:
        await terminate(client, verifier.id)
        receipt["verification_cleanup"] = "terminated"
        write_json(output / "plugin-receipt.json", receipt)
    receipt["independent_checks"] = "passed: six extra cases, input preservation, empty input"
    receipt["original_project_unchanged"] = True
    write_json(output / "plugin-receipt.json", receipt)
    print(json.dumps(receipt, indent=2), flush=True)


async def main():
    """Keep each paid verification run in a separate local evidence folder."""
    output = Path("artifacts") / ("live-" + time.strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True)
    print(f"Evidence: {output.resolve()}", flush=True)
    await smoke(output)
    await plugin_run(output.resolve())


if __name__ == "__main__":
    asyncio.run(main())
