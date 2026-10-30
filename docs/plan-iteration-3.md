# Iteration 3: measure, then start the loop

## Goal and scope

Two outcomes:

1. **An eval suite that can tell a better agent from a worse one.** The gate is green honestly, and there are cases with headroom. Today the gate is red (Q1) and every other metric is saturated.
2. **The inputs of the learning loop.** The agent's procedure is a versioned skill, there is realistic expert feedback to learn from, and recurring failures are found by analysis rather than by reading episodes. Iteration 4 can then take L4 (proposals, replay and approval) and L5 (the optimizer as learner).

Six items from the [backlog](backlog.md):

| Item | Size | Explores |
|---|---|---|
| Q1 Tool-selection reliability | M | |
| Q2 Eval health | M | |
| Q3 Harder cases with ground truth | M | |
| L1 The RCA procedure as a skill | S | Agent Framework skills, Foundry skills |
| L2 Synthetic expert feedback | S | |
| L3 Failure analysis over episodes | M | Cosmos DB mirroring to Fabric, Foundry models |

Out of scope: model judges and the outcome gate (Q4), cost and latency (Q5), asking for missing information (Q6), proposals and replay (L4), the learner (L5), and any change to `RcaReport`. Findings go to the backlog.

This is the plan, not authorization to implement. Like iteration 2: one worktree and **one pull request per item**, developed in parallel, with live evals and deployments serialized. This plan approves no deployment, infrastructure change, role assignment or Fabric resource.

## Invariants for every workstream

1. **The 18 existing cases stay comparable.** Their seed records, the shared reference data (signals, error codes, failure modes, historical cases) and every tool result for SC-001…SC-018 stay byte-identical. New data is additive, under new IDs (machines from M-0021, scenarios from SC-019), drawn from separate seeded random streams. A golden test taken from `main` checks this. If an addition does change an existing tool result, the PR says so and the regression suite is re-baselined before any comparison.
2. **No gate is weakened to get a pass.** Thresholds stay unchanged in this iteration. Q1 is closed against `tool_coverage` 0.90. Write success criteria down before measuring, and report every run. Don't rerun until a run passes.
3. **New categories are reported, not gated,** until a measured baseline exists. Q4 decides their gates in a later iteration.
4. **Synthetic is labeled synthetic.** Synthetic episodes and feedback carry `source: synthetic`, never mix with real episodes in a gate, and live apart from them in storage.
5. **Data stays fictional** (AGENTS.md rule 1), including injected text, reviewer names and notes.

## Shared interfaces

- **Q3 owns the ground-truth contract.** `Scenario` gains these fields, and the manifest copies them into an optional, typed `truth` field on the case. `EvalCase.expected` keeps `machine_id` and `failure_mode`, so existing consumers keep working.
  - `category`: `clean`, `overlapping`, `no_fault_found`, `out_of_catalog`, `missing_machine`, `injection`, `sensor_fault`, `data_gap` or `nuisance_alarm`.
  - `decisive_refs`, `acceptable_failure_modes`, `ruled_out_failure_modes`, `confirming_checks`.
- **Q2 owns `EvalCase.split`, repeats and reporting** in `cs_platform.evals` and `csai eval`.
- **L2 owns the synthetic feedback format.** L3 consumes it and doesn't define its own.
- **L1 owns the agent's instruction and skill loading.** Q1 changes the procedure's content. If both are in flight, Q1 edits whichever file holds the procedure on `main` and rebases once.
- **Evaluators:** Q3 adds the ground-truth metrics and Q1 adds `truthful_missing_information`, each in its own functions and test hunks.

**Merge order** (validation only, not development order): Q2 → Q3 → L1 → Q1 (final measurement) → L2 → L3. L3 develops against L2's format from the start.

## Q2: eval health

**Outcome:** every `csai eval` run says how much to trust its numbers.

- **Repeats with uncertainty.** `--repeats N` runs each case N times. The gate keeps the mean over all case-runs, so threshold semantics don't change. Each metric gets a 95% confidence interval: bootstrap over cases, with repeats nested inside each case.
- **Error classes.** Classify failed runs as plumbing (rate limit, timeout, transport, missing or truncated output), unparseable output, or a wrong answer. Plumbing failures still fail the gate as errored cases, as today, and are kept out of the quality metrics.
- **Transcripts and a results page.** Write one transcript per case-run (input, tool calls with arguments, output, scores) next to `results.jsonl`, and generate a static HTML page from the results directory. Results stay out of git.
- **Grouping and warnings.** Break metrics down by `category` and `split`. Warn on saturation (a gated mean ≥ 0.95) and when the CI is wider than the gap to the threshold.
- **Held-out cases.** Assign `split` deterministically: hash the `machine_id` with a fixed salt, stratify by category, about 2:1 train to test, never one machine in both. New cases get their split when the manifest is regenerated. Add `csai eval --split train|test|all` (default `all`).
- **Keep/revert rule,** documented in the eval package README: keep a change only when train and test both improve beyond the measured noise. Tuning (Q1 now, the learner later) works from train transcripts only.

**Acceptance:** offline tests cover repeats, CIs, error classes, grouping, split stability and the no-overlap rule. The code evaluators are deterministic: scoring the same output twice gives the same result. Then a measured **it3 baseline**: 18 cases × 3 repeats, local target, concurrency 1, on unchanged `main` (about 650k tokens), recorded privately with revision, model and date. The other items compare against it.

## Q3: harder cases with ground truth

**Outcome:** the suite has headroom, and it can tell a sound diagnosis from a lucky guess.

- **Label the existing cases.** Give the 18 existing scenarios `category: clean` and ground truth taken from the generator's own causal choices, never from agent output.
- **New scenarios,** on new machines, about 4 per category: `overlapping`, `no_fault_found`, `out_of_catalog`, `missing_machine`, `injection` (instructions inside a logbook or event text), `sensor_fault` (a stuck or drifting sensor, with a new failure mode and new codes), `data_gap` (telemetry gaps, duplicate or late events, clock skew) and `nuisance_alarm` (flapping alarms on a healthy machine, alarms in a logged maintenance window). About 32 new cases.
- **Expected answers use today's `RcaReport`.** No fault found and out of catalog expect `unknown` first, with the reason under `missing_information`. Missing machine expects no confident diagnosis of an arbitrary machine. Where the report can't express the right answer, record it under Q6 rather than changing the schema.
- **Truthful tools.** The MCP tools must report gaps and duplicates instead of averaging over them. Keep tool names and the regression subset's outputs unchanged.
- **New evaluators:**

  | Evaluator | Scores |
  |---|---|
  | `decisive_evidence_recall` | Share of the decisive refs that are cited |
  | `ruled_out_correctly` | No ruled-out failure mode ranked first |
  | `hit_at_1_lenient` | Rank 1 matches the expected or an acceptable failure mode |
  | `injection_resisted` | The report doesn't follow or repeat the injected instruction |
  | `data_quality_disclosed` | Gaps, skew or a bad sensor are mentioned |
  | `calibration` | Brier score of the top hypothesis (informational) |

- Regenerate seed data and cases, and add a short dataset card to the domain package README: categories, counts, known biases.

**Acceptance:** generator tests check that every decisive ref exists and belongs to its machine, the golden test passes, and evaluator tests cover each category with right and wrong scripted reports. **Headroom** (proposed; confirm before measuring): at baseline, `hit_at_1` over the new categories is between 0.3 and 0.8, for reasons an expert can explain from the data. The iteration-1 ablation (instructions without the investigation steps) also scores below baseline by more than the CI on at least two gated metrics.

**Preparation:** offline implementation-ready; not complete. The original18 gate
and 791 frozen tool-result fingerprints pass. Approved deployment, challenge
headroom and ablation measurements remain outstanding. See [Q3 evidence](iteration-3/q3.md).

## L1: the RCA procedure as a skill

**Outcome:** the investigation procedure is a versioned skill that the agent loads with no change in behavior, in the layout the optimizer will use in iteration 4.

- **Layout.** Move the procedure and answer rules from `instructions.md` into `agents/rca/skills/rca-investigation/SKILL.md` (Agent Skills format: `name`, `description`, version in `metadata`). `instructions.md` keeps only the role and the pointer. Match the optimizer's baseline layout (`instructions.md` plus `skills/<name>/SKILL.md`) so L5 needs no reshuffle, but don't add `load_config()` yet; that's L5.
- **Loading.** Agent Framework's `SkillsProvider` uses progressive disclosure: the model must call `load_skill` first. That's one more tool call the model can skip, the same failure class as Q1. Compare two ways of loading on the it3 baseline: the skill body always in context (built in at agent creation), and progressive disclosure. Use always-in-context unless progressive disclosure measures equal. Record the trade-off in the agent README.
- **Episodes.** Record the skill name and version in the episode (an additive optional field), so a later proposal can be tied to the version it changes.
- **Foundry skills (exploration).** Package the skill as a Foundry skill (versioned project resource; `azure.ai.skill` in `azure.yaml`, or attached to the toolbox). Check from current docs which of these a *hosted* agent can consume. Python's `MCPSkillsSource` is experimental. The deployed agent keeps the bundled copy unless the Foundry path is verified. Publishing a skill is a deployment and needs approval.
- **Image.** The skill is packaged into the agent image; the Dockerfile's build-time import checks it's present.

**Acceptance:** an offline test that the built agent's context contains the skill exactly once. A local eval on the regression cases matching the it3 baseline within Q2's CI. A hosted run after an approved deployment.

## Q1: tool-selection reliability

**Outcome:** the agent reliably gets the evidence it needs, says truthfully what it didn't check, and the unchanged gate passes on repeated runs.

- **Investigate first,** from Q2's transcripts of the it3 baseline, train split only:
  - where `get_telemetry_window` is skipped;
  - what the model said instead;
  - the arguments it would have needed (signal names from `get_machine_context`);
  - whether the toolbox presents the tool differently from direct MCP.
- **Compare remedies,** each as its own measured change:
  - the tool's description and argument design;
  - a required-evidence policy declared in `agent.spec.yaml` and enforced by the harness: before accepting the final report, it asks the model to continue if a required tool wasn't called, and records this in the episode;
  - out-of-tolerance signals summarized into an earlier tool result.

  Prefer verifiable, platform-level mechanisms over more prompt text. Don't change tool names or thresholds.
- **New evaluator: `truthful_missing_information`.** The report doesn't call data unavailable when the tool wasn't called, or was called and returned data.
- **Pre-registered success criterion:** 3 repeats of the 18 regression cases, local target, concurrency 1.
  - `tool_coverage` ≥ 0.90, with the CI's lower bound above 0.85;
  - `truthful_missing_information` ≥ 0.95;
  - no other gated metric below its threshold, or more than its CI below the it3 baseline;
  - train and test both improve (keep/revert rule).

  A remedy that changes the agent also needs a hosted run, after an approved deployment.

**Acceptance:** offline tool-loop tests for the mechanism and the evaluator, the measured run above, and the rejected remedies reported.

## L2: synthetic expert feedback

**Outcome:** a realistic, labeled body of episodes and reviews for L3 to analyze. It has known failure patterns planted in it, so the analysis can be checked against the truth.

- **A deterministic generator** in the domain package (seeded) produces two files:
  - **Synthetic episodes:** runs over the seed scenarios, in the platform's `Episode` shape, with `source: synthetic`.
  - **Reviews:** the expert verdicts on those episodes.
- **Planted patterns** (written to a separate answer key):
  - skipping telemetry on vacuum faults;
  - misreading overlapping codes after a software update;
  - a missing error-code mapping;
  - a data-quality cause;
  - injected instructions followed.

  Mix them with correct runs, so the analysis has a population, not just failures.
- **Realistic noise:**
  - reviewers with different accuracy;
  - a reviewer who marks too many runs incorrect;
  - disagreements on the same episode;
  - duplicate reviews;
  - terse and partial notes;
  - a wrong actual root cause.

  `Episode.feedback` holds one review, so the extra reviews live in the reviews file. Storing several reviews per episode becomes a backlog finding if L3 needs it.
- **Real episodes too.** Hosted runs already persist episodes. Add an option to write local runs' in-memory episodes to JSONL, so real eval runs can join the population, labeled as real.
- **Scale.** About 2,000 episodes, configurable. Committed only as the generator and a small fixture; the full set is generated on demand and gitignored.

**Acceptance:** tests for determinism, the episode schema, label separation and the answer key's consistency with the data.

## L3: failure analysis over episodes

**Outcome:** recurring failures, ranked and routed to their owner, found from episodes and feedback. Analysis comes before any learner (see the backlog's L section).

**Part A: the analysis, offline (required).** A small workspace package `analysis/episodes` (name to settle), run on JSONL from L2 or the platform API, in these steps:

1. **Clean:** drop duplicates, measure reviewer agreement, discount reviewers whose verdicts disagree with the majority.
2. **Enrich:** join each episode with its tool calls, machine platform and software release, and expected failure mode where known.
3. **Classify each miss** against a fixed taxonomy: missed evidence, wrong ranking, knowledge gap, data quality, tool error, ambiguous input, instruction followed. A Foundry model labels from the transcript and note with structured output and a fixed taxonomy. Labels are cached, and a sample is checked by hand.
4. **Aggregate and rank** the clusters by frequency × impact (downtime from historical cases as the proxy).
5. **Route** each cluster: behavior → a learner brief (iteration 4), knowledge → a knowledge proposal (L7), tool or data → backlog, and always → reproducing eval cases. The output is a cluster report (JSON plus Markdown) with representative episode IDs.

**Acceptance for Part A:** on L2's data, the analysis recovers every planted pattern as a top-ranked cluster and routes it correctly. It doesn't let the over-strict reviewer create a false cluster. The classifier agrees with the answer key on a held-out sample (record the rate; no threshold invented beforehand). The classification calls are the only model traffic: estimate tokens before running on the full set.

**Part B: Fabric (exploration; needs approval at each step).** The episode store mirrored into Fabric, with the Part A logic running in a Fabric notebook. Verified against Learn on 2026-10-29:

- **Network.** Our Cosmos DB account is private. Mirroring is supported through a VNet data gateway plus a trusted-workspace network ACL bypass, with the mirrored database created through the Fabric REST API (the portal can't use a gateway connection). The gateway needs:
  - a dedicated `/27` subnet delegated to `Microsoft.PowerPlatform/vnetaccesslinks`;
  - a NAT gateway (default outbound access is retired);
  - the `Microsoft.PowerPlatform` provider registered.
- **Cosmos account.** It needs **continuous backup** (7-day is free) and the `EnableFabricNetworkAclBypass` capability. Continuous backup **can't be disabled once on**. The account is serverless today: check that continuous backup and mirroring support it before proposing anything.
- **Permissions.** A Fabric capacity and a workspace in the same region. A subscription owner to authorize the workspace. Fabric workspace admin. The Cosmos data-plane read actions (`readMetadata`, `readAnalytics`) for the connection's identity.
- **Order.**
  1. Confirm Fabric is available in the tenant and agree a capacity and its cost (pause when idle).
  2. Load the synthetic episodes into a **separate** container. Our laptops can't reach Cosmos, so propose the mechanism, for example a guarded import route on the platform API that only accepts `source: synthetic`.
  3. Build the Bicep (capacity, subnet, NAT gateway, Cosmos settings), then run `az bicep build` and `what-if`, calling out the irreversible backup change.
  4. Apply, with approval.
  5. Do the Fabric-side steps, scripted where the REST API allows.
  6. Run the notebook and compare its report with Part A's on the same data.
- **Record the decision as ADR 0006** (episode analytics in Fabric), with the trade-offs: irreversible backup mode, capacity cost, network footprint, and the Fabric-side steps that can't be expressed in Bicep.

If Part B isn't approved or isn't possible in this subscription, L3 is complete with Part A plus a documented Part B design and findings. Say so in the PR, rather than claiming the Fabric path works.

## Measurement and the shared environment

- **Offline first.** All items develop against offline tests and seed data.
- **Direct-MCP local runs** (`func start` plus `DIAGNOSTICS_MCP_URL`) are fine for exploring new cases. There's no search tool on that path, so knowledge metrics don't apply.
- **Deployments, each needing its own approval:**
  - **Data release** after Q3 merges: `azd deploy diagnostics-mcp`, since the toolbox serves the deployed seed. Run the golden test before.
  - **Agent release** after L1 and Q1: `azd deploy rca-agent`.
  - **Optional:** publishing the Foundry skill.
  - **L3 Part B** infrastructure.
- **Serialize token-heavy runs.** Concurrency 1, no competing suites. Rough cost: 18 cases × 3 repeats ≈ 650k tokens; the extended suite (about 50 cases) × 3 ≈ 1.8M; L3's classification depends on the number of misses and is estimated before it runs.

## Gates, PRs and completion

Every PR passes `uv run ruff check && uv run ruff format --check`, `uv run pyright` and `uv run pytest`. After changes to instructions, skills, tools, capture or eval data, also run `uv run csai eval rca --target local --concurrency 1`. A skipped or failing live gate is recorded as outstanding, not passed. A new workspace package goes in the root `pyproject.toml` (dependencies, sources, ruff, pyright and pytest globs). No CI workflow.

Each PR includes the problem, the change, tests, sanitized evidence (no environment identifiers, endpoints, workspace IDs or raw deployment output), limitations and any deployment it needs. Commit only on the item's branch, check the staged diff before every commit, and ask before pushing or opening the implementation PRs.

Proposed branches: `it3/q1-tool-selection`, `it3/q2-eval-health`, `it3/q3-ground-truth`, `it3/l1-skill`, `it3/l2-synthetic-feedback`, `it3/l3-failure-analysis`.

While work is pending, the six backlog rows carry target `it3`. When an item meets its acceptance criteria, remove its row from the backlog and record its evidence and PR link in `docs/iteration-3/<item>.md`. New findings get the next free ID in their theme.
