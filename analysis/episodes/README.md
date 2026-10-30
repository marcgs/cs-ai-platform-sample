# Episode analysis (iteration 3, Part A)

Offline-first cleaning, enrichment, classification, clustering and owner handoffs.
No Azure, Fabric, deployment or learner changes occur by default.

## Offline preparation

From the repository root, after `uv sync --all-packages`:

```bash
uv run analyze-episodes analyze \
  --episodes packages/diagnostics-domain/tests/fixtures/feedback/episodes.jsonl \
  --reviews packages/diagnostics-domain/tests/fixtures/feedback/reviews.jsonl \
  --source synthetic --synthetic-seed-context \
  --output analysis/episodes/output/prepared
```

This writes JSON and escaped, plain Markdown. **It does not classify.** Agreed
misses appear under `unclassified` as enriched classifier inputs. There is no
production rule-based substitute presented as a model result. Real JSONL exports
use `--source real`; omit `--synthetic-seed-context`. Synthetic and real
populations must have separate reports, including their reviews.

### Explicit Foundry labeling

Only classification sends model traffic. Configure `FOUNDRY_PROJECT_ENDPOINT`
and `FOUNDRY_MODEL_DEPLOYMENT_NAME` in your environment, and sign in for Entra
authentication. No keys are used. Obtain approval for model costs before running.

```bash
uv run analyze-episodes analyze \
  --episodes episodes.jsonl --reviews reviews.jsonl --source synthetic \
  --synthetic-seed-context --labeler foundry \
  --cache analysis/episodes/output/labels \
  --estimate analysis/episodes/output/preflight.json
```

`--estimate` is a dry run: no credential or client is constructed. It reports
uncached requests, approximate input tokens (UTF-8 bytes / 3, with prompt/schema
overhead) and maximum output tokens. This is not a billing quote. Inspect the
estimate, then explicitly authorize the same inputs/settings:

```bash
uv run analyze-episodes analyze \
  --episodes episodes.jsonl --reviews reviews.jsonl --source synthetic \
  --synthetic-seed-context --labeler foundry \
  --cache analysis/episodes/output/labels \
  --approved-estimate analysis/episodes/output/preflight.json \
  --output analysis/episodes/output/classified
```

Changed inputs, model settings or increased uncached budgets require a new
estimate. Requests are sequential, use strict structured output, have no tools,
and set `store=False`. Quoted logbook instructions and notes are untrusted data,
not classifier instructions. This boundary reduces injection risk; it does not
prove that a live classifier resists every attack.

Successful labels are cached by SHA-256 of the **entire enriched input**, prompt,
schema, classifier version, model, endpoint and generation settings. Cache
corruption fails closed; errors are not cached or silently turned into labels.
Reports identify failed episode IDs and sanitized exception types; the CLI exits
1 after writing a partial report. Retrying explicitly can reuse successful labels.
Keep JSON, caches and transcripts local: they can contain sensitive real evidence.

Classifier v2 forwards the supported generation settings `temperature` and
`top_p` to the SDK and rejects other settings, including attempts to override
model, schema, `store=False` or the explicit output-token budget. Connection
metadata (`project_endpoint`) is separate from generation settings and remains
fingerprinted, but is not sent as a per-request option. Previous classifier
caches/preflights are invalidated; obtain a fresh estimate before any approved run.

## What the pipeline does

- One vote per normalized reviewer identity per episode, regardless of review
  row ID or repetition. The latest revision wins; equal-time content breaks ties
  deterministically, using case-preserving content when normalized values tie,
  never row IDs. Anonymous feedback is conservatively one voice.
- Reviewer reliability is smoothed leave-one-out majority agreement. Ties are
  excluded. A verdict needs two named supporters and more than 60% of weighted
  votes. These are consensus policy parameters, **not classifier quality gates**.
  Majority agreement is not expert correctness. Sparse/conflicting reviews stay
  uncertain; no single strict reviewer can establish a miss.
- Captured `machine_id` takes precedence over legacy synthetic `id` and incident
  text. Platform/software come from that context, with an explicit optional
  dataset fallback for the same selected machine. Expected modes are majority
  reviewer assertions, labeled `reviewer_consensus`, not truth. The pipeline does
  not read scenarios, answer keys or `EpisodeTruth.actual_failure_mode` (the
  agent's reported output).
- Impact is mean historical downtime for the asserted mode, falling back to the
  historical population mean. Without history it is zero, marked unavailable.
  Cluster score is frequency x mean proxy downtime, not estimated savings.
- Fixed taxonomy: `missed_evidence`, `wrong_ranking`, `knowledge_gap`,
  `data_quality`, `tool_error`, `ambiguous_input`, `instruction_followed`.
  Grouping combines category with a normalized evidence/condition signature.
  Unrelated pressure and temperature omissions do not become one taxonomy-only
  cluster. Platforms, releases and asserted modes remain visible in each cluster.
- Behavior and ambiguity route to `learner_brief`; knowledge to
  `knowledge_proposal`; tool/data to `backlog`. Handoffs include evidence
  rationales, representative IDs and **every member's reproducing eval case**.
  These replay candidates retain calls/notes and need expert-confirmed expected
  outcomes before promotion into an eval suite. No proposal is applied.

Review a sample of labels/rationales against the captured evidence before trusting
the ranking. Model accuracy and signature stability require live validation.

## Separate answer-key benchmark

The `benchmark` command is offline and is the only production consumer of the
generator-only answer key. Neither analysis nor its classifier accepts a key.
Use a separately generated seed not used in classifier development:

```bash
uv run analyze-episodes benchmark \
  --report analysis/episodes/output/classified.json \
  --answer-key answer_key.json \
  --sample-size 100 --output analysis/episodes/output/benchmark.json
```

For an explicitly selected pilot, add `--allow-subset`. The full generator key is
read **only here**, after classification and blind audit are frozen. Denominators
then cover only the report's sampled episodes; unsampled episodes are not counted
as misses or controls. Unknown episode IDs still fail validation.

It reports per-pattern best-cluster rank, coverage, purity and route, plus category
accuracy on a deterministic hash-selected sample of planted misses. Unclassified
cases are excluded from category accuracy but included in end-to-end category
recall; control false positives are counted separately. It enforces matching
populations and invents no pass threshold. It does not enforce training isolation:
the operator must reserve a distinct population.

## Small held-out pilot (separate approval, not a population run)

Reserve generation seed `20261030` and selection seed `l3-pilot-v1` before
inspecting transcripts or labels. Neither is used by the scripted recovery tests.
Freeze the classifier prompt/version and record the selected IDs and preflight.
Run from the root; generated inputs, reports and caches below are gitignored.
The output directories must be new or empty, not a mix with a previous population.

```bash
uv run generate-feedback --count 300 --seed 20261030 \
  --output-dir analysis/episodes/output/held-out-chronology
uv run analyze-episodes sample \
  --episodes analysis/episodes/output/held-out-chronology/episodes.jsonl \
  --reviews analysis/episodes/output/held-out-chronology/reviews.jsonl \
  --source synthetic --misses 30 --controls 20 --seed l3-pilot-v1 \
  --output-dir analysis/episodes/output/pilot-chronology

uv run analyze-episodes analyze \
  --episodes analysis/episodes/output/pilot-chronology/episodes.jsonl \
  --reviews analysis/episodes/output/pilot-chronology/reviews.jsonl \
  --source synthetic --synthetic-seed-context \
  --output analysis/episodes/output/pilot-chronology-prepared
```

`sample` reads only episodes and reviews, not the answer key or model labels.
It hash-selects 30 consensus misses and 20 comparisons from the other episodes.
Comparisons include correct **and uncertain** reviews, not verified negatives.
Reviewer reliability is recalculated on the selected cohort; the subsequent
preflight, not the requested stratum count, determines actual model traffic.
Selection is outcome-stratified, so its rates do not estimate population rates.

The reserved cohort has **50 episodes and 30 classification candidates**. A local
classifier-v2 dry run with locally loaded real model settings estimates
**72,463 input tokens plus at most 36,000 output tokens**: about **108.5k tokens**, 30 sequential logical
requests and no tools. This is a byte-based approximation, not billed usage or a
dollar quote. Monetary cost is approximately
`0.072463 × input-price-per-million + 0.036 × output-price-per-million`;
confirm the actual deployment's prices and reasoning-token accounting first.
The platform client retries only rate limits, at most four attempts per logical
request; the token estimate is not a hard billing ceiling.

Offline preparation has already generated these files in the preparation
worktree. Reuse them there rather than rerunning generation into nonempty
directories. The chronology-corrected population was generated once after merging
authoritative main `ae90cc5`, containing merged Q2/L2/Q3, into L3's `ed86b50`.
L3's review fixes, L1's existing skill and Q8/S6 notes remain intact. The unfinished
L1 restack has not been pulled. The correction moves retrospective challenge
logbook findings after their observations; it changes no classifier logic or settings.
The population has 300 episodes and 1,246 reviews; the pilot has 50 episodes and
207 reviews. Older `held-out`, `pilot`, `*-corrected` and assistant-audit artifacts
remain unchanged as **pre-final preparation only**, not acceptance input. Do not
mix their inputs, reports or caches with the corrected cohort.

The previous `held-out-final`, `pilot-final`, freeze and blind-input pages also
remain untouched, with their original provenance. This is a technical repair of
the **same preselected cohort**, not a new outcome-selected sample. Verification
asserts identical population IDs/order, selection file, 30 candidate IDs,
20 comparison IDs and review bytes. Only captured `get_logbook` result timestamps
change: 85/300 population episodes and 13/50 pilot episodes. Of the original
20 blind raw records, 16 remain canonical-byte/semantic identical and four change
only those timestamps. Stop if any other difference appears; do not select again.

The four corrected raw records are prepared separately, including captured
diagnostic output and reviews but no assessments, labels or planted metadata.
Their fresh isolated assistant audit is pending. Old audit assessments were not
read to perform this correction. Assistant review is not human/domain-expert
manual acceptance.

**No model calls or held-out answer-key inspection has occurred.** Commit and
freeze the reviewed integration, complete the four-record blind correction audit
and obtain a fresh final-configuration estimate before labeling. The new cache
is separate and empty; the preliminary estimate remains 30 logical calls,
72,463 approximate input tokens and at most 36,000 output tokens, unchanged from
the prior budget. Its fingerprint changes, so the old estimate cannot approve it:

```bash
test -n "$FOUNDRY_PROJECT_ENDPOINT"
test -n "$FOUNDRY_MODEL_DEPLOYMENT_NAME"
uv run analyze-episodes analyze \
  --episodes analysis/episodes/output/pilot-chronology/episodes.jsonl \
  --reviews analysis/episodes/output/pilot-chronology/reviews.jsonl \
  --source synthetic --synthetic-seed-context --labeler foundry \
  --cache analysis/episodes/output/pilot-chronology-labels \
  --estimate analysis/episodes/output/pilot-chronology-estimate.json
```

Inspect the estimate and obtain approval for **this small cohort and budget**.
Stop if its scope or cost differs from what was approved. With no competing
token-heavy run, the approved live command is:

```bash
uv run analyze-episodes analyze \
  --episodes analysis/episodes/output/pilot-chronology/episodes.jsonl \
  --reviews analysis/episodes/output/pilot-chronology/reviews.jsonl \
  --source synthetic --synthetic-seed-context --labeler foundry \
  --cache analysis/episodes/output/pilot-chronology-labels \
  --approved-estimate analysis/episodes/output/pilot-chronology-estimate.json \
  --output analysis/episodes/output/pilot-chronology-classified
```

There is **no authorization to classify all 936 candidates** in the default
2,000-episode population, nor to expand the pilot automatically.

### Blind manual audit and final benchmark

1. Keep `held-out-chronology/answer_key.json` closed. An auditor first reads the selected
   transcripts, tool results, captured `Episode.output` and raw reviews, without
   seeing model labels/rationales or planted truth metadata. Audit at
   least ten candidate misses and ten noncandidate comparisons, selected by
   ascending SHA-256 of `audit-v1:<episode-id>` within each group. The candidate
   IDs come from `pilot-chronology-prepared.json`'s `unclassified` entries, not the key.
   Create a blank, deterministic audit sheet without opening any key or model
   report:

   ```bash
   uv run python - <<'PY'
   import hashlib
   import json
   from pathlib import Path

   output = Path("analysis/episodes/output")
   report = json.loads((output / "pilot-chronology-prepared.json").read_text())
   candidates = {row["episode"]["id"] for row in report["unclassified"]}
   comparisons = set(report["episode_ids"]) - candidates
   def order(value):
       return hashlib.sha256(f"audit-v1:{value}".encode()).hexdigest()
   selected = sorted(candidates, key=order)[:10] + sorted(comparisons, key=order)[:10]
   with (output / "pilot-chronology-audit.jsonl").open("x", encoding="utf-8") as stream:
       for episode_id in sorted(selected, key=order):
           stream.write(json.dumps({
               "episode_id": episode_id, "assessment": None, "category": None,
               "evidence_citations": [], "confidence": None
           }) + "\n")
   PY
   ```

2. Record episode ID, independent miss/correct/uncertain assessment, taxonomy
   category or abstention, evidence citations and confidence. Review dissenting
   reviewers and alleged root causes; majority agreement is not expert truth.
   Keep this local, separate from classifier inputs and cache. Identify the
   auditor type: an assistant audit is not human/domain-expert manual acceptance.
3. Freeze that audit, then compare model labels and rationales. Record category
   agreement with numerator/denominator, abstentions, false-positive consensus
   misses, missed failures among comparisons, signature fragmentation and route
   errors. Inspect the strict reviewer's reliability and whether its dissent
   alone introduced any cluster. Do not equate scripted agreement with this audit.
4. Freeze the report and audit before opening the key through the benchmark:

   ```bash
   uv run analyze-episodes benchmark \
     --report analysis/episodes/output/pilot-chronology-classified.json \
     --answer-key analysis/episodes/output/held-out-chronology/answer_key.json \
     --allow-subset --sample-size 100 \
     --output analysis/episodes/output/pilot-chronology-benchmark.json
   ```

5. Record every pattern's rank, coverage, purity and route, category agreement and
   control false positives. A small pilot may omit a pattern or fail recovery;
   that leaves acceptance outstanding, not a reason to cherry-pick another
   sample. Any prompt/signature tuning requires a newly reserved confirmation
   seed. Expanding the cohort or running the full population needs new consent.

### Frozen assistant preparation audit

The corrected cohort and deterministic 20-entry audit selection retain exactly
the original IDs; no sample was chosen again after inspection. A separate local
assistant audit was frozen before classification or benchmarking:
`output/assistant-blind-audit-corrected-20261030.json`. Its sibling `.freeze.json`
binds the audit and corrected inputs with SHA-256 hashes.

It records five directly visible process omissions, seven uncertain agent misses
and eight records with no specific miss supported by the permitted evidence.
Primary annotations are five `missed_evidence`, two observed `knowledge_gap`
conditions, three observed `data_quality` conditions, two provisional
`wrong_ranking` claims and eight abstentions. Two omissions have unresolved
`instruction_followed` alternatives; hostile-text exposure alone does not prove
compliance. The corrected update dates agree in all five audited update-context
records.

This is **assistant evidence review, not human/domain-expert manual acceptance**.
The assistant had prior development and pre-fix audit context. It inspected only
corrected inputs, tool observations and raw reviews, excluding diagnostic output
fields, classifier outputs and the key. Therefore ranking, output overconfidence
and injection causality remain provisional. These annotations must not be used
as expert ground truth, model accuracy or a replacement for the required audit.
No new L3 implementation defect was demonstrated.

### Verified offline evidence

The test-only deterministic callable reads transcript evidence, never the key.
It proves pipeline mechanics, **not Foundry quality**:

- Independently seeded 200-episode noisy population (seed 2026): all five planted
  patterns are the top five clusters and route correctly. 91/100 planted misses
  reach classification; their category agreement is 91/91. One noisy control is
  a false positive. Per-pattern recall ranges from 80% to 95%.
- Integrated 2,000-episode population (seed 42, 8,300 reviews): all five patterns
  are the top five clusters, with correct routes. Recovery is 184/200, 186/200,
  191/200, 185/200 and 186/200, in generator pattern order. On a 100-case sample,
  94 were classified and all 94 matched the category. Four of 1,000 controls are
  false positives. Noise is not claimed to be eliminated.
- A separate strict-reviewer control test creates no cluster even after hundreds
  of duplicate assertions. Duplicate episode/review rows do not change results.

No live classification, manual label audit or held-out **Foundry** agreement has
been run. These remain outstanding measurements, not passing model gates.
Agent instructions, tools and capture are unchanged; no live RCA eval is run.

```bash
uv run pytest analysis/episodes --basetemp=analysis/episodes/.test-work
```

## Notebook-compatible use

No notebook resource or Fabric connection is created. A future notebook can use
the same pure preparation and injected-classifier interface:

```python
from episode_analysis import prepare, analyze

prepared = prepare(episodes, reviews, dataset)
offline_report = await analyze(prepared)  # no network, enriched unlabeled candidates
# After explicit preflight approval, pass a CachedClassifier to analyze().
```

Part B's infrastructure and mirroring design is separate in
[`ADR 0006`](../../docs/adr/0006-episode-analytics-in-fabric.md); nothing here
claims that the Fabric path has been provisioned or verified end to end.
