# L9 Part B: propose feedback eval cases

## Status

The 2026-11-03 close-out removes clustering as an admission requirement.
The implementation now retains every reviewed cohort episode in
`Report.review_candidates`, including correct/uncertain reviews and episodes
never classified. Consensus still rejects or defers unsupported cases.
Cluster metadata, when present, is corroborated as provenance, not required.
This is offline implementation; the first fresh-cohort **data PR**, its human
merge remain outstanding. The three-repeat baseline is postponed pending
remote-evaluation research; no baseline approval request is being prepared.

Offline implementation prepared for an explicitly authorized local-only commit
after Q8, Q9, L9 Part A and L8. No push, pull request, deployment or model call is
part of this validation. L8's acceptance criteria are confirmed; fresh-cohort
measurement and human review remain pending. L9 is not marked done.

## Command

```bash
uv run csai --no-azd cases propose path/to/report.json
```

For the retained fresh report, attach the full cohort sources offline:

```bash
uv run csai --no-azd cases propose path/to/report.json \
  --episodes path/to/cohort-episodes.jsonl --reviews path/to/cohort-reviews.jsonl
```

Both options are required together. Cohort membership, counts and recomputed
reviewer reliability must match the report. No classifier, answer key or model
is used. New reports already retain report-wide review candidates; the options
also make legacy v2 reports include episodes outside classification. Without
them, a legacy report can propose only the review evidence it retained.

The input must be an explicitly synthetic L8 report with the required
`schema_version: episode-analysis-v2`. Legacy pilots lack the review evidence
needed for promotion and are rejected rather than upgraded.

The command creates a deterministic local branch,
`feedback/cases-<first twelve characters of report SHA-256>`, and writes:

- `evals/rca/src/rca_evals/feedback_cases.jsonl`: proposed reviewed cases, additive
  to the generated seed manifest.
- `docs/iteration-4/proposals/<digest>/proposal.json`: all decisions and reasons.
- In the same directory: `report.json`, linked `evidence.md` and `pr-body.md`.

It does not stage, commit, push or open a pull request. A person reviews the diff
and evidence before publication. Existing generated `cases.jsonl` is never
rewritten. Identical reruns on the proposal branch produce identical files and
CLI output, including admission and duplicate decisions. Changed artifacts are
not overwritten. If the branch already exists elsewhere, switch to it explicitly
before rerunning. `--repository` selects a repository root for offline tooling/tests.
Conflicting existing case IDs are rejected rather than replaced. Manifest and
artifact destinations, including every parent directory, must not be symlinks;
these checks finish before any branch switch or file write.

## Admission

1. Discover candidates from all report-wide review evidence. Cluster membership
   is optional. When metadata exists, check its canonical identity and consistency
   with labels and source rows; reject conflicting copies of the same evidence.
2. Replay every candidate's captured calls through Part A's helper. Missing,
   truncated, changed, malformed or unsupported captures reject into the K4 list.
   Explicit non-replayable call metadata and capture errors also reject.
   Required candidate `capture_truncated` retains episode-level truncation flags;
   losing whole calls or other episode content cannot silently pass replay.
3. Check retained review IDs against their actual source rows, episode and source;
   reject repeated normalized reviewer identities, conflicting row IDs and missing
   reviewer weights. Anonymous votes cannot establish consensus.
4. Check cohort reliability counts and their smoothed weights. Reproduce the
   supplied `ReviewSummary` with those cohort weights, **not** newly estimated
   weights from candidate rows. Check verdict, cause, agreement, root-cause support,
   independent-reviewer count, notes and expected-mode basis.
5. Require at least two named independent reviewers agreeing on verdict and actual
   cause. Single reviews wait. Explicit verdict or cause disagreements go to an
   expert even when the reliability-weighted summary has a winner. Correct-output
   consensus is not a recurring failure.
6. Require one replayed machine identity consistent with the incident input and
   unambiguous generated scenario category for that replayed machine. Category
   does not come from a classifier label or the review's free-text note.
7. Link duplicates by machine, reviewer-supported failure mode and Q3 incident
   category, against both original18 and challenge cases, previous feedback cases
   and earlier admitted candidates.

The conservative disagreement rule matters: the generated population includes
occasional matching wrong assertions from several reviewers. A majority is not
proof. These checks detect internal inconsistency, not authenticated authorship
or independent causal truth; even unanimous reviews can be wrong. Human review
is still necessary.

## Cases, categories and splits

`EvalCase` gains optional `cohort` and `provenance`. Both are omitted when absent,
preserving serialization of original and challenge cases. New cases retain the
existing input/expected/truth/split schema and add:

- `cohort: feedback`;
- expected machine and **review-consensus** actual failure-mode ID;
- `truth.category` from existing incident metadata, with other truth fields empty;
- provenance: optional canonical cluster key/condition, episode, source review IDs and
  supporting review IDs, synthetic source, verdict, L8 analysis category and
  replay fingerprints.

New provenance explicitly labels `failure_mode_basis: reviewer_consensus` and
`category_basis: replay_matched_synthetic_scenario`. Older cases without either
label remain readable; a partially labeled source is rejected.

L8's failure-analysis category is not Q3's incident category. As approved during
close-out, reviewers establish the cause; seed scenario metadata establishes
only the incident category. Part A's four feedback-only
machines expose their copied incident metadata through `feedback_scenarios`;
promotion reads category only, never their expected cause. Unknown or ambiguous
incident metadata is deferred, not guessed from a condition or assumed clean.

**Real-feedback limitation:** this path admits synthetic reports only. Real
episodes cannot borrow category metadata from a seed scenario, even if a machine
identifier matches. They need independently supported incident-category metadata
and a reviewed admission path; reviewer cause consensus alone does not supply it.

No answer key, seed expected cause, decisive refs, alternatives, ruled-out modes,
checks or canaries supplies a new expected answer. Missing truth-dependent metrics
are not scored: decisive evidence and ruled-out checks naturally skip empty
fields; feedback injection-canary and specific data-quality judges explicitly
skip unsupported truth. Outcome, grounding, tool coverage and calibration remain
informational.

The loader appends the reviewed file as a feedback cohort and validates provenance,
duplicates and split conflicts. Q2's `assign_splits` receives original, challenge,
existing feedback and new cases together; existing machine assignments stay frozen.
Feedback failures never enter the quality gate's denominator until its baseline
is approved (plan invariant 3). The command proposes cases; it does not claim their PR
has been reviewed or merged.

## Integration details

The CLI declares its direct `episode-analysis` and `diagnostics-domain` dependencies.
It registers one new Typer group; Q8's eval commands/capture are untouched.

The combined L8 metrics exposed two generator-context overlaps. In this branch,
vacuum-omission scenarios are restricted to clean vacuum incidents, not injection
machines. Update transcripts look up an observed shared code. L2 fixtures are
regenerated through the generator; seed records, tools, original/challenge cases
and frozen L3 pilot artifacts remain unchanged.

## Verification

Close-out regressions cover unclustered consensus admission, split patterns,
forged evidence without a cluster, full-cohort attachment without classification,
optional-provenance loading and byte-identical public-command reruns. Older
validation below is retained as historical evidence, not the current admission rule.

The public CLI tests use real isolated local git repositories with no commits,
L2-generated populations, L8's actual preparation/analysis and a test-only offline
evidence classifier. They compare admitted cases with the separate answer key
only **after** admission.

- Ruff lint/format: passed.
- Strict pyright: zero errors and warnings.
- Public CLI proposal tests: 12 passed. Focused generator, L8 integration and
  proposal selection: 32 passed.
- Combined full offline suite: 439 passed, 32 existing SDK deprecation warnings.
- Frozen MCP and agent golden selection: 7 passed, 12 deselected.
- The corrected 2,000-episode / seed 2026 cohort replayed all 9,600 calls with no rejection.
- Count 200 / seed 2026 acceptance input: 92 candidate decisions; 3 admitted new
  cases, 29 duplicate links and 60 expert referrals. All admitted cases belong
  to planted failures and have the answer key's actual cause. Over-strict-only
  verdicts and wrong review assertions produce no new cases.
- Tests reject changed results, explicit non-replayable captures, forged summary
  statistics, missing review IDs, copied reviewer identities and unstable keys.
  Single reviews wait; cause disagreement refers to experts. Reruns are byte
  identical and the additive loader rejects duplicates and split leakage.
- Original/challenge `cases.jsonl`, seed records and frozen L3 pilot paths have
  no additional Part B changes. `git diff --check` passes.

Dependencies were restored only in this worktree's `.venv` after the CLI manifest
changed. The root checkout and shared environment were not modified.

Live `csai eval rca --target local`, the fresh L8 cohort, and a real reviewed PR
are not run or claimed: model traffic and publication are not authorized.

## Integration review — 2026-11-01

Fixed the episode-level capture flag loss at the L8 report boundary and added a
public CLI K4 regression. Also hardened the additive loader: it corroborates the
cluster-key hash against its recorded category/condition, requires fingerprint
digest syntax, rejects empty/duplicated review provenance and correct-output
verdicts, and rejects whitespace-padded incident identities that could bypass
duplicate or split checks. Admission still derives actual cause only from
independent review evidence, not classifier conditions or diagnostic output.

Validation from the integration worktree:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -q \
  --basetemp="$PWD/.pytest_cache/review-feedback-tmp" \
  analysis/episodes/tests packages/diagnostics-domain/tests \
  cli/tests/test_cli_cases.py services/diagnostics-mcp/tests \
  evals/rca/tests agents/rca/tests/test_agent.py
```

**225 passed**. Ruff lint/format passed over the owned analysis/domain/MCP
packages and promotion/loader files; strict Pyright passed over their source
packages and CLI promotion modules. `git diff --check` passed.
The existing worktree environment printed a Python patch-version mismatch
warning; no dependency installation or environment mutation was needed.
Test scratch repositories stayed inside the worktree and created no commits.

Full repository gates are reserved for the parent integration review.
The live RCA eval is intentionally skipped because model traffic is prohibited.
Fresh-cohort measurement, person review, item PRs and the published baseline
remain outstanding; this review claims no live acceptance.

## Ordered local commit validation

Reviewed promotion/loader code, public CLI tests, runtime dependencies and the
deferred platform feedback fields were copied unchanged onto the validated local
L8 commit. Only the two deferred cases-group registration lines were restored in
the CLI entry point. The CLI manifest change was followed by
`uv sync --all-packages --frozen`, using the copied ignored integration lock.
No SDK ranges or unrelated source files changed.

Final stack repository gates:

```bash
uv run --frozen --no-sync ruff check
uv run --frozen --no-sync ruff format --check
uv run --frozen --no-sync pyright
PYTHONDONTWRITEBYTECODE=1 uv run --frozen --no-sync pytest -q --tb=short \
  --basetemp="$PWD/.pytest_cache/l9-stack-tests"
```

**497 tests passed**, with 32 existing SDK deprecation warnings. Ruff lint and
formatting passed (**146 files**); strict Pyright reported **zero errors or
warnings**. Original/challenge cases, agent instructions, legacy tool goldens
and frozen pilot outputs remain unchanged. Test scratch artifacts are confined
to and cleaned from the new worktree.

The separately approved 50-case local RCA gate ran on the **uncommitted full
integration snapshot**, not these ordered clean commits. It is not a feedback
baseline or fresh L8 measurement. No additional live acceptance, model traffic,
deployment or publication is claimed or approved here.

## Copilot review follow-up

- **4436440053:** reject an incoming case whose ID conflicts with a different
  previously reviewed case. A public CLI regression corrects a reviewed cause
  without renaming its ID and confirms rejection preserves all files and the
  current branch.
- **4436440072:** reject symlink destinations and every symlinked parent.
  Manifest checks precede reads; all destination checks precede branch switches
  and proposal writes. Public CLI
  regressions cover dangling artifact links, existing/dangling artifact parents,
  existing/dangling feedback manifest links, original manifest links and
  symlinked manifest parents. Rejections preserve checkout contents, external
  destinations and the current branch.

Seven initial CLI regressions failed before repair; all **27 public proposal
tests** now pass. Native L9B fix gates passed **505 full offline tests**, with
32 existing SDK deprecation warnings; repository Ruff lint/format passed
(**146 files**) and strict Pyright reported zero errors or warnings.
No dependencies or SDK ranges changed. Original/challenge manifests, golden
responses and frozen pilot outputs remain unchanged.

The approved live gate remains pre-review evidence from the uncommitted
integration snapshot. Additional model traffic is not authorized; a fresh
post-fix live gate is skipped and remains outstanding. The parent owns restacking
these fixes with the parallel Q8/Q9 fixes and combined acceptance validation.
### Round-two compatibility and cohort review

- **4436545773**, dependent completion fix: candidates preserve actual status,
  creation and completion timestamps. Promotion rejects running or unfinished
  captures before reconstructing replay input, and forwards the original
  lifecycle fields. Completed failed captures remain supported. The narrow L8
  boundary model/pipeline/test change is included in this L9B fix, so native
  item commits remain self-contained; the native L8 branch is unchanged.
  Classifier behavior, prompts and fixed clustering vocabulary are unchanged.
- **4436549683**: seed-only manifest, gate and CLI baselines use an explicit
  absent feedback path. A real feedback file in an isolated package verifies
  default additive loading, exactly 50 original cases and the same 18 gate IDs.
  Existing duplicate, split, provenance and leakage assertions are retained.
- **4436549700**: runtime results propagate original/challenge/feedback labels.
  Console, legacy artifacts and offline durable rebuild report cohort means
  and hierarchical 95% intervals. Legacy journal rows recover absent labels
  from frozen cohort metadata, falling back to frozen case/gate metadata only
  when absent. Explicit label conflicts are rejected; journal bytes, scores,
  outputs and missing episodes are not rewritten or fabricated. Original18
  gate calculations are unchanged.

Focused reporting, lifecycle, loader and CLI regressions pass; the full native
offline suite passes **537 tests**, with 32 existing SDK warnings. Repository
Ruff lint/format (**147 files**) and strict Pyright pass. No dependency, SDK range,
original/Q3 manifest, tool golden or frozen pilot artifact changed.

The approved live evaluation was the pre-review uncommitted integration snapshot.
Additional model traffic is unapproved: a fresh post-fix live gate is skipped and
outstanding. Parent restacking must combine these cohort changes with the
parallel Q8 completion-certificate/load changes before rereview and acceptance.

### Round-three seed-only knowledge gate

Copilot comment **4436638946** identified one remaining seed-only baseline.
The measured knowledge-gate test now passes an explicitly absent feedback
manifest, retaining its existing 13-of-18 pass and 12-of-18 failure assertions.
The full offline suite passes **561 tests**; Ruff lint/format and strict
Pyright pass. Additive loading and original18 production gates are unchanged.
No model traffic, publication or deployment ran.

### Round-four blank-cause consensus

Copilot comment **4436761858** is addressed: a whitespace-only actual cause
does not contradict otherwise admissible reviewer consensus. The public CLI
regression retains two distinct named cause supporters, ignores a third blank
cause, and excludes that review from supporting provenance. Single-review
waiting and explicit-disagreement expert routing remain covered and unchanged.
The full offline suite passes **585 tests**, Ruff lint/format and strict
Pyright. No new model or cloud traffic ran.
