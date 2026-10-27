"""Telemetry bootstrap for processes that host agents outside Foundry (CLI, local runs).

Foundry hosted agents configure OpenTelemetry through their hosting library; don't call this
there. Elsewhere, call it once at startup.
"""

from typing import TYPE_CHECKING

from agent_framework.observability import enable_instrumentation

if TYPE_CHECKING:
    from cs_platform.settings import PlatformSettings

_configured = False


def configure_telemetry(settings: PlatformSettings, service_name: str) -> None:
    """Export to Application Insights when configured, and turn on agent instrumentation."""
    global _configured
    if _configured:
        return
    if settings.applicationinsights_connection_string:
        from microsoft.opentelemetry import use_microsoft_opentelemetry
        from opentelemetry.sdk.resources import Resource

        use_microsoft_opentelemetry(
            enable_azure_monitor=True,
            azure_monitor_connection_string=settings.applicationinsights_connection_string,
            resource=Resource.create({"service.name": service_name}),
        )
    enable_instrumentation()
    _configured = True
