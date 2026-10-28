"""Platform setup steps that run as azd hooks, after Bicep has created the resources.

    uv run python scripts/setup_platform.py seed-search     # postprovision
    uv run python scripts/setup_platform.py connect-tools   # postdeploy of diagnostics-mcp
    uv run python scripts/setup_platform.py grant-agent     # postdeploy of rca-agent

Each step is idempotent and reads its inputs from the azd environment (azd passes it to
hooks as environment variables). Authentication uses the developer's azd/Azure CLI sign-in.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from typing import TYPE_CHECKING, Any

import httpx
from azure.ai.projects import AIProjectClient
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import OpenAI

from diagnostics_domain.dataset import load_seed

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from diagnostics_domain.models import HistoricalCase

ARM = "https://management.azure.com"
ARM_SCOPE = f"{ARM}/.default"
SEARCH_SCOPE = "https://search.azure.com/.default"
AI_SCOPE = "https://ai.azure.com/.default"
SEARCH_API_VERSION = "2024-07-01"
CONNECTIONS_API_VERSION = "2025-04-01-preview"
EMBEDDING_DIMENSIONS = 3072  # text-embedding-3-large

MCP_CONNECTION = "diagnostics-mcp"
TOOLBOX = "diagnostics"
CASE_URL = "https://cases.diagnostics.example/{id}"


class SetupError(RuntimeError):
    pass


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SetupError(
            f"{name} isn't set; run through azd or export it from `azd env get-values`"
        )
    return value


def batched[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class Arm:
    """Minimal Azure Resource Manager client for the few control-plane calls needed here."""

    def __init__(self, credential: DefaultAzureCredential) -> None:
        self._credential = credential

    def request(
        self, method: str, path: str, api_version: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        token = self._credential.get_token(ARM_SCOPE).token
        response = httpx.request(
            method,
            f"{ARM}{path}",
            params={"api-version": api_version},
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=60,
        )
        if response.is_error:
            raise SetupError(f"{method} {path} failed ({response.status_code}): {response.text}")
        return response.json() if response.content else {}


# --- seed-search -----------------------------------------------------------------------------


def case_document(case: HistoricalCase, failure_mode_names: dict[str, str]) -> dict[str, Any]:
    mode = case.confirmed_failure_mode
    return {
        "id": case.id,
        "title": f"{case.id} on {case.machine_id}: {failure_mode_names[mode]}",
        "content": (
            f"Symptom: {case.symptom}\n"
            f"Confirmed failure mode: {mode} ({failure_mode_names[mode]})\n"
            f"Resolution: {case.resolution}\n"
            f"Downtime: {case.downtime_hours:.1f} hours"
        ),
        "machine_id": case.machine_id,
        "failure_mode_id": mode,
        "opened": case.opened.isoformat(),
        "url": CASE_URL.format(id=case.id),
    }


def index_definition(name: str, openai_endpoint: str, embedding_deployment: str) -> dict[str, Any]:
    """Hybrid index: keyword + semantic ranking + vectors, vectorized by Foundry at query time."""
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "title", "type": "Edm.String", "searchable": True},
            {"name": "content", "type": "Edm.String", "searchable": True},
            {"name": "machine_id", "type": "Edm.String", "filterable": True},
            {
                "name": "failure_mode_id",
                "type": "Edm.String",
                "filterable": True,
                "facetable": True,
            },
            {"name": "opened", "type": "Edm.DateTimeOffset", "filterable": True, "sortable": True},
            {"name": "url", "type": "Edm.String"},
            {
                "name": "content_vector",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "retrievable": False,
                "dimensions": EMBEDDING_DIMENSIONS,
                "vectorSearchProfile": "default",
            },
        ],
        "vectorSearch": {
            "algorithms": [{"name": "hnsw", "kind": "hnsw"}],
            "vectorizers": [
                {
                    "name": "foundry",
                    "kind": "azureOpenAI",
                    # No key: the search service's managed identity calls the deployment.
                    "azureOpenAIParameters": {
                        "resourceUri": openai_endpoint.rstrip("/"),
                        "deploymentId": embedding_deployment,
                        "modelName": embedding_deployment,
                    },
                }
            ],
            "profiles": [{"name": "default", "algorithm": "hnsw", "vectorizer": "foundry"}],
        },
        "semantic": {
            "defaultConfiguration": "default",
            "configurations": [
                {
                    "name": "default",
                    "prioritizedFields": {
                        "titleField": {"fieldName": "title"},
                        "prioritizedContentFields": [{"fieldName": "content"}],
                    },
                }
            ],
        },
    }


def seed_search(credential: DefaultAzureCredential) -> None:
    search_endpoint = env("AZURE_SEARCH_ENDPOINT")
    index_name = env("AZURE_SEARCH_INDEX_NAME")
    embedding_deployment = env("FOUNDRY_EMBEDDING_DEPLOYMENT_NAME")

    dataset = load_seed()
    names = {mode.id: mode.name for mode in dataset.failure_modes}
    documents = [case_document(case, names) for case in dataset.historical_cases]

    openai = OpenAI(
        base_url=f"{env('AZURE_OPENAI_ENDPOINT').rstrip('/')}/openai/v1/",
        api_key=get_bearer_token_provider(credential, AI_SCOPE),
    )
    for batch in batched(documents, 16):
        result = openai.embeddings.create(
            model=embedding_deployment, input=[doc["content"] for doc in batch]
        )
        for doc, item in zip(batch, result.data, strict=True):
            doc["content_vector"] = item.embedding

    token = credential.get_token(SEARCH_SCOPE).token
    with httpx.Client(
        base_url=search_endpoint,
        params={"api-version": SEARCH_API_VERSION},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    ) as search:
        definition = index_definition(
            index_name, env("AZURE_OPENAI_ENDPOINT"), embedding_deployment
        )
        search.put(f"/indexes('{index_name}')", json=definition).raise_for_status()
        actions = [{"@search.action": "mergeOrUpload", **doc} for doc in documents]
        search.post(
            f"/indexes('{index_name}')/docs/index", json={"value": actions}
        ).raise_for_status()
    print(f"Index {index_name}: {len(documents)} historical cases")


# --- connect-tools ---------------------------------------------------------------------------


def connect_mcp_server(arm: Arm) -> None:
    """Project connection holding the MCP server's function key, so no client ever sees it."""
    app_id = (
        f"/subscriptions/{env('AZURE_SUBSCRIPTION_ID')}/resourceGroups/{env('AZURE_RESOURCE_GROUP')}"
        f"/providers/Microsoft.Web/sites/{env('DIAGNOSTICS_MCP_FUNCTION_NAME')}"
    )
    keys = arm.request("POST", f"{app_id}/host/default/listkeys", "2024-04-01")
    key = keys.get("systemKeys", {}).get("mcp_extension")
    if not key:
        raise SetupError("The mcp_extension system key doesn't exist yet; is the MCP app deployed?")
    arm.request(
        "PUT",
        f"{env('AZURE_AI_PROJECT_ID')}/connections/{MCP_CONNECTION}",
        CONNECTIONS_API_VERSION,
        {
            "properties": {
                "category": "RemoteTool",
                "target": env("DIAGNOSTICS_MCP_ENDPOINT"),
                "authType": "CustomKeys",
                "credentials": {"keys": {"x-functions-key": key}},
                "isSharedToAll": True,
            }
        },
    )
    print(f"Connection {MCP_CONNECTION}: {env('DIAGNOSTICS_MCP_ENDPOINT')}")


def toolbox_definition() -> dict[str, Any]:
    return {
        "description": "Diagnostic tools: machine data over MCP and historical cases in AI Search.",
        "tools": [
            {
                "type": "mcp",
                "server_label": "diagnostics",
                "server_url": env("DIAGNOSTICS_MCP_ENDPOINT"),
                "project_connection_id": MCP_CONNECTION,
                "require_approval": "never",
            },
            {
                "type": "azure_ai_search",
                "azure_ai_search": {
                    "indexes": [
                        {
                            "project_connection_id": env("AZURE_SEARCH_CONNECTION_ID"),
                            "index_name": env("AZURE_SEARCH_INDEX_NAME"),
                            "query_type": "vector_semantic_hybrid",
                            "top_k": 5,
                        }
                    ]
                },
            },
        ],
    }


def publish_toolbox(project: AIProjectClient) -> str:
    """Create a toolbox version when the definition changed, and make it the default."""
    definition = toolbox_definition()
    digest = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()[:16]
    try:
        existing_versions = list(project.toolboxes.list_versions(TOOLBOX))
    except ResourceNotFoundError:
        existing_versions = []
    for existing in existing_versions:
        if (existing.metadata or {}).get("definition") == digest:
            version = existing.version
            break
    else:
        created = project.toolboxes.create_version(
            TOOLBOX, body={**definition, "metadata": {"definition": digest}}
        )
        version = created.version
    project.toolboxes.update(TOOLBOX, default_version=version)
    print(f"Toolbox {TOOLBOX}: default version {version}")
    return version


def connect_tools(credential: DefaultAzureCredential) -> None:
    connect_mcp_server(Arm(credential))
    project_endpoint = env("FOUNDRY_PROJECT_ENDPOINT")
    version = publish_toolbox(AIProjectClient(project_endpoint, credential))
    endpoint = f"{project_endpoint}/toolboxes/{TOOLBOX}/versions/{version}/mcp?api-version=v1"
    subprocess.run(["azd", "env", "set", "TOOLBOX_ENDPOINT", endpoint], check=True)


# --- grant-agent -----------------------------------------------------------------------------


COSMOS_DATA_CONTRIBUTOR = "00000000-0000-0000-0000-000000000002"


def grant_agent(credential: DefaultAzureCredential) -> None:
    # azd records the deployed agent's instance identity in the environment.
    principal_id = env("AGENT_RCA_AGENT_INSTANCE_IDENTITY_PRINCIPAL_ID")
    account_id = (
        f"/subscriptions/{env('AZURE_SUBSCRIPTION_ID')}/resourceGroups/{env('AZURE_RESOURCE_GROUP')}"
        f"/providers/Microsoft.DocumentDB/databaseAccounts/{env('COSMOS_ACCOUNT_NAME')}"
    )
    # Deterministic assignment name, so reruns update instead of duplicating.
    assignment_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{account_id}/{principal_id}")
    Arm(credential).request(
        "PUT",
        f"{account_id}/sqlRoleAssignments/{assignment_id}",
        "2024-11-15",
        {
            "properties": {
                "principalId": principal_id,
                "roleDefinitionId": f"{account_id}/sqlRoleDefinitions/{COSMOS_DATA_CONTRIBUTOR}",
                "scope": account_id,
            }
        },
    )
    print(f"Agent identity {principal_id}: Cosmos DB data contributor")


def main(argv: Sequence[str] | None = None) -> None:
    steps = {"seed-search": seed_search, "connect-tools": connect_tools, "grant-agent": grant_agent}
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("step", choices=steps)
    args = parser.parse_args(argv)
    try:
        steps[args.step](DefaultAzureCredential())
    except SetupError as error:
        sys.exit(f"{args.step}: {error}")


if __name__ == "__main__":
    main()
