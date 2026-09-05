"""Shared retrieval boundaries and deterministic helpers."""

from marx_engels.retrieval_core.ports import (
    EvidenceRepository,
    ExactSearchIndex,
    LexicalIndex,
    Retriever,
    ScopeResolver,
    SearchPipeline,
    VectorIndex,
)
from marx_engels.retrieval_core.records import AuthoritativeEvidenceRecord
from marx_engels.retrieval_core.units import RetrievalUnitSpec, retrieval_units_for_passage

__all__ = [
    "AuthoritativeEvidenceRecord",
    "EvidenceRepository",
    "ExactSearchIndex",
    "LexicalIndex",
    "RetrievalUnitSpec",
    "Retriever",
    "ScopeResolver",
    "SearchPipeline",
    "VectorIndex",
    "retrieval_units_for_passage",
]
