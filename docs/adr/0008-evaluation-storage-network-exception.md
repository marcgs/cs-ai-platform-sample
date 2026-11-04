# ADR 0008: A scoped network exception for evaluation storage

- **Status:** Accepted
- **Date:** 2026-11-02

## Context

Foundry evaluation stores its inputs and results in a storage account connected to the project. In this sample, storage is private ([ADR 0003](0003-private-data-stores.md)): public network access disabled, default deny, a private endpoint and Entra-only access.

With the evaluation storage set up that way, evaluation runs failed before they started. The project's managed identity got HTTP 403 `AuthorizationFailure` on `CreateContainer`, although it had Storage Blob Data Contributor. The evaluation service doesn't reach storage through the private endpoint. A resource-instance rule for the Foundry account alone didn't admit the project's requests either. Microsoft's private-network evaluation template (15a in the Foundry samples) allows trusted Azure services instead.

## Decision

- Evaluation data gets its **own storage account** (`infra/modules/evaluation-storage.bicep`), separate from the Functions' storage.
- It keeps public network access disabled, default deny, a private blob endpoint, no shared keys, and only the project identity's Blob Data Contributor role.
- Its firewall **allows trusted Azure services** (`bypass: AzureServices`) and has a resource-instance rule for the Foundry account.
- The project has a **capability host** (`infra/modules/foundry.bicep`), which network-injected projects need for evaluation.

## Consequences

- Foundry evaluation works in the network-injected project; a 50-row run with four judges completed.
- The account isn't private-link only: eligible trusted Azure services can reach it through its public service endpoint, even with public network access disabled. Access still needs an Entra identity with a data role; there's no anonymous or key access.
- Uploading evaluation datasets with the SDK's dataset upload still fails at this boundary; the project Files API works (see [Foundry findings](../foundry-findings.md)).
- The details of the failures and what was tried are in [Foundry findings](../foundry-findings.md#evaluation-in-a-private-network-project-needs-more-than-a-capability-host).
