# Iteration 4: a trusted measure, fed by feedback

## Goal and scope

Original intended outcomes; the close-out decisions below narrow what ships:

1. **Every eval run is kept and visible in Foundry.** A run's records survive an interruption, and each run is published to the project's evaluation view, so baselines can be compared per agent and skill version where the agent lives. `csai eval` stays the gate.
2. **Feedback grows the eval suite.** Feedback with reviewer consensus becomes reviewed eval cases in a pull request, and the grown suite gets a new baseline, gated as in [ADR 0009](adr/0009-evaluation-system-design.md) and published to Foundry with judges only. Clustering was measured and recorded as a finding (see the close-out decisions below).

This is the first half of a turn of the learning loop (see the backlog's [L section](backlog.md#l-governed-learning-loop)): a better measure first. The second half, a learner proposing a change and the platform replaying it (L4, L5, L10, L11), is iteration 5, measured against this iteration's baseline. Q1 (tool selection) and Q7 (knowledge citation) are its candidate first targets, so they aren't fixed by hand here.

Four items from the [backlog](backlog.md):

| Item | Size | Explores |
|---|---|---|
| Q8 Durable in-progress eval capture | M | |
| Q9 Eval runs published in Foundry | M | Foundry evaluations, capability hosts, custom evaluators |
| L8 Stable evidence-pattern clustering | M | Foundry models for classification |
| L9 Feedback becomes eval cases, as a pull request | M | |

During acceptance, the user adopted Q11 (explicit infrastructure-only publication
retries, size S) as additional recovery scope and approved its offline
implementation. [ADR 0007](adr/0007-infrastructure-only-publication-retries.md)
records the exception to one cloud run per immutable measurement. This adds no
automatic retry or model-usage authorization.

### Close-out decisions — 3 November 2026

The user simplified the close-out. Where older text below conflicts, these decisions win.

1. **The gate is four outcome metrics** ([ADR 0009](adr/0009-evaluation-system-design.md)): `hit_at_1_lenient`, `decisive_evidence_recall` and `evidence_grounded` on minimum means from the new baseline, and `injection_resisted` as a hard check. Invalid reports (`schema_valid = 0`) score zero on applicable outcomes and are counted separately, not excluded as plumbing or made a separate hard check. Foundry publication carries the four judges only; the mirrors of local scores go (Q16). Q4 moves into this iteration.
2. **Feedback becomes eval cases without clustering.** A candidate needs reviewer consensus, a successful replay and no duplicate. The stable-cluster admission rule is removed: whether one case is correct doesn't depend on how its episode was grouped. A cluster key stays in a case's provenance when one exists, as information only.
3. **L8 is a measured finding, not a blocker.** The fresh classification failed its confirmed criteria (three of five pattern recalls below 0.8, fragmentation 2.4 against 1.5), but precision is 1.0 for every pattern and no cluster came from the over-strict reviewer. The clusters are pure but too fine. No retuning or rerun on this batch, whose key is open. The fix moves to L12, with the learner (L4, L5), on a fresh batch. The top-five cluster review is no longer needed for close-out.

**Direction update — 3 November 2026:** finish Q4 as the local reference and
fallback and L9 with labeled reviewer-cause/scenario-category provenance.
Stop Q16 judges-only publication pending research into Foundry-run evaluation
with the agent target, built-in judges and custom evaluators. Its branch stays
unmerged. The three-repeat baseline is postponed; do not prepare its approval
request. The first feedback-case data PR follows L9's implementation merge.
No model runs, publication or Azure writes are authorized.

**Final close-out scope:** the spike plan merged in
[#31](https://github.com/marcgs/cs-ai-platform-sample/pull/31).
The three-repeat baseline, **its publication and Q17** move to the spike's
follow-up, after its decision. No baseline approval request is being prepared.
Q16 is closed as superseded; [#29](https://github.com/marcgs/cs-ai-platform-sample/pull/29)
is closed and its branch remains unmerged. The existing publisher and evidence
remain; the earlier judges-only direction is not implemented on main.

### Final status — 3 November 2026

| Item | Close-out status |
|---|---|
| Q8 | Delivered in [#20](https://github.com/marcgs/cs-ai-platform-sample/pull/20); durable capture and offline rebuild validated ([evidence](iteration-4/q8.md)) |
| Q9 | Delivered in [#21](https://github.com/marcgs/cs-ai-platform-sample/pull/21) and [#26](https://github.com/marcgs/cs-ai-platform-sample/pull/26); one 50-row publication confirmed, numeric audit passed ([evidence](iteration-4/q9.md)) |
| Q11 | Delivered in [#26](https://github.com/marcgs/cs-ai-platform-sample/pull/26); approved infrastructure-only recovery completed, original receipts retained ([ADR 0007](adr/0007-infrastructure-only-publication-retries.md)) |
| Q4 | Done in merged [#28](https://github.com/marcgs/cs-ai-platform-sample/pull/28); local reference/fallback, provisional floors 0.70 / 0.65 / 0.85 and injection hard check |
| L9 | Replay in [#23](https://github.com/marcgs/cs-ai-platform-sample/pull/23), proposals in [#22](https://github.com/marcgs/cs-ai-platform-sample/pull/22), consensus admission completed in merged [#30](https://github.com/marcgs/cs-ai-platform-sample/pull/30) |
| First feedback cases | [#32](https://github.com/marcgs/cs-ai-platform-sample/pull/32) open for human review/merge: 3 admitted, 8 duplicates, 12 rejected, 27 expert referrals from all 50 fresh-cohort episodes |
| L8 | Closed as a finding, continued under L12; fresh acceptance failed recall/fragmentation, no retuning or rerun ([evidence](iteration-4/l8.md#approved-fresh-classification-and-failed-acceptance--3-november-2026)) |
| Q16 | Closed, superseded by the spike; #29 closed/unmerged |
| Three-repeat baseline and publication | Deferred to the #31 spike decision and follow-up; provisional floors remain |
| Q17 score trend | Deferred to the same spike follow-up; not implemented |

After the final #28 text-matching fix, the retained 50-case measurement re-scores
at **0.78 / 0.75 / 0.92**, unchanged, with all four injection checks passing.
Four invalid reports count at zero, no plumbing failures are excluded.
Means and intervals are in the [eval guide](../evals/rca/README.md).
The read-only source journal remains unchanged; no threshold question remains.
The combined implementation and feedback-case proposal each pass Ruff,
strict Pyright and **670 offline tests**.

Remaining steps, in order:

1. A person reviews and merges the feedback-case PR (#32).
2. A person reviews and merges the separate close-out documentation PR.
3. Only then proceed to the spike's run 1, with its separate model/write approvals.

No new model runs, publication, Azure writes or deployments were performed
during this close-out. The baseline, its publication and Q17 are not prerequisites
for it. See the [closing summary](iteration-4/close-out.md).

**Historical plan and execution follow.** Dated estimates, pending checks and
the original acceptance sequence below describe their time, not new authorization
or the final close-out scope above.

### Acceptance execution update — 2 November 2026

Q9 publication no longer blocks local acceptance. L8's fresh classification and
human acceptance, the feedback-case proposal/PR, and the grown-suite local
baseline may proceed in their dependency order while publication is diagnosed.
Each model-consuming measurement still needs its own cost approval, and token
work remains serialized at concurrency 1. Keep durable local evidence and
publish saved measurements later; **published in Foundry remains open**.
The baseline still follows the first feedback-case PR's human review and merge.

| Local step | Expected model usage before approval |
|---|---|
| L8 fresh classification | Frozen preflight: 30 uncached requests, about 141,046 input + at most 36,000 output tokens; retry/hidden overhead is additional |
| Feedback-case proposal | Zero model tokens for deterministic `csai cases propose`; commits, push and PR opening need separate permission |
| Three-repeat local baseline | About 2.15M agent tokens for the existing 50 cases, plus about 43k per added feedback case; no cloud judges until later publication |

The logged project-identity CreateContainer AuthorizationFailure persisted
after an approved account-only rule. A separately approved AzureServices bypass
then enabled publication without an Owner grant or other access change.
Actual StorageBlobLogs ingestion works; ARM destination-type readback still
differs from the declaration.

The approved retry completed in **19m37.727s with 50 output rows and zero
errored**, despite the publisher's 900-second observation timeout. The
200 judge invocations report 763,268 tokens. The user confirmed the rows,
code/judge scores and version labels in the portal.
Of 450 common scores, 410 match exactly and 40 calibration values differ by
less than 10^-15. All service-retained inline inputs match exactly; the internal
stage producing the returned differences is unknown. The user approved an
offline per-row audit at absolute tolerance 1e-12 and a separately named
`calibration_score = 1 - Brier`. The audit passes **450/450** comparisons and
the new grader is implemented offline in [#26](https://github.com/marcgs/cs-ai-platform-sample/pull/26).
Local gates and the existing run stay unchanged. Schema-4 migration and live
verification belong to the later baseline publication, which still needs approval.
The current 50-failed display includes inverted calibration pass flags and is
not a replacement for the local gate. No republication is approved.
See [Q9 evidence](iteration-4/q9.md#completed-validation-and-acceptance-findings--2-november-2026)
and [ADR 0008](adr/0008-evaluation-storage-network-exception.md).
Any matching network/RBAC fix and another request need separate approval.
If a setup aligned with template 15a in both
respects still fails, stop and prepare the support-case evidence; do not add
publisher retry, receipt or lock machinery.

L8's fresh 300-episode population and 50-episode cohort are generated, the
preflight is frozen, and the approved offline 10+10 blind pack is prepared.
The key remains closed. Blind person judgments,
classification token approval, the measurement and human acceptance remain
outstanding; no classification has run.

Out of scope: tool selection (Q1), knowledge citation (Q7), cost and latency (Q5), asking for missing information (Q6), proposals, the learner, release and the post-release check (L4, L5, L10, L11), scheduling (L6), knowledge from diagnoses (L7), replayable data beyond the check in L9 (K4), Fabric, and any change to the agent's behavior or `RcaReport`. Findings go to the backlog.

This is the plan, not authorization to implement. Like iterations 2 and 3: one worktree and **one pull request per item**, developed in parallel, with live evals, model traffic and deployments serialized. This plan approves no deployment, infrastructure change, role assignment or model traffic.

### Closing iteration 3

Done in the pull request that adds this plan, in the backlog only:

- L1 and L3 are marked done it3, with their open gaps kept in the notes: the `SkillsProvider` comparison (L1) and Part A acceptance (L3, carried as L8).
- Q1 loses its it3 target; it wasn't attempted and waits for the learner.
- The capability-host finding from the Q9 spike is recorded in Q9's note.

## Invariants for every workstream

1. **Existing cases stay comparable.** The original 18 and the Q3 challenge cases, their seed records and their tool results stay byte-identical; the golden tests from iteration 3 keep passing. Feedback cases are additive, in their own cohort.
2. **No gate is weakened to get a pass,** and `csai eval` remains the gate. Foundry results are reporting until they are shown to agree with `csai eval` (Q9). Write success criteria down before measuring, report every run, and don't rerun until a run passes.
3. **The feedback cohort is reported, not gated,** until a measured baseline exists and Q4 decides its gates.
4. **Ground truth never comes from a model.** A feedback case's expected answer is the reviewers' consensus verdict. A model may only draft fields a person reviews in the pull request.
5. **No tuning on an opened key.** L3's pilot and its answer key are opened. L8 is measured on a fresh population and cohort whose key nobody reads before the criteria are fixed.
6. **Synthetic is labeled synthetic,** in the data, in published Foundry runs and in pull request text. Data stays fictional (AGENTS.md rule 1).
7. **Evidence is sanitized.** Foundry report URLs, run IDs and resource names don't go into tracked files.

## Shared interfaces

- **Q8 owns the run record:** the files a run writes as it goes (case-run results, episodes, transcripts) and the summary derived from them. Q9 publishes from that record, never from in-memory state.
- **Q9 owns publishing:** what a published row contains, how runs are named, and the run metadata (revision, agent version, skill version, dataset version, split, cohort).
- **L8 owns cluster identity and the report contract:** a stable cluster key that L9 can cite and that survives a rerun of the analysis on the same input. Each candidate case in the report also carries its episode's `ReviewSummary` (independent reviewers, agreement, root-cause support) and the IDs of the reviews behind it. Today the report keeps only review notes, so L9 couldn't check consensus or cite reviews from it.
- **L9 owns replay-compatible feedback data** (its Part A): synthetic transcripts whose tool results are what today's tools return.
- **L9 owns the feedback case format:** the case file, its `cohort: feedback`, and the provenance fields. It reuses Q3's `truth` field and Q2's split rule.

**Merge order:** Q8 → Q9 → L9 Part A → L8 → L9 Part B, then the baseline. L9 Part A must merge before L8 generates its fresh cohort, or that cohort can't replay. Q8, L9 Part A and L8's offline work can start at once; Q9's infrastructure step can be prepared in parallel.

## Q8: durable in-progress eval capture

**Outcome:** an interrupted run keeps everything it completed, and says it's incomplete.

- **Write as you go.** Append each case-run's result, episode and transcript to the results directory as soon as it completes, flushed to disk. The summary, the HTML page and the gate are derived from those records, not held in memory until the end.
- **Interruptions are recorded, not repaired.** On cancellation or a fatal error, write a summary marked `incomplete`, with the case-runs that never started listed as such. Failed attempts stay in the record. Never reconstruct a missing episode from scores.
- **No quality-seeking resume.** If a resume is added, it may only run case-runs that never started, with the same configuration. It never repeats a completed or failed one.
- **Rebuild from disk:** `csai eval report <results-dir>` regenerates the summary and page from the records.

**Acceptance:** offline tests interrupt a scripted suite at several points (between case-runs, during a tool call, during export) and check that completed records survive, the summary says `incomplete`, and the gate fails. The public CLI path is the one under test, not a private driver. The retained iteration 3 cancellation (in Q8's backlog note) is the scenario to reproduce.

## Q9: eval runs published in Foundry

**Outcome:** every `csai eval` run can be published to the project's evaluation view, with our metrics and Foundry's judges side by side.

**Part A: the project capability host (infrastructure; needs approval).**

1. Add a project-level capability host of kind `Agents`, with no connections, to `infra/modules/foundry.bicep`, following foundry-samples template 15a (`add-project-capability-host.bicep`). Check current docs first: capability hosts are a preview area, and capability settings are replacing them in places.
2. Run `az bicep build` and `az deployment sub what-if`, and call out any delete or replace.
3. The user applies it (`azd provision`).
4. Check: the capability host reaches `Succeeded`, and the hosted agent still answers (one `csai diagnose --target hosted`).
5. If a published run still fails, read the error before changing anything. The likely next step is a storage connection; it needs its own approval. The fallback is a second Foundry project without network injection, used only for evals: record it as a decision with an ADR.

**Part B: publishing.**

- **Publish from the record:** `csai eval publish <results-dir>`, and `--publish` on a run, which calls the same code after the run. Publishing can't change the gate's outcome.
- **Rows** carry the case ID, split, category, cohort, query, response, tool calls, ground truth, and our per-case scores.
- **Our metrics in Foundry.** Show the code-based scores as Foundry metrics with a code-based custom evaluator (preview) whose `grade()` returns the precomputed score from the row. Calibration is published separately as `calibration_score = 1 - Brier` to match higher-is-better semantics, without changing the local loss or gate. Porting the evaluators themselves into `grade()` is a later choice; the sandbox has no network access and limits on code size.
- **Foundry's judges** run next to them: the existing three (task adherence, intent resolution, coherence) plus tool call accuracy, since rows carry tool calls. They are reported only (Q4 decides any gating).
- **Naming and metadata.** One evaluation per suite, one run per measurement, labeled with revision, agent version, skill version and dataset version, so the portal's run comparison compares baselines.
- **Docs.** Update AGENTS.md, ADR 0004's consequence and the platform tour once a run completes. Don't edit the iteration 1 plan; it's history.

**Acceptance:** offline tests for the row mapping and run metadata, with the Foundry client faked at the boundary. Then one published run whose per-row code scores agree with `csai eval` at absolute difference <= 1e-12 (no relative tolerance), and a short comparison of judge scores against our metrics (informational). The user explicitly approved this numeric tolerance after inspecting the 40 sub-1e-15 calibration differences; exact equality was not achieved. For future `calibration_score`, compare against 1 - local Brier. If the retained iteration 3 results are still on disk and Q8 can read them, publish those, so this costs judge tokens only. Otherwise publish a small run (the original 18, one repeat).

## L8: stable evidence-pattern clustering

**Outcome:** a cluster means one recurring pattern, so promoting it to cases (L9) and later routing it to a learner is safe.

- **Fixed condition vocabulary.** The classifier picks the condition from a closed list taken from the catalog and taxonomy, using structured output, instead of free text. Clusters group on canonical keys, so `prompt_injection_logbook` and `prompt_injection_in_logbook` can't split.
- **Sharper category definitions,** with examples from the train split only. Where two categories keep being confused, merge or define them; record the change.
- **Stable cluster keys** derived from the canonical category and condition, not from order or labels' wording.
- **Review evidence in the report.** Candidate cases carry their `ReviewSummary` and source review IDs (see Shared interfaces). Existing pilot outputs stay frozen; only new reports use the extended contract.
- **Fresh measurement.** After L9 Part A merges, generate a new population and cohort (new seeds) with L2's generator and the same selection rule as L3's pilot. Nobody reads its key before the criteria below are confirmed.
- **Criteria, proposed; confirm before measuring:** per planted pattern, best-cluster recall ≥ 0.8; at most 1.5 clusters per planted pattern; no cluster formed by the over-strict reviewer; category agreement and route accuracy reported against L3's pilot (24/30 and 27/30).
- **A person reviews** the top clusters and a sample of labels in the report. L3 had no human acceptance; this is it, recorded in `docs/iteration-4/l8.md`.

**Acceptance:** offline tests for canonicalization, stable keys and grouping. The fresh measurement is model traffic: estimate tokens first (about 30–50 classification requests, as in L3's pilot) and run only with approval.

**Outcome (3 November 2026):** measured and failed; recorded as a finding and continued as L12. See the close-out decisions above and [the L8 record](iteration-4/l8.md).

## L9: feedback becomes eval cases, as a pull request

**Outcome:** a command turns a cluster report into a branch with reviewed eval cases, ready for a person to open as a pull request.

**Part A: replay-compatible feedback data (prerequisite).** L2's transcripts don't match today's tools. `make_transcript` records the raw machine record as the `get_machine_context` result, while the tool returns `MachineContext` (with `reference_time` and `signals`). Some contexts also inject events and logbook entries that exist in no seed (`EV-SYN-UNMAPPED`, `LB-SYN-UPDATE`). As it stands, every synthetic candidate would fail the replay check.

- Build every synthetic tool result with the same `DiagnosticsTools` functions the MCP server uses, over the seed.
- A context that needs data the seed lacks either adds it as additive seed data under new IDs (existing records and tool results stay byte-identical, checked by the golden tests) or stays non-replayable on purpose, labeled as such, so the replay check rejects it.
- Regenerate L2's fixtures with the generator. L3's pilot outputs stay frozen.
- **Acceptance:** a test replays every tool call of a generated cohort against `DiagnosticsTools` and gets identical results, except the cases labeled non-replayable. The replay check still rejects a deliberately changed result. Each planted pattern has replayable episodes.

**Part B: promotion.**

- **Input:** the fresh cohort's report, whose candidate eval cases (L3 marks them "require expert review before promotion") carry their review evidence. Clusters are not an admission criterion (close-out decision 2).
- **Admission rules,** each with its reason in the output:
  - **Consensus:** at least two independent reviewers agree on the verdict and the actual root cause, read from the candidate's `ReviewSummary` (L3's reliability-weighted consensus). Disagreement goes to an expert list; a single review waits.
  - **Replayable:** replaying the episode's captured tool calls against today's tools gives the same results, compared by the tool fingerprints from iteration 3. A mismatch rejects the case and is listed under K4.
  - **Not a duplicate** of an existing case (same machine, failure mode and category); it links to the existing case instead.
- **Case format:** the episode's input; `expected` from the consensus verdict; Q3's `truth` with `category` and only the fields the reviews support (reviews don't give decisive refs, so those metrics don't apply and the report says so); `cohort: feedback`; `split` from Q2's machine rule; provenance with the cluster key, episode and review IDs from the report and `source: synthetic`.
- **Where cases live:** a reviewed file next to the generated `cases.jsonl` (for example `feedback_cases.jsonl`), not regenerated from the seed, loaded by the suite as its own cohort.
- **Output of the command,** for example `csai cases propose <report>`: the new case file on a new local branch, plus a pull request body: the cluster, consensus statistics, admitted and rejected candidates with reasons, links to episodes and reviews. It doesn't push or open the pull request (AGENTS.md rule 5).

**Acceptance:** offline tests on L2's answer key: the command admits cases only from planted patterns and none from the over-strict reviewer or wrong reviews, rejects a case whose tool results changed or that is labeled non-replayable, and gives identical output on a rerun. Then one real pull request with the first batch, from L8's fresh cohort, reviewed and merged by a person.

## The new baseline

**Deferred at close-out:** baseline measurement and publication wait for the
[#31 spike](spike-foundry-native-eval.md) decision. The design and estimate below
are historical planning, not an approval request or a commitment to the old
publication path.

After L9's first pull request merges:

- Run the full suite (original 18, Q3 challenge cases, the feedback cohort) with `--repeats 3 --concurrency 1` on the local target, with Q8's capture. Retain the measurement and publish it after Q9 works.
- Record it in `docs/iteration-4/baseline.md`: revision, model deployment and exact resolved model version, date, per cohort and split, with confidence intervals. Iteration 5's proposals are judged against this run.
- Cost: the measured planning reference below is about 2.15M agent tokens plus 2.29M judge tokens for the existing 50 cases, before adding merged feedback cases. Measurement and publication each need approval.
- No data release is expected, since feedback cases use seed machines. If L9 changes any tool result, stop: that breaks invariant 1.

### Preparation and estimate — 3 November 2026

Baseline planning only. No baseline or publication is authorized. The separate
L8 classification approval has now been consumed by one retained run that
failed the confirmed acceptance criteria; no further classification is approved.
The first feedback-case PR comes from consensus feedback, not accepted
clustering (close-out decision 2), and must be reviewed and merged by a person
before the final iteration-4 baseline.
Do not treat a 50-case pre-feedback measurement as that final baseline.

The current suite has **18 original and 32 challenge cases**, no merged
feedback cases, and 36 train / 14 test cases. With three repeats this is
**150 case-runs: 54 original, 96 challenge; 108 train, 42 test**.
Let **F** be the number of cases admitted by the later, human-merged feedback
PR. Only then add its feedback cohort: **3F case-runs**, with the existing
machine-based split rule. The gate is ADR 0009's: each gated metric over every
case it applies to, with injection as a hard check.

The saved single-repeat validation used 715,382 agent tokens and took
15m17.764s from recorded start to the last episode completion. Its separate
50-row publication used 763,268 judge tokens across 200 invocations and took
19m37.727s. These are measurements from the saved records, not new runs.

| Work | Existing 50 cases, three repeats | Additional budget per merged feedback case |
|---|---:|---:|
| Local agent tokens | 2,146,146 (about 2.15M) | About 42,923 |
| Four Foundry judges | 2,289,804 (about 2.29M); 600 invocations | About 45,796; 12 invocations |
| Combined tokens | 4,435,950 (about 4.44M) | About 88,719 |
| Local agent duration | About 46 minutes by linear scaling; allow 45–60 minutes | About 55 seconds before headroom |
| Publication duration | About 59 minutes by linear scaling; allow 60–90 minutes | About 71 seconds before headroom |

With no feedback increment, allow roughly **1h45–2h30 total**, with local
measurement and publication serialized. Feedback complexity, changed model
versions, retries, rate limiting, service startup and hidden evaluator work can
change these estimates. They are not spending ceilings. Recalculate for the
actual merged feedback count and obtain separate run and publication approvals.

Keep the local baseline at **concurrency 1**, one token-heavy job at a time,
within **50 requests/minute and 50,000 tokens/minute**. Token-only lower bounds
for the base estimate are about 43 minutes for the agent and 46 minutes for
judges; request-count limits and latency still apply. Honor service retry
delays, retain errors and actual usage, and do not rerun cases to seek a pass.
The existing publication API has no client judge-concurrency setting; Foundry
schedules those judges. Do not promise that `--concurrency 1` controls them.
That limitation must be explicit in the later publication approval.
The current publisher's 15-minute observation timeout is shorter than this
estimate: observe the same registered run read-only after timeout, never
resubmit it merely because local polling ended.

Before any later run, freeze the selected revision, cases, versions and
configuration. Use Q8 durable capture, three repeats, concurrency one and no
quality-seeking retries. Publication is judges only (Q16), a new evaluation
definition; the existing populated evaluation and run stay as evidence.
Publishing one repeat instead of three cuts judge tokens to about a third; the
approval request should offer both.

`baseline.md` remains absent until a baseline is measured; this plan is not
acceptance evidence. Its model provenance must include:

- The agent deployment name **and exact served model name/version**, with
  read-only deployment snapshots immediately before and after the run and
  response-reported model identifiers where available. A deployment alias
  alone is insufficient because its upgrade policy can advance the version.
- The judge deployment and its independently observed exact model version at
  publication, including the service's reported usage model identifiers. The
  earlier judge reported **gpt-5.4-mini-2026-03-17**; that does not establish
  the future agent or judge version.
- Timestamped version changes or mixed versions rather than one assumed
  version for the whole measurement. If the exact version cannot be verified,
  leave that provenance gate outstanding. Record all revisions, date, agent,
  skill and dataset versions, per-cohort/split scores and confidence intervals.

## Measurement and the shared environment

- **Offline first.** All items develop against offline tests, seed data and L2's generator.
- **Each of these needs its own approval:**
  - Q9 Part A: `azd provision` with the project capability host, and any storage connection after it.
  - Publishing to the Foundry project (it writes evaluations and evaluator versions there).
  - L8's classification run on the fresh cohort.
  - The baseline run.
- **Serialize token-heavy work.** Concurrency 1, one suite or classification at a time, within both the 50 requests/minute and 50k tokens/minute model limits. Foundry judge scheduling is service-managed, not controlled by the local concurrency flag.

## Gates, PRs and completion

Every PR passes `uv run ruff check && uv run ruff format --check`, `uv run pyright` and `uv run pytest`. After changes to capture, eval data or the eval harness, also run `uv run csai eval rca --target local --concurrency 1`. A skipped or failing live gate is recorded as outstanding, not passed. No CI workflow.

Each PR includes the problem, the change, tests, sanitized evidence, limitations and any deployment it needs. Commit only on the item's branch, check the staged diff before every commit, and ask before pushing or opening the implementation PRs.

Proposed branches: `it4/q8-durable-capture`, `it4/q9-foundry-evals`, `it4/l8-stable-clusters`, `it4/l9a-replayable-feedback`, `it4/l9-feedback-cases`. L9 is one backlog item with two PRs.

While work is pending, the four backlog rows carry target `it4`. When an item meets its acceptance criteria, mark it done with its PR link and record its evidence in `docs/iteration-4/<item>.md`. New findings get the next free ID in their theme.

## Implementation and validation status

Clean-main preparation at `7b56c46` passed 590 tests after the local S6 SDK
compatibility restoration; the initial two failures remain recorded. The
reviewed drift-preserving provision retained subnet NSGs, Cosmos DB failover,
connection sharing, account routing and model policies. The project host is
`Succeeded`, one hosted diagnosis verified its exact stored episode, and
episodes listing works. Explicit seeding confirmed 40 historical cases;
automatic provision-hook dispatch remains unverified (S14).

The post-review local validation retained all 50 case-runs, episodes and
transcripts, passed the unchanged original-18 gate and preserved its journal
through offline rebuilding. Dedicated private evaluation storage, diagnostics
and the approved network-only exception enabled one completed, portal-confirmed
publication. The earlier rejected requests, startup failure and original
receipts remain retained. No Owner grant was needed.

The recovery implementation merged in [#26](https://github.com/marcgs/cs-ai-platform-sample/pull/26).
With the calibration and retry-review corrections it passes **616 tests, 32 existing warnings**, Ruff
(149 formatted files), strict Pyright and Bicep build. Calibration reporting
is fixed offline and the numeric audit passes 450/450 at absolute tolerance
1e-12 in [#26](https://github.com/marcgs/cs-ai-platform-sample/pull/26).
Incompatible schema-3 definitions stop publication pending reviewed migration;
the completed run is not changed. No Azure writes,
further model runs or republication are approved. The fresh L8 pilot completed
30 valid labels with zero errors, but failed three per-pattern recall checks
and the fragmentation limit. All 20 blind judgments have person acceptance;
L8 is recorded as a finding (close-out decision 3). The first case PR is now
[#32](https://github.com/marcgs/cs-ai-platform-sample/pull/32), awaiting human merge.
The three-repeat baseline, its publication and Q17 moved to the spike follow-up.
See [the sanitized Q9 evidence](iteration-4/q9.md).

The reviewed implementation is committed in five stacked item pull requests.
The original dirty checkout and the uncommitted integration snapshot were
preserved. All domain data and measurements are synthetic and fictional.

| Item | Implementation PR | Initial stacked offline tests | Final disposition |
|---|---|---|---|
| Q8 | [#20](https://github.com/marcgs/cs-ai-platform-sample/pull/20) | 426 | Complete; final feedback-suite baseline deferred |
| Q9 | [#21](https://github.com/marcgs/cs-ai-platform-sample/pull/21), recovery [#26](https://github.com/marcgs/cs-ai-platform-sample/pull/26) | 454 | Complete with retained limitations; further publication work follows the spike decision |
| Q11 | Recovery [#26](https://github.com/marcgs/cs-ai-platform-sample/pull/26) | 77 focused / 608 full before calibration fix | Approved live retry completed; recovery PR merged |
| L9 Part A | [#23](https://github.com/marcgs/cs-ai-platform-sample/pull/23) | 456 | No additional live measurement for replay implementation |
| L8 | [#24](https://github.com/marcgs/cs-ai-platform-sample/pull/24) | 478 | Fresh pilot failed recall/fragmentation criteria; recorded as a finding, continued as L12 |
| L9 Part B | [#22](https://github.com/marcgs/cs-ai-platform-sample/pull/22), admission [#30](https://github.com/marcgs/cs-ai-platform-sample/pull/30) | 497 | Implementation complete; case PR #32 awaits human review/merge |

Each standalone stack passed Ruff lint and formatting, strict Pyright, its
full offline test suite, staged safety checks and normal pre-commit hooks.
Bicep build passed. Before GitHub review, all 43 modified or new non-Markdown
source, test, data and configuration files in the initial final stack matched
the reviewed integration snapshot exactly. Agent behavior, original cases, thresholds and frozen
iteration-3 evidence remain unchanged.

Parallel reviews fixed journal-integrity and frozen-gate checks, gate-safe
publishing errors, truncated-evidence rejection, blank root-cause claims,
and feedback provenance validation. A freshly recreated environment initially
lacked the packaging test's `hatchling` backend; restoring it locally made
all 497 tests pass without a dependency-manifest change. S7 records the
reproducibility follow-up.

### Approved live local validation

The user approved one live local eval: 50 synthetic cases, one repeat,
concurrency one, no publication. An initial invocation lacked the worktree's
azd configuration and stopped before any case started (exit 2). Its incomplete
record was retained. The public offline report rebuild kept zero completed
case-runs and failed the gate (exit 1).

The configured invocation used the root checkout's azd values privately in
the child process. It completed with exit 0: 50 unique case-runs, 50 successful
episodes and 50 transcripts, with no failed attempts, interrupted or
never-started case-runs, or truncated episodes. Provenance records synthetic
data and the uncommitted harness actually measured. The later commits do not
relabel that run as a clean-commit measurement. No case was rerun to seek a pass.

| Metric | Original 18 (gated) | Challenge 32 (reported) | All 50 |
|---|---|---|---|
| Schema valid | 1.000 | 0.875 | 0.920 |
| Hit at 1 | 1.000 | 0.656 | 0.780 |
| Hit at 3 | 1.000 | 0.875 | 0.920 |
| Evidence grounded | 1.000 | 1.000 | 1.000 |
| Tool coverage | 0.900 | 0.906 | 0.904 |
| Used knowledge | 0.889 | 0.719 | 0.780 |

Original-18 thresholds are unchanged. Tool coverage sits exactly at its
0.90 threshold (95% bootstrap interval 0.856-0.944); a single-repeat pass does
not establish reliability or replace previous failed measurements. The
knowledge-use interval is 0.722-1.000. Saturation and threshold-gap warnings
remain in the summary.

The completed run's public offline report rebuild also exited 0 and produced
the identical complete summary. Results and all durable journal files stayed
byte-identical. Raw records and deployment previews remain private, outside
tracked files.

### Remaining acceptance

A fresh subscription what-if showed one capability-host create,
44 modifications and five unsupported resources, with no resource deletions
or replacements. Removing only the new host from the same compiled template
produced identical modification resource sets and complete modification
payloads for all 44 resources. They predate Q9, but are not automatically safe
to apply. Both previews have five unsupported resources; their payloads
differ. No infrastructure was applied or accepted for provisioning.

Q10, Q14 and Q15 close by removing the mirrors (ADR 0009, Q16); their evidence
stays in the Q9 record.

The user confirmed L8's proposed criteria before any fresh population
generation or key inspection: best-cluster recall at least 0.8 per planted
pattern, at most 1.5 clusters per planted pattern, no cluster formed by the
over-strict reviewer, and category agreement and route accuracy reported
against the frozen pilot. This does not approve classification traffic.

Implementation PR review and merge do not complete the remaining live or
human acceptance. The remaining close-out follows the decisions of 3 November
(top of this plan). This single-repeat validation is not the new iteration
baseline.

### GitHub review fixes

The five PRs form a native GitHub stack in the plan's dependency order.
Their first Copilot reviews identified eleven code issues; L8 had no open
code findings and retained its fresh-measurement and person-acceptance gap.

The fixes stop persistence failures from becoming model retries, finalize
only after required exports, protect private journal permissions, preserve
recoverable partial-write tails and sync new directory entries. Publishing
preserves capture-completeness flags, rejects incomplete tool-call judging,
labels calibration loss as lower-is-better and reuses saved measurements'
remote runs across publication retries. Copied scenarios now reference their
own evidence. Proposal writes reject conflicting case IDs and symlinked
destinations or parents before any branch or file mutation.

After restacking the fixes, the full combined suite passed **524 offline
tests**, Ruff lint and formatting, strict Pyright and diff checks. The
original cases, thresholds, agent behavior and frozen pilot remain unchanged.
The approved live run above predates these review fixes. A fresh local eval
after the capture/data fixes was skipped because further model traffic was
not authorized; it remains outstanding. Fresh Copilot reviews are required
before the implementation stack merges.

The second Copilot round identified eight further inline issues and an
initialization-order gap. Episode exports now use private, durable creation;
report destinations are reserved before model calls and remain visibly
incomplete until durable completion. A completion certificate distinguishes
successful finalization from failed completion fsync, and the journal exists
before its manifest is published. Suite-scoped publication locking prevents
different measurements from creating duplicate evaluations.

Replay and promotion reject unfinished captures. Seed-only tests explicitly
exclude feedback manifests, while additive-loading tests retain their gate
assertions. Results and rebuilt reports carry separate original, challenge
and feedback cohort metrics and intervals. Legacy cohort recovery uses frozen
metadata without rewriting evidence; its fixtures explicitly predate the
completion-certificate protocol. Production certificate checks are unchanged.

After the second restack, **561 offline tests**, Ruff lint/format, strict
Pyright and diff checks pass. No further model traffic, publication or
deployment ran. The live and human acceptance gaps above remain outstanding;
another current-head Copilot review precedes implementation merge.

The third review surfaced three inline findings and five additional Q8
findings in the review body. Results opens now reject symlinks atomically;
rebuilds refuse active writers, preventing stale exports from replacing
finalized measurements. Requested episode outputs are reserved before target
calls. Manifests accept the effective retry/backoff settings, and an offline
concurrent interruption regression verifies sibling cancellation and retained
attempt identities.

Publication uses shared per-user measurement coordination and migrates legacy
receipts. Confirmed creation rejections clear pending receipts durably;
ambiguous outcomes remain blocked. The remaining knowledge-gate test now
explicitly excludes feedback without changing its threshold assertions.

After the third restack, **575 offline tests**, Ruff lint/format, strict
Pyright and diff checks pass. Original data, gates and agent behavior remain
unchanged. No new model traffic, publication or deployment ran; another
current-head review is required before merge, and live/human acceptance
remains outstanding.

The copied-legacy-archive gap is now enforced rather than left as a warning.
New captures carry certificate-verified shared-coordination provenance.
Legacy captures without matching receipt evidence fail before authentication
or SDK calls; original evidence can be imported with `--legacy-receipts`.
Missing origins, including never-published legacy archives, require
reconciliation rather than treating an empty remote listing as proof.
After restacking this fix, **584 offline tests**, Ruff lint/format, strict
Pyright and diff checks pass. No additional cloud or model traffic ran.

The fourth review's three inline findings are addressed. Finalization owns
writing and syncing the reserved episode export before completion, including
direct writer callers; the CLI no longer writes it separately. An absent
default legacy directory stays untouched, while existing or explicit origins
remain locked and fail closed. Blank reviewer causes no longer contradict
consensus and do not count as cause support; actual disagreement still
requires expert review.

The combined fourth-round stack passes **590 offline tests**, Ruff
lint/format, strict Pyright and diff checks. Fresh current-head Copilot reviews
are required before merge. Live and human acceptance remain outstanding.
