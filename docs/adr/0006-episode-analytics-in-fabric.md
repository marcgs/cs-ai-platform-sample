# ADR 0006: Offline episode analysis before optional Fabric mirroring

- **Status:** Proposed; Fabric deployment is not approved or verified
- **Date:** 2026-10-29

## Context

Episode analysis must work without changing the shared Azure environment. The
episode account is serverless, Entra-only and reachable through a private
endpoint. Synthetic episodes must remain separate from real episodes.

Fabric mirroring is an optional analytical copy, not a prerequisite for finding
recurring failures. Its network setup is more involved than adding a notebook.

## Decision

Implement analysis over exported JSONL first. Use the same input schema and
analysis code for a future Fabric notebook. Keep model classification explicit,
cached and separate from deterministic cleaning, aggregation and routing.

Do not provision a Fabric capacity, change Cosmos DB settings, register resource
providers, import episodes or grant access as part of the offline implementation.
Each step needs approval.

If Fabric exploration is approved:

1. Confirm tenant availability, region, capacity cost and a pause policy. Confirm
   serverless account compatibility for the actual account before proposing a
   backup migration. The general documentation alone is not account validation.
2. Plan a separate synthetic container and a guarded import mechanism through
   the platform API. Do not copy synthetic records into the real episode
   container.
3. Express Azure resources and roles in Bicep. Preserve `EnableServerless` when
   adding capabilities. Review build and subscription what-if output before any
   apply; explicitly identify irreversible changes.
4. Configure a dedicated gateway subnet of at least `/27`, delegated to
   `Microsoft.PowerPlatform/vnetaccesslinks`, private DNS access to Cosmos DB,
   and explicit outbound connectivity through a NAT gateway.
5. Configure continuous backup, `EnableFabricNetworkAclBypass` and the specific
   trusted workspace authorization while keeping public network access disabled.
   Treat migration to continuous backup as irreversible.
6. Create the gateway connection with supported OAuth authentication, then create
   the mirrored database through the Fabric REST API. The mirroring portal
   cannot select the gateway connection. Do not assume a managed identity is
   supported: the current mirroring limitations exclude it.
7. Mirror only the intended synthetic container. Run the notebook and compare
   its report with the local report on identical data before claiming parity.

The connection requires Cosmos DB `readMetadata` and `readAnalytics` data
actions. The private-network walkthrough also grants Data Contributor; review
that broader permission and its necessity before proposing assignments. Never
silently grant it outside Bicep.

## Consequences

- Offline analysis can be tested without Azure access or model traffic.
- Fabric capacity, NAT gateway and gateway footprint introduce ongoing cost.
  Continuous seven-day backup has no backup-storage charge, but restores cost
  money.
- The gateway is used for connection setup and testing. Ongoing replication runs
  in the Fabric Replicator service over an internal network; it does not traverse
  the private endpoint or the gateway. Trusted-workspace authorization is an
  explicit additional access path.
- Nested episode fields become JSON strings in the SQL analytics endpoint.
  Notebook loading must reconstruct the same typed records used locally.
- Fabric workspace permissions control the analytical copy independently of the
  source store. Its access policy must be reviewed separately.
- Until deployment and parity checks are approved and performed, this remains a
  design, not evidence that Fabric mirroring works in the deployed environment.

## Sources

Microsoft Learn, checked 2026-10-29:

- [Cosmos DB mirroring overview](https://learn.microsoft.com/en-us/fabric/mirroring/azure-cosmos-db)
- [Private-network setup](https://learn.microsoft.com/en-us/fabric/mirroring/azure-cosmos-db-private-network)
- [Mirroring limitations](https://learn.microsoft.com/en-us/fabric/mirroring/azure-cosmos-db-limitations)
- [Continuous backup](https://learn.microsoft.com/en-us/azure/cosmos-db/continuous-backup-restore-introduction)
- [Serverless accounts](https://learn.microsoft.com/en-us/azure/cosmos-db/serverless)
