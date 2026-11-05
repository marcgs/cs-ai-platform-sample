import socket
from unittest.mock import patch

import pytest
from scripts import setup_platform as setup


def test_public_mode_does_not_require_private_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_PRIVATE_NETWORKING", raising=False)
    with patch.object(socket, "getaddrinfo", side_effect=AssertionError("unexpected DNS")):
        setup.check_private_endpoints("https://service.example")


@pytest.mark.parametrize(
    ("addresses", "valid"),
    [
        (["10.40.1.4", "10.40.1.5"], True),
        (["10.40.1.4", "20.1.1.1"], False),
        (["127.0.0.1"], False),
        (["169.254.169.254"], False),
        ([], False),
    ],
)
def test_private_dns_preflight(
    monkeypatch: pytest.MonkeyPatch, addresses: list[str], *, valid: bool
) -> None:
    monkeypatch.setenv("AZURE_PRIVATE_NETWORKING", "true")
    results = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))
        for address in addresses
    ]
    with patch.object(socket, "getaddrinfo", return_value=results):
        if valid:
            setup.check_private_endpoints("https://service.example")
        else:
            with pytest.raises(setup.SetupError, match="jump host"):
                setup.check_private_endpoints("https://service.example")


def test_private_seeding_stops_before_model_calls_until_link_is_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in {
        "AZURE_PRIVATE_NETWORKING": "true",
        "AZURE_SEARCH_ENDPOINT": "https://search.example",
        "AZURE_OPENAI_ENDPOINT": "https://model.example",
        "AZURE_SEARCH_SHARED_PRIVATE_LINK_ID": "/synthetic/sharedPrivateLinkResources/vectorizer",
    }.items():
        monkeypatch.setenv(key, value)
    with (
        patch.object(setup, "check_private_endpoints"),
        patch.object(setup.Arm, "request", return_value={"properties": {"status": "Pending"}}),
        patch.object(setup, "OpenAI") as model,
        patch.object(setup, "DefaultAzureCredential") as credential,
        pytest.raises(setup.SetupError, match="Approve Search"),
    ):
        setup.seed_search(credential.return_value)
    model.assert_not_called()


@pytest.mark.parametrize("private", [False, True])
def test_hook_uses_developer_identity_only_in_private_mode(
    monkeypatch: pytest.MonkeyPatch, *, private: bool
) -> None:
    monkeypatch.setenv("AZURE_PRIVATE_NETWORKING", str(private).lower())
    with (
        patch.object(setup, "DefaultAzureCredential") as credential,
        patch.object(setup, "grant_agent") as grant,
    ):
        setup.main(["grant-agent"])
    credential.assert_called_once_with(exclude_managed_identity_credential=private)
    grant.assert_called_once_with(credential.return_value)
