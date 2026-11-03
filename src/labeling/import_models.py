"""Validated import contracts shared by HTTP and command-line clients."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class ImportCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source: str = Field(min_length=1)
    row: StrictInt = Field(ge=0)
    column: str = Field(min_length=1)
    error_type: str = Field(default="manual_review", min_length=1)
    explanation: str = "Imported for manual review."
    suggested_value: str | list[str] | None = None

    @field_validator("column")
    @classmethod
    def normalize_header(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Column name cannot be blank")
        return value.strip()


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    run_id: str
    sources: dict[str, str]
    candidates: list[ImportCandidate] | None = None
