# ADR 0008: A scoped evaluation-storage network exception

- **Status:** Accepted; bypass verified and publication completed, reporting acceptance pending
- **Date:** 2026-11-02

## Context

The evaluation service rejects pending-result upload before creating a run.
One approved reproduction, followed by a 12-minute diagnostic wait, produced
one storage HTTP 403: OAuth, CreateContainer, AuthorizationFailure, requested
by the Foundry project managed identity. The project already has Storage Blob
Data Contributor. This evidence supports repairing network admission first,
not adding blob-tag Owner permissions.

Storage has public network access disabled, default deny, bypass None and a
private blob endpoint. A private endpoint does not ensure that every managed
evaluation-service request uses it. Template 15a instead permits trusted
AzureServices traffic; its broader Owner grant is a separate difference.

The current [trusted-service list](https://learn.microsoft.com/azure/storage/common/storage-network-security-trusted-azure-services)
includes Foundry Tools under managed-identity access and recommends
resource-instance rules for specific resources. Its provider spelling is
`Microsoft.CognitiveService/accounts`; the deployed ARM type is
`Microsoft.CognitiveServices/accounts`. The [resource-instance guide](https://learn.microsoft.com/azure/storage/common/storage-network-security-resource-instances)
documents resource-ID/tenant rules and independent data-role requirements.
Neither explicitly establishes that a parent-account rule covers a
child-project identity. This is a verification boundary, not proven support
for the observed project request.

## Decision

- Prepare one resource-instance network rule for the existing Foundry account
  only, using its derived resource ID and the deployment tenant:

  ```bicep
  resourceAccessRules: [
    {
      resourceId: foundryAccountId
      tenantId: subscription().tenantId
    }
  ]
  ```

- Keep bypass None, public network access Disabled, default deny, private
  endpoint/DNS, keyless authentication and the project Contributor grant.
  Do not add account/user roles, conditional Owner, IP rules or broader sharing.
- Review the compiled declaration before one separately approved targeted
  network-rule write. Do not reprovision or recreate a capability host.
- Make one separately approved identical publication request from the saved
  measurement, preserving its original receipt and failed run. Correlate any
  further denial with scoped storage logs. Parent-rule effectiveness remains
  unverified until this check.
- Do not automatically fall back to AzureServices. If the narrower rule does
  not admit the project request, present the evidence and obtain a separate
  decision. Any later permission change must follow its own logged denial.
- If a setup aligned with 15a in both network and RBAC still fails, stop and
  prepare support-case evidence. Do not add publisher retry machinery.

The user approved Bicep preparation, one targeted account-only rule write and
one identical retry with the disclosed possible judge cost. This authorizes
neither a broader bypass nor an RBAC change.

The write executed once and readback verified its account/tenant rule, unchanged
network restrictions, private endpoint and effective role IDs. The approved
retry again received pending-result upload HTTP 403 before run creation.
The next scoped log correlation identifies the same project identity, OAuth,
CreateContainer and AuthorizationFailure. The rule was verified 76.8 seconds
before retry start. Control-plane acceptance did not establish admission for
this child-project request; no universal propagation or inheritance guarantee
is claimed.

## Approved follow-on

Change only bypass None to AzureServices, matching template 15a. Retain the
existing account-only rule, public access Disabled, default deny, private
endpoint and all current roles. The logged failure is still network-related,
not a permission mismatch. No Owner grant is part of this proposal.

This is broader than the preferred resource-instance exception. Current
trusted-service documentation identifies Foundry managed-identity access, and
the narrower observed attempt did not admit the project request. The exception
is intended to admit the managed evaluation service while retaining separate
Entra data authorization; it does not make storage anonymously accessible.
It does permit eligible trusted-service traffic over the public service endpoint
despite public access Disabled, so it is not a private-link-only design.

The user separately approved Bicep preparation, one targeted bypass write and
one more identical possibly judged request with the disclosed cost. No Owner
grant or other access change is authorized. A later logged permission mismatch needs its own decision;
if both template differences are aligned and publication still fails, stop
for support evidence rather than more publisher machinery.

The bypass-only write executed once and readback verified unchanged remaining
access settings, encryption and effective roles. After at least 90 seconds,
the one approved retry registered a new cloud run, in_progress with no rows
yet at the read-only check. No conditional Owner was needed to clear this
creation-time rejection. Later storage operations and evaluation completion
remain unverified; no successful portal/metric acceptance is claimed.

The publisher later reached its existing 900-second observation timeout, exit 2.
Read-only inspection finds the same run in_progress with no service error or
output items, and no scoped storage 403 since its start at the check. No new
run, broader role grant or network change follows from that timeout. Continue
observing the accepted run; completion remains outstanding.

The same observed run subsequently completed in 19m37.727s with 50 output rows
and zero errored, without conditional Owner or resubmission. This verifies a
completed publication after the network-only exception. Portal acceptance,
exact numeric fidelity and calibration pass-direction reporting remain
separate findings; no further network or role change is indicated by them.

## Consequences

This is an authenticated exception for a specific resource, not general public
access or anonymous blob access. It nevertheless permits qualifying traffic
through Storage's public service endpoint: do not describe it as
private-link-only. [Storage limitations](https://learn.microsoft.com/azure/storage/common/storage-network-security-limitations)
say trusted-service and resource-instance exceptions take precedence and can
remain effective when public network access is Disabled.

The narrower rule reduces network admission scope compared with AzureServices,
but may not cover the child-project identity. Network admission grants no data
permissions; Entra authorization remains separate. Successful container creation
would not establish later blob-tag permissions, completed judges or portal
acceptance. The approved attempt can consume roughly 680k mapped judge input
tokens plus hidden prompts, output/reasoning and runtime charges.
