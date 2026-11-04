# CS AI Platform sample

A reference sample that shows the path from **an agent prototype** to **an agent running on a governed Azure platform**. The platform gives agents model access, tools, knowledge grounding, telemetry, evaluation gates, an episode/feedback trail and repeatable deployment. A fictional root-cause-analysis (RCA) diagnostics agent proves it works.

> All data in this repository is **synthetic and fictional**. It contains no customer data, names or machine types.

- What and why: [`docs/specification.md`](docs/specification.md) · [`docs/architecture.md`](docs/architecture.md)
- What we learned about Foundry, its limitations and how we got past them: [`docs/foundry-findings.md`](docs/foundry-findings.md)
- Using it, one case end to end: [`docs/walkthrough.md`](docs/walkthrough.md) · each part in Azure: [`docs/platform-tour.md`](docs/platform-tour.md)
- How it was built: [`docs/plan-iteration-1.md`](docs/plan-iteration-1.md) · current plan: [`docs/plan-iteration-5.md`](docs/plan-iteration-5.md) · decisions in [`docs/adr/`](docs/adr/)
- Adding an agent: [`docs/onboarding-an-agent.md`](docs/onboarding-an-agent.md)
- Ideas and what's next: [`docs/backlog.md`](docs/backlog.md)
- Changing the code (rules, commands, gotchas; for people and coding agents): [`AGENTS.md`](AGENTS.md)

## What runs where

- **Microsoft Foundry:** model deployments (gpt-5.4-mini, text-embedding-3-large; EU data zone), the hosted `rca-agent` (Agent Framework, container), the `diagnostics` toolbox (MCP tools + AI Search) and its connections.
- **Azure Functions (Flex Consumption):** the diagnostics MCP server and the platform API for episodes and feedback.
- **Data:** Cosmos DB for episodes and AI Search for historical cases. Cosmos DB and the functions' storage are reachable only through private endpoints.
- **Observability:** Application Insights and Log Analytics.
- **Your machine:** `csai`, the command line to diagnose, evaluate, and review episodes.

## Quickstart

### Prerequisites

- [uv](https://docs.astral.sh/uv/) 0.13+ (installs Python 3.14)
- [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/) 1.37+ with the Foundry extensions: `azd extension install microsoft.foundry`
- [Azure CLI](https://learn.microsoft.com/cli/azure/) (templates use it for validation; `csai` and the hooks use your sign-in)
- [Azure Functions Core Tools v4](https://learn.microsoft.com/azure/azure-functions/functions-run-local), to run the MCP server locally
- An Azure subscription where you can create resources and role assignments (Owner, or Contributor + Role Based Access Control Administrator)

If your machine must use a package mirror, configure it in your user-level uv configuration, never in this repository ([`docs/dependencies.md`](docs/dependencies.md)).

### Deploy

```bash
uv sync --all-packages
uv run pre-commit install

azd auth login && az login
azd env new cs-platform-dev
azd env set AZURE_LOCATION swedencentral
# optional: if AI Search has no capacity in that region
azd env set AZURE_SEARCH_LOCATION northeurope

azd up        # about 20 minutes on an empty subscription
```

`azd up` provisions everything with Bicep, seeds the search index, deploys both function apps, publishes the toolbox, builds the agent image in the registry, deploys the hosted agent and grants its identity access to the episode store. See [architecture → deployment](docs/architecture.md#deployment).

### Try it

```bash
uv run csai diagnose "M-0007: Pressure excursions in the chamber, purge flow looks lower than normal."
```

That prints the agent's ranked hypotheses with their evidence, and the episode ID. [`docs/walkthrough.md`](docs/walkthrough.md) takes it from there: questioning the answer in the playground, reviewing the episode, recording an expert verdict and running the eval gate.

Hosted diagnoses also print the Responses ID and verify the exact stored episode,
including failed runs. If persistence is delayed or unavailable, the CLI says the
episode is unverified rather than selecting a similar incident.
`csai episodes show <episode-id>` displays the stored Response ID (absent on older episodes).

For repeated evals with confidence intervals and private transcripts, run
`uv run csai eval rca --target local --repeats 3 --concurrency 1`.
Results and actual episodes are flushed to a durable journal as each case-run finishes.
After an interruption, `uv run csai --no-azd eval report .eval-results/<run>`
rebuilds the summary and HTML offline. An incomplete run always fails the gate;
reporting never reruns a case or reconstructs an episode.
See the [eval guide](evals/rca/README.md) for splits, artifacts and paired comparisons.

The gate covers applicable original and challenge cases: minimum means for
`hit_at_1_lenient`, `decisive_evidence_recall` and `evidence_grounded`, and a hard
`injection_resisted` check. Invalid reports score zero; feedback is report-only.
The approved provisional floors are 0.70 / 0.65 / 0.85. The three-repeat baseline,
its publication and the score trend page (Q17) wait for the
[#31 spike](docs/spike-foundry-native-eval.md) decision; the local gate stays
the reference and fallback.

After explicit publishing approval, `uv run csai eval publish .eval-results/<run>`
publishes the saved measurement without rerunning the agent. Publishing never
changes the local gate. The 50-case validation completed and is visible in
Foundry. All 450 published code scores meet the approved absolute parity
tolerance of `1e-12`. The offline calibration correction and sparse-score
limitations remain documented evidence, not further close-out work.
Judges-only publishing (#29) is closed and unmerged, superseded by the spike;
main retains the existing publisher and the completed run is unchanged.
The first feedback-case proposal, [#32](https://github.com/marcgs/cs-ai-platform-sample/pull/32),
is open for human review and merge.
See [Q9's validation and limitations](docs/iteration-4/q9.md).

After separate approval, this creates or resumes one infrastructure-only attempt:

```bash
uv run csai eval publish .eval-results/<run> --retry-infrastructure <failed-run-id>
```

It requires retained receipt lineage and a zero-row
`EvaluationSessionNotBound` failure with no output items. The original failed run,
receipt and frozen measurement remain unchanged. Other errors, partial grades
and quality failures cannot use this option; see [ADR 0007](docs/adr/0007-infrastructure-only-publication-retries.md).

To turn a synthetic L8 v2 report into an offline case proposal from every reviewed
episode in its fresh cohort (including episodes never classified):

```bash
uv run csai --no-azd cases propose path/to/report.json \
  --episodes path/to/cohort-episodes.jsonl --reviews path/to/cohort-reviews.jsonl
```

This creates a local branch, proposed feedback cases and a PR body; it never
commits, pushes or opens a PR. Human review remains required. See
[L9 Part B](docs/iteration-4/l9b.md).
Admission requires consensus, replay and no duplicate, not cluster membership.
Reviews establish the expected cause; the replay-matched synthetic scenario
supplies only incident category. Cluster provenance is optional.
Provenance labels these two bases separately. This path is synthetic-only; real
feedback needs independently supported incident-category metadata.
See the [iteration-4 close-out](docs/iteration-4/close-out.md) for delivered
work, retained measurements and deferred work.

### Clean up

```bash
azd down --purge
```

Fixed costs while deployed are a few euros per day, mostly AI Search Basic and the private endpoints; model usage is pay-per-token (about 10–15k tokens per diagnosis).

## Development

```bash
uv run ruff check && uv run ruff format --check   # lint and format
uv run pyright                                     # types (strict for all source packages)
uv run pytest                                      # tests, all offline

uv run csai eval rca --target local                # quality gate with the agent in-process
uv run csai diagnose "M-0001: ..." --target local  # one run, episode kept in memory
```

`csai` reads its settings from the active azd environment. To run the agent against the MCP server on your machine instead of the toolbox, see [`agents/rca/README.md`](agents/rca/README.md).

For a low-sample, model-free comparison of authenticated toolbox, direct MCP and
in-process tool latency, see [the A6 measurement command and baseline](docs/iteration-2/a6-latency.md).

There's no CI pipeline in this exploration repository: pre-commit hooks and `csai eval` are the gates. [`docs/ci-cd.md`](docs/ci-cd.md) maps them onto a pipeline.

## Repository layout

| Path | Purpose |
|---|---|
| `packages/cs-platform` | The platform harness: agent specs, episode capture and stores, eval harness, telemetry ([README](packages/cs-platform/README.md)) |
| `packages/diagnostics-domain` | Synthetic diagnostics domain, data generator and seed data |
| `agents/rca` | The RCA agent: spec, instructions, report schema, hosted entry point, image ([README](agents/rca/README.md)) |
| `evals/rca` | The RCA eval suite: case manifest, thresholds, evaluators |
| `services/diagnostics-mcp` | Read-only diagnostic tools as an MCP server on Azure Functions ([README](services/diagnostics-mcp/README.md)) |
| `services/platform-api` | Episodes and feedback over the private episode store, on Azure Functions |
| `cli` | `csai`: diagnose, eval, episodes, feedback |
| `infra` | Bicep for every Azure resource (`main.bicep` + modules) |
| `scripts` | azd hooks: function packaging, search seeding, toolbox, agent access |
| `docs` | Specification, architecture, plan, ADRs, onboarding, backlog |

## Dependencies

`uv.lock` is local only (gitignored): everyone resolves against their own configured package index. Deployments install the locally locked versions: the function apps from prebuilt wheels, the agent image from an exported, hashed requirements file without index URLs. See [ADR 0002](docs/adr/0002-local-lock-files.md).
