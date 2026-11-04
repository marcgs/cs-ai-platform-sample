# Iteration 5: evaluation the Foundry way

## Where this fits

From here on, the sample is brought into its final shape one stage at a time, in one thin end-to-end pass. Each stage gets one iteration, is done in its final shape before the next starts, and adds what it uncovers to [Foundry findings](foundry-findings.md).

| Stage | Iteration | Done when |
|---|---|---|
| 1. Infrastructure, hosted agent, toolbox | done (1–3) | `csai diagnose` works against the deployed agent |
| **2. Evaluation the Foundry way** | **5** | One command evaluates the hosted agent in Foundry, the gate is computed from its results, and our own evaluation harness is gone |
| 3. Episodes and expert feedback | 6 | An expert verdict is recorded on a hosted episode and visible |
| 4. Feedback becomes cases | 7 | A pull request adds reviewed cases to the Foundry evaluation dataset |
| 5. A learner proposes a change | 8 | A pull request changes the skill and its replay in Foundry is posted on it |
| 6. Release and check | 9 | The merged change runs as a new agent version, and its effect is measured |

Each stage starts from Foundry's documented way. The pages to start from, and what they mean for us:

| Stage | Microsoft Learn pages | What we have today |
|---|---|---|
| 1 | [Hosted agents](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents), [Host Agent Framework agents](https://learn.microsoft.com/azure/foundry/how-to/develop/framework-hosted-agents), [Use a toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent), [Author azure.yaml](https://learn.microsoft.com/azure/foundry/agents/how-to/author-azure-yaml) | Matches; check against the current pages when touched |
| 2 | [Evaluate a hosted agent](https://learn.microsoft.com/azure/foundry/observability/quickstarts/quickstart-evaluate-hosted-agent), [Evaluate agents](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluate-agent), [Dataset schema](https://learn.microsoft.com/azure/foundry/observability/how-to/evaluation-dataset-schema), [Custom evaluators](https://learn.microsoft.com/azure/foundry/concepts/evaluation-evaluators/custom-evaluators), [Get results](https://learn.microsoft.com/azure/foundry/observability/how-to/cloud-evaluation-results), [Compare results](https://learn.microsoft.com/azure/foundry/how-to/evaluate-results) | Our own harness; this iteration replaces it |
| 3 | [Tracing](https://learn.microsoft.com/azure/foundry/observability/concepts/trace-agent-concept), [Annotate traces with human feedback](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-annotations), [Log end user feedback](https://learn.microsoft.com/azure/foundry/observability/how-to/log-end-user-feedback) | Our own episode store in Cosmos DB and a feedback API |
| 4 | [Convert traces into evaluation datasets](https://learn.microsoft.com/azure/foundry/observability/how-to/traces-to-dataset), [Cluster analysis](https://learn.microsoft.com/azure/foundry/observability/how-to/cluster-analysis), [Human evaluation](https://learn.microsoft.com/azure/foundry/observability/how-to/human-evaluation) | Our own clustering and case proposals |
| 5 | [Agent optimizer](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-optimizer-overview), [Make your agent optimizer-ready](https://learn.microsoft.com/azure/foundry/agents/how-to/make-agent-optimizer-ready), [Optimize instructions, skills, tools and models](https://learn.microsoft.com/azure/foundry/agents/how-to/optimize-agent-targets) | Nothing yet; a coding agent was the plan |
| 6 | [Promote releases and roll out versions](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-production), [Manage lifecycle](https://learn.microsoft.com/azure/foundry/agents/how-to/manage-hosted-agent), [CI/CD](https://learn.microsoft.com/azure/foundry/agents/how-to/set-up-ci-cd-cli) | Nothing yet |

Stages 5 and 6 stay thin: one cluster, one proposal, one release. The aim is to see every stage work and where it breaks, not to make the learner good.

Rules for every iteration: official documentation first ([AGENTS.md](../AGENTS.md#official-documentation-first)): each item starts from the Microsoft Learn page that covers it, follows it, and departs from it only for a gap recorded in the findings. Also the hard rules in AGENTS.md, and nothing from a later stage.

## Goal

Evaluating the agent looks like Microsoft's [hosted agent evaluation quickstart](https://learn.microsoft.com/azure/foundry/observability/quickstarts/quickstart-evaluate-hosted-agent), plus only what our gate needs:

- one `eval.yaml` and one `azd` command;
- Foundry calls the hosted agent and scores it with the four built-in judges and our gate metrics;
- a short script turns the run's results into the gate decision;
- the local runner, the publisher and the spike scripts are deleted, and the docs describe the new flow.

## Scope

In order. Each item is one pull request.

| # | Item | Backlog | Done when |
|---|---|---|---|
| 1 | Fix the hosting adapter | Q21 | Hosted tool-call arguments are one JSON object each and reported usage matches the episode's usage, shown on a few cases after deployment |
| 2 | One recipe, one command | Q22 | `azd ai eval` (or `azd ai agent eval`) with `evals/rca/eval.yaml` runs the hosted agent on the cases and scores them, without extra scripts except where a recorded gap needs one |
| 3 | Smaller judge inputs | Q24 | Judge tokens per case measured before and after; dataset rows hold only what an evaluator reads; no search URLs |
| 4 | Gate from Foundry results | Q23 | `csai gate <run>` reads a Foundry run and prints the three means and the injection check against the thresholds, exiting non-zero on failure; checked against the retained 50-case scoreboard (0.78 / 0.75 / 0.92, injection 4/4) |
| 5 | First Foundry measurement | Q25 (first run) | One 50-case run of the deployed agent with all evaluators, gated by item 4, recorded in the eval guide |
| 6 | Retire our harness | Q27 | The code and docs below are gone, and README, architecture, walkthrough and the eval guide describe only the new flow |

### Item 2: the single-run attempt

Try one run first: the agent target plus judges plus our code evaluators. Timebox: one day. If it doesn't work, use two runs (the agent run, then scoring of its saved outputs, with tool-call arguments converted for the judges) and record why in the findings. Either way it's one command for the user.

Gate metrics run as code evaluators with the answer key in the dataset. Metrics that apply to only some cases (`decisive_evidence_recall`, `injection_resisted`) need "doesn't apply". Try a labeled neutral score or an endpoint evaluator's `skipped` within the same timebox; otherwise they get one evaluation each over their applicable cases. Reporting metrics that apply to every case come along; sparse reporting metrics are dropped. Judges report and don't gate.

Names follow ADR 0010: evaluation `rca-quality`, runs named by agent version and date, one evaluator name per metric, dataset `rca-cases` versioned with the cases.

### Item 6: what goes

| Goes | Stays |
|---|---|
| The local runner and reporting in `cs_platform` (`evals.py` runner parts, `eval_runs.py`, `eval_reporting.py`, `retry.py`) | The case and answer-key types, moved next to the cases if `cs_platform` no longer needs them |
| `csai eval`, `csai eval publish`, receipts and the Foundry publisher (`eval_cli.py`, `eval_publish.py`, `eval_receipts.py`, `foundry.py`) | `csai diagnose`, `csai episodes` and the case tooling (`csai cases`) |
| The spike scripts in `evals/rca/foundry/` that the final recipe doesn't use | The scoring functions, now Foundry code evaluators, and their tests |
| ADR 0007's retry machinery, marked superseded | The cases, the case generator, `thresholds.yaml` |

Check what still imports each module before deleting it. Iteration and spike records stay in git history; tag the commit before item 6 as `before-foundry-eval`.

## Approvals needed

- **A deployment** of the agent with the adapter fix (item 1). The user runs or approves `azd deploy`.
- **Model tokens.** Estimated at measured rates (about 25k agent and up to 22k judge tokens per case, less after item 3):

  | Work | Tokens, about |
  |---|---|
  | Item 1: checking the fix on 5 cases | 0.25M |
  | Item 2: development runs on 5–10 cases | 0.5M |
  | Item 3: before/after on 5 cases | 0.2M |
  | Item 5: one 50-case run | 1.5–2.4M |
  | **Total** | **2.5–3.4M** |

  Each item reports its actual usage. Stop and ask before exceeding an item's estimate by more than half.
- **Foundry project writes** (datasets, evaluator versions, evaluations, runs) are approved for this iteration. Deleting anything still needs the user's approval, including stage 2 of the spike cleanup once item 5 has run.

## Not in this iteration

- The three-repeat baseline and run comparison (Q25's rest, Q17): after item 5, with its own budget.
- Agent Framework `evaluate_agent` locally (Q26).
- The search moderation failure (S16), unless it blocks item 2.
- Feedback, cases from feedback and the learner: stages 3 to 5.
- Infrastructure or network changes. If one turns out to be needed, stop and ask.

## Gates

Every pull request: ruff, pyright and pytest green; the staged diff checked against the hard rules; new limitations added to the findings. Commit on a feature branch; the user pushes and merges.
