# ADR 0007: Explicit infrastructure-only publication retries

- **Status:** Accepted; offline implementation and live retry verified
- **Date:** 2026-11-02

## Context

A saved clean-main measurement was accepted for cloud evaluation, but its run
failed during runtime startup with `EvaluationSessionNotBound`, zero evaluated
rows and no output items. Normal publishing correctly retrieves that failed
run rather than creating a duplicate. Repairing infrastructure cannot change
the terminal run, so strict one-cloud-run-per-measurement deduplication prevents
publishing the same measurement successfully.

Changing the measurement identity or deleting the failed run would erase the
history or misrepresent the evidence. Automatic retries could spend tokens or
repeat quality failures without approval.

## Decision

- Keep measurements immutable and retain every failed publication.
- Normal publishing remains idempotent. A separate `--retry-infrastructure`
  option names a retained prior run and requires separate operator approval.
- Admit only a terminal `EvaluationSessionNotBound` startup failure with
  matching frozen provenance, positive receipt lineage, zero total/passed/failed
  rows, zero or unspecified errored count and an empty paginated output-item
  listing. Other errors, ambiguous evidence and partial or quality grades stop.
- Keep the original receipt unchanged. Bind a separate deterministic attempt
  receipt to the measurement, endpoint, judge and prior run. Link the cloud run
  name to its parent without dropping frozen metadata.
- Repeating the same approved request resumes that attempt, including after
  timeouts or uncertain outcomes. Shared measurement coordination serializes
  copies; unknown duplicates and conflicting lineage stop submission.
- Every additional attempt needs a new approval and cost disclosure. No agent
  rerun, automatic loop, receipt reset, failed-run deletion or host recreation.

## Consequences

One immutable agent measurement may have several explicitly approved cloud
publication attempts. This is a narrow exception to the original deduplication
contract, not a way to seek passing scores. A further infrastructure failure can
only be retried through its own retained receipt lineage and another approval.

Recovery requires the original receipt and registered attempt receipts, even
when remote run metadata is visible. Losing them blocks submission rather than
treating their absence as proof that no run exists.

Cloud judge scheduling is service-managed; the SDK exposes no concurrency
setting. Costs and quotas must be disclosed before each attempt, and local
suites/classification stay serialized. Offline tests establish admission,
lineage and idempotency. The approved retry completed with 50 output rows and
was confirmed in the portal; reporting findings are recorded in
[Q9's evidence](../iteration-4/q9.md). Sparse-score parity stays blocked under Q10.
