# Candidate Azure Services: CS AI Platform

- **Purpose:** Exploration input for building a sample on Azure services and solutions that could fit the scenario below. This is not an architecture decision.
- **Sources:** Microsoft Learn (Foundry Agent Service, Agent Framework docs).
- **Compiled:** 27 October 2026.

## Scenario

A **customer support (CS) organization** services complex industrial equipment in the field. It has promising diagnostic agent prototypes, but no repeatable way to run them in production. The goal is a **minimum viable CS AI platform** that turns those prototypes into production-grade agents. One **root-cause analysis (RCA) workflow for field engineers** validates the platform.

**What's being built:**

- **Shared agent harness and orchestration.** Existing diagnostic agents are put into production, not rebuilt.
- **An RCA workflow for field engineers.** It pulls evidence from machine telemetry and event logs, error-code references, service logbooks, diagnostic knowledge bases and historical cases, then returns ranked root-cause hypotheses with the evidence behind them.
- **An evaluation pipeline.** This covers a case manifest, a scorecard, an evaluation dataset and regression testing.
- **Observability:** telemetry, tracing and usage metrics before a pilot.
- **A governed feedback loop.** Record each diagnostic episode, propose improvements, require a subject-matter expert (SME) to approve them, then replay cases to check the result.
- **A repeatable path for developers** to take prototypes to production (IaC, CI/CD, dev experience).
- **Room to add** further CS workflows (e.g. action planning, repair and recovery) later.

**Typical constraints that matter for service choices:**

- Everything runs in the organization's own Azure tenant.
- Services often need **internal approval**, so reusing existing IaC and approved components is preferred.
- Data residency rules may apply, and diagnostic data is sensitive.
- More than one model provider may be in play.
- Some components may need to run **at the edge**, close to the equipment.

## Azure services worth exploring

Priority means priority for the sample: **H** is core to the MVP story, **M** is likely useful, **L** is optional or later.

| Area | Azure service | Why it's relevant here | Sample priority |
|---|---|---|---|
| **Agent platform** | **Microsoft Foundry** (projects, model catalog) | One place for models, agents, evaluation and tracing; the natural agentic foundation. | H |
| | **Foundry Agent Service: hosted agents** | Runs Agent Framework code in containers with a managed endpoint, autoscaling, an Entra identity per agent and built-in tracing. A natural home for the harness and the RCA agent. | H |
| | **Microsoft Agent Framework (MAF)** | Handles multi-agent workflows such as evidence gathering, then hypothesis ranking, then action. Emits OpenTelemetry. | H |
| | **Foundry Toolboxes / MCP** | Wraps the diagnostic tools (telemetry, event logs, error codes, knowledge bases) once as MCP tools and shares them across agents with central auth and versioning. Fits the "reusable platform" goal. | H |
| | **Foundry Models: Azure OpenAI and partner models (e.g. Mistral)** | Model choice per task, and the ability to compare providers on the same evaluation set. | H |
| | **Microsoft Discovery** | Worth a look if the RCA work leans toward scientific reasoning. | L |
| **Knowledge and retrieval** | **Azure AI Search / Foundry IQ** | Hybrid and vector retrieval over logbooks, historical cases, diagnostic content and error-code mappings, so hypotheses come with evidence. | H |
| | **Azure Content Understanding / Document Intelligence** | Extracts text and structure from logbooks, PDFs and email threads during ingestion. | M |
| | **Azure Cosmos DB** | Stores diagnostic episodes (reasoning, evidence, hypotheses, expert corrections), agent session state and feedback. Supports vector search. | H |
| | **Azure Data Explorer / Fabric Real-Time Intelligence** | Fast queries over machine telemetry and event logs (time series) that agents call as tools. | M |
| | **Microsoft Fabric / OneLake** | Analytics layer for episode data, KPI baselines and value-realization reporting. Fabric IQ is available as an agent tool. | M |
| **Evaluation and feedback loop** | **Foundry Evaluations** (+ MAF `FoundryEvals`) | Evaluation pipeline and dataset with built-in evaluators plus custom RCA rubrics, run on datasets or production traces. | H |
| | **Foundry agent optimizer** (preview) | Proposes improved instructions and skills from evaluations. Lines up with the "governed proposals" outer loop, but the SME gate still applies. | M |
| | **Azure Logic Apps / Durable Functions** | Runs the SME approval workflow: proposal, review, approve, replay validation, promote. | M |
| **Observability** | **Application Insights / Azure Monitor** (+ Foundry tracing) | End-to-end traces of model calls, tool calls and decisions, plus dashboards. Required before a pilot. | H |
| | **Log Analytics** | Central log store for KQL queries and alerts. | H |
| **Security and governance** | **Microsoft Entra ID / Entra Agent ID** | Each agent gets its own identity. On-behalf-of access to diagnostic data keeps the field engineer's own permissions. | H |
| | **Azure AI Content Safety / Foundry guardrails** | Protects against prompt injection, including injected instructions inside logbooks or emails, and filters unsafe output. Supports a responsible-AI review. | H |
| | **Azure Key Vault, Private Link / VNet integration** | Secrets handling and network isolation for sensitive data and data residency. | H |
| | **Microsoft Purview** | Data classification, lineage and AI-interaction governance for sensitive diagnostic data. | M |
| | **Microsoft Defender for Cloud (AI threat protection)** | Security posture checks and threat detection on AI workloads. | L |
| **Integration and APIs** | **Azure API Management (AI gateway)** | One governed entry point for models and tools: token limits, load balancing across models, auth, usage metrics per use case. Key to onboarding future use cases. | H |
| | **Azure Event Grid / Service Bus** | Event-driven triggers, such as a machine-down event starting an RCA run, and loose coupling with existing systems. | M |
| | **Azure Functions** | Lightweight custom tools and MCP servers in front of legacy diagnostic APIs. | M |
| **Hosting and runtime** | **Azure Container Apps** | Hosts custom tool services, the UI back end and MCP servers if Foundry hosted agents don't fit the approved stack. | M |
| | **Azure Kubernetes Service (AKS)** | Fallback if the organization standardizes on Kubernetes. | L |
| | **Azure Arc / Foundry Local** | On-prem or edge inference when data can't leave the site. | L |
| **User experience** | **Copilot Studio / Microsoft Teams / M365 Copilot publishing** | A fast channel to field engineers by publishing a Foundry agent to Teams or Copilot. | M |
| | **Azure Static Web Apps / App Service** | Custom field-engineer UI for showing evidence, giving feedback and approving or rejecting hypotheses. | M |
| **Developer path** | **GitHub + GitHub Actions + GitHub Copilot** | CI/CD with evaluation quality gates that fail the build when metrics regress. | H |
| | **Azure Developer CLI (azd) + Bicep/Terraform** | Repeatable templates for setting up and deploying an agent. Core to the "prototype to production" path. | H |
| | **Azure DevOps** | Used if the organization standardizes on it for backlog and pipelines. | L |

## Suggested minimal sample to explore first

1. A **Foundry project** with a chat model deployment.
2. An **Agent Framework RCA agent** deployed as a **hosted agent**.
3. Mock diagnostic tools (telemetry, event logs, logbook search) exposed through a **Toolbox / MCP**, with logbook search grounded in **AI Search**.
4. Diagnostic episodes stored in **Cosmos DB**.
5. **Application Insights** tracing and a **Foundry evaluation** run against a small case manifest.
6. **APIM** as the gateway in front.
7. Everything deployed with **azd/Bicep**, and **GitHub Actions** blocking deploys when evaluation scores drop.

That covers the core platform outcomes (platform, use case, evaluation, observability, developer pathway) in one thin slice.

## Caveats

- Hosted agents, tracing and the agent optimizer are partly in preview. Organizations often require explicit acceptance of non-GA services, so flag them early.
- Every service has to be checked against the organization's approved-component list before it's used.
