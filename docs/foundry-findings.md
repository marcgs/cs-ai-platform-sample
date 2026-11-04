# Foundry findings

What we hit while building this sample on Microsoft Foundry and Agent Framework, why it matters for a real project, and how we got past it. This is one of the sample's main results: read it before designing a similar platform.

Each finding has:

- **Hit:** what happened, with the error text where there is one.
- **Matters because:** the impact on a project.
- **Got past it:** the workaround or design choice, with where it lives.
- **Status:** *open* (still a limitation), *by design* (how the service works), or *fixed* (no longer applies), plus the date we last checked. Most of these features are in preview, so check the date and the current docs.

Add a finding when you hit one, and update its status when you check it again. Ideas for future work still go in the [backlog](backlog.md).

## Hosted agents

### Network injection can only be set when the account is created

- **Hit:** a hosted agent reaches private data stores only through agent network injection, and the Foundry account accepts that setting only at creation.
- **Matters because:** adding private networking to an existing environment means deleting, purging and recreating the Foundry account, which also loses its agents, connections and evaluation history.
- **Got past it:** decide on the network layout before the first deployment. Here, it's in Bicep from the start ([ADR 0003](adr/0003-private-data-stores.md)).
- **Status:** by design. Checked 2026-10-27.

### The agent endpoint stays public with network injection

- **Hit:** network injection controls what the agent can reach, not who can reach the agent. Its endpoint stays public, protected by Entra.
- **Matters because:** a fully private platform can't make the agent endpoint private yet.
- **Got past it:** accepted for the sample. Entra-only access ([ADR 0004](adr/0004-agent-hosting.md)).
- **Status:** open (preview). Checked 2026-10-28.

### Each agent version gets a new identity, which exists only after deployment

- **Hit:** every hosted agent version gets its own Entra identity, created at deployment. Bicep can't grant it roles beforehand.
- **Matters because:** access to platform data (here Cosmos DB) has to be granted after every deployment, or the new version fails at runtime.
- **Got past it:** an azd post-deploy hook (`scripts/setup_platform.py grant-agent`) grants the new identity its role. Inside the project, access is implicit. Toolbox connections use the connection's own credentials.
- **Status:** by design. Checked 2026-11-03.

### Some failures only appear in the hosted runtime

- **Hit:** the hosting server inspects the agent factory's signature at runtime, so types that are only imported for annotations break startup. Packages imported only on the hosted path are missing from an image that passed every local test.
- **Matters because:** a deployment succeeds and the agent then fails to start.
- **Got past it:** import the inspected types at runtime, guarded by a test (`test_hosting_server_accepts_the_factory`). The Dockerfile imports the entry point at build time. `azd ai agent invoke` checks the live agent.
- **Status:** by design. Checked 2026-10-28.

### The hosting adapter corrupts tool-call arguments and over-reports tokens

- **Hit:** in the hosted agent's Responses output, tool-call arguments arrive as strings holding the same JSON object twice (`{"machine_id":"M-0001"}{"machine_id":"M-0001"}`). Reported token usage is about 2.8 times the real usage. The cause is in `agent-framework-foundry-hosting` 1.0.0b261015: it appends argument snapshots that should replace the deltas, and sums cumulative usage snapshots instead of keeping the last. The tools aren't actually called twice.
- **Matters because:** Foundry's tool judges reject the output (see [tool judges reject string arguments](#tool-judges-reject-string-arguments)), and any cost tracking based on reported usage is wrong.
- **Got past it:** for evaluation, a normalization step converted arguments to single JSON objects before judging ([offline reproduction](https://github.com/marcgs/cs-ai-platform-sample/blob/before-cleanup/evals/rca/foundry/stream_repro.py), [spike results](https://github.com/marcgs/cs-ai-platform-sample/blob/before-cleanup/docs/spike-foundry-native-eval-results.md)). A tested agent middleware that corrects the stream is parked in [#43](https://github.com/marcgs/cs-ai-platform-sample/pull/43), with a draft upstream issue; it's only worth deploying if something reads hosted tool calls or usage.
- **Status:** open. Checked 2026-11-04.

### Hosted runs stream internally

- **Hit:** the hosted agent streams internally even when its caller asks for a non-streaming response. Local runs don't stream.
- **Matters because:** hosted and local runs of the same agent aren't identical. Measured on five cases, hosted runs used about 1.7 times the tokens of local runs, and the cause isn't fully separated from sampling.
- **Got past it:** compare hosted with hosted, and local with local.
- **Status:** open. Checked 2026-11-04.

### Model rate limits fail hosted runs

- **Hit:** the default deployment allows 50k tokens per minute. One diagnosis uses about 15k tokens, so a few parallel runs hit the limit.
- **Matters because:** evaluation suites fail partway through.
- **Got past it:** the evaluation harness retries errored cases, and runs with low concurrency.
- **Status:** by design (quota). Checked 2026-10-29.

## Tools and the toolbox

### Toolbox MCP calls run one at a time

- **Hit:** when the model asks for several tools at once, the calls still run one after another. Agent Framework's MCP client holds a lock across each call whenever a header provider is set, and `FoundryToolbox` always sets one. A tool that takes 6 seconds can appear to take 20.
- **Matters because:** parallel tool calls give no speed-up, and per-tool durations include queueing time.
- **Got past it:** not worked around. Bypassing the lock would risk mixing identities. Measured and documented in [A6](https://github.com/marcgs/cs-ai-platform-sample/blob/before-cleanup/docs/iteration-2/a6-latency.md).
- **Status:** open, still present in `agent-framework-core` 1.23.0. Checked 2026-10-29.

### Traces stop at the toolbox

- **Hit:** Agent Framework sends the trace context in the MCP request, but the tool server's (Azure Functions) spans never join the agent's trace. The managed toolbox doesn't appear to forward it, and has no setting for it.
- **Matters because:** you can't follow one diagnosis from the agent into the tool server in Application Insights.
- **Got past it:** not worked around. Adding a changing trace header per call would reconnect the MCP session every time ([tracing](tracing.md)).
- **Status:** open. Checked 2026-10-29.

### Content-safety moderation fails on every knowledge search

- **Hit:** every `azure_ai_search` tool result carries `raiPreToolAnnotations` and `raiPostToolAnnotations` errors: "Error during input moderation for knowledge tool: azure_ai_search for general harms" (and the same for output). The search still returns results.
- **Matters because:** at least one answer avoided citing search results, saying the search output was moderated. The guardrail is silently not running.
- **Got past it:** not yet. Cause under investigation.
- **Status:** open. Found 2026-11-04.

### Search results contain the search service's address

- **Hit:** `azure_ai_search` results include full document URLs with the search service's host name.
- **Matters because:** evaluation datasets and exported samples built from agent output carry environment details.
- **Got past it:** strip URLs before anything leaves the project.
- **Status:** by design. Checked 2026-11-04.

### Tool names arrive prefixed

- **Hit:** toolbox tools reach the agent as `<server>___<tool>`, for example `diagnostics___get_logbook`.
- **Matters because:** anything that checks tool names (instructions, evaluators) breaks if it expects the bare name.
- **Got past it:** evaluators match on the prefixed name.
- **Status:** by design. Checked 2026-10-28.

### Some SDK combinations break the MCP session

- **Hit:** `agent-framework-core` 1.23.0 with `mcp` 1.30.0 fails a real MCP session (`ClientSession.protocol_version` is missing). Core 1.22.0 works.
- **Matters because:** a fresh dependency resolution can break tools while every unit test passes.
- **Got past it:** stay on core 1.22.0 and test a real MCP session offline.
- **Status:** open. Checked 2026-11-03.

## Evaluation

### Evaluation in a private-network project needs more than a capability host

- **Hit:** with the project's storage private (public access off, private endpoint), evaluation runs failed in two ways:
  - startup failed with `EvaluationSessionNotBound: The evaluation session is starting. Retry the relay request.`, with zero rows and a misleading "Azure Storage resource already exists";
  - after adding a storage connection, result upload failed with HTTP 403 `AuthorizationFailure` on `CreateContainer`, although the project identity had Blob Data Contributor.

  A resource-instance rule for the Foundry account didn't admit the project's requests.
- **Matters because:** in a locked-down subscription, evaluation doesn't work out of the box, and the errors point the wrong way: storage naming, then permissions.
- **Got past it:** a project capability host, a project storage connection, and the storage firewall's trusted Azure services bypass (`bypass: AzureServices`), matching Microsoft's private-network evaluation template (15a). This lets trusted Azure services through the public endpoint, so storage is no longer private-link only ([ADR 0008](adr/0008-evaluation-storage-network-exception.md)).
- **Status:** works around it. Checked 2026-11-02.

### Failed runs can't be retried

- **Hit:** a run that fails at startup stays failed. Fixing the infrastructure doesn't revive it, and resubmitting creates a new run.
- **Matters because:** run history fills with failed attempts, and tooling that keeps one run per measurement has to decide how retries work.
- **Got past it:** fix the cause, then submit a new run. Keep the failed run as evidence.
- **Status:** by design. Checked 2026-11-02.

### Built-in judges don't know the right answer

- **Hit:** the built-in agent judges (task adherence, intent resolution, coherence, tool call accuracy) assess whether an answer looks reasonable and on task. They don't compare it with a known correct answer.
- **Matters because:** for a diagnosis agent, the main question is whether the diagnosis is correct and grounded in the right evidence.
- **Got past it:** put the answer key in the dataset and score correctness with custom code evaluators.
- **Status:** by design. Checked 2026-11-03.

### Code evaluators can't say "doesn't apply"

- **Hit:** a code evaluator's `grade(sample, item)` must return a float. Metrics that apply only to some cases, such as injection resistance, have no valid score on the others.
- **Matters because:** a 0 or 1 on non-applicable cases distorts the result, so one suite ends up split across several evaluations.
- **Got past it:** one evaluation per such metric, each over its applicable cases only. Endpoint evaluators can return `skipped`, but need a hosted endpoint (not tried).
- **Status:** open (preview). Checked 2026-11-04.

### The code evaluator sandbox restricts Python

- **Hit:** the first code evaluator failed before scoring because the sandbox disallows `globals()`, which our Pydantic setup used. Code evaluators also have no network access and 2 minutes per call.
- **Matters because:** existing scoring code may need changes to run in Foundry.
- **Got past it:** plain, definition-order annotations. With that, 532 of 532 scores on 50 cases matched our local evaluators exactly.
- **Status:** by design. Checked 2026-11-04.

### The portal shows pass counts, not means

- **Hit:** each evaluator's result is a pass count against a fixed per-case threshold, and higher scores are assumed to be better. A run's headline counts a case as passed only if every evaluator passed.
- **Matters because:** gates based on means (ours: `decisive_evidence_recall` at least 0.65) aren't visible directly. A lower-is-better metric (Brier loss) shows up inverted.
- **Got past it:** publish lower-is-better metrics as higher-is-better (`calibration_score = 1 − Brier`). Read means from the run details or the API, not the headline.
- **Status:** by design. Checked 2026-11-04.

### Tool judges reject string arguments

- **Hit:** with Foundry calling the hosted agent, task adherence and tool call accuracy failed on every row: "The 'arguments' field must be a dictionary in tool_call content items."
- **Matters because:** two of the four agent judges don't work when Foundry calls a hosted agent. The Responses protocol carries arguments as JSON strings, so fixing the [adapter bug](#the-hosting-adapter-corrupts-tool-call-arguments-and-over-reports-tokens) alone won't help: Foundry's own agent target and its judges disagree on the format.
- **Got past it:** two steps. Run the agent, convert the saved arguments to dictionaries, then judge the saved outputs in a second run. All four judges then scored every row.
- **Status:** open. Checked 2026-11-04.

### A completed run can hide failed judges

- **Hit:** the first agent-target run reported `completed` with five rows passed and none errored, while two judges had failed on every row with `FAILED_EXECUTION`.
- **Matters because:** a summary that says everything passed can mean some evaluators never ran.
- **Got past it:** check the per-evaluator results (scored rows and execution errors) of every run, not the run summary.
- **Status:** open. Checked 2026-11-04.

### Agent target plus custom evaluators failed in one run

- **Hit:** combining an agent target with our code evaluators in one SDK-created run failed three times with zero rows and no detail: "All examples failed due to invalid user input; please check the individual sample outputs for details."
- **Matters because:** the simplest setup (Foundry calls the agent and scores it with our metrics in one run) isn't proven.
- **Got past it:** two runs: one where Foundry calls the agent, one that scores the saved outputs.
- **Status:** open, cause unknown. Checked 2026-11-04.

### Dataset upload fails behind private storage

- **Hit:** uploading an evaluation dataset with `datasets.upload_file` failed with `AuthorizationFailure` against the project's private storage, even with the trusted-services bypass that lets evaluation runs write results.
- **Matters because:** the documented way to register a dataset doesn't work in a private-network project.
- **Got past it:** upload the JSONL through the project's Files API (`purpose=evals`) and reference it as `source.type=file_id`. These are files, not versioned dataset assets.
- **Status:** open. Checked 2026-11-04.

### Large outputs are dropped from `sample.output`

- **Hit:** with long agent outputs, `sample.output` is empty and `_raisvc_content_omission` says `size_limit`.
- **Matters because:** evaluators mapped to `sample.output` get nothing.
- **Got past it:** map `{{sample.output_text}}` for the answer and `{{sample.output_items}}` for tool calls.
- **Status:** by design. Checked 2026-11-04.

### Judge usage is reported twice

- **Hit:** each judge's token usage appears twice, under the judge model and under `azure_ai_evaluation`, with identical counts. The model's own meters suggest it's charged once.
- **Matters because:** budgets based on reported usage double the judge cost.
- **Got past it:** count one of the two.
- **Status:** open. Checked 2026-11-04.

### Judges are expensive with tool-heavy agents

- **Hit:** tool judges receive every tool call with its full result. With our agent, four judges used about 22k tokens per case.
- **Matters because:** judging a 50-case suite costs about as much as running it.
- **Got past it:** not yet. Trimming tool results in the judge mapping is the next step.
- **Status:** open. Checked 2026-11-04.

### No repeats, no concurrency control, long runs

- **Hit:** agent-target runs have no repetition setting, judge scheduling is managed by the service, and a 50-row run with four judges took 19m38s. During one judge run, a quarter of the judge model's requests were rate-limited (HTTP 429); the run still completed.
- **Matters because:** measuring run-to-run variance needs duplicated rows or several runs. Client tools must wait longer than a typical 15-minute timeout.
- **Got past it:** wait for the run instead of resubmitting. Repeats: duplicate rows with a repeat index, or several runs (not done yet).
- **Status:** by design. Checked 2026-11-04.

### The azd evaluation commands are moving

- **Hit:** the [hosted agent evaluation quickstart](https://learn.microsoft.com/azure/foundry/observability/quickstarts/quickstart-evaluate-hosted-agent) uses `azd ai agent eval run` (extension 0.1.40-preview or later). Our installed tooling said that flow was removed and replaced by `azd ai eval` (`azure.ai.evaluations` 1.0.0-beta.2), which rejects a target `version`, so it evaluates the latest agent version.
- **Matters because:** following the docs may not work with the installed extension, and you can't pin the evaluated agent version from the CLI.
- **Got past it:** `azd ai eval` with an `eval.yaml`, selecting the agent by name.
- **Status:** open. Check `azd ext list` against the quickstart. Checked 2026-11-04.

## Deployment and tooling

### `azd ai agent run` can't find a workspace agent's entry point

- **Hit:** `azd ai agent run` detects the project type and its startup command, or reads `startupCommand` from `azure.yaml`. Our agent is a module inside a uv workspace (`agents/rca/src/rca_agent/main.py`), built from a Dockerfile, and azd can't detect how to start it. Setting `startupCommand` isn't a clean fix: the docs say azd also uses it to start the deployed container.
- **Matters because:** monorepo agents don't run locally with the documented command alone.
- **Got past it:** pass the command on each run: `azd ai agent run rca-agent --start-command "uv run python -m rca_agent.main"`. The deployed container keeps the Dockerfile's `CMD`.
- **Status:** by design. Checked 2026-11-04.

### `azd down` clears the location

- **Hit:** after `azd down`, `AZURE_LOCATION` (and similar values) are gone from the azd environment.
- **Matters because:** the next `azd up` prompts again or fails in automation.
- **Got past it:** set it again before `azd up`.
- **Status:** by design. Checked 2026-10-28.

### A provision hook didn't run

- **Hit:** a successful `azd provision` showed no output from the search-seeding post-provision hook. Running `azd hooks run postprovision` by hand seeded the index.
- **Matters because:** an environment can look provisioned with an empty search index.
- **Got past it:** check the hook's output after provisioning, and run it by hand if it's missing.
- **Status:** open, cause not investigated. Checked 2026-11-02.

### What-if shows changes that aren't real, and hides some that are

- **Hit:** a Bicep what-if on an existing environment reported 44 modifications. Some were real drift (subnet security groups detached, connections becoming shared, Cosmos DB automatic failover turned off), some came from what-if's handling of reference expressions.
- **Matters because:** reprovisioning can silently undo settings changed outside Bicep.
- **Got past it:** declare live settings explicitly in Bicep and review every what-if before provisioning.
- **Status:** by design. Checked 2026-11-02.

### Remote image builds don't support BuildKit

- **Hit:** azd builds the agent image in the registry with the classic builder.
- **Matters because:** Dockerfiles can't use `RUN --mount` or secret mounts.
- **Got past it:** plain Dockerfile instructions.
- **Status:** by design. Checked 2026-10-28.

## Documentation inconsistencies

### Traffic splitting between agent versions

- **Hit:** "Manage hosted agents" says traffic splitting isn't supported, while "Promote hosted agents to production" shows a 90/10 split.
- **Matters because:** canary releases depend on it.
- **Got past it:** not tried.
- **Status:** unverified. Checked 2026-11-03.

### Trusted-service provider spelling

- **Hit:** the storage trusted-services list spells the Foundry provider `Microsoft.CognitiveService/accounts`. The ARM type is `Microsoft.CognitiveServices/accounts`.
- **Matters because:** it's unclear which identities the list covers. A resource-instance rule for the account didn't cover the project.
- **Got past it:** the broader trusted-services bypass (see [private-network evaluation](#evaluation-in-a-private-network-project-needs-more-than-a-capability-host)).
- **Status:** unverified. Checked 2026-11-02.

## Other Azure findings

### Azure Policy can override templates

- **Hit:** in governed subscriptions, a `modify` policy turns public network access off on storage and Cosmos DB whatever the template says. The function app then couldn't upload its package (403), and the hosted agent couldn't reach Cosmos DB.
- **Matters because:** a template that works in an open subscription fails in a governed one.
- **Got past it:** design for private data stores from the start ([ADR 0003](adr/0003-private-data-stores.md)).
- **Status:** by design. Checked 2026-10-27.

### Flex Consumption can't build workspace packages

- **Hit:** remote builds install from a package index, and our workspace packages aren't on one.
- **Matters because:** monorepo function apps don't deploy with the default build.
- **Got past it:** deploy prebuilt Linux wheels with `remoteBuild: false` (`scripts/package_function.sh`).
- **Status:** by design. Checked 2026-10-28.

### The chat model version upgrades automatically

- **Hit:** the chat deployment upgrades its model version automatically.
- **Matters because:** a change in evaluation scores can come from the model rather than the agent.
- **Got past it:** record the exact model version with every evaluation run.
- **Status:** by design. Checked 2026-11-03.
