# ADR 0001: Python 3.14 as the baseline

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

The sample should use the latest Python practical for the target runtimes: Foundry hosted agents (our own container image) and Azure Functions Flex Consumption (the MCP server).

On 2026-10-27, Python 3.15.1 is the newest release. Our dependencies were checked by resolving with `uv pip compile --only-binary :all:`:

| Python | Result |
|---|---|
| 3.15 | `agent-framework` falls back to an old beta (`1.0.0b251120`). The current `agent-framework-core>=1.22` needs `pyyaml>=6.0`, which has no 3.15 wheels yet, so it would have to build from source. |
| 3.14 | Everything resolves from wheels: `agent-framework 1.22.0`, `azure-ai-agentserver-responses 2.3.0`, `azure-ai-projects 2.7.0`, `microsoft-opentelemetry 1.5.0`. |

Azure Functions supports Python 3.14 as **GA** on Flex Consumption. Python 3.15 is **preview** only.

## Decision

Use **Python 3.14** everywhere (`requires-python = ">=3.14,<3.15"`, `.python-version`, container base image, Functions runtime).

## Consequences

- One interpreter version across agent, MCP server, CLI and CI.
- Revisit once PyYAML ships 3.15 wheels and Functions reaches GA for 3.15. The upgrade is a one-line change plus a re-lock.
