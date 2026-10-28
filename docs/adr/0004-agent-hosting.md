# ADR 0004: Foundry hosted agents with Agent Framework and toolboxes

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

The platform needs to run agents written in code (the RCA agent has a strict output schema, deterministic episode capture and custom middleware), give them governed access to models and tools, and stay close to what an enterprise platform team can operate. Options considered:

- **Foundry prompt agents:** fully managed, but no room for our own middleware (episode capture) or code-level control of the run.
- **Self-hosted (Container Apps or AKS):** full control, but the platform then owns scaling, identity per agent, session management and the agent endpoint.
- **Foundry hosted agents:** our container (Responses protocol) on Foundry-managed compute, with an agent identity, sessions, an endpoint and traces provided by Foundry.

## Decision

- Agents are **Foundry hosted agents** built with **Microsoft Agent Framework**, served by `agent_framework_foundry_hosting.ResponsesHostServer`, deployed as containers built remotely in ACR by azd (`azure.ai.agent` service).
- The platform harness (`cs-platform`) is a library inside each agent's image, not a separate service: specs, middleware and stores are shared code.
- Tools come from a **Foundry toolbox**: one MCP endpoint per tool set, with credentials held in project connections (MCP server key, Entra for AI Search). Agents never see tool secrets.
- The hosted agent is **injected into the platform's virtual network**, so it reaches private data stores (ADR 0003).

## Consequences

- Each agent version gets its own Entra agent identity; access to platform data (Cosmos DB) is granted after deployment (`grant-agent` hook), because the identity doesn't exist before.
- Hosted agents, toolboxes and the azd extensions are in preview; versions are pinned (`requiredVersions` in `azure.yaml`, minimum versions in `pyproject.toml`).
- Deploy-time-only failures exist that local runs can't show (signature inspection at startup, packages only the hosted path imports). The Dockerfile imports the entry point at build time, and `csai eval --target hosted` checks what's live.
- Cloud evaluations published to Foundry need capability hosts in a network-injected project; the code-based gate doesn't depend on them.
- The agent endpoint stays public (Entra-protected) in this preview, even with network injection.
