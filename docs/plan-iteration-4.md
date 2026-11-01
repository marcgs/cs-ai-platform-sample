# Iteration 4: a trusted measure, fed by feedback

## Goal and scope

Two outcomes:

1. **Every eval run is kept and visible in Foundry.** A run's records survive an interruption, and each run is published to the project's evaluation view, so baselines can be compared per agent and skill version where the agent lives. `csai eval` stays the gate.
2. **Feedback grows the eval suite.** Clusters from episode analysis are stable enough to act on, clusters with reviewer consensus become reviewed eval cases in a pull request, and the grown suite gets a new baseline, published to Foundry.

This is the first half of a turn of the learning loop (see the backlog's [L section](backlog.md#l-governed-learning-loop)): a better measure first. The second half, a learner proposing a change and the platform replaying it (L4, L5, L10, L11), is iteration 5, measured against this iteration's baseline. Q1 (tool selection) and Q7 (knowledge citation) are its candidate first targets, so they aren't fixed by hand here.

Four items from the [backlog](backlog.md):

| Item | Size | Explores |
|---|---|---|
| Q8 Durable in-progress eval capture | M | |
| Q9 Eval runs published in Foundry | M | Foundry evaluations, capability hosts, custom evaluators |
| L8 Stable evidence-pattern clustering | M | Foundry models for classification |
| L9 Feedback becomes eval cases, as a pull request | M | |

Out of scope: tool selection (Q1), knowledge citation (Q7), changes to which metrics gate (Q4), cost and latency (Q5), asking for missing information (Q6), proposals, the learner, release and the post-release check (L4, L5, L10, L11), scheduling (L6), knowledge from diagnoses (L7), replayable data beyond the check in L9 (K4), Fabric, and any change to the agent's behavior or `RcaReport`. Findings go to the backlog.

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
- **Our metrics in Foundry.** Show the code-based scores as Foundry metrics with a code-based custom evaluator (preview) whose `grade()` returns the precomputed score from the row. Porting the evaluators themselves into `grade()` is a later choice; the sandbox has no network access and limits on code size.
- **Foundry's judges** run next to them: the existing three (task adherence, intent resolution, coherence) plus tool call accuracy, since rows carry tool calls. They are reported only (Q4 decides any gating).
- **Naming and metadata.** One evaluation per suite, one run per measurement, labeled with revision, agent version, skill version and dataset version, so the portal's run comparison compares baselines.
- **Docs.** Update AGENTS.md, ADR 0004's consequence and the platform tour once a run completes. Don't edit the iteration 1 plan; it's history.

**Acceptance:** offline tests for the row mapping and run metadata, with the Foundry client faked at the boundary. Then one published run whose mirrored metrics equal `csai eval`'s exactly, and a short comparison of judge scores against our metrics (informational). If the retained iteration 3 results are still on disk and Q8 can read them, publish those, so this costs judge tokens only. Otherwise publish a small run (the original 18, one repeat).

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

## L9: feedback becomes eval cases, as a pull request

**Outcome:** a command turns a cluster report into a branch with reviewed eval cases, ready for a person to open as a pull request.

**Part A: replay-compatible feedback data (prerequisite).** L2's transcripts don't match today's tools. `make_transcript` records the raw machine record as the `get_machine_context` result, while the tool returns `MachineContext` (with `reference_time` and `signals`). Some contexts also inject events and logbook entries that exist in no seed (`EV-SYN-UNMAPPED`, `LB-SYN-UPDATE`). As it stands, every synthetic candidate would fail the replay check.

- Build every synthetic tool result with the same `DiagnosticsTools` functions the MCP server uses, over the seed.
- A context that needs data the seed lacks either adds it as additive seed data under new IDs (existing records and tool results stay byte-identical, checked by the golden tests) or stays non-replayable on purpose, labeled as such, so the replay check rejects it.
- Regenerate L2's fixtures with the generator. L3's pilot outputs stay frozen.
- **Acceptance:** a test replays every tool call of a generated cohort against `DiagnosticsTools` and gets identical results, except the cases labeled non-replayable. The replay check still rejects a deliberately changed result. Each planted pattern has replayable episodes.

**Part B: promotion.**

- **Input:** L8's cluster report, whose clusters already carry candidate eval cases (L3 marks them "require expert review before promotion"), with their review evidence.
- **Admission rules,** each with its reason in the output:
  - **Consensus:** at least two independent reviewers agree on the verdict and the actual root cause, read from the candidate's `ReviewSummary` (L3's reliability-weighted consensus). Disagreement goes to an expert list; a single review waits.
  - **Stable cluster:** the cluster has a stable key from L8.
  - **Replayable:** replaying the episode's captured tool calls against today's tools gives the same results, compared by the tool fingerprints from iteration 3. A mismatch rejects the case and is listed under K4.
  - **Not a duplicate** of an existing case (same machine, failure mode and category); it links to the existing case instead.
- **Case format:** the episode's input; `expected` from the consensus verdict; Q3's `truth` with `category` and only the fields the reviews support (reviews don't give decisive refs, so those metrics don't apply and the report says so); `cohort: feedback`; `split` from Q2's machine rule; provenance with the cluster key, episode and review IDs from the report and `source: synthetic`.
- **Where cases live:** a reviewed file next to the generated `cases.jsonl` (for example `feedback_cases.jsonl`), not regenerated from the seed, loaded by the suite as its own cohort.
- **Output of the command,** for example `csai cases propose <report>`: the new case file on a new local branch, plus a pull request body: the cluster, consensus statistics, admitted and rejected candidates with reasons, links to episodes and reviews. It doesn't push or open the pull request (AGENTS.md rule 5).

**Acceptance:** offline tests on L2's answer key: the command admits cases only from planted patterns and none from the over-strict reviewer or wrong reviews, rejects a case whose tool results changed or that is labeled non-replayable, and gives identical output on a rerun. Then one real pull request with the first batch, from L8's fresh cohort, reviewed and merged by a person.

## The new baseline

After L9's first pull request merges:

- Run the full suite (original 18, Q3 challenge cases, the feedback cohort) with `--repeats 3 --concurrency 1` on the local target, with Q8's capture, and publish it (Q9).
- Record it in `docs/iteration-4/baseline.md`: revision, model, date, per cohort and split, with confidence intervals. Iteration 5's proposals are judged against this run.
- Cost: about 50 cases plus the feedback cohort × 3 repeats × 12k tokens, roughly 2M tokens, plus judge tokens. It needs approval.
- No data release is expected, since feedback cases use seed machines. If L9 changes any tool result, stop: that breaks invariant 1.

## Measurement and the shared environment

- **Offline first.** All items develop against offline tests, seed data and L2's generator.
- **Each of these needs its own approval:**
  - Q9 Part A: `azd provision` with the project capability host, and any storage connection after it.
  - Publishing to the Foundry project (it writes evaluations and evaluator versions there).
  - L8's classification run on the fresh cohort.
  - The baseline run.
- **Serialize token-heavy work.** Concurrency 1, one suite or classification at a time, within the 50k TPM model limit.

## Gates, PRs and completion

Every PR passes `uv run ruff check && uv run ruff format --check`, `uv run pyright` and `uv run pytest`. After changes to capture, eval data or the eval harness, also run `uv run csai eval rca --target local --concurrency 1`. A skipped or failing live gate is recorded as outstanding, not passed. No CI workflow.

Each PR includes the problem, the change, tests, sanitized evidence, limitations and any deployment it needs. Commit only on the item's branch, check the staged diff before every commit, and ask before pushing or opening the implementation PRs.

Proposed branches: `it4/q8-durable-capture`, `it4/q9-foundry-evals`, `it4/l8-stable-clusters`, `it4/l9a-replayable-feedback`, `it4/l9-feedback-cases`. L9 is one backlog item with two PRs.

While work is pending, the four backlog rows carry target `it4`. When an item meets its acceptance criteria, mark it done with its PR link and record its evidence in `docs/iteration-4/<item>.md`. New findings get the next free ID in their theme.

## Implementation and validation status

The reviewed implementation is committed in five stacked item pull requests.
The original dirty checkout and the uncommitted integration snapshot were
preserved. All domain data and measurements are synthetic and fictional.

| Item | Implementation PR | Initial stacked offline tests | Still outstanding |
|---|---|---|---|
| Q8 | [#20](https://github.com/marcgs/cs-ai-platform-sample/pull/20) | 426 | Fresh local eval after capture review fixes |
| Q9 | [#21](https://github.com/marcgs/cs-ai-platform-sample/pull/21) | 454 | Approved deployment, hosted smoke test, publication and parity comparison |
| L9 Part A | [#23](https://github.com/marcgs/cs-ai-platform-sample/pull/23) | 456 | No additional live measurement for replay implementation |
| L8 | [#24](https://github.com/marcgs/cs-ai-platform-sample/pull/24) | 478 | Fresh approved measurement and person acceptance |
| L9 Part B | [#22](https://github.com/marcgs/cs-ai-platform-sample/pull/22) | 497 | First fresh-cohort case PR reviewed and merged by a person |

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

Q10 keeps sparse-score parity explicitly blocked: one Foundry run per
measurement, sparse scores retained in rows, no invented missing scores and
no gate changes. Publication remains unperformed.

The user confirmed L8's proposed criteria before any fresh population
generation or key inspection: best-cluster recall at least 0.8 per planted
pattern, at most 1.5 clusters per planted pattern, no cluster formed by the
over-strict reviewer, and category agreement and route accuracy reported
against the frozen pilot. This does not approve classification traffic.

Implementation PR review and merge do not complete the remaining live or
human acceptance. The first reviewed feedback-case batch and the approved
three-repeat baseline still follow fresh L8 measurement and publication
setup. This single-repeat validation is not the new iteration baseline.

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
