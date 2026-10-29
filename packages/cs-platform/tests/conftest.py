import pytest

from cs_platform.spec import AgentSpec


@pytest.fixture
def spec() -> AgentSpec:
    return AgentSpec(
        name="test-agent",
        version="1.2.3",
        description="Agent under test.",
        instructions="Diagnose the machine.",
    )
