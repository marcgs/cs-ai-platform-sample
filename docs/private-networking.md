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

1. On the workstation, bootstrap the network and access host with example values. The private key stays in `~/.ssh`, never in the repository.
   ```bash
   ENV_NAME=cs-platform-private
   REGION=francecentral
   ssh-keygen -t ed25519 -f ~/.ssh/cs-platform-jump
   az deployment sub create --name private-bootstrap --location "$REGION" \
     --template-file infra/bootstrap.bicep \
     --parameters environmentName="$ENV_NAME" location="$REGION" \
       adminPublicKey="$(cat ~/.ssh/cs-platform-jump.pub)"
   ```
2. In the portal, open the VM → **Connect** → **Bastion**, choose **SSH Private Key from Local File**, user `jumpadmin`, and the key from step 1. Install Git, Azure CLI, azd with its Foundry extension, uv and Docker, then clone `main`.
   ```bash
   az login --use-device-code
   azd auth login --use-device-code
   docker info
   ```
3. On the VM, select the bootstrap subscription and reuse its environment name, region and public key.
   ```bash
   azd env new cs-platform-private
   azd env set AZURE_LOCATION francecentral
   azd env set AZURE_PRIVATE_NETWORKING true
   azd env set AZURE_JUMP_ADMIN_PUBLIC_KEY "$(cat ~/.ssh/authorized_keys)"
   uv sync --all-packages
   ```
4. Preserve [external subnet NSGs](architecture.md#deployment); match `AZURE_VNET_ADDRESS_PREFIX` and `AZURE_JUMP_VM_SIZE` to bootstrap if nondefault, and set the agent's `docker.remoteBuild: false` in this VM checkout only.
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

Hooks and `csai` use developer credentials (`az login`, `azd auth login`). Deallocate the VM when unused; its disk and the private endpoints still cost money.

## Read-only validation, 2026-11-05

Both templates build without new warnings; ruff, pyright and 269 offline tests pass. No Azure changes were applied.

| What-if | Create | Modify | Delete | Other |
|---|---:|---:|---:|---|
| Current azd values, private mode off | 0 | 49 | 0 | 13 NoChange, 11 Ignore, 6 Unsupported |
| Untouched public baseline | 0 | 49 | 0 | 13 NoChange, 11 Ignore, 6 Unsupported |
| New placeholder environment, France Central, private mode on | 106 | 0 | 0 | 6 Unsupported |

No replacements. Public supported-resource results match the baseline, but its NSG, storage-rule and logging drift is real; see the [findings](foundry-findings.md#what-if-shows-changes-that-arent-real-and-hides-some-that-are) before reprovisioning.
