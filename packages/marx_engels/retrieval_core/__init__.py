"""Shared retrieval boundaries and deterministic helpers."""

from marx_engels.retrieval_core.ports import (
    EvidenceRepository,
    ExactSearchIndex,
    LexicalIndex,
    ScopeResolver,
    SearchPipeline,
    VectorIndex,
)
from marx_engels.retrieval_core.records import AuthoritativeEvidenceRecord

__all__ = [
    "AuthoritativeEvidenceRecord",
    "EvidenceRepository",
    "ExactSearchIndex",
    "LexicalIndex",
    "ScopeResolver",
    "SearchPipeline",
    "VectorIndex",
]
