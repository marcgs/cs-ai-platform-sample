"""Evidence: the unit every agent cites, and every evaluator can verify."""

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    """One piece of evidence, traceable to a concrete record in a source system."""

    model_config = ConfigDict(frozen=True)

    source: str = Field(description="Tool or knowledge source, e.g. get_error_events.")
    ref: str = Field(description="Identifier of the cited record, e.g. EV-000123 or LB-00042.")
    excerpt: str = Field(description="The relevant fact from that record, in a sentence.")
