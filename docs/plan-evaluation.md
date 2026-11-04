# Plan: evaluation the Foundry way

**Goal:** evaluating the RCA agent works the way the Foundry documentation describes it, with our own code only where a gap is proven and recorded in [Foundry findings](foundry-findings.md). When this plan is done, its results go into the README, architecture, walkthrough and an ADR, and this file is deleted.

## What's already there

- **50 test cases** with answer keys in [`evals/rca`](../evals/rca/README.md), generated from the seed scenarios.
- **The infrastructure Foundry evaluation needs in this private network:** a project capability host and a dedicated evaluation storage account ([ADR 0008](adr/0008-evaluation-storage-network-exception.md)).
- **What we learned the first time**, in the findings' [evaluation section](foundry-findings.md#evaluation). Read it before starting; most of it will come up again.
- **Step 1 is done:** `evals/azure.eval.yaml` and the README's Evaluate section. It uses `azd ai eval` instead of the quickstart's removed `azd ai agent eval`, a local source instead of a dataset, and judges that see the final answer but not the tool calls; the findings say why.
- **Step 2 is done:** the rows in `evals/rca/queries.jsonl` carry the answer key, and six code evaluators score each case against it next to the two judges ([`evals/rca`](../evals/rca/README.md#evaluation)). Metrics that don't apply to a case score 1.0 there; each row's `applicable_metrics` says where a score counts, for step 3. Open: a run's agent calls stop working after about 14 minutes, so all 50 cases took two runs; splitting the cases into batches is proposed, not built ([finding](foundry-findings.md#an-evaluation-runs-agent-calls-stop-working-after-about-14-minutes)).

## Steps

One step at a time, each one pull request. Don't start a step before the previous one works.

| # | Step | Done when |
|---|---|---|
| 1 | **The quickstart, exactly.** Follow [Evaluate your hosted agent](https://learn.microsoft.com/azure/foundry/observability/quickstarts/quickstart-evaluate-hosted-agent) (azd tab): a queries file, two built-in evaluators (intent resolution, task adherence), `eval.yaml`, one `azd` command. Use a handful of queries from the test cases. | The run shows up in the portal with scores, started by one command that's in the README |
| 2 | **Correctness against the answer key.** Add the answer key to the dataset, and the outcome checks as Foundry custom evaluators, written from scratch: `hit_at_1` (expected failure mode ranked first), `hit_at_1_lenient` (or an accepted alternative, or a justified `unknown` when the case names no machine), `hit_at_3` (in the top three), `decisive_evidence_recall` (share of the decisive references cited), `evidence_grounded` (share of cited references that exist and belong to the machine) and `injection_resisted` (planted instructions not followed). Check against the [custom evaluators](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/custom-evaluators) docs which kind fits each check. | Per-case scores for each check visible in the portal, on all 50 cases |
| 3 | **Pass or fail.** First check what Foundry and azd offer: the structured `azd ai eval` flow has a documented pass-rate quality gate for CI ([test a hosted agent](https://learn.microsoft.com/azure/foundry/agents/how-to/test-hosted-agent#run-structured-evaluations)). Write our own only if that can't express what's needed. | One command says pass or fail and exits non-zero on fail |
| 4 | **First measurement.** All 50 cases, all evaluators, on the deployed agent. Set the pass criteria from it. | Results recorded in the eval guide; pass criteria set from them |

## Rules

- **Docs first.** Before each step, read the current Microsoft Learn pages; preview features change. If the docs and the installed tools disagree, record it in the findings and say which one you followed.
- **Every limitation, bug or workaround goes into the findings**, with how we got past it and the date checked.
- **Names in the Foundry project:** one evaluation for the suite (`rca-quality`), runs named by agent version and date, one name per custom evaluator, one named dataset per version of the cases. No throwaway items left behind; delete experiments once a step is done (with the user's approval).
- **Approvals:** model tokens cost money. Estimate each run before starting it and get the user's approval; stop and ask before going more than half over. Foundry project writes (datasets, evaluators, evaluations, runs) are fine within an approved step. Infrastructure, network, role or deployment changes always need the user's approval.
- **Keep it small.** No parity checks against old code, no receipts or retry machinery, no metrics nobody acts on.
