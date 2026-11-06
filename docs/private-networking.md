# Private networking

Set `AZURE_PRIVATE_NETWORKING=true` for a new environment; the default is `false`. Set `AZURE_LOCATION` explicitly; `AZURE_SEARCH_LOCATION` can differ.

## What is created

| Service | Private mode |
|---|---|
| Foundry | Public access off; endpoint with Cognitive Services, OpenAI and Foundry DNS zones |
| Registry | Premium; private endpoint; public access and trusted-service bypass off |
| AI Search | Private inbound; `openai_account` shared link for the query vectorizer |
| Monitoring | AMPLS covers Application Insights and Log Analytics; private ingestion/query |
| Functions | Private MCP and platform API endpoints, including SCM DNS |
| Evaluation storage | Bypass off; `AZURE_EVALUATION_TRUSTED_SERVICES_BYPASS=true` is the fallback |
| Access | Ubuntu B2s VM with SSH key sign-in, Bastion Developer, default outbound access; no public IPs |

Existing private storage and Cosmos stay unchanged: 11 VNet endpoints, one Search-managed endpoint and 14 DNS zones.

## Step 4 runbook (requires approval)

Use a new environment; these commands change Azure and incur the [plan's costs](plan-corporate-readiness.md#costs). France Central is proposed; check quota and capacity first.

1. On the workstation, bootstrap the network and access host with example values. The private key stays in `~/.ssh`, never in the repository; the portal's Bastion connection needs an RSA key in PEM format ([Learn](https://learn.microsoft.com/azure/bastion/bastion-connect-vm-ssh-linux#authentication-details)).
   ```bash
   ENV_NAME=cs-platform-private
   REGION=francecentral
   ssh-keygen -t rsa -b 4096 -m PEM -f ~/.ssh/cs-platform-jump
   az deployment sub create --name private-bootstrap --location "$REGION" \
     --template-file infra/bootstrap.bicep \
     --parameters environmentName="$ENV_NAME" location="$REGION" \
       adminPublicKey="$(cat ~/.ssh/cs-platform-jump.pub)"
   ```
   A governed subscription can attach NSGs to the subnets after the first run. When rerunning the bootstrap, pass them in so the deployment doesn't detach them, and check its what-if first.
   ```bash
   VNET=$(az network vnet list -g "rg-$ENV_NAME" --query "[0].name" -o tsv)
   nsg() { az network vnet subnet show -g "rg-$ENV_NAME" --vnet-name "$VNET" -n "$1" --query networkSecurityGroup.id -o tsv; }
   # add to the --parameters above:
   #   privateEndpointSubnetNetworkSecurityGroupId="$(nsg snet-private-endpoints)" \
   #   functionsSubnetNetworkSecurityGroupId="$(nsg snet-functions)" \
   #   agentsSubnetNetworkSecurityGroupId="$(nsg snet-agents)"
   ```
2. In the portal, open the VM → **Connect** → **Bastion**, choose **SSH Private Key from Local File**, user `jumpadmin`, and the private key from step 1. Install the tools, then reconnect so the `docker` group and `PATH` apply.
   ```bash
   sudo apt-get update && sudo apt-get install -y git docker.io
   sudo usermod -aG docker "$USER"
   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
   curl -fsSL https://aka.ms/install-azd.sh | bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. After reconnecting, sign in as the VM's managed identity, which the bootstrap made Owner of the subscription. Conditional Access can block user sign-ins from the VM (device code flow, location or device), and it doesn't apply to managed identities ([findings](foundry-findings.md#conditional-access-can-block-sign-in-on-the-jump-host)).
   ```bash
   azd extension install microsoft.foundry
   azd extension install azure.ai.evaluations
   git clone <this repository> && cd <its folder>
   az login --identity
   azd auth login --managed-identity
   docker info
   ```
   Then reuse the bootstrap's environment name, region and public key, and grant the data-plane roles to the identity.
   ```bash
   azd env new cs-platform-private
   azd env set AZURE_LOCATION francecentral
   azd env set AZURE_PRIVATE_NETWORKING true
   azd env set AZURE_JUMP_ADMIN_PUBLIC_KEY "$(cat ~/.ssh/authorized_keys)"
   azd env set AZURE_PRINCIPAL_ID "$(az vm list -g rg-cs-platform-private --query "[0].identity.principalId" -o tsv)"
   azd env set AZURE_PRINCIPAL_TYPE ServicePrincipal
   uv sync --all-packages
   ```
4. Preserve [external subnet NSGs](architecture.md#deployment) with the same IDs in `PRIVATE_ENDPOINT_SUBNET_NSG_ID`, `FUNCTIONS_SUBNET_NSG_ID` and `AGENTS_SUBNET_NSG_ID`; match `AZURE_VNET_ADDRESS_PREFIX` and `AZURE_JUMP_VM_SIZE` to bootstrap if nondefault, and set the agent's `docker.remoteBuild: false` in this VM checkout only.
5. Review the environment's what-if, then provision and deploy from the VM.
   ```bash
   azd up
   ```
6. If seeding stops, approve only Search's `foundry-vectorizer` request on the Foundry account; wait for Search's link to show `Approved` / `Succeeded`, then rerun `azd up`.
7. Check `seed-search` and `connect-tools` output, then read the private API.
   ```bash
   uv run csai episodes list
   ```

The access path is deliberately simple: Bastion Developer and default outbound access need no public IP, which governed subscriptions can block ([findings](foundry-findings.md#azure-policy-can-override-templates)). A corporate deployment would use its existing VPN or ExpressRoute instead. Step 5's private Foundry portal check needs a browser in the network, for example a small Windows VM opened through the same Bastion.

Hooks and `csai` use the Azure CLI and azd sign-ins, here the VM's identity. Anyone who can open the VM through Bastion acts with that identity's subscription Owner rights, which is acceptable for a sample subscription only. Deallocate the VM when unused; its disk and the private endpoints still cost money.

## Read-only validation, 2026-11-05

Both templates build without new warnings; ruff, pyright and 269 offline tests pass. No Azure changes were applied.

| What-if | Create | Modify | Delete | Other |
|---|---:|---:|---:|---|
| Current azd values, private mode off | 0 | 49 | 0 | 13 NoChange, 11 Ignore, 6 Unsupported |
| Untouched public baseline | 0 | 49 | 0 | 13 NoChange, 11 Ignore, 6 Unsupported |
| New placeholder environment, France Central, private mode on | 106 | 0 | 0 | 6 Unsupported |

No replacements. Public supported-resource results match the baseline, but its NSG, storage-rule and logging drift is real; see the [findings](foundry-findings.md#what-if-shows-changes-that-arent-real-and-hides-some-that-are) before reprovisioning.
