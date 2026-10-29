"""Telemetry bootstrap for processes that host agents outside Foundry (CLI, local runs).

Foundry hosted agents configure OpenTelemetry through their hosting library; don't call this
there. Elsewhere, call it once at startup.
"""

import atexit
import logging
import os
from typing import TYPE_CHECKING, Protocol

from agent_framework.observability import enable_instrumentation
from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

if TYPE_CHECKING:
    from cs_platform.settings import PlatformSettings

_configured = False
logger = logging.getLogger(__name__)


class _Flushable(Protocol):
    def force_flush(self, timeout_millis: int = ...) -> bool: ...


_owned_providers: list[_Flushable] = []


def configure_telemetry(settings: PlatformSettings, service_name: str) -> None:
    """Export to Application Insights when configured, and turn on agent instrumentation."""
    global _configured
    if _configured:
        return
    # A host or embedding application may already own the global provider.
    if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
        os.environ.setdefault("OTEL_TRACES_SAMPLER", "parentbased_always_on")
        resource = Resource.create({"service.name": service_name})
        if settings.applicationinsights_connection_string:
            from microsoft.opentelemetry import use_microsoft_opentelemetry

            use_microsoft_opentelemetry(
                enable_azure_monitor=True,
                azure_monitor_connection_string=settings.applicationinsights_connection_string,
                resource=resource,
                instrumentation_options={"httpx": {"enabled": True}},
            )
            meter_provider = metrics.get_meter_provider()
            logger_provider = get_logger_provider()
            if isinstance(meter_provider, MeterProvider):
                _owned_providers.append(meter_provider)
            if isinstance(logger_provider, LoggerProvider):
                _owned_providers.append(logger_provider)
        else:
            trace.set_tracer_provider(TracerProvider(resource=resource))
        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            _owned_providers.append(provider)
            atexit.register(flush_telemetry)
    enable_instrumentation()
    _configured = True


def flush_telemetry() -> None:
    """Flush this bootstrap's exporter before a short-lived local process exits."""
    for provider in _owned_providers:
        try:
            if not provider.force_flush(timeout_millis=10_000):
                logger.warning("Local telemetry flush timed out")
        except Exception:
            logger.warning("Local telemetry flush failed", exc_info=True)
