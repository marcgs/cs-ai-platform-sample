# Foundry findings

What we hit while building this sample on Microsoft Foundry, Agent Framework and azd, and how we got past it. This is one of the sample's main results: read it before designing a similar platform.

Each finding has a **Hit** (what happened and why it matters), a **Workaround** (where it lives in this repository) and a **Status**: *open* (still a limitation), *by design* (how the service works) or *unverified*, with the date we last checked. Most of these features are in preview, so check the date against the current docs.

Add a finding when you hit one, and update its status when you check it again. Ideas go in the [backlog](backlog.md).

## Summary

| Finding | Status | Workaround |
|---|---|---|
| **Hosted agents** | | |
| [Network injection only at account creation](#network-injection-can-only-be-set-when-the-account-is-created) | by design | Decide the network before the first deployment |
| [The agent endpoint stays public](#the-agent-endpoint-stays-public-with-network-injection) | open | Entra-only access |
| [A new identity per agent version](#each-agent-version-gets-a-new-identity-which-exists-only-after-deployment) | by design | Post-deploy hook grants its role |
| [Failures only in the hosted runtime](#some-failures-only-appear-in-the-hosted-runtime) | by design | Runtime imports, a test, a build-time import |
| [The hosting adapter corrupts tool calls and usage](#the-hosting-adapter-corrupts-tool-call-arguments-and-over-reports-tokens) | open | Nothing reads them; a fix is parked |
| [Hosted runs stream internally](#hosted-runs-stream-internally) | open | Compare hosted with hosted |
| [Model rate limits](#model-rate-limits-fail-hosted-runs) | by design | Retry 429s; low concurrency |
| **Tools and the toolbox** | | |
| [Toolbox MCP calls run one at a time](#toolbox-mcp-calls-run-one-at-a-time) | open | None |
| [Traces stop at the toolbox](#traces-stop-at-the-toolbox) | open | None |
| [Moderation fails on every knowledge search](#content-safety-moderation-fails-on-every-knowledge-search) | open | None yet |
| [Search results contain the service's address](#search-results-contain-the-search-services-address) | by design | Strip URLs before export |
| [Tool names arrive prefixed](#tool-names-arrive-prefixed) | by design | Match the prefixed name |
| [Some SDK combinations break the MCP session](#some-sdk-combinations-break-the-mcp-session) | open | Pin `agent-framework-core` 1.22.0 |
| **Evaluation** | | |
| [A private-network project needs more than a capability host](#evaluation-in-a-private-network-project-needs-more-than-a-capability-host) | open | Trusted-services bypass on evaluation storage |
| [Dataset upload fails behind private storage](#dataset-upload-fails-behind-private-storage) | open | Local source in `azure.eval.yaml` |
| [Agent-target runs can lose answers](#agent-target-evaluations-can-lose-responses-mid-run) | open | Treat any failed call as an invalid run |
| [Run summaries hide errors](#a-completed-run-can-hide-failed-evaluators) | open | Check every row's `sample.error` |
| [Built-in judges don't know the right answer](#built-in-judges-dont-know-the-right-answer) | by design | Code evaluators with an answer key |
| [Tool judges reject string arguments](#tool-judges-reject-string-arguments) | open | Judges see only the final answer |
| [Code evaluators can't say "doesn't apply"](#code-evaluators-cant-say-doesnt-apply) | open | 1.0 plus `applicable_metrics` per row |
| [The code evaluator sandbox restricts Python](#the-code-evaluator-sandbox-restricts-python) | by design | Standard library only |
| [The portal shows pass counts, not means](#the-portal-shows-pass-counts-not-means) | by design | `rca_evals.gate` |
| [azd's pass-rate gate can't express our gate](#azds-pass-rate-gate-cannot-express-the-rca-gate) | by design | `rca_evals.gate` |
| [`azd ai eval` is an early beta](#azd-ai-eval-is-an-early-beta) | open | See the entry |
| [An evaluation's evaluators can't be changed](#an-evaluations-evaluators-cant-be-changed) | by design | `create` a new evaluation |
| [No retries, no repeats, slow runs](#no-retries-no-repeats-slow-runs) | by design | New runs; several full runs |
| [Large outputs are dropped from `sample.output`](#large-outputs-are-dropped-from-sampleoutput) | by design | Map `sample.output_text` |
| [Judge usage is reported twice](#judge-usage-is-reported-twice) | open | Count one |
| **Deployment and tooling** | | |
| [`azd ai agent run` can't find a workspace agent](#azd-ai-agent-run-cant-find-a-workspace-agents-entry-point) | by design | `--start-command` |
| [`azd down` clears the location](#azd-down-clears-the-location) | by design | Set it again |
| [A provision hook didn't run](#a-provision-hook-didnt-run) | open | Check its output |
| [What-if is noisy and incomplete](#what-if-shows-changes-that-arent-real-and-hides-some-that-are) | by design | Declare live settings in Bicep |
| [Remote image builds don't support BuildKit](#remote-image-builds-dont-support-buildkit) | by design | Plain Dockerfile |
| [Azure Policy can override templates](#azure-policy-can-override-templates) | by design | Private data stores from the start |
| [Flex Consumption can't build workspace packages](#flex-consumption-cant-build-workspace-packages) | by design | Prebuilt wheels |
| [The chat model version upgrades itself](#the-chat-model-version-upgrades-automatically) | by design | Record it with every run |
| **Documentation inconsistencies** | | |
| [Traffic splitting between agent versions](#traffic-splitting-between-agent-versions) | unverified | Not tried |
| [Trusted-service provider spelling](#trusted-service-provider-spelling) | unverified | The broader bypass |

## Hosted agents

### Network injection can only be set when the account is created

- **Hit:** a hosted agent reaches private data stores only through agent network injection, and the Foundry account accepts that setting only at creation. Adding it later means deleting, purging and recreating the account, which loses its agents, connections and evaluation history.
- **Workaround:** decide on the network layout before the first deployment. Here, it's in Bicep from the start ([ADR 0003](adr/0003-private-data-stores.md)).
- **Status:** by design. Checked 2026-10-27.

### The agent endpoint stays public with network injection

- **Hit:** network injection controls what the agent can reach, not who can reach the agent. Its endpoint stays public, protected by Entra, so a fully private platform isn't possible yet.
- **Workaround:** accepted for the sample: Entra-only access ([ADR 0004](adr/0004-agent-hosting.md)).
- **Status:** open (preview). Checked 2026-10-28.

### Each agent version gets a new identity, which exists only after deployment

- **Hit:** every hosted agent version gets its own Entra identity, created at deployment, so Bicep can't grant it roles beforehand. Without a grant after every deployment, the new version fails at runtime when it reaches platform data (here Cosmos DB).
- **Workaround:** an azd post-deploy hook (`scripts/setup_platform.py grant-agent`) grants the new identity its role. Inside the project, access is implicit. Toolbox connections use the connection's own credentials.
- **Status:** by design. Checked 2026-11-03.

### Some failures only appear in the hosted runtime

- **Hit:** the hosting server inspects the agent factory's signature at runtime, so types imported only for annotations break startup. Packages imported only on the hosted path are missing from an image that passed every local test. The deployment succeeds, and the agent then fails to start.
- **Workaround:** import the inspected types at runtime, guarded by `test_hosting_server_accepts_the_factory`. The Dockerfile imports the entry point at build time. `azd ai agent invoke` checks the live agent.
- **Status:** by design. Checked 2026-10-28.

### The hosting adapter corrupts tool-call arguments and over-reports tokens

- **Hit:** in the hosted agent's Responses output, tool-call arguments arrive as strings holding the same JSON object twice (`{"machine_id":"M-0001"}{"machine_id":"M-0001"}`), and reported token usage is about 2.8 times the real usage. `agent-framework-foundry-hosting` 1.0.0b261015 appends argument snapshots that should replace the deltas, and sums cumulative usage snapshots instead of keeping the last. The tools aren't called twice. Cost tracking from reported usage is wrong, and Foundry's tool judges reject the output ([below](#tool-judges-reject-string-arguments)).
- **Workaround:** nothing in the sample reads hosted tool calls or reported usage; episodes record their own. A tested middleware that corrects the stream is in the closed [#43](https://github.com/marcgs/cs-ai-platform-sample/pull/43), with an [offline reproduction](https://github.com/marcgs/cs-ai-platform-sample/blob/before-cleanup/evals/rca/foundry/stream_repro.py).
- **Status:** open. Checked 2026-11-04.

### Hosted runs stream internally

- **Hit:** the hosted agent streams internally even when the caller asks for a non-streaming response; local runs don't. On five cases, hosted runs used about 1.7 times the tokens of local runs, not fully separated from sampling.
- **Workaround:** compare hosted with hosted, and local with local.
- **Status:** open. Checked 2026-11-04.

### Model rate limits fail hosted runs

- **Hit:** the default deployment allows 50k tokens per minute. One diagnosis uses about 15k tokens, so a few parallel runs hit the limit and fail.
- **Workaround:** the agent's chat client retries model 429s within a budget (`cs_platform.retry`, [its README](../packages/cs-platform/README.md#model-rate-limits)). Keep evaluation concurrency low.
- **Status:** by design (quota). Checked 2026-10-29.

## Tools and the toolbox

### Toolbox MCP calls run one at a time

- **Hit:** when the model asks for several tools at once, the calls still run one after another: Agent Framework's MCP client holds a lock across each call whenever a header provider is set, and `FoundryToolbox` always sets one. A tool that takes 6 seconds can appear to take 20, and per-tool durations include queueing.
- **Workaround:** none. Bypassing the lock would risk mixing identities.
- **Status:** open in `agent-framework-core` 1.23.0. Checked 2026-10-29.

### Traces stop at the toolbox

- **Hit:** Agent Framework sends the trace context in the MCP request, but the tool server's spans never join the agent's trace; the managed toolbox doesn't appear to forward it and has no setting for it. You can't follow one diagnosis from the agent into the tool server.
- **Workaround:** none. A changing trace header per call would reconnect the MCP session every time ([observability](architecture.md#observability)).
- **Status:** open. Checked 2026-10-29.

### Content-safety moderation fails on every knowledge search

- **Hit:** every `azure_ai_search` tool result carries `raiPreToolAnnotations` and `raiPostToolAnnotations` errors: "Error during input moderation for knowledge tool: azure_ai_search for general harms" (and the same for output). The search still returns results, so the guardrail is silently not running. At least one answer avoided citing search results, saying they were moderated.
- **Workaround:** none yet; cause not investigated.
- **Status:** open. Found 2026-11-04.

### Search results contain the search service's address

- **Hit:** `azure_ai_search` results include document URLs with the search service's host name, so anything exported from agent output carries environment details.
- **Workaround:** strip URLs before anything leaves the project.
- **Status:** by design. Checked 2026-11-04.

### Tool names arrive prefixed

- **Hit:** toolbox tools reach the agent as `<server>___<tool>`, for example `diagnostics___get_logbook`. Anything that checks tool names breaks if it expects the bare name.
- **Workaround:** match on the prefixed name.
- **Status:** by design. Checked 2026-10-28.

### Some SDK combinations break the MCP session

- **Hit:** `agent-framework-core` 1.23.0 with `mcp` 1.30.0 fails a real MCP session (`ClientSession.protocol_version` is missing), while every unit test passes. Core 1.22.0 works.
- **Workaround:** stay on core 1.22.0, and test a real MCP session offline.
- **Status:** open. Checked 2026-11-03.

## Evaluation

### Evaluation in a private-network project needs more than a capability host

- **Hit:** with the project's storage private, evaluation runs failed first at startup (`EvaluationSessionNotBound: The evaluation session is starting. Retry the relay request.`, zero rows, and a misleading "Azure Storage resource already exists"), then, with a storage connection, at result upload (HTTP 403 `AuthorizationFailure` on `CreateContainer`, although the project identity had Blob Data Contributor). A resource-instance rule for the Foundry account didn't admit the project's requests. The errors point at naming, then permissions.
- **Workaround:** a project capability host, a project storage connection and the storage firewall's trusted Azure services bypass, as in Microsoft's private-network evaluation template (15a). Storage is then no longer private-link only ([ADR 0008](adr/0008-evaluation-storage-network-exception.md)).
- **Status:** open. Checked 2026-11-02.

### Dataset upload fails behind private storage

- **Hit:** uploading an evaluation dataset (`datasets.upload_file`, or `azd ai eval create` with a dataset) fails with 403 `AuthorizationFailure` against the project's private storage, even with the bypass above. Local-source runs still leave autogenerated `eval-data-*` data assets in the project, one per run, which the Files API listing doesn't show.
- **Workaround:** a local source in `evals/azure.eval.yaml` (`source: {type: local, file: …}`) sends the rows with each run. There's no versioned dataset; the cases are versioned in git. List datasets too when cleaning up a project.
- **Status:** open. Checked 2026-11-05.

### Agent-target evaluations can lose responses mid-run

- **Hit:** in 2 of 5 full 50-row runs with the agent as target, Foundry lost answers the agent had already given, then stopped calling it. The failed rows show `TARGET_INVOCATION_FAILED` with one of two errors:
  - "(SystemError) Long-running agent response timed out after 30 minute(s). Response ID: …";
  - "(UserError) Error code: 424 - {'error': 'CustomerManagedDownstreamError', 'message': 'Data proxy returned 424 because the customer-managed downstream service responded with 403. …', 'innerStatusCode': 403}".

  The run still ends `completed` with `errored: 0`. The code evaluators score the empty answers 0, so a broken call looks like a wrong answer.
- **What the agent's telemetry shows** (Log Analytics, one episode span per request):
  - **Run 1** (2026-11-04, 14:17 UTC): rows 1–32 succeeded. Row 33 reached the agent at 14.2 minutes and was answered at 14.5 minutes, but recorded as the first 424/403. Rows 34–50 never reached the agent.
  - **Run 2** (2026-11-04, 18:05 UTC): rows 1–37 succeeded. Rows 38 and 40 were answered in 8 and 15 seconds (each error's response ID matches a stored episode's conversation), but Foundry waited 30 minutes for each. After each wait, the next rows ran in a new agent container. Row 45 was answered in 3 seconds, then recorded as the first 424/403. Rows 46–50 never reached the agent. The run took 86 minutes instead of about 21.
  - Rows are sent one at a time. Each takes about 17 or 33 seconds even when the agent answers in 7, as if Foundry polls about every 16.5 seconds.
- **Ruled out:**
  - The cases: every failed row succeeded in other runs.
  - The agent: it answered every row that reached it and logged no errors.
  - A fixed time limit: the first 424/403 came at 14.5 minutes in one run and at 74 minutes in the other.
  - The session idle timeout: requests arrived continuously, apart from Foundry's own waits.
  - The session quota, subnet addresses and model rate limits: the [limits page](https://learn.microsoft.com/azure/foundry/agents/concepts/limits-quotas-regions#limit-error-reference) gives them HTTP 429 with their own codes, and the runs used one request at a time. The [evaluation limits](https://learn.microsoft.com/azure/foundry/concepts/evaluation-regions-limits-virtual-network#rate-limits) cover only row size and count, and the [troubleshooting](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-results#troubleshoot-cloud-evaluation) 403 advice is about the caller's credentials.
- **Workaround:** `rca_evals.gate` fails any run with a row's `sample.error` as an agent error, never as a wrong answer. A run with failed calls isn't used for measurement; submit a new full run instead of rerunning a subset.
- **Status:** open, cause unknown. A support request is drafted but not sent while we watch for more failures. Checked 2026-11-05.

### A completed run can hide failed evaluators

- **Hit:** run summaries say `completed` with `errored: 0` when evaluators failed. Two judges once failed on every row with `FAILED_EXECUTION` while the run reported five rows passed. Code evaluators sometimes fail in the sandbox with "An error occurred during grading" and record score 0 with status `completed`. This happened on 4 rows in 3 runs, for code that scores the same answer correctly locally.
- **Workaround:** check each evaluator's nested `sample.error`, not the run summary or a zero score. `rca_evals.gate` fails on errors in its gate metrics and reports errors in the others without gating.
- **Status:** open. Checked 2026-11-05.

### Built-in judges don't know the right answer

- **Hit:** the built-in agent judges (task adherence, intent resolution, coherence, tool call accuracy) assess whether an answer looks reasonable and on task, not whether it matches a known correct answer. For a diagnosis agent, correctness and grounding are the main question.
- **Workaround:** the answer key goes in each row, and code evaluators score correctness ([eval guide](../evals/rca/README.md#evaluation)). The judges report and don't gate.
- **Status:** by design. Checked 2026-11-03.

### Tool judges reject string arguments

- **Hit:** with Foundry calling the hosted agent, the judges that read tool calls (task adherence, tool call accuracy, and intent resolution with azd's default mapping of `{{sample.output_items}}` and `{{sample.tool_calls}}`) fail on every row: "The 'arguments' field must be a dictionary in tool_call content items." The Responses protocol carries arguments as JSON strings, so Foundry's agent target and its judges disagree on the format. Fixing the [adapter bug](#the-hosting-adapter-corrupts-tool-call-arguments-and-over-reports-tokens) wouldn't help.
- **Workaround:** the judges get `response: {{sample.output_text}}`, and `tool_calls` is bound to a null column in the rows, because azd rejects an empty binding (`evals/azure.eval.yaml`). They score every row but don't see the tool calls. That also keeps them cheap: with tool results, four judges used about 22k tokens per case, about as much as running the agent.
- **Status:** open. Checked 2026-11-04.

### Code evaluators can't say "doesn't apply"

- **Hit:** a code evaluator's `grade(sample, item)` must return a float. Returning `None` doesn't skip the row: Foundry records an error with score 0, although run results have a `skipped` count. The docs don't describe a way to skip. Metrics that apply only to some cases, such as injection resistance, have no valid score on the others.
- **Workaround:** `decisive_evidence_recall` and `injection_resisted` score 1.0 where they don't apply, and each row lists its `applicable_metrics`, which `rca_evals.gate` uses for means. The portal's pass counts still include those cases. Endpoint evaluators can return `skipped` but need a hosted endpoint (backlog Q29).
- **Status:** open (preview). Checked 2026-11-04.

### The code evaluator sandbox restricts Python

- **Hit:** the sandbox disallows `globals()`, which Pydantic needed, has no network access, allows 2 minutes per call, and doesn't document its Python version. Existing scoring code may need changes.
- **Workaround:** `rca_evals.graders` uses only the standard library, runs on Python 3.9 too, and gets the valid references in the row. Its scores matched local scoring on 532 of 532 checks.
- **Status:** by design. Checked 2026-11-04.

### The portal shows pass counts, not means

- **Hit:** each evaluator's result is a pass count against a fixed per-case threshold, higher assumed better, and a run's headline counts a case as passed only if every evaluator passed. A gate based on means isn't visible.
- **Workaround:** `rca_evals.gate` computes the means from the saved results. Use the portal to inspect single rows.
- **Status:** by design. Checked 2026-11-05.

### azd's pass-rate gate cannot express the RCA gate

- **Hit:** azd's documented [CI gate](https://learn.microsoft.com/azure/foundry/agents/how-to/set-up-ci-cd-cli#verify-with-eval-in-ci) is `--fail-on any-failure` or `--fail-on pass-rate=<0..1>`: passed cases over all cases, with errored and skipped cases counting against it. It can't express per-metric minimum means over applicable cases, a hard injection check, diagnostic-only evaluators, or errors kept apart from wrong answers. It also fails to read back local-source runs ([below](#azd-ai-eval-is-an-early-beta)).
- **Workaround:** the read-only `uv run python -m rca_evals.gate` reads the saved results with the project's OpenAI client and applies `evals/rca/gate.json` ([ADR 0011](adr/0011-foundry-evaluation-and-measured-gate.md)).
- **Status:** by design. Checked 2026-11-04.

### `azd ai eval` is an early beta

- **Hit:** with `azure.ai.evaluations` 1.0.0-beta.2 and `azure.ai.agents` 1.0.0-beta.23:
  - **The commands moved.** The [hosted agent evaluation quickstart](https://learn.microsoft.com/azure/foundry/observability/quickstarts/quickstart-evaluate-hosted-agent) (updated 2026-10-21) uses `azd ai agent eval run`, which now only prints "The legacy agent evaluation workflow has been removed". `azd ai eval` uses `evals/azure.eval.yaml` in a different format and rejects a target `version`, so it always evaluates the latest agent version.
  - **Runs can't be read back** for a local-source eval: `run start` (without `--no-wait`), `run show` and `run list` fail with `json: cannot unmarshal string into Go struct field EvalRunDataSource.data_source.source.content`.
  - **The code evaluator schema differs from the docs.** The [custom evaluators](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/custom-evaluators) docs wrap inputs in an `item` envelope; azd reads that as one input named `item` and refuses it.
  - **No environment variables:** `model: ${FOUNDRY_MODEL_DEPLOYMENT_NAME}` reaches the service as written.
  - **Side effects:** `init` rewrote `azure.yaml`, dropping its comments and re-sorting keys. `create` makes a new evaluation with the same name on every call.
- **Workaround:**
  - Use `azd ai eval create` once per environment and after changes, then `run start --no-wait`. Read the results with `rca_evals.gate` or the portal.
  - The evaluators use a flat `data_schema` (`rca_evals.assets`).
  - The judge model's deployment name is written out in `evals/azure.eval.yaml`.
  - `azure.yaml` has no `azure.ai.eval` service.
- **Status:** open. Compare `azd ext list` with the quickstart. Checked 2026-11-04.

### An evaluation's evaluators can't be changed

- **Hit:** updating an evaluation (`POST /openai/v1/evals/{id}`) with new `testing_criteria` returns 200 but keeps the old ones; only the name and metadata are updatable. Adding an evaluator means a new evaluation, and the old runs stay with the old one.
- **Workaround:** `azd ai eval create rca-quality` after changing `evals/azure.eval.yaml`. `rca_evals.gate` uses the newest evaluation of that name.
- **Status:** by design. Checked 2026-11-04.

### No retries, no repeats, slow runs

- **Hit:** a failed run stays failed, and resubmitting creates a new run. Agent-target runs have no repetition setting, judge scheduling is up to the service, and a 50-row run takes about 20 minutes. During one run, a quarter of the judge model's requests were rate-limited; the run still completed.
- **Workaround:** fix the cause and submit a new run, keeping the failed one as evidence. Measure run-to-run variation with several full runs ([first measurement](../evals/rca/README.md#first-measurement)). Wait longer than a typical 15-minute client timeout.
- **Status:** by design. Checked 2026-11-05.

### Large outputs are dropped from `sample.output`

- **Hit:** with long agent outputs, `sample.output` is empty and `_raisvc_content_omission` says `size_limit`, so evaluators mapped to it get nothing.
- **Workaround:** map `{{sample.output_text}}` for the answer. To read an answer back, use a judge's recorded input.
- **Status:** by design. Checked 2026-11-04.

### Judge usage is reported twice

- **Hit:** each judge's token usage appears twice, under the judge model and under `azure_ai_evaluation`, with identical counts (29,426 tokens under each for 10 judge calls). The model's own meters suggest it's charged once, so a budget based on reported usage doubles the judge cost.
- **Workaround:** count one of the two.
- **Status:** open. Checked 2026-11-04.

## Deployment and tooling

### `azd ai agent run` can't find a workspace agent's entry point

- **Hit:** `azd ai agent run` detects a project's startup command or reads `startupCommand` from `azure.yaml`. It can't detect a module in a uv workspace built from a Dockerfile (`agents/rca/src/rca_agent/main.py`), and `startupCommand` would also start the deployed container.
- **Workaround:** `azd ai agent run rca-agent --start-command "uv run python -m rca_agent.main"`. The deployed container keeps the Dockerfile's `CMD`.
- **Status:** by design. Checked 2026-11-04.

### `azd down` clears the location

- **Hit:** after `azd down`, `AZURE_LOCATION` and similar values are gone from the azd environment, so the next `azd up` prompts again or fails in automation.
- **Workaround:** set it again before `azd up`.
- **Status:** by design. Checked 2026-10-28.

### A provision hook didn't run

- **Hit:** a successful `azd provision` showed no output from the search-seeding post-provision hook, leaving an empty search index. Running `azd hooks run postprovision` by hand seeded it.
- **Workaround:** check the hook's output after provisioning, and run it by hand if it's missing.
- **Status:** open, cause not investigated. Checked 2026-11-02.

### What-if shows changes that aren't real, and hides some that are

- **Hit:** a Bicep what-if on an existing environment reported 44 modifications. Some were real drift (subnet security groups detached, connections becoming shared, Cosmos DB automatic failover off); others came from how what-if handles reference expressions. Reprovisioning can silently undo settings changed outside Bicep.
- **Workaround:** declare live settings explicitly in Bicep, and review every what-if before provisioning.
- **Status:** by design. Checked 2026-11-02.

### Remote image builds don't support BuildKit

- **Hit:** azd builds the agent image in the registry with the classic builder, so Dockerfiles can't use `RUN --mount` or secret mounts.
- **Workaround:** plain Dockerfile instructions.
- **Status:** by design. Checked 2026-10-28.

### Azure Policy can override templates

- **Hit:** in governed subscriptions, a `modify` policy turns public network access off on storage and Cosmos DB, whatever the template says. The function app then couldn't upload its package (403), and the hosted agent couldn't reach Cosmos DB.
- **Workaround:** design for private data stores from the start ([ADR 0003](adr/0003-private-data-stores.md)).
- **Status:** by design. Checked 2026-10-27.

### Flex Consumption can't build workspace packages

- **Hit:** Flex Consumption remote builds install from a package index, and workspace packages aren't on one.
- **Workaround:** deploy prebuilt Linux wheels with `remoteBuild: false` (`scripts/package_function.sh`).
- **Status:** by design. Checked 2026-10-28.

### The chat model version upgrades automatically

- **Hit:** the chat deployment upgrades its model version automatically, so a change in evaluation scores can come from the model rather than the agent.
- **Workaround:** record the exact model version with every measurement.
- **Status:** by design. Checked 2026-11-03.

## Documentation inconsistencies

### Traffic splitting between agent versions

- **Hit:** "Manage hosted agents" says traffic splitting isn't supported, while "Promote hosted agents to production" shows a 90/10 split. Canary releases depend on it.
- **Workaround:** not tried.
- **Status:** unverified. Checked 2026-11-03.

### Trusted-service provider spelling

- **Hit:** the storage trusted-services list spells the Foundry provider `Microsoft.CognitiveService/accounts`; the ARM type is `Microsoft.CognitiveServices/accounts`. It's unclear which identities the list covers, and a resource-instance rule for the account didn't cover the project.
- **Workaround:** the broader trusted-services bypass ([private-network evaluation](#evaluation-in-a-private-network-project-needs-more-than-a-capability-host)).
- **Status:** unverified. Checked 2026-11-02.
