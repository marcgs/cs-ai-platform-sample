# Plan: corporate readiness

The sample's main question is how Foundry fits a corporate setup, where data and endpoints must stay private. Today only the data stores are private. Foundry, the registry, AI Search and monitoring are public, and network injection with a public Foundry endpoint [isn't a documented setup](foundry-findings.md#network-injection-with-a-public-foundry-endpoint-isnt-a-documented-setup). This plan answers whether the sample works fully private, and records what breaks. The learning path (stage 3 onward) waits until it's done, because network injection is fixed when the Foundry account is created: work on the current account wouldn't carry over.

When this plan is done, its results go into the findings, the architecture, the README and an ADR, and this file is deleted.

## Rules

- **Docs first.** Follow Microsoft's documented setup: [networking options](https://learn.microsoft.com/azure/foundry/agents/concepts/networking-options), [network isolation](https://learn.microsoft.com/azure/foundry/how-to/configure-private-link), [toolbox network isolation](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox-network-isolation) and the private-network templates (15 and 19 in [foundry-samples](https://github.com/microsoft-foundry/foundry-samples/tree/main/infrastructure/infrastructure-setup-bicep)). Take ideas from the templates; don't copy them in.
- **Findings for everything.** Every failure, workaround and doc inconsistency goes into [Foundry findings](foundry-findings.md), with the date checked. Update existing entries rather than adding near-duplicates.
- **Both modes stay.** Private networking is a Bicep parameter, not a replacement. The public mode stays the default until step 6 decides otherwise.
- **The current environment stays as it is** until step 6, except for step 1's approved agent deployment. The private one is a new azd environment.
- **Approvals:** the hard rules in [AGENTS.md](../AGENTS.md) apply. Anything that changes Azure (provision, deploy, delete) or spends model tokens needs the user's approval with a USD estimate. Read-only checks (`az bicep build`, `what-if`, `show`/`list`) don't.
- **One step per pull request.** ruff, pyright and pytest green; staged diff checked for environment details.

## Steps

### 1. Package upgrades

Check whether newer releases fix the bugs we work around. Offline first, then one deployment to the current environment.

- Upgrade `agent-framework-foundry-hosting` (after 1.0.0b261015), `agent-framework-core` (1.24) and `mcp` (2.x), with the minimum versions in the `pyproject.toml` files that need them.
- Offline: the tests, including `test_real_mcp_session_propagates_episode_context_in_metadata`.
- Deployed, with approval (about $0.10): three invocations, then compare the hosted output's tool-call arguments and reported usage with the episodes.
- **Done when** the findings say for each of the [hosting adapter](foundry-findings.md#the-hosting-adapter-corrupts-tool-call-arguments-and-over-reports-tokens), [MCP session](foundry-findings.md#some-sdk-combinations-break-the-mcp-session) and [hosted streaming](foundry-findings.md#hosted-runs-stream-internally) entries whether it's fixed, and the upgrades are kept or reverted.

### 2. Documentation checks

No Azure changes, no cost.

- Region availability, in Sweden Central and North Europe, of everything the sample uses or the private setup needs: hosted agents, network injection, toolboxes, evaluation, trace annotations, private registry for hosted agents, and Azure Monitor Private Link Scope.
- The support terms when a GA service runs preview parts (the evaluation service with preview evaluators).
- Whether network injection and the private registry carry preview terms.
- Which Entra Agent ID features the agent identities would use, and their licensing.
- **Done when** the findings' appendix and "Not tested yet" are updated, and anything that blocks step 3 is raised with the user.

### 3. A private mode in Bicep

Add a parameter (for example `privateNetworking`, default `false`) that, when true:

- turns off public access on the Foundry account and adds its private endpoint and DNS zones;
- makes the container registry private (a private endpoint needs the Premium SKU);
- makes AI Search private, and gives it a shared private link to Foundry for its query vectorizer, which calls the embedding model;
- puts Application Insights and Log Analytics behind an Azure Monitor Private Link Scope;
- gives the MCP function app and the platform API private inbound access;
- tries evaluation storage **without** the trusted-services bypass of [ADR 0006](adr/0006-evaluation-storage-network-exception.md), keeping the bypass as a fallback;
- adds a way in for deployment and development: a small jump VM in its own subnet, with Entra sign-in and no public IP, reached through Azure Bastion (Developer SKU if available in the region, otherwise Basic). A self-hosted CI runner would use the same subnet later.

Also check whether `azure.yaml`, the hooks (`scripts/setup_platform.py`) and `csai` need changes when the data planes are private. For example, the toolbox hook and search seeding have to run from inside the network.

- **Done when** `az bicep build` passes, a `what-if` for a new environment with `privateNetworking=true` is reviewed with the user, the public mode's `what-if` shows no changes for the current environment, and the cost estimate below is confirmed with the Azure pricing calculator. Nothing is provisioned in this step.

### 4. Provision the private environment

With approval, the user provisions a new azd environment (for example `cs-platform-private`) with `privateNetworking=true`: first the network and the jump host, then `azd up` from the jump host. Record every manual step and every failure.

- **Done when** `azd up` completes from inside the network, or the blocking failure is in the findings with what was tried.

### 5. The sample end to end, privately

From the jump host, with approval for the tokens (about $1, plus any full runs approved under item 4):

1. `azd ai agent invoke` with a known case; the agent calls the toolbox's MCP tools and AI Search.
2. The episode is in Cosmos DB, and `csai episodes list` and `show` work.
3. The trace is in Application Insights and in the Foundry portal.
4. A 5-case evaluation run as a smoke test, checked with `rca_evals.gate`. It can't say anything about the [lost answers](foundry-findings.md#agent-target-evaluations-can-lose-responses-mid-run), which appeared after 30 or more rows and not in every full run. Comparing the two setups needs full 50-case runs in both, with the same package versions: propose the number of runs and their cost (about $1 each) for approval, or leave the cause open.
5. One trace annotation (Foundry's [human feedback](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-annotations), preview), as input for stage 3.
6. Whether content-safety moderation on knowledge searches still [fails](foundry-findings.md#content-safety-moderation-fails-on-every-knowledge-search).
7. The Foundry portal from the jump host: agents, playground, traces, evaluations.

- **Done when** each item works or has a finding, and the findings' "At a glance" and "Not tested yet" reflect the result.

### 6. Decide and close

- With the user: does private become the sample's main mode, and is the current environment deleted? Deleting it needs explicit approval.
- An ADR for the decision, updating ADR 0003 (and ADR 0006 if the bypass is no longer needed).
- README, architecture and walkthrough describe both modes and how to work in the private one.
- Delete this plan.

## Costs

Rough USD estimates for the private environment, on top of the current one while both run. Step 3 confirms them with the Azure pricing calculator.

| Item | Per day, about |
|---|---|
| Fixed costs of a second environment (AI Search Basic, Cosmos DB, Functions, existing private endpoints) | $5 |
| About eight more private endpoints, private DNS zones | $2 |
| Container registry Premium instead of Basic | $1.50 |
| Jump VM (small, deallocated when not in use) | $1 |
| Azure Bastion Basic (zero if the Developer SKU is available) | $4.50 |
| **Total while both environments run** | **$10–15** |

Model tokens: about $0.10 for step 1 and about $1 for step 5. A two-week spike costs roughly $150–200, less if the current environment is deleted early in step 6.

## Not in this plan

- Stage 3 onward of the learning path.
- Moving evaluation from `azd ai eval` to the SDK, replacing the hosting adapter, or Entra for the two function keys: candidates for after this plan, depending on step 1 and on what the private setup shows.
- An active CI pipeline.
