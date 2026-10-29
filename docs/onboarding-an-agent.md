# Onboarding an agent

How to put a new agent on the platform, using the RCA agent as the template. An agent brings its behavior (instructions, output schema, tools it needs, eval cases); the platform brings everything else (model access, toolbox, episode capture, telemetry, evaluation, hosting, deployment).

The example below adds a fictional `maintenance-planner` agent that turns a confirmed root cause into a repair plan.

## 1. Create the agent package

```text
agents/maintenance-planner/
  pyproject.toml                       # depends on cs-platform; workspace source
  Dockerfile                           # copy agents/rca/Dockerfile, change the package names
  src/maintenance_planner/
    agent.spec.yaml                    # name, version, description, instructions, tools, eval suite
    instructions.md                    # how to work and the rules for the answer
    plan.py                            # Pydantic output schema (extra="forbid", all fields required)
    agent.py                           # create_agent(): build_agent(spec, client, store, tools, response_format)
    main.py                            # ResponsesHostServer(agent_factory).run()
  tests/
```

- **Spec and instructions.** Keep the investigation procedure explicit and name the tools; the eval's tool-coverage metric checks that the agent actually uses them.
- **Output schema.** Use the shared `cs_platform.evidence.Evidence` for anything the agent claims from data, so evaluators can verify refs.
- **Hosted entry point.** Copy `agents/rca/src/rca_agent/main.py`. Import the types used in `agent_factory`'s signature at runtime: the hosting server evaluates them (Python 3.14).
- **Offline test.** Use `cs_platform.testing.ScriptedChatClient` to run the real tool loop with scripted model turns, as in `agents/rca/tests/test_agent.py`.

Add the package to the root `pyproject.toml` (dependencies and `[tool.uv.sources]`) and run `uv sync --all-packages`.

## 2. Give it tools

- **Existing tools:** reuse the `diagnostics` toolbox; nothing to deploy.
- **New data source:** add a read-only tool server like `services/diagnostics-mcp` (an MCP server on Azure Functions), a `function-app.bicep` module instance and an azd service. Then add it to the toolbox in `scripts/setup_platform.py` (`toolbox_definition()`), or publish a separate toolbox for the agent.
- **Knowledge:** add an index (and seeding) next to `diagnostics-cases`, and an `azure_ai_search` entry in the toolbox.

Agents get tools only through a toolbox (`TOOLBOX_ENDPOINT`); a direct `DIAGNOSTICS_MCP_URL` is for local development.

## 3. Write the eval suite

```text
evals/maintenance-planner/
  pyproject.toml
  src/maintenance_planner_evals/
    __init__.py         # load_suite() -> EvalSuite.from_files(...)
    cases.jsonl         # {"id", "input", "expected": {...}} per line, reviewed like code
    thresholds.yaml     # minimums per metric
    evaluators.py       # plain functions: (EvalCase, RunOutput) -> {metric: 0..1}
```

Start with schema validity, the task outcome, evidence grounding and tool coverage. Set thresholds from a measured baseline, then check that a deliberately broken instruction fails the gate.

Register the agent in `cli/src/csai/targets.py` (`AGENTS`) with its azd service name, `create_agent`, output type, suite loader and a terminal renderer. `csai eval`, `csai diagnose` and `csai episodes show` then work for it.

## 4. Deploy it

Add an `azure.ai.agent` service to `azure.yaml`, copying `rca-agent`: the `prepackage` export hook, `docker` settings (context `../..`), `env` (`AZURE_AI_MODEL_DEPLOYMENT_NAME`, `TOOLBOX_ENDPOINT`, `COSMOS_*`, `PYTHONNOUSERSITE`) and the `postdeploy` hook that grants its identity the Cosmos DB role (`AZD_AGENT_SERVICE=<service> ... grant-agent`; azd records the identity as `AGENT_<SERVICE>_INSTANCE_IDENTITY_PRINCIPAL_ID`).

```bash
uv run csai eval maintenance-planner --target local    # gate before deploying
azd deploy maintenance-planner
uv run csai eval maintenance-planner --target hosted   # gate what's live
```

## Checklist

- [ ] Spec, instructions and output schema; offline tests pass
- [ ] Tools reachable through a toolbox; no secrets in code or settings
- [ ] Eval suite with thresholds from a baseline; a broken instruction fails it
- [ ] Registered in `csai`; `csai diagnose` works locally
- [ ] Deployed with azd; hosted eval passes; episodes visible with `csai episodes list`
