# Onboarding an agent

How to put a new agent on the platform, using the RCA agent as the template. An agent brings its behavior (instructions, output schema, tools it needs, test cases); the platform brings everything else (model access, toolbox, episode capture, telemetry, hosting, deployment).

The example below adds a fictional `maintenance-planner` agent that turns a confirmed root cause into a repair plan.

## 1. Create the agent package

```text
agents/maintenance-planner/
  pyproject.toml                       # depends on cs-platform; workspace source
  Dockerfile                           # copy agents/rca/Dockerfile, change the package names
  src/maintenance_planner/
    agent.spec.yaml                    # name, version, description, instructions, tools, test cases
    instructions.md                    # how to work and the rules for the answer
    plan.py                            # Pydantic output schema (extra="forbid", all fields required)
    agent.py                           # create_agent(): build_agent(spec, client, store, tools, response_format)
    main.py                            # ResponsesHostServer(agent_factory).run()
  tests/
```

- **Spec and instructions.** Keep the investigation procedure explicit and name the tools, so you can check in its episodes that the agent actually uses them.
- **Output schema.** Use the shared `cs_platform.evidence.Evidence` for anything the agent claims from data, so its references can be checked against tool results.
- **Hosted entry point.** Copy `agents/rca/src/rca_agent/main.py`. Import the types used in `agent_factory`'s signature at runtime: the hosting server evaluates them (Python 3.14).
- **Offline test.** Use `cs_platform.testing.ScriptedChatClient` to run the real tool loop with scripted model turns, as in `agents/rca/tests/test_agent.py`.

Add the package to the root `pyproject.toml` (dependencies and `[tool.uv.sources]`) and run `uv sync --all-packages`.

## 2. Give it tools

- **Existing tools:** reuse the `diagnostics` toolbox; nothing to deploy.
- **New data source:** add a read-only tool server like `services/diagnostics-mcp` (an MCP server on Azure Functions), a `function-app.bicep` module instance and an azd service. Then add it to the toolbox in `scripts/setup_platform.py` (`toolbox_definition()`), or publish a separate toolbox for the agent.
- **Knowledge:** add an index (and seeding) next to `diagnostics-cases`, and an `azure_ai_search` entry in the toolbox.

Agents get tools only through a toolbox (`TOOLBOX_ENDPOINT`); a direct `DIAGNOSTICS_MCP_URL` is for local development.

## 3. Write its test cases

Give the agent a set of test cases with known answers, generated from synthetic data like `evals/rca` (see its [README](../evals/rca/README.md)): one line per case with the input and an answer key, reviewed like code. Follow the RCA evaluation design ([ADR 0007](adr/0007-foundry-evaluation-and-measured-gate.md)): Foundry calls the hosted agent, built-in judges report and code evaluators compare reports with the answer key. Define the new agent's applicability and gate criteria explicitly and measure its own baseline; `rca_evals.gate` and the RCA thresholds are specific to RCA.

To show the agent's reports readably in `csai episodes show`, add its output type and a renderer to `render_output()` in `cli/src/csai/app.py`.

## 4. Deploy it

Add an `azure.ai.agent` service to `azure.yaml`, copying `rca-agent`: the `prepackage` export hook, `docker` settings (context `../..`), `env` (`AZURE_AI_MODEL_DEPLOYMENT_NAME`, `TOOLBOX_ENDPOINT`, `COSMOS_*`, `PYTHONNOUSERSITE`) and the `postdeploy` hook that grants its identity the Cosmos DB role (`AZD_AGENT_SERVICE=<service> ... grant-agent`; azd records the identity as `AGENT_<SERVICE>_INSTANCE_IDENTITY_PRINCIPAL_ID`).

```bash
azd ai agent run maintenance-planner --start-command "uv run python -m maintenance_planner.main"   # try it locally first
azd ai agent invoke --local "…"
azd deploy maintenance-planner
azd ai agent invoke maintenance-planner "…"         # check what's live
```

## Checklist

- [ ] Spec, instructions and output schema; offline tests pass
- [ ] Tools reachable through a toolbox; no secrets in code or settings
- [ ] Test cases with answer keys, generated and reviewed like code
- [ ] Runs locally with `azd ai agent run … --start-command …`
- [ ] Deployed with azd; `azd ai agent invoke` works; episodes visible with `csai episodes list`
