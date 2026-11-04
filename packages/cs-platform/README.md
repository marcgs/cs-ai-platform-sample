# cs-platform

The reusable agent harness. An agent is declared by a spec and built by the platform, which wires in the cross-cutting capabilities once for every agent.

| Module | Provides |
|---|---|
| `spec.py` | `AgentSpec` and `load_spec()`: name, version, description, instructions file, tool sources, test cases |
| `settings.py` | `PlatformSettings.from_env()`: Foundry project and model deployment, toolbox/MCP endpoint, Cosmos DB, Application Insights |
| `factory.py` | `build_agent()`, plus `foundry_client()` and `episode_store()` for the Azure-backed defaults |
| `retry.py` | A bounded, asynchronous 429-only retry policy for one Foundry model turn |
| `capture.py` | Middleware that records every run as an episode: input, tool calls (arguments, result, duration, errors), structured output, token usage, trace ID |
| `episodes.py` | `Episode`, `ToolCall`, `Feedback`; the `EpisodeStore` protocol with in-memory and Cosmos DB implementations |
| `episode_io.py` | Explicitly source-separated local JSONL export/import, without accessing an episode store |
| `hosting.py` | Bind each host-issued Responses ID to its exact episode, independently of input, timing or session |
| `evidence.py` | `Evidence`: the cited unit (source, ref, excerpt) agents put in their output |
| `telemetry.py` | `configure_telemetry()` for processes outside Foundry hosting: Azure Monitor export plus agent instrumentation |
| `testing.py` | `ScriptedChatClient` for offline tests (below) |

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

## Episodes

Capture is deterministic: the platform writes the episode, not the model. A failing episode store is logged and never fails the user's request. Graceful cancellation records the failed episode and the interrupted tool call before propagating; a hard process stop may prevent that final write, and missing episodes are never reconstructed.

- `Episode.skill` optionally records the bundled procedure's name and version, independently of the agent version. The RCA agent attaches it through its own episode-store adapter.
- `Episode.source` is `real` for actual runs (including runs against the fictional seed data) and `synthetic` for simulated ones. `export_episodes(episodes, path)` writes explicit labels and refuses mixed populations and existing files; `load_episodes` requires every record to carry a matching label. Neither touches a store. See the [synthetic feedback generator](../diagnostics-domain/README.md).

## Hosted response identity

The hosting adapter doesn't put `AgentResponse.additional_properties["episode_id"]` into the Responses output, but its `prepare_options` hook exposes the host-issued Responses ID. The hosted entry point passes it to capture with `prepare_episode_options`, and capture removes it before the model or tools run.

A hosted episode records `hosted_response_id` and uses `hosted_episode_id(response_id)` as its key: a UUID5 of `cs-platform:hosted-response:<response_id>`. A Responses ID therefore identifies its episode exactly, without relying on input text, timing or session. Failed runs keep the same binding once execution reaches capture. Local runs get a random episode ID. Deploy the agent and `platform-api` together when the `Episode` model changes: the API packages its own `cs-platform`, and an older one silently drops new fields.

## Model rate limits

`foundry_client()` turns off the OpenAI SDK's broader automatic retries and retries only model 429s: at most four attempts and 120 seconds of waiting per turn. Server `Retry-After` (seconds or HTTP date) takes precedence over exponential backoff with jitter; a delay longer than the remaining budget ends the turn. Cancellation and other failures propagate immediately. A streamed turn isn't retried once it has emitted an update, and tools and earlier turns are never replayed.

Each 429 logs a sanitized warning and adds a `cs_platform.model.rate_limit` span event with the attempt, delay and decision. This doesn't add model capacity.

## Tests

`ScriptedChatClient` (`cs_platform.testing`) returns scripted model turns while Agent Framework's real tool-invocation loop runs the tools. The capture tests cover streaming and non-streaming runs, tool failures, model failures, invalid structured output and store outages, all without Azure.
