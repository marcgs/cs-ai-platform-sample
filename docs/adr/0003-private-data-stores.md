# ADR 0003: Private data stores, public control and model endpoints

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

Governed subscriptions commonly enforce private networking through Azure Policy. In the subscription this sample was first deployed to, a policy with a `modify` effect sets public network access to Disabled on Storage accounts and Cosmos DB accounts, whatever the template says. With public templates, that broke two things:

- The Flex Consumption app couldn't reach its storage account, so the deployment package upload failed (403).
- Nothing outside a virtual network could read or write episodes in Cosmos DB, including the hosted agent.

A production platform would have this shape anyway, so the sample should deploy cleanly under such a policy rather than ask for an exemption.

Making every service private (Foundry, the registry, AI Search, Application Insights) would also force `azd up`, `azd deploy` and local agent runs to happen from inside the network, through a VPN, a jump host or self-hosted runners. That's too much for an exploration sample.

## Decision

- One virtual network with three subnets: private endpoints, Flex Consumption integration, and Foundry agent network injection (the last two delegated to `Microsoft.App/environments`).
- Storage (blob, queue, table) and Cosmos DB have public network access disabled and are reached through private endpoints with private DNS zones linked to the network.
- The function app uses VNet integration to reach its storage. Hosted agents are injected into the agent subnet to reach Cosmos DB.
- Foundry, the registry and AI Search stay public with Entra-only access, so developers can deploy and run agents from their own machines.
- The address space is a parameter (`vnetAddressPrefix`, default `10.40.0.0/16`) so it can be changed to avoid overlaps when peering.

## Consequences

- Local runs (`rca-local`) can't reach Cosmos DB; they keep episodes in memory. Reading episodes and attaching feedback from a developer machine goes through a platform endpoint, not directly to Cosmos DB.
- Agent network injection can only be set when the Foundry account is created. An environment created before this decision has to be recreated (`azd down --purge`, then `azd up`).
- With a hosted agent deployed, the agent subnet holds a service association link. Tear down by deleting and purging the Foundry account before the network; `azd down --purge` deletes the whole resource group.
- Four private endpoints and the private DNS zones add a small fixed monthly cost.
- Going fully private later means adding private endpoints for the remaining services and running deployments from inside the network (see the iteration 2 backlog).
