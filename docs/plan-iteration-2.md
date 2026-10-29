# Iteration 2: trustworthy results

## Goal and scope

Make eval results, episodes and traces reliable enough to compare future agent changes. Take **all six items in [backlog section A](backlog.md#a-trustworthy-results): A1-A6**. No items from other themes are included.

This is the plan, not authorization to start implementation. Implement the six items in parallel, in isolated worktrees, with **one pull request per item**. Do not combine them into one implementation PR. Deployment and live validation are coordinated, not concurrent.

The user approved the A5 deployment after validation during planning. This does not approve infrastructure changes for A1 or A6, destructive operations, or deployments from other workstreams.

**Execution update (2026-10-29):** the user subsequently authorized implementation in six separate, unmerged PRs. After all offline integration gates pass, a coordinated combined A1–A4 feature deployment, updated toolbox metadata and serialized live evals are also authorized. Deployment and model traffic still require the coordinator's explicit slot release; infrastructure, capacity, network changes and destructive operations remain unapproved.

## Workstreams and pull requests

Create each branch from the same agreed `main` commit after this plan is accepted. The branch names below are proposed, not created.

| Item | Branch | PR title | Primary ownership |
|---|---|---|---|
| A1 | `it2/a1-rate-limits` | Handle model rate limits without losing episodes | `packages/cs-platform/src/cs_platform/factory.py`, retry implementation and focused tests; model-capacity configuration only if justified |
| A2 | `it2/a2-knowledge-search` | Require historical-case search in RCA investigations | `agents/rca/src/rca_agent/instructions.md`, toolbox search metadata in `scripts/setup_platform.py`, RCA evals and tests |
| A3 | `it2/a3-trace-continuity` | Make local and hosted diagnostic traces reliable | `packages/cs-platform/src/cs_platform/telemetry.py`, trace handling in `capture.py`, local startup paths, MCP instrumentation if needed |
| A4 | `it2/a4-episode-correlation` | Correlate hosted responses with their exact episodes | Episode correlation fields, hosting boundary, `cli/src/csai/{app,targets,platform}.py`, platform API and store changes if required |
| A5 | `it2/a5-deploy-review-fixes` | Verify deployed review fixes end to end | Deployment verification and sanitized evidence in `docs/iteration-2/a5-deployment.md`; no duplicate implementation of PR #1 |
| A6 | `it2/a6-toolbox-latency` | Measure and reduce diagnostic toolbox latency | Reproducible measurement tooling, `docs/iteration-2/a6-latency.md`, narrowly justified connection or infrastructure changes |

Each PR must be independently reviewable against `main`. Keep shared-file edits narrow; do not make A1-A4 depend on another unmerged feature branch. If a necessary interface cannot be made additive, record the dependency explicitly and rebase the affected branch rather than copying another item's implementation.

## A1: rate-limit handling

**Outcome:** a transient model 429 does not immediately fail a hosted diagnosis, and an exhausted run remains visible as a failed episode.

Start at `cs_platform.factory.foundry_client()`. Inspect the installed Agent Framework and model SDK retry behavior before adding another retry layer. The eval harness already retries errored cases; that is not a substitute for handling a model turn inside the agent.

- Use one bounded, asynchronous retry policy at the model-call boundary. Honor server retry delays, use backoff with jitter otherwise, and propagate cancellation. Do not retry authentication, validation or other permanent errors.
- Cover streaming explicitly. Retry only where safe before output is emitted; do not restart an entire investigation or duplicate tool calls after a partially emitted turn.
- Preserve one episode per diagnosis. Record exhausted errors and make recovered rate limits observable without marking a successful run failed.
- Check quota and capacity read-only. Propose a parameterized capacity increase only if needed and supported; do not silently change a shared model deployment or treat capacity as the retry fix.

**Acceptance:** offline tests cover recovery after 429, exhaustion, permanent failure, cancellation and the relevant streaming boundary. A controlled hosted check records attempts and the terminal episode outcome without deliberately flooding the deployment. Existing eval gates remain green.

**Handoff:** A1 owns retry semantics; coordinate only the minimal recorder hook with A3/A4 if required.

## A2: knowledge search

**Outcome:** the agent consults historical cases and cites relevant results without substituting them for evidence from the current machine.

- Give the toolbox search tool a diagnostic-specific description in `scripts/setup_platform.py`; verify the current Foundry metadata schema before changing the payload.
- Require a historical-case search when the search tool is available. Preserve the supported direct-MCP path, where no search tool is supplied, and disclose unavailable knowledge rather than inventing evidence.
- Test that returned historical-case refs can be cited, that irrelevant results need not be cited, and that absent search does not cause a fabricated call or citation.
- Measure repeated full-suite runs before setting a `used_knowledge` minimum. This metric currently checks `HC-` citations, not whether search ran: verify calls as well, and do not improve the score by forcing irrelevant citations.
- Add a threshold only from a documented stable baseline, retaining every existing threshold. If results are unstable, report the item incomplete rather than inventing a passing minimum.

**Acceptance:** focused offline tool-loop and evaluator tests pass; repeated local evals show historical search and grounded citations without regressions. Hosted verification confirms that the updated metadata actually reaches the agent after a coordinated deployment.

## A3: trace continuity

**Outcome:** new local and hosted runs have usable trace IDs, with trace continuity through diagnostic MCP calls and a documented sampling policy.

- Investigate the missing older hosted runs using available deployment history, exporter configuration, ingestion delay, retention and sampling evidence. Distinguish an invalid or absent trace context from a trace that was not exported.
- Inspect when the agent middleware reads the current span. Fix local span lifetime and telemetry bootstrap across both `rca-local` and `csai --target local`, including eval. Do not invent a trace ID disconnected from exported spans.
- Verify propagation across agent, toolbox and MCP server using one diagnostic call. Fix instrumentation where supported; identify a managed-service boundary explicitly if propagation cannot be controlled.
- Choose and document sampling for this low-volume sample, including the consequences for cost and missing traces. Preserve hosting-library ownership of hosted telemetry.
- Flush short-lived local exporters on shutdown where necessary.

**Acceptance:** offline tests use an in-memory exporter to establish valid trace context and parent-child relationships. Fresh local and hosted traces match episode IDs and include the expected spans. Record the evidence for the older gaps, or state why the historical cause cannot be established; do not claim that unexported history can be recovered.

**Handoff:** give A6 the trace queries and span interpretation. A6 can collect timing baselines before this fix, but final attribution uses the verified traces.

## A4: episode-response correlation

**Outcome:** two simultaneous hosted requests with identical input cannot select each other's episode.

The current CLI searches ten recent episodes by input and creation time. Capture already adds `episode_id` to the framework response's `additional_properties`, but that does not prove the hosted Responses protocol exposes it.

- First verify what the installed hosting adapter preserves: response metadata, response ID or session context. Prefer returning the exact episode ID if supported.
- If that cannot round-trip, persist an exact request/response identifier through a supported hosting hook and add the corresponding store/API lookup. A session ID alone is insufficient if several turns can share a session.
- Carry the identifier through `RunOutput` and the CLI as needed. Keep old stored episodes readable with additive optional fields.
- Remove input/time matching as the authoritative path. Handle missing identifiers, delayed persistence and missing episodes explicitly; any polling must be bounded and keyed by the exact identifier.
- Preserve the local target and report schema. Do not place infrastructure correlation fields in the model's `RcaReport`.

**Acceptance:** offline tests cover identical concurrent inputs, out-of-order completion, delayed/missing episodes and old records. A hosted run proves that the CLI's episode belongs to that exact response. Include failed-run correlation where the host exposes the identifier.

**Handoff:** A4 owns correlation fields and their API contract. A3 owns trace-ID behavior in capture; coordinate separate hunks in the existing capture tests.

## A5: deploy the review fixes

**Outcome:** the fixes already merged through PR #1 are proven to be running in the hosted agent and both function apps.

This is a release-verification item, not another implementation of the fixes. Its separate PR contains a reproducible checklist and sanitized verification evidence.

- Pin the release to a known `main` commit containing PR #1. Confirm the full offline gates, function packaging, locked dependency export and Docker build-context exclusions before deployment. Never commit the local lock or generated exports.
- Record the existing service versions and rollback procedure before changing them. Do not deploy from any of the six work-in-progress branches.
- After A6's unchanged baseline is captured, run the approved `azd deploy` from the pinned revision. Hooks may publish the toolbox and grant the agent identity its documented episode-store role.
- Run a hosted diagnosis, then `csai episodes show <episode-id>`. Until A4 is deployed, use an isolated request and verify its identity carefully; do not claim this proves A4.
- Check the stored episode through the API for complete tool results within the size budget and explicit truncation markers when applicable. The CLI summary alone does not display all raw tool results.
- Verify nested `.env` exclusions from the build context using non-secret fixture checks and the packaging tests, not by displaying or committing real environment files.

**Acceptance:** the A5 PR identifies the source revision, checks performed, pass/fail results and verification time, without environment identifiers, endpoints, credentials or raw deployment output. Deployment failure leaves A5 incomplete, with the recovery decision recorded; no automatic destructive rollback.

Any later deployment of A1-A4 or A6 needs a coordinated release and explicit approval. A5's approval does not authorize provisioning, networking changes or a capacity increase.

## A6: toolbox latency

**Outcome:** a reproducible measurement separates the observed 4-18 second toolbox calls from model time and roughly 50 ms direct-tool execution, and supports a measured remedy or a specific service limitation.

- Capture the unchanged deployed baseline before A5. Use identical tool names, arguments, region and data; distinguish first/cold calls from warm calls.
- Compare toolbox and direct MCP transport where the latter is already authorized. Separate network transport from in-process `DiagnosticsTools` execution; a 50 ms in-process call is not a comparable network baseline.
- Record per-call distributions, sample counts, errors, whole-diagnosis latency, client/session reuse and relevant spans. Keep raw environment-specific artifacts outside tracked files.
- Use A3's verified trace path to locate time in the proxy, Functions startup, MCP session initialization or tool execution. Do not subtract timings from unrelated runs to claim attribution.
- Change only a measured cause: reuse connections if lifecycle evidence supports it, or propose parameterized always-ready capacity if cold starts dominate. Verify current Flex Consumption support, configuration and ongoing cost before proposing infrastructure changes.
- Repeat the same measurement after the change, with other workstreams held fixed. Record a numerical success criterion from the baseline before tuning, not after seeing results.

**Acceptance:** another developer can repeat the comparison. The PR reports before/after timings and correctness checks. If latency lies in an uncontrollable managed-service boundary, document the evidence and limitation rather than claiming an unmeasured improvement. Infrastructure apply remains subject to separate approval.

## Parallel execution and shared-environment schedule

1. **Start all six workstreams together.** Use six worktrees and one owner per item. A1-A4 develop against offline tests; A5 prepares release verification; A6 captures the unchanged live baseline. No parallel writer changes the shared deployment.
2. **Freeze the baseline.** Record source revision, dependency versions, model configuration, concurrency and run conditions privately. A3 can investigate traces read-only in parallel. Serialize token-heavy measurements against the shared model so rate limits do not invalidate comparisons.
3. **Run A5's approved release.** After baseline capture and its validation gates, deploy the pinned existing fixes and complete A5's hosted checks. Record this as a new baseline, not a transparent continuation of the old one.
4. **Open six separate PRs as their deliverables are ready.** Use draft PRs for outstanding live evidence. Link each PR to its backlog ID and this plan; document any actual dependencies and skipped gates. Do not mark an item done merely because a draft exists.
5. **Integrate and verify.** Merge A3 before A6's final trace-based conclusions. Prefer A1 before expensive repeated A2 evals; A4 can merge independently. Rebase overlapping patches and rerun their tests. These are validation/merge constraints, not reasons to develop sequentially.
6. **Validate the combined release.** Obtain approval for any subsequent deployment or infrastructure apply. Compare the integrated version with the post-A5 baseline, then close the iteration only when all six items meet their acceptance criteria.

For code changes, every PR must pass:

```bash
uv run ruff check && uv run ruff format --check
uv run pyright
uv run pytest
```

Run focused tests during development, then these full repository gates before committing. Do not add a CI workflow. After instruction, schema, tool, capture or eval-data changes, also run:

```bash
uv run csai eval rca --target local --concurrency 1
```

Live evals use Azure models and toolbox calls and incur token costs. Repeat baseline/candidate measurements as needed without concurrent suites competing for quota. Record any skipped live gate as outstanding, not passed.

For any proposed infrastructure apply, first build `infra/main.bicep`, then run subscription what-if with the active azd environment's parameters. Review all delete/replace operations and obtain approval before applying; do not recreate network-injected resources.

## PR and completion rules

Each item PR includes the problem, minimal change or investigation, tests, sanitized evidence, remaining limitations and any deployment needed. A5 and a measurement-only A6 may be documentation/evidence PRs; do not manufacture code changes to justify a PR.

Keep commits organization-neutral and free of environment specifics. Check the staged diff before every commit. Commit on the item's feature branch only; obtain explicit permission before pushing branches and opening the implementation PRs. No implementation branches, commits, pushes, PRs or deployments are part of preparing this plan.

Keep the backlog targets at `it2` while work is pending. When an item is verified, change its target to `done it2` and add its own PR link in the notes. Each PR edits only its own backlog row. Update shared architecture/package documentation where behavior changes, and link measured findings from the corresponding backlog row.
