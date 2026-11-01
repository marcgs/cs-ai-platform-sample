# L9 Part B: propose feedback eval cases

## Status

Offline implementation prepared for an explicitly authorized local-only commit
after Q8, Q9, L9 Part A and L8. No push, pull request, deployment or model call is
part of this validation. L8's acceptance criteria are confirmed; fresh-cohort
measurement and human review remain pending. L9 is not marked done.

## Command

```bash
uv run csai --no-azd cases propose path/to/report.json
```

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

## Admission

1. Check stable canonical cluster identity, label and episode membership.
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
   unambiguous supported incident-category metadata.
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
- provenance: canonical cluster key/condition, episode, source review IDs and
  supporting review IDs, synthetic source, verdict, L8 analysis category and
  replay fingerprints.

L8's failure-analysis category is not Q3's incident category. Existing manifest
and seed incident metadata establish the latter. Part A's four feedback-only
machines expose their copied incident metadata through `feedback_scenarios`;
promotion reads category only, never their expected cause. Unknown or ambiguous
incident metadata is deferred, not guessed from a condition or assumed clean.

No answer key, seed expected cause, decisive refs, alternatives, ruled-out modes,
checks or canaries supplies a new expected answer. Missing truth-dependent metrics
are not scored: decisive evidence and ruled-out checks naturally skip empty
fields; feedback injection-canary and specific data-quality judges explicitly
skip unsupported truth. Outcome, grounding, tool coverage and calibration remain
informational.

The loader appends the reviewed file as a feedback cohort and validates provenance,
duplicates and split conflicts. Q2's `assign_splits` receives original, challenge,
existing feedback and new cases together; existing machine assignments stay frozen.
`EvalSuite.gate_case_ids` remains exactly original18. Feedback failures never enter
that gate's denominator. The command proposes cases; it does not claim their PR
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
