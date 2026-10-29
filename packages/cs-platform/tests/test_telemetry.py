import atexit
from unittest.mock import Mock

import pytest
from microsoft import opentelemetry as distro
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from cs_platform import telemetry
from cs_platform.settings import PlatformSettings


@pytest.fixture(autouse=True)
def reset_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_owned_providers", [])


def test_bootstrap_without_exporter_still_creates_real_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OTEL_TRACES_SAMPLER", raising=False)
    installed: list[TracerProvider] = []

    monkeypatch.setattr(
        trace,
        "get_tracer_provider",
        lambda: installed[0] if installed else trace.ProxyTracerProvider(),
    )
    monkeypatch.setattr(trace, "set_tracer_provider", installed.append)
    register = Mock()
    monkeypatch.setattr(atexit, "register", register)
    telemetry.configure_telemetry(
        PlatformSettings(foundry_project_endpoint="https://example.test"),
        service_name="test-local",
    )
    [provider] = installed
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer(__name__).start_as_current_span("local") as span:
        assert span.get_span_context().is_valid
        assert span.is_recording()
    telemetry.flush_telemetry()
    [exported] = exporter.get_finished_spans()
    assert exported.context == span.get_span_context()
    register.assert_any_call(telemetry.flush_telemetry)
    registrations = register.call_count
    telemetry.configure_telemetry(
        PlatformSettings(foundry_project_endpoint="https://example.test"),
        service_name="ignored-second-bootstrap",
    )
    assert provider.resource.attributes["service.name"] == "test-local"
    assert register.call_count == registrations
    provider.shutdown()


def test_existing_provider_and_sampling_are_not_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_off")
    provider = TracerProvider()
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    install = Mock()
    monkeypatch.setattr(trace, "set_tracer_provider", install)
    with provider.get_tracer(__name__).start_as_current_span("existing") as span:
        assert not span.is_recording()
    telemetry.configure_telemetry(
        PlatformSettings(
            foundry_project_endpoint="https://example.test",
            applicationinsights_connection_string="not-used",
        ),
        service_name="must-not-replace-host",
    )
    install.assert_not_called()
    assert telemetry._owned_providers == []
    provider.shutdown()


def test_flush_continues_after_an_exporter_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    failed = Mock()
    failed.force_flush.side_effect = RuntimeError("export failed")
    healthy = Mock()
    monkeypatch.setattr(telemetry, "_owned_providers", [failed, healthy])
    telemetry.flush_telemetry()
    healthy.force_flush.assert_called_once_with(timeout_millis=10_000)


def test_azure_export_bootstrap_preserves_explicit_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_off")
    provider = TracerProvider()
    installed: list[TracerProvider] = []
    monkeypatch.setattr(
        trace,
        "get_tracer_provider",
        lambda: installed[0] if installed else trace.ProxyTracerProvider(),
    )
    configure = Mock(side_effect=lambda **_: installed.append(provider))
    monkeypatch.setattr(distro, "use_microsoft_opentelemetry", configure)
    monkeypatch.setattr(atexit, "register", Mock())
    telemetry.configure_telemetry(
        PlatformSettings(
            foundry_project_endpoint="https://example.test",
            applicationinsights_connection_string="test-connection",
        ),
        service_name="test-local",
    )
    configure.assert_called_once()
    assert configure.call_args.kwargs["enable_azure_monitor"] is True
    assert configure.call_args.kwargs["resource"].attributes["service.name"] == "test-local"
    assert configure.call_args.kwargs["instrumentation_options"]["httpx"]["enabled"] is True
    with provider.get_tracer(__name__).start_as_current_span("unsampled") as span:
        assert not span.is_recording()
    provider.shutdown()
