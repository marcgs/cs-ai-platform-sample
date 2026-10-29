# ADR 0005: Bicep for all infrastructure, azd as the workflow

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

Setting up the platform on another machine or subscription should take one command. The resources span Foundry, networking, data stores and function apps; some setup can't be expressed as ARM resources (search index content, Foundry toolboxes, roles for identities created at deploy time).

## Decision

- **Bicep for every Azure resource**, in `infra/` (subscription scope, one resource group per azd environment). Modules per concern; role assignments next to the resources they protect.
- **azd** drives provisioning and deployment (`azure.yaml`): the Bicep provider for infrastructure, `function` hosts for the function apps, the `azure.ai.agent` host for hosted agents.
- **Hooks for the data-plane setup Bicep can't do**, in one idempotent script (`scripts/setup_platform.py`): seed the search index (`postprovision`), register the MCP connection and publish the toolbox (`postdeploy` of the MCP app, because its key exists only then), grant the agent identity its Cosmos DB role (`postdeploy` of the agent).
- Settings flow through the azd environment: Bicep outputs become environment values that `azure.yaml`, the hooks and `csai` read.
- Validate templates with `az bicep build` and `az deployment sub validate` (and `what-if` for changes) before `azd provision`.

## Consequences

- `azd up` creates the whole platform from an empty subscription in about 20 minutes; `azd down --purge` removes it.
- `azd down` also clears values such as `AZURE_LOCATION` from the environment; set them again before the next `azd up`.
- Toolbox and connections are created by the script rather than declared as `azure.ai.toolbox` / `azure.ai.connection` services, trading the declarative form for control over ordering (the key exists only after the MCP deploy) and idempotence.
- Function apps deploy prebuilt Linux wheels (no remote build): workspace packages aren't on a package index, and the locked versions are installed.
