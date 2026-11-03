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

| ID | Item | Why | Explores | Size | Target |
|---|---|---|---|---|---|
| Q1 | **Tool-selection reliability** | The gate is red: the agent skips `get_telemetry_window` in up to 10 of 18 cases (`tool_coverage` 0.89 against 0.90) and calls the unchecked data unavailable. | | M | |
| Q2 | **Eval health** | Nobody knows how much scores vary between runs, or whether a failure was the model or the plumbing. | | M | done it3 ([#13](https://github.com/marcgs/cs-ai-platform-sample/pull/13)) |
| Q3 | **Harder cases with ground truth** | All 18 cases pass at baseline, so the suite can't show improvement, and a root-cause label can't tell a sound diagnosis from a lucky guess. | | M | done it3 ([#16](https://github.com/marcgs/cs-ai-platform-sample/pull/16)) |
| Q4 | **Gate on outcomes, with model judges** | `tool_coverage` rewards a ritual, and the specification asks for model-based evaluators. | `azure-ai-evaluation` | S | |
| Q5 | **Cost and latency per diagnosis** | Time to diagnosis is the main outcome, and cost decides the model. | Foundry tracing | S | |
| Q6 | **Ask instead of guess** | Given a symptom without a machine, the agent picks one and diagnoses it; the report can't ask a question. | | S | |
| Q7 | **Knowledge-citation reliability** | The pinned iteration-3 baseline cites historical knowledge in only 24 of 54 runs, below the unchanged 0.70 gate despite correct diagnoses; investigate retrieval versus citation failures without forcing irrelevant citations. | | M | |
| Q8 | **Durable in-progress eval capture** | A fatal interruption can discard completed results and episodes before the CLI's final export; checkpoint actual records without turning cancellation or recovery into quality-seeking resampling. | | M | it4 |
| Q9 | **Eval runs published in Foundry** | Baselines and replays should be visible and comparable per agent version where the agent lives, not only in a terminal. | Foundry evaluations, capability hosts, custom evaluators | M | it4 |
| Q10 | **Sparse-score parity in Foundry** | The code-evaluator contract has no documented not-applicable result, so local sparse metrics and plumbing exclusions cannot be mirrored as unconditional per-row grades. | Foundry custom evaluators | S | |
| Q11 | **Explicit infrastructure-only publication retries** | Allow explicitly approved attempts for a positively evidenced zero-row startup failure, retaining failed runs, immutable measurements and receipt lineage. | Foundry evaluations | S | it4 |
| Q12 | **Evaluation upload denial diagnosis** | Logged project-identity CreateContainer AuthorizationFailure cleared after the approved AzureServices bypass; the 50-row run completed without an Owner grant. Dedicated diagnostic destination-type readback still differs from its declaration. | Foundry evaluations, storage networking/RBAC/ABAC | S | |
| Q13 | **Publication polling deadline** | The fixed 15-minute publisher wait expires while a registered 50-case/four-judge run remains active. Distinguish observation timeout from terminal failure and review the wait policy without resubmitting measurements. | Foundry evaluation monitoring | S | |
| Q14 | **Calibration pass direction in Foundry** | Offline fix publishes calibration_score = 1 - Brier, higher-is-better, preserving local gates and the existing run. Schema-4 migration and live verification await the approved baseline publication. | Foundry code-evaluator pass metadata | S | |
| Q15 | **Numeric transport fidelity in Foundry** | All 450 per-row published code scores pass the approved absolute tolerance of 1e-12; 40 calibration values differ by at most 9.97465998686664e-16 at an unknown service stage. All 532 retained raw input scores match exactly. | Inline evaluation-data serialization | S | |

Notes:

- **Q1:** found in the [PR #9](https://github.com/marcgs/cs-ai-platform-sample/pull/9) review; the failed run was accepted as recorded, not as a pass. Earlier suites skipped the tool in 7–8 cases. The numbered instruction alone is insufficient. Keep the threshold; don't rerun to get a pass.
- **Q1, after it3:** not attempted in iteration 3. Kept as a candidate first target for the learner (L4, L5) rather than a hand fix.
- **Q2:** repeats with confidence intervals, plumbing failures apart from wrong answers, per-case transcripts, a saturation warning, and train and held-out cases split by machine (the keep/revert rule that L4 relies on).
- **Q3:** decisive evidence, acceptable alternatives and ruled-out modes per scenario; categories such as overlapping, no fault found, out of catalog, missing machine, injection and noisy data. Keep the 18 existing cases byte-identical so the baseline stays comparable.
- **Q3, measured:** one approved live experiment completed 150 baseline and 54 ablation results. Original18 baseline gates pass unchanged; challenge hit-at-1 is 69/96. Removing the investigation procedure degrades coverage and knowledge use beyond their paired confidence intervals, overall and on both splits. Failed attempts and ablation gate failures remain retained; see [Q3 evidence](iteration-3/q3.md).
- **Q6:** Q3's missing-machine cohort scores 1/12 on both hit-at-1 and schema validity. This report-only finding does not authorize report-schema or behavioral changes.
- **Q4:** a change to which metrics gate needs the user's approval, and not as Q1's fix.
- **Q7:** the [retained Q2 baseline](iteration-3/q2.md) ran the unchanged `fae76ff` agent and dataset, 18 cases with three repeats at concurrency one. `used_knowledge` was 0.444 (95% CI approximately 0.28–0.61), while `hit_at_1` was 1.00 and search was called in 0.67 of runs. The run failed and was retained; no threshold was lowered and no rerun was used to seek a pass.
- **Q7, separate observation:** the later Q3 control scores 49/54 on knowledge use. It neither replaces the failed Q2 run nor proves consistent citation reliability or a causal L1 improvement.
- **Q8:** the first isolated L1 measurement was cancelled during MCP tool discovery after 25 completed case-runs. Only rounded console observations survived; no complete result or episode export was written. Private recovery drivers journal actual records immediately, but the public CLI still exports after the suite. Preserve genuine cancellation and failed attempts; do not reconstruct missing episodes from scores.
- **Q8, implementation:** [#20](https://github.com/marcgs/cs-ai-platform-sample/pull/20) adds durable capture and public offline rebuilding. Copilot review fixes cover persistence retry barriers, export finalization, private permissions, partial-write recovery and directory durability. The separately approved clean-main `7b56c46` post-fix measurement passed the original gate with 50 retained case-runs, episodes and transcripts, no retries, and a byte-preserving public report rebuild; see [Q8 evidence](iteration-4/q8.md#fresh-post-review-acceptance--2-november-2026). Its single-repeat publication completed; the final baseline remains outstanding.
- **Q9:** `csai eval --publish` exists since iteration 1 and fails here. Checked 2026-10-30 against Learn and the deployed environment (read-only): a network-injected project needs a capability host at both the account and the project. The account has one (network injection creates it); the project has none and no storage connection. A project capability host of kind `Agents` without connections can be added to an existing project once the account has one (foundry-samples template 15a, `add-project-capability-host.bicep`), so the "only at creation" constraint in AGENTS.md and ADR 0004 looks outdated for this case. The project identity already has Foundry User on the account. Capability hosts can't be updated, only deleted and recreated; deleting one orphans the agent state stored through it. Code-based custom evaluators (preview) run a `grade()` function in a sandbox without network access. Not yet verified: whether a run completes without a storage connection, and whether the host changes anything for the running hosted agent.
- **Q9, implementation:** durable-record publishing and the project-host declaration are in [#21](https://github.com/marcgs/cs-ai-platform-sample/pull/21), but deployment and live publication are not accepted. With and without the new host, subscription previews have identical modification payloads for 44 resources and five unsupported resources each; the host is the only create. The existing modifications still need review before provisioning. See [Q9 evidence](iteration-4/q9.md).
- **Q9, acceptance:** drift-preserving provision and hosted/API smoke passed. The mapping rejection, empty-definition replacement, retained zero-row startup failure and upload-denial attempts are recorded in [publication evidence](iteration-4/q9.md). After the logged network-only repair, one approved retry completed with 50 rows. The user confirmed rows, code/judge scores and version labels in the portal. Reporting corrections, sparse parity and the final baseline remain open.
- **Q10:** the user chose one run per measurement, retaining applicable sparse scores in rows and explicitly blocking parity acceptance. Only uniformly applicable metrics are mirrored; plumbing-bearing runs do not mirror quality aggregates. A metric-schema change needs a reviewed migration of the suite's single Foundry evaluation. Do not invent missing scores or change local gates.
- **Q11:** found during Q9's first mapped cloud run: the service accepted the run and then failed before producing rows. The publisher retains and retrieves that failed run. The user adopted the narrow recovery contract and approved offline implementation as additional iteration-4 recovery scope; see [ADR 0007](adr/0007-infrastructure-only-publication-retries.md).
- **Q11, implementation:** `--retry-infrastructure` requires positively evidenced zero-row `EvaluationSessionNotBound` failure and retained receipt lineage. A separate deterministic attempt receipt preserves the original run, receipt and all frozen metadata; repeating an approved request resumes that attempt. All 77 focused tests and 608 full tests pass, with 32 existing warnings, Ruff and strict Pyright green. The implementation is committed on `it4/finish-acceptance`, and the separately approved post-network-repair retry completed without resubmission. Another publication still needs separate approval.
- **Q12:** the verified project Contributor grant lacks explicit blob-tag data actions. Current template 15a additionally assigns project Blob Data Owner at storage-account scope with an ABAC condition on tag read/write/filter operations; other Owner blob permissions remain account-wide. Newer evaluation-permissions guidance says project Contributor suffices, while older region guidance asks for Owner on account and project identities. The upload's public error gives no storage-specific code or failing identity, so missing tag permissions are a hypothesis, not a proven root cause. No Owner, account-identity or developer grant, sharing change or public/key exception is approved. The user chose to pause with permissions unchanged; no broader preparation was adopted.
- **Q12, logged diagnosis:** the approved logging create, separately approved corrective PUT and single possibly judged reproduction have executed. After 12 minutes, one scoped StorageBlobLogs 403 identifies the project identity, OAuth, CreateContainer and AuthorizationFailure. Actual ingestion works despite ARM GET's null destination type; exact readback parity remains open. An account-only resource-instance rule is proposed in [ADR 0008](adr/0008-evaluation-storage-network-exception.md), not applied; documentation does not explicitly establish its child-project coverage. No Owner or network change is approved. Another request may consume about 680k mapped judge input tokens plus additional charges and needs separate approval. Stop after failure with both 15a differences resolved. Local L8/case/baseline acceptance no longer waits for publication.
- **Q12, account-only attempt:** the user subsequently approved one account-only rule write and one possibly judged retry. The write was verified with bypass None, public access Disabled, private endpoint and effective role IDs unchanged. The retry again received pending-upload HTTP 403; its new scoped log correlation is pending. Both approvals are consumed. No broader bypass, Owner grant or further request is authorized.
- **Q12, post-rule logs:** the correlated denial remains project-identity OAuth CreateContainer AuthorizationFailure, with the narrow rule verified 76.8 seconds before retry start. The account-only attempt did not resolve network admission. A bypass-only AzureServices change matching 15a is proposed, not approved; no permission-mismatch evidence justifies Owner. Remote state still has only the retained original failed run.
- **Q12, bypass accepted:** the user subsequently approved one bypass-only AzureServices write and one possibly judged retry. Readback verifies other network restrictions, private endpoint, encryption and roles unchanged. After at least 90 seconds, the retry registered a new in_progress run; row counts are zero at that check and completion/portal parity are pending. Creation-time rejection cleared without Owner. No concurrent local model job or further write is authorized.
- **Q13:** the approved publisher exited 2 after its 900-second polling deadline. Read-only inspection finds the same run in_progress, no service error and zero output items; the local timeout did not cancel it. The original receipt/58-file measurement remain intact. A bounded read-only observer watches that run without creating another. No publisher wait-policy change is authorized; see [Q9 evidence](iteration-4/q9.md#publisher-timeout-existing-cloud-run-still-active--2-november-2026).
- **Q13, completion:** the same run completed in 19m37.727s with 50 output rows and zero errored; no resubmission followed the observation timeout. The reported 200 judge invocations used 763,268 tokens, not twice that amount despite duplicated model/wrapper usage entries.
- **Q14/Q15:** final comparison verifies frozen provenance and 410/450 exact common-score matches. All 40 differences are calibration-only, maximum about 9.97 × 10^-16, at an unknown service stage after exact inline input. Calibration pass flags disagree with lower-is-better in all 50 rows and contribute to the 50-failed display; the local gate is unchanged. Portal confirmation passed. The user approved the offline score mapping and numeric audit at absolute tolerance 1e-12, not another publication; see [completed validation](iteration-4/q9.md#completed-validation-and-acceptance-findings--2-november-2026).
- **Q14/Q15, offline acceptance:** [#26](https://github.com/marcgs/cs-ai-platform-sample/pull/26) adds the separately named score and incompatible-definition guard coverage. All **450/450** per-row code-score comparisons pass absolute tolerance **1e-12**, with 410 exact; no pass-count proxy is used. Schema 3 and the existing raw-loss run remain unchanged. The next baseline publication needs reviewed migration and token approval. Sparse parity stays blocked; see [the audit](iteration-4/q9.md#approved-offline-reporting-correction-and-numeric-parity).

## L. Governed learning loop

Capture and feedback exist. This theme adds the rest of the specification's loop (§6). Each turn produces two kinds of pull request, in this order, and a person merging one is the approval:

1. **Analysis** groups episodes and feedback into clusters and says how strong each signal is.
2. **Cases first.** Clusters where reviewers agree become new eval cases, in a pull request. Merging it moves the baseline, which is measured again and published.
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
| L8 | **Stable evidence-pattern clustering** | L3's frozen live pilot turns 30 labels into 21 clusters; equivalent condition names split patterns and taxonomy mistakes misroute cases. Validate consolidation and category distinctions without tuning on the opened held-out key. | | M | it4 |
| L9 | **Feedback becomes eval cases, as a pull request** | The first thing the loop should produce is a better measure, not a changed agent. | | M | it4 |
| L10 | **Release an approved change** | A merged proposal has to become the deployed agent version, and be easy to roll back. | Foundry agent versions | S | |
| L11 | **Check the change worked** | Without it nobody knows whether a merged change fixed its cluster, and the loop never closes. | | S | |

Notes:

- **L1:** [#15](https://github.com/marcgs/cs-ai-platform-sample/pull/15) merged the eager packaged skill with local/hosted evidence. The planned comparison with native `SkillsProvider` progressive loading is still unperformed; the provider exists in the validated SDK. Do not equate packaging completion with completion of that comparison.
- **L3:** routes each cluster to its owner: behavior to L5, knowledge to L7, tools or data to this backlog, and reproducing cases to the eval suite.
- **L3, measured:** the approved 50-episode pilot has 24/30 category agreement against the key, 27/30 member routes correct, no classified key-controls among 19, and best-cluster ranks 3/9/2/1/4. Assistant-audit category agreement is separately 3/8 supported classified misses, not human-expert accuracy. The user approved merging [#17](https://github.com/marcgs/cs-ai-platform-sample/pull/17), but Part A acceptance remains incomplete.
- **L8:** exact `(category, normalized condition)` grouping splits `prompt_injection_logbook` and `prompt_injection_in_logbook`. Per-pattern best-cluster recall is 25%-71.4%. No post-key alias merge, prompt tuning or second pilot was performed; future scope and a fresh evaluation cohort need approval.
- **L9:** L3's cluster report already carries candidate eval cases that "require expert review before promotion"; L9 is that promotion. A cluster becomes cases only on reviewer consensus; where reviewers disagree it goes to an expert, and a single review waits for more. The ground truth is the consensus verdict, never a model's. Each case links to its episodes and reviews. Opening the pull request stays with a person (AGENTS.md rule 5).
- **L4:** a proposal records its cluster, its diff and its replay. It replays on the cluster's cases and on the train and held-out splits (Q2), and is kept only if it improves the cluster without a held-out regression. Scores go to the pull request and to Foundry (Q9). The learner never edits evaluators, thresholds or cases, and never sees held-out transcripts.
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
- Continuous evaluation of production traffic (after Q9).
- Model comparison across providers, and the model router.
- Conversations (multi-turn) and managed agent memory.
- Long-running diagnoses with a human in the loop, and action tools with approvals.
- Multi-agent workflows.
- Voice for engineers at the machine.
- Edge and on-premises inference (Foundry Local).
- Environments, promotion and active CI/CD.
- A third agent framework.
