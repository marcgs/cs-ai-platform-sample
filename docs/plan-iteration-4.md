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
- **L8 owns cluster identity:** a stable cluster key that L9 can cite and that survives a rerun of the analysis on the same input.
- **L9 owns the feedback case format:** the case file, its `cohort: feedback`, and the provenance fields. It reuses Q3's `truth` field and Q2's split rule.

**Merge order:** Q8 → Q9 → L8 → L9, then the baseline. Q8 and L8 can start at once; Q9's infrastructure step can be prepared in parallel.

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
- **Fresh measurement.** Generate a new population and cohort (new seeds) with L2's generator and the same selection rule as L3's pilot. Nobody reads its key before the criteria below are confirmed.
- **Criteria, proposed; confirm before measuring:** per planted pattern, best-cluster recall ≥ 0.8; at most 1.5 clusters per planted pattern; no cluster formed by the over-strict reviewer; category agreement and route accuracy reported against L3's pilot (24/30 and 27/30).
- **A person reviews** the top clusters and a sample of labels in the report. L3 had no human acceptance; this is it, recorded in `docs/iteration-4/l8.md`.

**Acceptance:** offline tests for canonicalization, stable keys and grouping. The fresh measurement is model traffic: estimate tokens first (about 30–50 classification requests, as in L3's pilot) and run only with approval.

## L9: feedback becomes eval cases, as a pull request

**Outcome:** a command turns a cluster report into a branch with reviewed eval cases, ready for a person to open as a pull request.

- **Input:** L8's cluster report, whose clusters already carry candidate eval cases (L3 marks them "require expert review before promotion").
- **Admission rules,** each with its reason in the output:
  - **Consensus:** at least two independent reviewers agree on the verdict and the actual root cause, using L3's reliability-weighted consensus. Disagreement goes to an expert list; a single review waits.
  - **Stable cluster:** the cluster has a stable key from L8.
  - **Replayable:** replaying the episode's captured tool calls against today's tools gives the same results, compared by the tool fingerprints from iteration 3. A mismatch rejects the case and is listed under K4.
  - **Not a duplicate** of an existing case (same machine, failure mode and category); it links to the existing case instead.
- **Case format:** the episode's input; `expected` from the consensus verdict; Q3's `truth` with `category` and only the fields the reviews support (reviews don't give decisive refs, so those metrics don't apply and the report says so); `cohort: feedback`; `split` from Q2's machine rule; provenance with the cluster key, episode and review IDs and `source: synthetic`.
- **Where cases live:** a reviewed file next to the generated `cases.jsonl` (for example `feedback_cases.jsonl`), not regenerated from the seed, loaded by the suite as its own cohort.
- **Output of the command,** for example `csai cases propose <report>`: the new case file on a new local branch, plus a pull request body: the cluster, consensus statistics, admitted and rejected candidates with reasons, links to episodes and reviews. It doesn't push or open the pull request (AGENTS.md rule 5).

**Acceptance:** offline tests on L2's answer key: the command admits cases only from planted patterns and none from the over-strict reviewer or wrong reviews, rejects a case whose tool results changed, and gives identical output on a rerun. Then one real pull request with the first batch, from L8's fresh cohort, reviewed and merged by a person.

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

Proposed branches: `it4/q8-durable-capture`, `it4/q9-foundry-evals`, `it4/l8-stable-clusters`, `it4/l9-feedback-cases`.

While work is pending, the four backlog rows carry target `it4`. When an item meets its acceptance criteria, mark it done with its PR link and record its evidence in `docs/iteration-4/<item>.md`. New findings get the next free ID in their theme.
