"""Base configuration for stable contract models."""

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Immutable, closed model used at module and HTTP boundaries."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        validate_default=True,
    )
