"""The RCA agent's structured output.

All fields are required and extra fields are forbidden, so the JSON schema works with strict
structured outputs.
"""

from pydantic import BaseModel, ConfigDict, Field

from cs_platform.evidence import Evidence


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(description="1 for the most likely root cause.")
    failure_mode_id: str = Field(
        description="Failure mode ID from lookup_error_code (e.g. FM-01), or 'unknown'."
    )
    title: str = Field(description="Short name of the hypothesis.")
    root_cause: str = Field(description="The underlying cause, in one or two sentences.")
    confidence: float = Field(description="0.0 to 1.0: how strongly the evidence supports it.")
    evidence: list[Evidence] = Field(description="At least one item, each citing a real ref.")
    recommended_checks: list[str] = Field(description="Concrete checks, most decisive first.")


class RcaReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_id: str
    summary: str = Field(description="Two or three sentences for the field engineer.")
    hypotheses: list[Hypothesis] = Field(description="1 to 3 hypotheses, ranked.")
    missing_information: list[str] = Field(
        description="What couldn't be verified and would increase certainty."
    )
