# Private networking

`AZURE_PRIVATE_NETWORKING=true` opts a **new environment** into private data planes.
The default is `false`; existing resource names, SKUs and network settings are unchanged.
Set `AZURE_LOCATION` explicitly. `AZURE_SEARCH_LOCATION` can select a different Search
region; private endpoints still belong to the VNet's region.

This is the implementation for corporate-readiness step 3, not evidence that the private
environment works end to end. Nothing was provisioned during this step.

## What is created

| Service | Private mode |
|---|---|
| Foundry | Public access disabled; one `account` endpoint, with Cognitive Services, OpenAI and Foundry private DNS zones. Existing agent subnet injection and project capability host retained. |
| Container registry | Premium, public access disabled, no trusted-services bypass; `registry` endpoint. The zone group registers login and regional data records in `privatelink.azurecr.io`. |
| AI Search | Basic, public access disabled; inbound `searchService` endpoint and outbound `openai_account` shared private link to the Foundry embedding model. Search's existing identity/role handles authentication. |
| Monitoring | AMPLS with ingestion and query `PrivateOnly`, both workspace and Application Insights scoped to it, and public ingestion/query disabled on both resources. One endpoint with all five required zones; the blob zone is shared with storage. Hosted tracing still needs its connection-string authentication. |
| Functions | MCP and platform API public inbound disabled, each with a `sites` endpoint. The zone group registers app and SCM records in the same web private DNS zone. Outbound Flex integration is unchanged. |
| Evaluation storage | Private blob endpoint, `bypass: None`, no resource-instance exception. `AZURE_EVALUATION_TRUSTED_SERVICES_BYPASS=true` restores the ADR 0006 exception **only in private mode**. Public mode always retains the existing exception. Evaluation without it is not proven. |
| Access | A dedicated jump subnet, Ubuntu 24.04 B2s VM (size configurable), system identity and `AADSSHLoginForLinux`, no VM public IP, password or configured SSH keys. VM Administrator Login for the deploying user and resource-group Reader. A service-principal deployer must separately arrange a human login role in Bicep. |
| Bastion and egress | Basic by default, or `AZURE_BASTION_SKU=Standard` for native clients. Dedicated `/26` Bastion subnet. SSH to the jump subnet allowed only from that subnet; other inbound denied. NAT provides explicit outbound access for sign-in, packages and image builds. Bastion and NAT each have a public IP; neither is a public VM login endpoint. |

There are **11 VNet private endpoints plus Search's managed shared endpoint**, and 14
private DNS zones. No firewall, VPN, runner or pipeline is added. Private inbound does
not mean deny-all internet egress: developer tooling and Entra still need public endpoints.
Agent state remains platform-managed as before; this is not a migration to Standard
bring-your-own conversation storage.

## Step 4 runbook (requires approval)

The commands below change Azure and incur the [plan's costs](plan-corporate-readiness.md#costs).
They were **not run** in step 3. Use a new environment, not the current account.

1. Agree the region, address space, quota, permissions and cost. **France Central** is
   the proposed spike region, not a template default. It supports hosted agents, batch
   and playground evaluation, semantic Search, and private networking. The current
   Search region page doesn't mark it as capacity-constrained. Sweden Central, North
   Europe, Germany West Central and West Europe are marked high-demand. Model listing
   advertises both required model versions with DataZoneStandard in France Central;
   this is not a reservation of model or Search capacity. B2s has no listed subscription
   restrictions there, and the Ubuntu image is available.
2. With approval, bootstrap only the network and access host from the workstation.
   Names below are examples, not identifiers from a deployed environment:

   ```bash
   ENV_NAME=cs-platform-private
   REGION=francecentral
   PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv)
   az deployment sub create --name private-bootstrap --location "$REGION" \
     --template-file infra/bootstrap.bicep \
     --parameters environmentName="$ENV_NAME" location="$REGION" \
       principalId="$PRINCIPAL_ID" bastionSku=Basic
   ```

   For another address space, VM size or Bastion SKU, pass the corresponding
   `vnetAddressPrefix`, `jumpVmSize`, `bastionSku` parameter in **both phases**.
   Wait for the Entra extension to succeed. Use the VM's **Connect / Bastion /
   Microsoft Entra ID** portal option. Basic supports this browser SSH session.
   Native `az network bastion ssh --auth-type AAD` needs Standard; its tunneling
   property is enabled automatically when that SKU is selected. No local-key or
   password fallback is configured. What-if accepted this keyless VM shape, but
   guest provisioning and sign-in still need this first live check.
3. In the jump-host browser shell, install Git, Azure CLI, azd, its Foundry extension,
   uv and Docker Engine using their official installation instructions. Make sure
   the signed-in user can run `docker info`. Clone the repository and this branch.
   Tools are deliberately not installed by a root download-and-execute VM extension.
   Sign in with `az login --use-device-code` and `azd auth login --use-device-code`;
   use the same subscription and human principal as bootstrap. The VM's system
   identity is only for SSH, not for deployment.
4. Create local azd state **on the VM** with the same environment name and region:

   ```bash
   azd env new cs-platform-private
   azd env set AZURE_LOCATION francecentral
   azd env set AZURE_PRIVATE_NETWORKING true
   azd env set AZURE_BASTION_SKU Basic
   ```

   Select the bootstrap subscription when prompted. Keep local azd state on the VM;
   don't paste it into git or a PR. If using nondefaults, set
   `AZURE_VNET_ADDRESS_PREFIX` and `AZURE_JUMP_VM_SIZE` to the bootstrap values too.
   Inspect policy-added subnet NSGs after bootstrap.
   Preserve any associations using `PRIVATE_ENDPOINT_SUBNET_NSG_ID`,
   `FUNCTIONS_SUBNET_NSG_ID` and `AGENTS_SUBNET_NSG_ID` as described in the
   [architecture](architecture.md#deployment). Also review any policy-applied
   Bastion subnet rules against the [Bastion NSG requirements](https://learn.microsoft.com/azure/bastion/bastion-nsg).
   Don't accept a what-if that removes an externally attached NSG.
5. In **this VM checkout only**, change `services.rca-agent.docker.remoteBuild` in
   `azure.yaml` from `true` to `false`. Keep that local edit uncommitted. azd parses
   this field as a boolean, not an interpolated environment variable. The public
   checkout retains remote builds. Private ACR's default remote Tasks pool cannot
   push to the private registry; local Docker builds/pushes use the VM's network and
   the developer's AcrPush role. No paid dedicated build pool or public bypass is used.
6. Review `az deployment sub what-if` with the selected environment's parameters,
   then, with approval, run `azd up` from the VM. The main template reuses bootstrap's
   resource names. Search seeding will stop before any model calls until its shared
   link is approved. In the Foundry account's **Networking / Private endpoint
   connections**, identify the Search request for `foundry-vectorizer` using its
   request message, source and the Search **Shared Private Access** page. Approve
   **only that connection**, not every pending request. It is in a Microsoft-managed
   tenant, so its endpoint link itself isn't browsable. Wait for Search's link to
   report `Approved` and `Succeeded`, then rerun `azd up`. This is a manual resource-owner
   trust decision; the hook checks it but does not approve unknown connections.
7. Check the `seed-search` and `connect-tools` output. The former calls private
   OpenAI and Search; the latter publishes to the private Foundry project.
   `grant-agent` and function-key retrieval are ARM calls and need no routing change.
   The hooks and `csai` deliberately exclude managed-identity fallback so the jump
   VM's SSH identity doesn't shadow the signed-in developer. Run `csai` on the VM;
   its API URL and authentication don't change. Connection failures and 403s in
   private mode include a network/access hint, not an automatic public fallback.
8. Perform step 5's approved smoke tests. In particular test the **query vectorizer**,
   not just seeding: seeding calls the model directly from the VM, whereas query
   vectorization uses Search's shared link. Check evaluation storage with bypass
   off before considering the fallback. Private tracing is still preview.

The minimal Linux host and Basic browser SSH support deployment, not a desktop browser.
For step 5's private **Foundry portal** check, plan an approved client path separately:
for example Standard with an Entra native SSH tunnel and DNS-aware browser proxy,
or an existing VPN-connected workstation. Standard changes cost by $2.40/day.
Don't claim the portal works merely because CLI invocation works.

Deallocate the VM when unused; its disk, NAT, private endpoints, registry, Search and
Bastion continue to accrue charges. Deleting either environment requires separate approval.

## Read-only validation, 2026-11-05

`az bicep build --file infra/main.bicep` and the bootstrap build pass with no template
warnings. The CLI's available-Bicep-update notice was also present on the baseline.
Ruff check/format, pyright and all 269 offline tests pass.

Both subscription what-ifs used the active subscription without creating an azd
environment or resource group. Environment-specific parameter files and raw results
were kept outside the repository. No resource changes were applied.

| What-if | Create | Modify | Delete | Other |
|---|---:|---:|---:|---|
| Current azd values, `privateNetworking=false` | 0 | 49 | 0 | 13 NoChange, 11 Ignore, 6 Unsupported |
| Same current values, untouched baseline | 0 | 49 | 0 | 13 NoChange, 11 Ignore, 6 Unsupported |
| New placeholder environment, France Central, `privateNetworking=true`, bypass off | 106 | 0 | 0 | 6 Unsupported |

Every **supported-resource** current-environment result is byte-for-byte identical
to the baseline. The six unsupported dynamic role assignments differ only in their
unevaluated expressions; no resource replacement or deletion is reported.
The placeholder name derives a new resource group and new resource names; it isn't
an existing or reserved environment.

The public result is **not a clean no-op**, even before this change. Most deltas are
reference-expression expansion, read-only properties or server defaults. However,
the existing template would detach NSGs on all three original subnets when their
preservation parameters are empty. It also declares `Dedicated` for evaluation
diagnostic logs where the live setting is absent, changing the destination table mode.
It would remove one extra evaluation-storage resource-instance rule, while keeping
the trusted-services bypass. That rule's intended ownership needs review too.
Don't dismiss these as noise or reprovision the current environment without resolving
them. They are pre-existing, outside step 3's private-mode change. ARM what-if cannot
prove private DNS, role propagation, extension execution, Search capacity, model quota
or the runtime paths in step 5.

## Sources checked

Microsoft Learn pages and sample templates were read on 2026-11-05. Templates
[15](https://github.com/microsoft-foundry/foundry-samples/tree/main/infrastructure/infrastructure-setup-bicep/15-private-network-standard-agent-setup)
and [19](https://github.com/microsoft-foundry/foundry-samples/tree/main/infrastructure/infrastructure-setup-bicep/19-private-network-agent-tools)
informed the topology; they aren't copied into this repository.

| Setting | Reference |
|---|---|
| Foundry topology, capability host, private ACR project creation cutoff | [Networking options](https://learn.microsoft.com/azure/foundry/agents/concepts/networking-options), [private link](https://learn.microsoft.com/azure/foundry/how-to/configure-private-link), [VNet how-to](https://learn.microsoft.com/azure/foundry/agents/how-to/virtual-networks), [toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox-network-isolation) |
| All endpoint group IDs and DNS zones, including ACR data and web SCM records | [Private endpoint DNS table and footnotes](https://learn.microsoft.com/azure/private-link/private-endpoint-dns) |
| Foundry `2025-06-01`, ACR `2023-07-01`, Search `2025-05-01` | [Account schema](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2025-06-01/accounts), [registry schema](https://learn.microsoft.com/azure/templates/microsoft.containerregistry/2023-07-01/registries), [Search schema](https://learn.microsoft.com/azure/templates/microsoft.search/2025-05-01/searchservices) |
| Shared link group and approval lifecycle | [Shared private link](https://learn.microsoft.com/azure/search/search-indexer-howto-access-private), [2025-05-01 schema](https://learn.microsoft.com/azure/templates/microsoft.search/2025-05-01/searchservices/sharedprivatelinkresources) |
| AMPLS `2021-07-01-preview`, scopes, ingestion/query settings | [Monitor setup](https://learn.microsoft.com/azure/azure-monitor/fundamentals/private-link-configure), [scope schema](https://learn.microsoft.com/azure/templates/microsoft.insights/2021-07-01-preview/privatelinkscopes), [scoped resources](https://learn.microsoft.com/azure/templates/microsoft.insights/2021-07-01-preview/privatelinkscopes/scopedresources), [workspace `2023-09-01`](https://learn.microsoft.com/azure/templates/microsoft.operationalinsights/2023-09-01/workspaces), [Insights `2020-02-02`](https://learn.microsoft.com/azure/templates/microsoft.insights/2020-02-02/components) |
| Flex private inbound, storage bypass | [Functions networking](https://learn.microsoft.com/azure/azure-functions/functions-networking-options), [sites `2024-04-01`](https://learn.microsoft.com/azure/templates/microsoft.web/2024-04-01/sites), [storage `2023-05-01`](https://learn.microsoft.com/azure/templates/microsoft.storage/2023-05-01/storageaccounts) |
| Network resources `2024-05-01`; private DNS `2024-06-01` | [VNet](https://learn.microsoft.com/azure/templates/microsoft.network/2024-05-01/virtualnetworks), [endpoints](https://learn.microsoft.com/azure/templates/microsoft.network/2024-05-01/privateendpoints), [zone groups](https://learn.microsoft.com/azure/templates/microsoft.network/2024-05-01/privateendpoints/privatednszonegroups), [NAT](https://learn.microsoft.com/azure/templates/microsoft.network/2024-05-01/natgateways), [public IP](https://learn.microsoft.com/azure/templates/microsoft.network/2024-05-01/publicipaddresses), [NIC](https://learn.microsoft.com/azure/templates/microsoft.network/2024-05-01/networkinterfaces), [NSG](https://learn.microsoft.com/azure/templates/microsoft.network/2024-05-01/networksecuritygroups), [Bastion](https://learn.microsoft.com/azure/templates/microsoft.network/2024-05-01/bastionhosts), [DNS](https://learn.microsoft.com/azure/templates/microsoft.network/2024-06-01/privatednszones), [VNet links](https://learn.microsoft.com/azure/templates/microsoft.network/2024-06-01/privatednszones/virtualnetworklinks) |
| Jump host `2024-07-01`, Entra extension, Basic vs Standard | [VM](https://learn.microsoft.com/azure/templates/microsoft.compute/2024-07-01/virtualmachines), [extension](https://learn.microsoft.com/azure/templates/microsoft.compute/2024-07-01/virtualmachines/extensions), [Entra Linux](https://learn.microsoft.com/entra/identity/devices/howto-vm-sign-in-azure-ad-linux), [Bastion Entra](https://learn.microsoft.com/azure/bastion/bastion-entra-id-authentication), [SKU/regions](https://learn.microsoft.com/azure/bastion/bastion-sku-comparison), [explicit outbound](https://learn.microsoft.com/azure/virtual-network/ip-services/default-outbound-access) |
| New role IDs and assignment API | [VM Administrator Login `1c0163c0-47e6-4577-8991-ea5c82e286e4`](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/compute#virtual-machine-administrator-login), [Reader `acdd72a7-3385-48ef-bd42-f606fba81ae7`](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/general#reader), [assignments `2022-04-01`](https://learn.microsoft.com/azure/templates/microsoft.authorization/2022-04-01/roleassignments) |
| Retained role IDs (all checked, none changed) | [AI/Search](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/ai-machine-learning), [containers](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/containers), [Monitor](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/monitor), [storage](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles/storage), [Cosmos native roles](https://learn.microsoft.com/azure/cosmos-db/nosql/how-to-grant-data-plane-access) |
| Bootstrap resource group `2024-03-01` | [Resource group schema](https://learn.microsoft.com/azure/templates/microsoft.resources/2024-03-01/resourcegroups) |
| Local image build and private registry | [Foundry registry workflow](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-private-azure-container-registry), [ACR private endpoint and Tasks restriction](https://learn.microsoft.com/azure/container-registry/container-registry-private-endpoints) |
