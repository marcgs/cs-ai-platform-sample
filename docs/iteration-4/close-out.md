# Iteration 4 close-out

Status: implementation complete; the first feedback-case PR and this close-out
record await human review and merge. All domain data is synthetic and fictional.

## Delivered

- **Durable evaluation capture (Q8):** [#20](https://github.com/marcgs/cs-ai-platform-sample/pull/20),
  with interruption-safe records and offline report rebuilding
  ([evidence](q8.md)).
- **Saved-run publication and explicit infrastructure-only recovery (Q9/Q11):**
  [#21](https://github.com/marcgs/cs-ai-platform-sample/pull/21) and
  [#26](https://github.com/marcgs/cs-ai-platform-sample/pull/26).
  Earlier failed requests and receipts remain evidence ([Q9 record](q9.md),
  [ADR 0007](../adr/0007-infrastructure-only-publication-retries.md),
  [ADR 0008](../adr/0008-evaluation-storage-network-exception.md)).
- **Local outcome gate (Q4):** merged
  [#28](https://github.com/marcgs/cs-ai-platform-sample/pull/28).
  Three minimum means and the injection hard check cover applicable original
  and challenge cases. Invalid reports score zero; only true plumbing is excluded.
- **Consensus admission (L9):** merged
  [#30](https://github.com/marcgs/cs-ai-platform-sample/pull/30), following
  replay [#23](https://github.com/marcgs/cs-ai-platform-sample/pull/23) and
  proposal tooling [#22](https://github.com/marcgs/cs-ai-platform-sample/pull/22).
  Consensus, replay and no duplicate replace cluster membership
  ([admission and integrity rules](l9b.md)).

## Measured and proposed

The retained 50-case single-repeat measurement and its completed 50-row
publication remain the reference, not a grown-suite baseline. The original
publication's numeric audit passes 450/450 at absolute tolerance `1e-12`
([measurement and publication evidence](q9.md#completed-validation-and-acceptance-findings--2-november-2026)).
The final offline outcome re-score is unchanged at **0.78 / 0.75 / 0.92**,
with all four injection checks passing, four invalid reports and no plumbing
failures. [Means, applicability and intervals](../../evals/rca/README.md)
come from the unchanged journal, not new model calls.

The first data proposal, [#32](https://github.com/marcgs/cs-ai-platform-sample/pull/32),
considers all 50 fresh-cohort episodes: **2 retained cases, 8 duplicates,
12 correct-output rejections, 27 expert referrals and 1 manually excluded
conflict**. `FB-099561399790d755` (`M-0010`) was manually excluded.
Four independent reviewers support each retained verdict; cause support is
0.75 / 1.00. The original automatic proposal admitted 3 cases; its frozen
decisions, source reviews and replay fingerprints remain historical evidence.
A deterministic rerun reproduces the original automatic proposal, not the
manually corrected two-case manifest. No cause investigation or new guard was
implemented; L9 records the deferred same-input conflict check.
The implementation and data proposal pass Ruff, strict Pyright and 670 offline tests.

Human review/merge is still required: these are proposed cases, not an accepted
baseline. Cause comes from reviewer consensus; category comes only from the
replay-matched synthetic scenario, labeled in provenance. Real feedback needs
independently supported category metadata. Feedback remains report-only.

## Decided and moved

- **L8 closes as a finding (L12):** the fresh measurement failed recall and
  fragmentation criteria despite pure clusters. All 20 blind judgments have
  person acceptance; top-five cluster review is no longer needed. No retuning
  or rerun on the opened key
  ([retained outcome](l8.md#approved-fresh-classification-and-failed-acceptance--3-november-2026)).
- **Q16 closes as superseded:** [#29](https://github.com/marcgs/cs-ai-platform-sample/pull/29)
  is closed and its branch unmerged. It contains judges-only publication,
  observation-timeout handling and removal of mirror-only machinery.
  Main keeps the existing publisher; historical runs are not deleted or migrated.
- **The three-repeat baseline, its publication and Q17 move after the spike
  decision** in [#31](https://github.com/marcgs/cs-ai-platform-sample/pull/31)
  ([plan](../spike-foundry-native-eval.md)). Provisional floors
  **0.70 / 0.65 / 0.85** remain approved; no threshold question or baseline
  approval request is pending. The local gate stays the reference and fallback.

This close-out used no model runs, Foundry publication, Azure writes or
deployments. The live eval after adding feedback data was deliberately skipped
under that boundary. The spike has not run. Its run 1 follows human merge of
the case and close-out PRs and still needs separate model/write approval.
