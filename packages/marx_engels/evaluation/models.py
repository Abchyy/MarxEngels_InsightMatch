"""Internal golden-dataset case model. This is not a public V1 contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from marx_engels.contracts import SearchMode, SearchScope


class GoldenCase(BaseModel):
    """Reviewed evaluation case used only inside the evaluation boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    case_id: str = Field(min_length=1)
    query: str = Field(min_length=1, max_length=500)
    mode: SearchMode
    scope: SearchScope
    expected_evidence_ids: list[str] = Field(default_factory=list)
    forbidden_evidence_ids: list[str] = Field(default_factory=list)
    expected_labels: dict[str, str] = Field(default_factory=dict)
    notes: str = ""
    annotator: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)

    @field_validator("case_id", "query", "annotator", "reviewer", "dataset_version")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain a non-whitespace character")
        return value.strip()

    @field_validator("expected_evidence_ids", "forbidden_evidence_ids")
    @classmethod
    def reject_blank_or_duplicate_ids(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("evidence IDs must be non-empty")
        if len(stripped) != len(set(stripped)):
            raise ValueError("evidence IDs must not contain duplicates")
        return stripped

    @field_validator("expected_labels")
    @classmethod
    def reject_blank_label_keys_and_values(cls, values: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in values.items():
            stripped_key = key.strip()
            stripped_value = value.strip()
            if not stripped_key or not stripped_value:
                raise ValueError("expected_labels keys and values must be non-empty")
            normalized[stripped_key] = stripped_value
        return normalized

    @model_validator(mode="after")
    def expected_and_forbidden_must_be_disjoint(self) -> GoldenCase:
        overlap = sorted(set(self.expected_evidence_ids) & set(self.forbidden_evidence_ids))
        if overlap:
            raise ValueError(
                "expected_evidence_ids and forbidden_evidence_ids must be disjoint: "
                + ", ".join(overlap)
            )
        return self

    @model_validator(mode="after")
    def labels_must_reference_known_evidence_ids(self) -> GoldenCase:
        known_ids = set(self.expected_evidence_ids) | set(self.forbidden_evidence_ids)
        dangling = sorted(key for key in self.expected_labels if key not in known_ids)
        if dangling:
            raise ValueError(
                "expected_labels keys must belong to expected_evidence_ids or "
                "forbidden_evidence_ids: " + ", ".join(dangling)
            )
        return self

    @model_validator(mode="after")
    def annotator_must_differ_from_reviewer(self) -> GoldenCase:
        if self.annotator == self.reviewer:
            raise ValueError("annotator and reviewer must be different people")
        return self
