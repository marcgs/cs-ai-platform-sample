# cs-platform

The reusable agent harness. An agent is declared by a spec and built by the platform, which wires in the cross-cutting capabilities once for every agent.

| Module | Provides |
|---|---|
| `spec.py` | `AgentSpec` and `load_spec()`: name, version, description, instructions file, tool sources, eval suite |
| `settings.py` | `PlatformSettings.from_env()`: Foundry project and model deployment, toolbox/MCP endpoint, Cosmos DB, Application Insights |
| `factory.py` | `build_agent()`, plus `foundry_client()` and `episode_store()` for the Azure-backed defaults |
| `retry.py` | A bounded, asynchronous 429-only retry policy for one Foundry model turn |
| `capture.py` | Middleware that records every run as an episode: input, tool calls (arguments, result, duration, errors), structured output, token usage, trace ID |
| `episodes.py` | `Episode`, `ToolCall`, `Feedback`; the `EpisodeStore` protocol with in-memory and Cosmos DB implementations |
| `evals.py` | Eval harness: `EvalCase`, `EvalSuite` (cases, thresholds, evaluators), `run_suite()` with concurrency and retries, `SuiteResult` with metrics and gate failures |
| `evidence.py` | `Evidence`: the cited unit (source, ref, excerpt) agents put in their output and evaluators verify |
| `telemetry.py` | `configure_telemetry()` for processes outside Foundry hosting: Azure Monitor export plus agent instrumentation |

```python
spec = load_spec(Path("agents/rca/agent.spec.yaml"))
settings = PlatformSettings.from_env()
agent = build_agent(
    spec,
    client=foundry_client(settings, credential),
    store=episode_store(settings, credential),
    tools=[diagnostics_tools],
    response_format=RcaReport,
)
response = await agent.run("M-0001: overlay drift and stage temperature alarm")
episode_id = response.additional_properties["episode_id"]
```

Capture is deterministic: the platform writes the episode, not the model. A failing episode store is logged and never fails the user's request.

`foundry_client()` disables the OpenAI SDK's broader automatic retries and retries only
model 429s: at most four attempts and 120 seconds of total waiting per turn. Server
`Retry-After` (seconds or HTTP date) and millisecond delays take precedence over exponential
backoff with jitter. A server delay exceeding the remaining wait budget ends the turn;
it is never shortened. Cancellation and non-429 failures propagate immediately.
Streaming retries stop at the first update, even metadata-only output. Tools and earlier
model turns are never replayed. The successful stream's original finalizer is preserved.

Each 429 produces a sanitized warning and a `cs_platform.model.rate_limit` span event
with attempt, delay, retry decision and whether streaming output was emitted. Recovered
runs remain successful; exhausted runs retain the existing failed-episode recording.
This does not change model capacity. Hosted validation and the live eval gate require
a separately approved feature deployment and serialized model traffic; offline checks
do not establish those acceptance results.

## Tests

`tests/conftest.py` provides `ScriptedChatClient`, a chat client that returns scripted model turns while Agent Framework's real tool-invocation loop runs the tools. The capture tests cover streaming and non-streaming runs, tool failures, model failures, invalid structured output and store outages, all without Azure.
