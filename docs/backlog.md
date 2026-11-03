# Backlog

Open work for the platform, grouped by theme, with stable IDs (`Q3`) that iteration plans refer to.

An item belongs here if it does at least one of two things:

- closes a gap between the sample and the [specification](specification.md): its platform capabilities (§5), the governed learning loop (§6) or its requirements (§7);
- tries an Azure technology the project is likely to use, in the place the platform would use it.

Everything else goes under [Later](#later) as one line, or is left out. Items removed in the October 2026 rework are in git history (commit `f19dbc8`).

## How to use it

- **Add an item** to the theme it fits, with the next free ID, one sentence of why, and the technology it explores, if any. IDs are never reused or renumbered.
- **Notes** record only verified facts and constraints. Design belongs in the iteration plan, written when the item is taken; check preview features again at that point.
- **Size** is a rough first guess: **S** up to a day, **M** a few days, **L** a week or more.
- **Target** is empty until an iteration takes the item; then it names the iteration (`it3`). Remove completed items, and keep their evidence and pull request links in the iteration record (`docs/iteration-N/`).
- An iteration's scope and order live in its plan (`docs/plan-iteration-N.md`).

## Themes

| Theme | What it shows |
|---|---|
| [Q. Evaluation you can trust](#q-evaluation-you-can-trust) | Scores that tell a better agent from a worse one |
| [L. Governed learning loop](#l-governed-learning-loop) | Expert feedback becomes approved, replayed improvements (spec §6) |
| [K. Knowledge and data](#k-knowledge-and-data) | Diagnostic knowledge and telemetry beyond the seed data |
| [R. Agent runtimes and channels](#r-agent-runtimes-and-channels) | Other ways to run the agent and reach engineers |
| [S. Security and operations](#s-security-and-operations) | Entra everywhere, central control, and knowing when it breaks |

## Q. Evaluation you can trust

The design is [ADR 0009](adr/0009-evaluation-system-design.md): a small outcome gate computed locally, model judges in Foundry, and more cases rather than more metrics.

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| Q4 | **Gate on four outcome metrics** | `tool_coverage` and `used_knowledge` reward a ritual; the gate should say whether the diagnosis is right, grounded and safe ([ADR 0009](adr/0009-evaluation-system-design.md)). | | M | done it4 ([#28](https://github.com/marcgs/cs-ai-platform-sample/pull/28)) |
| Q16 | **Publish judges only** | Superseded by the Foundry-native evaluation spike; the branch remains unmerged. | Foundry evaluations | S | closed, superseded ([#29](https://github.com/marcgs/cs-ai-platform-sample/pull/29)) |
| Q17 | **Score trend across runs** | Progress needs a scoreboard over time, including the metrics Foundry can't show; today each run is a separate report. | | S | Q20 spike follow-up |
| Q18 | **Judges checked against expert labels** | A model judge can only join the gate once its agreement with experts is measured on the same cases. | Foundry evaluators | S | |
| Q19 | **Grow thin cohorts** | Four injection cases and twelve missing-machine cases give intervals too wide to act on; the gate and the learner need more cases, not more metrics. | | M | |
| Q20 | **Foundry-run agent evaluation** | Foundry's own flow calls the hosted agent and scores it; we've only sent Foundry our results. Shows what a team gets from Foundry alone, compared with our harness. | Foundry agent-target evaluation, `azd ai agent eval` | M | spike |
| Q5 | **Cost and latency per diagnosis** | Time to diagnosis is the main outcome, and cost decides the model. | Foundry tracing | S | |
| Q6 | **Ask instead of guess** | Given a symptom without a machine, the agent picks one and diagnoses it; the report can't ask a question. | | S | |

Notes:

- **Q4:** done in [#28](https://github.com/marcgs/cs-ai-platform-sample/pull/28): minimum means for `hit_at_1_lenient`, `decisive_evidence_recall` and `evidence_grounded` across applicable original and challenge cases; `injection_resisted` hard-fails any applicable failed case-run. Invalid reports score zero, stay in the denominator and are counted separately; only true plumbing is excluded. Other metrics and feedback stay report-only. Approved provisional minimums 0.70 / 0.65 / 0.85 pass the final retained 50-case re-score at 0.78 / 0.75 / 0.92 (four invalid reports, no plumbing, all four injection checks pass); see the [eval guide](../evals/rca/README.md).
- **Baseline (Q4 follow-up), target: Q20 spike follow-up.** The three-repeat baseline and its publication wait for [#31](https://github.com/marcgs/cs-ai-platform-sample/pull/31)'s decision and human merge of the feedback cases. They replace provisional floors in the selected evaluation setup; no approval request is being prepared.
- **Q16:** closed as superseded by [the Q20 spike](spike-foundry-native-eval.md). [#29](https://github.com/marcgs/cs-ai-platform-sample/pull/29) is closed; its judges-only definition, observation-timeout handling and mirror removal remain on an unmerged branch. Main still has the existing publisher. Earlier sparse-parity, calibration-direction and transport findings remain evidence in [Q9](iteration-4/q9.md), not extra iteration-4 completion gates. Further publication work depends on the spike decision.
- **Q17:** read the retained run records (`results.summary.json` per run), not Foundry. One static page: each gated metric per run with its interval and threshold, by agent, skill and exact model version. The chat deployment upgrades its model version automatically, so a change in the trend can come from the model rather than the agent.
- **Q18:** the 20 blind person judgments from L8's fresh cohort are a first label set. Measure each judge's agreement on the same episodes before it gates anything.
- **Q19:** grow where intervals are widest first: injection, missing machine, then the other challenge categories. Q3's generator and answer-key format apply; L9 adds feedback cases on top.
- **Q20:** widened in [#31](https://github.com/marcgs/cs-ai-platform-sample/pull/31) into a spike on whether Foundry can run the whole evaluation: agent target, judges, all our metrics as custom evaluators (endpoint evaluators for sparse applicability), repeats, comparison and a pipeline gate. Plan and capability matrix in [the spike plan](spike-foundry-native-eval.md); the decision becomes ADR 0010. No probe has run. Run 1 follows human merge of the case and close-out PRs and separate model/write approvals.
- **Q5:** report cost and latency per diagnosis; don't gate on them.
- **Q6:** Q3's missing-machine cohort scores 1/12 on both hit-at-1 and schema validity.

## L. Governed learning loop

Capture and feedback exist. This theme adds the rest of the specification's loop (§6). Each turn produces two kinds of pull request, in this order, and a person merging one is the approval:

1. **Analysis** groups episodes and feedback into clusters and says how strong each signal is.
2. **Cases first.** Reviewed episodes with consensus, successful replay and no duplicate become new eval cases, in a pull request; clustering is not admission. A person merges it before a new baseline. Iteration 4's baseline and publication wait for the Q20 spike decision.
3. **Then proposals.** A learner turns one behavior cluster into a change to the skill, in a pull request. The platform replays it against the new baseline and posts the scores; a person merges or closes it.
4. **After release**, the platform checks whether the cluster shrank.

The learner is whatever writes the diff. Everything around it (cases, replay, scores, review) is deterministic, and that's what makes the loop safe.

| Stage | Items |
|---|---|
| Capture, feedback | done; synthetic feedback at scale: L2 |
| Analysis | L3, L8 |
| Feedback → eval cases (pull request) | L9 |
| Baseline, measured and published | Q2, Q8, Q9 |
| Proposal (pull request) | L5 |
| Replay and merge | L4 |
| Release and check | L10, L11 |
| Run on a schedule | L6 |
| Confirmed diagnoses → knowledge | L7 |

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| L1 | **The RCA procedure as a skill** | A versioned skill is the unit the loop changes and the optimizer works on. | Agent Framework skills, Foundry skills | S | done it3 ([#15](https://github.com/marcgs/cs-ai-platform-sample/pull/15)) |
| L2 | **Synthetic expert feedback** | The loop needs feedback with realistic patterns and noise, including wrong reviews that must not push a change through. | | S | done it3 ([#14](https://github.com/marcgs/cs-ai-platform-sample/pull/14)) |
| L3 | **Failure analysis over episodes** | At scale, feedback has to be cleaned, classified and ranked into clusters before anything learns from it; most clusters aren't prompt problems. | Cosmos DB mirroring to Fabric, Foundry models for classification | M | done it3 ([#17](https://github.com/marcgs/cs-ai-platform-sample/pull/17)) |
| L4 | **Proposals are replayed and merged** | No change to agent behavior without a passing replay and a person's approval. | | M | |
| L5 | **A learner drafts proposals** | Turns one diagnosed cluster into a candidate change to the skill. | Coding agents, Foundry agent optimizer | M | |
| L6 | **The loop on a schedule** | Until then a person starts each turn of the loop by hand. | Cosmos DB change feed, Logic Apps or Container Apps jobs | M | |
| L7 | **Confirmed diagnoses become knowledge** | Every confirmed diagnosis is a new historical case; today the index holds only seed data. | AI Search | S | |
| L8 | **Stable evidence-pattern clustering** | L3's frozen live pilot turns 30 labels into 21 clusters; equivalent condition names split patterns and taxonomy mistakes misroute cases. Validate consolidation and category distinctions without tuning on the opened held-out key. | | M | it4, closed as a finding (L12) |
| L9 | **Feedback becomes eval cases, as a pull request** | The first thing the loop should produce is a better measure, not a changed agent. | | M | done it4 ([#30](https://github.com/marcgs/cs-ai-platform-sample/pull/30)); case PR pending |
| L10 | **Release an approved change** | A merged proposal has to become the deployed agent version, and be easy to roll back. | Foundry agent versions | S | |
| L11 | **Check the change worked** | Without it nobody knows whether a merged change fixed its cluster, and the loop never closes. | | S | |
| L12 | **Clusters that match recurring patterns** | The fresh L8 run's clusters are pure (precision 1.0) but too fine: three of five patterns split into 3–4 clusters. A learner needs one cluster per pattern to pick what to work on. | | M | |

Notes:

- **L1:** [#15](https://github.com/marcgs/cs-ai-platform-sample/pull/15) merged the eager packaged skill with local/hosted evidence. The planned comparison with native `SkillsProvider` progressive loading is still unperformed; the provider exists in the validated SDK. Do not equate packaging completion with completion of that comparison.
- **L3:** routes each cluster to its owner: behavior to L5, knowledge to L7, tools or data to this backlog, and reproducing cases to the eval suite.
- **L3, measured:** the approved 50-episode pilot has 24/30 category agreement against the key, 27/30 member routes correct, no classified key-controls among 19, and best-cluster ranks 3/9/2/1/4. Assistant-audit category agreement is separately 3/8 supported classified misses, not human-expert accuracy. The user approved merging [#17](https://github.com/marcgs/cs-ai-platform-sample/pull/17), but Part A acceptance remains incomplete.
- **L8:** exact `(category, normalized condition)` grouping splits `prompt_injection_logbook` and `prompt_injection_in_logbook`. Per-pattern best-cluster recall is 25%-71.4%. No post-key alias merge, prompt tuning or second pilot was performed; future scope and a fresh evaluation cohort need approval.
- **L8/L12, fresh measurement:** one approved v3 run produced 30 valid labels and 11 clusters, using 118,210 reported tokens. Best-cluster recalls are 0.50/0.50/0.75/0.875/0.833; fragmentation is 2.4 against 1.5, so acceptance fails. Key category/member-route agreement is 26/30 and 28/30; person agreement is separately 6/9 and 5/9 on classified person misses. All 20 blind judgments have person acceptance; top-five cluster review is no longer needed for close-out. Outputs were frozen before the key opened; no retuning or rerun followed. L8 closes as a finding continued under L12. See [the retained L8 outcome](iteration-4/l8.md#approved-fresh-classification-and-failed-acceptance--3-november-2026).
- **L12:** recorded on 2026-11-03 as a finding, not an iteration-4 blocker. The splits follow the cluster key `(category, condition)`: the condition is often the machine fault being diagnosed rather than the agent's mistake, and the category wavers between `missed_evidence` and `wrong_ranking` for the same pattern. To try, on a fresh batch whose key nobody has read: cluster on the category first with the condition as a subgroup, and define the two categories against each other with train-split examples. Take it with the learner (L4, L5), which is what needs clusters.
- **L9:** done in [#30](https://github.com/marcgs/cs-ai-platform-sample/pull/30): consensus, replay and no duplicate, not clustering. All reviewed fresh-cohort episodes are candidates, including those never classified. Corroborated reviewer cause plus replay-matched synthetic scenario category are labeled separately in provenance; other truth fields stay empty. Real feedback still needs independent category metadata. Integrity and deterministic-rerun checks pass. The first data proposal, [#32](https://github.com/marcgs/cs-ai-platform-sample/pull/32), admits 3 of 50 candidates and is open for human review/merge, not yet accepted. Add its merged link to the completed L9 record after that review; do not treat an open proposal as merged. See [L9 Part B](iteration-4/l9b.md).
- **L4:** a proposal records its cluster, its diff and its replay. It replays on the cluster's cases and on the train and held-out splits (Q2), and is kept only if it improves the cluster without a held-out regression. Scores go to the pull request and to Foundry (Q9). The learner never edits evaluators, thresholds or cases, and never sees held-out transcripts.
- **L4, first targets:** two process gaps, moved here from the evaluation theme on 2026-11-03 because they're agent behavior, not measurement. Tool selection: the agent skips `get_telemetry_window` in up to 10 of 18 cases and calls the unchecked data unavailable ([PR #9](https://github.com/marcgs/cs-ai-platform-sample/pull/9) review). Knowledge citation: the [retained Q2 baseline](iteration-3/q2.md) cites historical cases in 24 of 54 runs (0.444, 95% CI about 0.28–0.61) despite correct diagnoses, while a later Q3 control scores 49/54. Neither was fixed by hand.
- **L5:** checked 2026-10-29. The optimizer improves a hosted agent's instructions, skills, function-calling tool descriptions and model choice. The agent loads its configuration through the optimizer package (`load_config()`). Our tools are MCP, so tool optimization doesn't apply. It scores with an eval model on binary criteria; `eval.yaml` takes a held-out `validation_dataset`, which should come from Q2's test split. Verify first that it runs in a network-injected project (see Q9) and whether it can score with our evaluators. Start with a coding agent (Claude Code or GitHub's coding agent) writing one diff per cluster, editing only the skill directory, and compare the optimizer with it on the same cluster.
- **L10:** episodes record the skill version (L1), so every later episode shows which version produced it. Rollback is redeploying the previous version; a canary relates to S5.
- **L11:** run the agent on fresh cases matching the cluster's pattern and compare the cluster's rate per skill version. With synthetic feedback this stands in for field results; say so in the report.

## K. Knowledge and data

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| K1 | **A knowledge base over historical cases** | A knowledge base plans its own queries and returns cited results, and could serve future document sources too. | Foundry IQ | M | |
| K2 | **Manuals and service bulletins as knowledge** | Most diagnostic knowledge lives in documents; the index holds only structured cases. | Content Understanding | L | |
| K3 | **Telemetry in a time-series store** | Real telemetry needs a store the tools can query at scale. | Fabric Real-Time Intelligence or Azure Data Explorer | L | |
| K4 | **Replayable data for cases from feedback** | A case from an episode only replays truthfully if the tools return what they returned then; the static seed hides this. | | M | |

Notes:

- **K2:** needs synthetic documents (manuals, bulletins) consistent with the catalog, with refs the evaluators can check.

## R. Agent runtimes and channels

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| R1 | **The RCA skill on a managed harness** | Shows what a managed agent loop gives and costs, with the same tools, suite and episodes around it. | Copilot harness | M | |
| R2 | **A triage agent calling RCA** | The hosted agent already exposes an A2A endpoint; a triage agent can route to it without glue code. | A2A | M | |
| R3 | **Engineers ask from Teams** | Field engineers ask where they already work. | Teams, Microsoft 365 Copilot | M | |

Notes:

- **R1:** checked 2026-10-29. The harness rejects `text.format`, so there's no strict `RcaReport`. Every request needs a `conversation`. The agent identity needs the Foundry User role on the project to call a toolbox, assigned after creation. Shell, web, file and subagent tools are on by default. Sweden Central is supported. A prompt agent runs none of our code, so episodes must be built outside the agent (from the response and trace).

## S. Security and operations

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| S1 | **Entra for the MCP server and platform API** | The last two keys: the MCP function key held by Foundry and the platform API key `csai` fetches. | Functions built-in auth, app registrations | M | |
| S2 | **Prompt-injection guardrails** | A logbook entry or tool result can carry instructions; protect at the platform, not only in the prompt. | Foundry guardrails, AI red-teaming agent | M | |
| S3 | **AI gateway** | Quotas per agent, logging and failover for models and tools. | API Management | L | |
| S4 | **Fleet view and kill switch** | Someone has to see every agent, its cost and errors, and be able to stop one fast. | Foundry Control Plane, Entra Agent ID | M | |
| S5 | **Canary diagnosis and alerts** | Failed runs, store outages and rate limiting should page someone. | Foundry monitoring, Azure Monitor alerts | S | |
| S6 | **SDK dependency compatibility** | A fresh dependency resolution can break the real MCP session even when the baseline local resolution passes; verify compatible SDK ranges without committing a lock file. | Agent Framework, MCP | S | |
| S7 | **Reproducible offline packaging gate** | A freshly recreated workspace environment lacks `hatchling`, so the offline skill-packaging test fails until its build backend is installed separately. | uv, Hatchling | S | |
| S13 | **Drift-safe reprovisioning** | The full provision preview detaches subnet NSGs, changes connection sharing and disables Cosmos DB automatic failover; preserve or explicitly approve existing live configuration before acceptance provisioning. | ARM what-if, Bicep | S | |
| S14 | **Verify provision-hook dispatch** | An approved provision succeeded without search-seeding completion output, while explicitly running the postprovision hook seeded successfully; establish reliable hook dispatch and its verification. | azd hooks | S | |

Notes:

- **S2:** test with Q3's injection cases, starting in annotate mode.
- **S6:** found during iteration-3 validation: `agent-framework-core` 1.23.0 with `mcp` 1.30.0 fails both parameterizations of `test_real_mcp_session_propagates_episode_context_in_metadata` because `ClientSession.protocol_version` is absent. Framework core 1.22.0 with MCP 1.30.0 passes. No compatibility constraint was changed as part of Q2.
- **S6, live observation:** the isolated L1 attempt also encountered cancellation inside `FoundryToolbox.connect` / `session.list_tools` with core 1.22.0 and MCP 1.30.0. Its origin is unproven; the traceback does not distinguish an SDK lifecycle defect from a transient fault.
- **S7:** integration review passed 496 tests but failed the skill-packaging test with `ModuleNotFoundError: No module named 'hatchling'` after uv recreated the environment. Installing the missing backend locally with `uv pip install hatchling` made all 497 tests pass. No dependency manifest was changed; make the offline test's build requirements reproducible separately.
- **S13:** read-only acceptance preparation on clean `7b56c46` reproduced 44 modifications and five unsupported resources. Three subnet NSG associations are removed, three connections change `isSharedToAll` from false to true, and Cosmos DB automatic failover changes from true to false. Twelve role-principal expressions and both apps' settings/storage were verified as drift. The user-approved prepared branch removes the real deltas with environment-backed NSG IDs and explicit live settings; deployment and unsupported-assignment verification remain outstanding. No provisioning was performed; see [Q9 acceptance preparation](iteration-4/q9.md#acceptance-preparation--1-november-2026). S8–S12 are reserved for the separate networking plan.
- **S13, applied:** after separate approval, provision succeeded from the prepared branch. Post-provision reads confirmed the three NSGs, failover, connection visibility, model policies and account routing were preserved. The infrastructure is committed in [#26](https://github.com/marcgs/cs-ai-platform-sample/pull/26), not yet merged, so unchanged main retains the unsafe preview.
- **S14:** the successful acceptance provision had no search-seeding completion in its retained log. Explicitly invoking the already-approved `azd hooks run postprovision` exited zero and printed 40 historical cases. Automatic dispatch is unverified, not passed; the cause was not investigated as part of acceptance.

## Later

Kept in view, not planned. Each would get a proper item when it becomes relevant.

- Full private networking for Foundry, the registry, AI Search and Application Insights.
- Continuous evaluation of production traffic (after Q9), judges only ([ADR 0009](adr/0009-evaluation-system-design.md)).
- Agent Framework `evaluate_agent` as the eval runner, if its local results can reach the Foundry portal (ADR 0009).
- Model comparison across providers, and the model router.
- Conversations (multi-turn) and managed agent memory.
- Long-running diagnoses with a human in the loop, and action tools with approvals.
- Multi-agent workflows.
- Voice for engineers at the machine.
- Edge and on-premises inference (Foundry Local).
- Environments, promotion and active CI/CD.
- A third agent framework.
