# L9 Part A: replay-compatible synthetic feedback

## Scope and status

L9 Part A is stacked after the locally validated Q8 and Q9 commits, prepared for
an explicitly authorized local-only commit. Its independent draft was first
validated against `origin/main`. No push, pull request, deployment or model call
is part of this validation. L9 is not marked done. L8's fresh cohort, human
acceptance and L9 Part B promotion remain separate work.

## Implementation

- `DiagnosticsTools` and its result models moved unchanged to
  `diagnostics_domain.tools`. `diagnostics_mcp.tools` re-exports the existing API;
  MCP wrappers and runtime dependency declarations are unchanged. No domain-to-service
  dependency or new third-party dependency is introduced.
- Transcripts call these functions directly. Updates, untrusted logbook instructions
  and collection problems reuse the existing harder seed cohorts.
- Four new machines, their telemetry and logbook records, and `EC-9901` events
  supply the missing-mapping context. The generator appends records only; existing
  seed records, eval scenarios and tool results are unchanged.
- Successful missing-mapping controls use telemetry and service clues instead of
  fabricated Azure search results. All newly generated episodes are replayable;
  no unsupported context needs non-replayable metadata.
- L2's ten-record fixture is regenerated with count 10, seed 42. Published L3
  pilot artifacts and their opened answer keys are frozen, not regenerated.

## Contract for Part B

`diagnostics_domain.feedback_replay` exports:

```python
replay_episode(episode: Episode, *, tools: DiagnosticsTools | None = None) -> ReplayResult
execute_tool_call(call: ToolCall, tools: DiagnosticsTools) -> str
tool_fingerprint(call: ToolCall) -> str
```

`ReplayResult` has `replayable: bool`, `fingerprints: list[str]` and
`issues: list[ReplayIssue]`. Issues contain `call_index`, `tool_name`, `reason`;
index -1 denotes an incomplete episode. All models forbid extra fields.
No platform episode schema changes are required.

The fingerprint is SHA-256 over sorted, compact JSON containing the normalized
tool name (toolbox prefix removed), arguments and parsed JSON result. It excludes
timings. Comparison rejects changed results; unsupported tools and incomplete
captures fail closed. There was no pre-existing tool-result fingerprint helper in
this branch; the L3 classifier fingerprint hashes classifier inputs and settings,
not replayed calls. This helper does not replace that cache key.

Part B must also check L8 v2 review evidence, exclusions and duplicate identities.
Replayability alone says nothing about whether an episode is a valid new eval case.
Old transcript overlays and unsupported search calls fail replay; do not silently
treat a frozen v1 pilot as a replay-compatible promotion input.

## Earlier implementation verification

- `uv run --no-sync ruff check`: passed.
- `uv run --no-sync ruff format --check`: passed (128 files).
- `uv run --no-sync pyright`: zero errors or warnings.
- Focused domain, MCP, agent and coupled analysis test: 91 passed.
- `uv run --no-sync pytest -q`: 407 passed; 32 existing SDK deprecation warnings.
- A generated 2,000-episode cohort (seed 2026) replayed all 9,600 calls with no
  rejection. Each planted pattern had 200 replayable failure episodes.
- Tests also replay 100-episode cohorts with seeds 7 and 42, reject changed,
  unsupported and incomplete calls, compare existing records and tool results
  across all 52 prior machines, and retain the frozen 791-response legacy golden.
- `git diff --check`: passed. Frozen L3 pilot paths have no diff.

The test-only L3 evidence classifier was adjusted to recognize real response
fields and existing seed text; production classification and pilot artifacts
were not changed. Its assertions were not relaxed.

The initially absent worktree dependencies were restored into its own `.venv`
using a copied, gitignored local lock and `uv sync --all-packages`. The shared
checkout's environment was not modified.

Live `csai eval rca --target local` was intentionally not run during that
offline implementation work; model traffic was not authorized.

## Independent draft validation

The draft copies only reviewed domain/MCP code, tests and documentation.
The seed and established ten-episode fixture (seed 42) are regenerated with
their existing generators and match the reviewed integration snapshot byte for
byte. No fresh population/cohort, new answer key or classification is generated.
L8 production analysis, feedback promotion, eval feedback loading and Q8/Q9
changes are not included.

The legacy L3 test-only evidence classifier required a compatibility adjustment
for real `possible_causes` results and existing injection/update text. Only those
observational checks change; legacy condition labels, assertions and production
analysis code remain unchanged. The old transcript-overlay checks failed the
independent draft's pattern-recovery test before this adjustment.

The new worktree initially lacked Ruff. After that validation failure,
`uv sync --all-packages` restored dependencies into this worktree's own `.venv`
using the integration worktree's copied, ignored local lock. No shared environment
was modified and no dependency manifest or SDK range changed.

All independent draft gates pass:

```bash
uv run --no-sync ruff check
uv run --no-sync ruff format --check
uv run --no-sync pyright
PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -q --tb=short \
  --basetemp="$PWD/.test-artifacts/l9a-draft"
```

Full offline pytest: **407 passed**, with 32 existing SDK deprecation warnings.
Ruff lint/format passed; strict Pyright reported zero errors or warnings.
The original/challenge manifest, agent instructions, legacy golden and frozen
pilot paths remain unchanged. Local test scratch artifacts are removed before
staging. Existing pre-commit hooks remain enabled for the local commit.

## Stacked local validation

After applying the independent L9A draft without committing onto Q9 (which
already follows Q8), all repository gates were rerun: Ruff lint/format
(**137 files**), strict Pyright (**zero errors or warnings**) and full offline
pytest (**456 passed**, 32 existing SDK deprecation warnings).
The local lock stayed ignored; test scratch artifacts were confined to and
cleaned from the new worktree. No code changed during restacking.

## Separate integrated live evidence

The parent reports 497 passing integrated offline tests, Ruff lint/format,
strict Pyright and Bicep build. A separately approved single local RCA gate
completed 50 cases with exit 0 on the **uncommitted full integration snapshot**.
That result is not live proof for this independent L9A draft commit, not a
feedback-cohort baseline and not fresh L8 classification acceptance.
No additional model traffic, deployment or publication is approved here.

## Copilot review follow-up

Comment **4436431183** identified copied scenarios whose decisive references
still named the original machines. `feedback_scenarios` now remaps telemetry,
event and logbook references using the exact allocation performed by
`extend_feedback_seed`. Four regression cases failed before the fix; each now
resolves all decisive evidence through the copied machine's real tool results,
including its unmapped-code events, without changing original scenario fields.

Native L9A fix validation: **460 full offline tests passed** (32 existing SDK
deprecation warnings), Ruff lint/format passed (**137 files**), and strict
Pyright reported zero errors or warnings. The focused feedback/golden selection
passed **24 tests**. Running the seed and case generators produced no tracked
data change; the existing fixture and frozen pilots remain unchanged.

The approved live gate was the pre-review uncommitted integration measurement.
No new model traffic is authorized, so a fresh post-fix live gate is skipped and
remains outstanding. Restacking the parallel item fixes and their combined
validation is parent-owned.
### Round-two replay completion review

Copilot comment **4436545773** is addressed: replay rejects running captures
and captures without an episode completion timestamp, even when every tool call
is complete. Completed failed episodes remain replayable when their tool capture
is complete and matches the current tools. Four focused lifecycle regressions
and the full native offline suite pass (**479 tests**, 32 existing SDK warnings).
Repository Ruff lint/format (**138 files**) and strict Pyright pass.

The dependent L9B fix preserves actual lifecycle evidence in the analysis
candidate and rejects incomplete candidates before reconstruction. No seed,
manifest, tool golden or frozen pilot artifact changed. The approved live run
was the pre-review uncommitted integration snapshot; a fresh post-fix live gate
is unapproved, skipped and outstanding.
