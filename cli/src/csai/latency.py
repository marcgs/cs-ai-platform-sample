"""Sequential, model-free comparison of local execution and authenticated MCP paths."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agent_framework import MCPStreamableHTTPTool
from agent_framework.foundry import FoundryToolbox
from azure.identity.aio import AzureCliCredential
from pydantic import BaseModel, ConfigDict

from diagnostics_mcp.tools import DiagnosticsTools, MachineContext

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from mcp.types import CallToolResult


class Sample(BaseModel):
    """One timed operation; failed calls are not successful latency samples."""

    model_config = ConfigDict(extra="forbid")

    path: str
    phase: str
    session: int
    started: str
    seconds: float
    error: str | None
    result_sha256: str | None
    matches_local: bool | None


def parse_context(result: CallToolResult) -> str:
    """Reject protocol/domain errors and normalize the synthetic tool's JSON payload."""
    if result.isError:
        raise ValueError("MCP tool returned isError")
    if result.structuredContent is not None:
        return MachineContext.model_validate(result.structuredContent).model_dump_json()
    texts = [item.text for item in result.content if item.type == "text"]
    if len(texts) != 1:
        raise ValueError("Expected one machine-context JSON text result")
    return MachineContext.model_validate_json(texts[0]).model_dump_json()


def digest(value: str) -> str:
    """Compare JSON content independently of object key order and whitespace."""
    canonical = json.dumps(json.loads(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def summarize(samples: list[Sample]) -> list[dict[str, str | int | float | None]]:
    """Report each phase separately, with nearest-rank p95 and explicit failures."""
    groups = sorted({(sample.path, sample.phase) for sample in samples})
    rows: list[dict[str, str | int | float | None]] = []
    for path, phase in groups:
        group = [s for s in samples if (s.path, s.phase) == (path, phase)]
        times = sorted(s.seconds for s in group if s.error is None)
        rows.append(
            {
                "path": path,
                "phase": phase,
                "attempts": len(group),
                "errors": sum(s.error is not None for s in group),
                "min_s": min(times) if times else None,
                "median_s": statistics.median(times) if times else None,
                "p95_s": times[math.ceil(0.95 * len(times)) - 1] if times else None,
                "max_s": max(times) if times else None,
            }
        )
    return rows


async def measure_transport(
    client: MCPStreamableHTTPTool,
    *,
    path: str,
    machine_id: str,
    expected: str,
    warm_calls: int,
    session: int,
    record: Callable[[Sample], None],
) -> None:
    """Reuse one client/session across calls; separate discovery, calls and teardown."""
    phase = "initialize"
    started = datetime.now(UTC).isoformat()
    start = time.perf_counter()
    try:
        await client.connect()
        names = [
            function.name
            for function in client.functions
            if function.name == "get_machine_context"
            or function.name.endswith("___get_machine_context")
        ]
        if len(names) != 1:
            raise ValueError("Expected exactly one get_machine_context tool")
        record(
            Sample(
                path=path,
                phase=phase,
                session=session,
                started=started,
                seconds=time.perf_counter() - start,
                error=None,
                result_sha256=None,
                matches_local=None,
            )
        )
        for index in range(warm_calls + 1):
            phase = "first" if index == 0 else "warm"
            started = datetime.now(UTC).isoformat()
            start = time.perf_counter()
            result_hash: str | None = None
            matches: bool | None = None
            error: str | None = None
            try:
                value = await client.call_tool(names[0], machine_id=machine_id)
                if not isinstance(value, str):
                    raise TypeError("Expected the configured JSON result parser")
                result_hash = digest(value)
                matches = result_hash == expected
                if not matches:
                    error = "PayloadMismatch"
            except Exception as exc:
                error = type(exc).__name__
            record(
                Sample(
                    path=path,
                    phase=phase,
                    session=session,
                    started=started,
                    seconds=time.perf_counter() - start,
                    error=error,
                    result_sha256=result_hash,
                    matches_local=matches,
                )
            )
    except Exception as exc:
        record(
            Sample(
                path=path,
                phase=phase,
                session=session,
                started=started,
                seconds=time.perf_counter() - start,
                error=type(exc).__name__,
                result_sha256=None,
                matches_local=None,
            )
        )
    finally:
        start = time.perf_counter()
        started = datetime.now(UTC).isoformat()
        error = None
        try:
            await client.close()
        except Exception as exc:
            error = type(exc).__name__
        record(
            Sample(
                path=path,
                phase="close",
                session=session,
                started=started,
                seconds=time.perf_counter() - start,
                error=error,
                result_sha256=None,
                matches_local=None,
            )
        )


def read_environment(project: Path) -> dict[str, str]:
    """Read an existing azd environment without changing it; process values override it."""
    result = subprocess.run(
        ["azd", "env", "get-values", "--output", "json"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )
    values: dict[str, str] = json.loads(result.stdout)
    return values | dict(os.environ)


async def run(
    *,
    environment: Mapping[str, str],
    output: Path,
    warm_calls: int,
    sessions: int,
    machine_id: str,
    order: list[str],
) -> bool:
    """Measure without models or writes to Azure; secrets stay in memory."""
    samples: list[Sample] = []
    metadata = {
        "revision": (
            await asyncio.to_thread(
                subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
            )
        ).strip(),
        "started": datetime.now(UTC).isoformat(),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("agent-framework-core", "mcp", "httpx", "azure-identity")
        },
        "environment": {
            key: environment.get(key)
            for key in (
                "AZURE_LOCATION",
                "TOOLBOX_ENDPOINT",
                "DIAGNOSTICS_MCP_ENDPOINT",
                "FOUNDRY_PROJECT_ENDPOINT",
                "FOUNDRY_MODEL_DEPLOYMENT_NAME",
                "AZURE_AI_MODEL_DEPLOYMENT_NAME",
            )
        },
        "concurrency": 1,
        "tool": "get_machine_context",
        "arguments": {"machine_id": machine_id},
        "order": order,
        "warm_calls": warm_calls,
        "sessions": sessions,
        "cold_start": "Unknown; first means a new client, not a proven server cold start.",
        "whole_diagnosis": "Not measured; this command makes no model calls.",
    }

    def record(sample: Sample) -> None:
        samples.append(sample)
        output.write_text(
            json.dumps(
                metadata
                | {"samples": [s.model_dump() for s in samples], "summary": summarize(samples)},
                indent=2,
            )
            + "\n"
        )

    tools = DiagnosticsTools.from_seed()
    expected: str | None = None
    for index in range(warm_calls + 1):
        started = datetime.now(UTC).isoformat()
        start = time.perf_counter()
        value = tools.machine_context(machine_id).model_dump_json()
        elapsed = time.perf_counter() - start
        result_hash = digest(value)
        expected = result_hash
        record(
            Sample(
                path="in_process",
                phase="first" if index == 0 else "warm",
                session=0,
                started=started,
                seconds=elapsed,
                error=None,
                result_sha256=result_hash,
                matches_local=True,
            )
        )
    assert expected is not None
    # ARM listkeys is a read operation, despite its POST verb. Never persist its response.
    app_id = (
        f"/subscriptions/{environment['AZURE_SUBSCRIPTION_ID']}/resourceGroups/"
        f"{environment['AZURE_RESOURCE_GROUP']}/providers/Microsoft.Web/sites/"
        f"{environment['DIAGNOSTICS_MCP_FUNCTION_NAME']}"
    )
    keys: dict[str, dict[str, str]] = json.loads(
        await asyncio.to_thread(
            subprocess.check_output,
            [
                "az",
                "rest",
                "--method",
                "post",
                "--url",
                f"https://management.azure.com{app_id}/host/default/listkeys?api-version=2024-04-01",
                "--output",
                "json",
            ],
            text=True,
        )
    )
    async with AzureCliCredential() as credential:
        for session in range(sessions):
            for path in order:
                client = (
                    FoundryToolbox(
                        credential,
                        url=environment["TOOLBOX_ENDPOINT"],
                        parse_tool_results=parse_context,
                    )
                    if path == "toolbox"
                    else MCPStreamableHTTPTool(
                        "diagnostics",
                        environment["DIAGNOSTICS_MCP_ENDPOINT"],
                        static_headers={"x-functions-key": keys["systemKeys"]["mcp_extension"]},
                        load_prompts=False,
                        parse_tool_results=parse_context,
                    )
                )
                await measure_transport(
                    client,
                    path=path,
                    machine_id=machine_id,
                    expected=expected,
                    warm_calls=warm_calls,
                    session=session,
                    record=record,
                )
    print(json.dumps(summarize(samples), indent=2))
    return all(sample.error is None for sample in samples)


def main() -> None:
    """Run a low-sample authenticated comparison, writing only a gitignored artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--azd-project", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path(".azure/a6-latency.json"))
    parser.add_argument("--machine-id", default="M-0007")
    parser.add_argument("--warm-calls", type=int, default=3)
    parser.add_argument("--sessions", type=int, default=1)
    parser.add_argument("--direct-first", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.warm_calls <= 10 or not 1 <= args.sessions <= 3:
        parser.error("Use 0-10 warm calls and 1-3 sessions; concurrency is always one")
    if (
        subprocess.run(
            ["git", "check-ignore", "--quiet", str(args.output)],
            check=False,
        ).returncode
        != 0
    ):
        parser.error("--output must be gitignored; raw metadata must not be committed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    environment = read_environment(args.azd_project)
    success = asyncio.run(
        run(
            environment=environment,
            output=args.output,
            warm_calls=args.warm_calls,
            sessions=args.sessions,
            machine_id=args.machine_id,
            order=["direct", "toolbox"] if args.direct_first else ["toolbox", "direct"],
        )
    )
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
