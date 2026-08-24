"""Internal thematic clustering types. These are not public V1 contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from marx_engels.contracts import Candidate, Evidence, ReleaseInfo, SearchOverview, SearchScope

CLASSIFICATION_NOTICE = "语义聚类不是唯一权威思想分类"
OTHER_RELATED_GROUP_ID = "other_related"
OTHER_RELATED_LABEL = "其他相关"
OTHER_RELATED_GROUP_TYPE = "other_related"
THEME_GROUP_TYPE = "theme"


@dataclass(frozen=True, slots=True)
class ThematicPipelineConfig:
    lexical_top_k: int = 100
    vector_top_k: int = 100
    fusion_top_k: int = 80
    final_top_k: int = 20
    rrf_k: int = 60
    min_cluster_input: int = 2
    min_rerank_score: float = 0.1


@dataclass(frozen=True, slots=True)
class ClusterAssignment:
    cluster_id: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ThemeLabel:
    cluster_id: str
    label: str
    summary: str | None = None
    evidence_ids: tuple[str, ...] = ()
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class SanitizedGrouping:
    themes: tuple[ClusterAssignment, ...]
    other_related_ids: tuple[str, ...]


class ThemeClusterer(Protocol):
    async def cluster(
        self,
        evidence_ids: Sequence[str],
        vectors: Mapping[str, Sequence[float]],
    ) -> Sequence[ClusterAssignment]: ...


class ThemeLabeler(Protocol):
    async def label(
        self,
        *,
        cluster_id: str,
        query: str,
        evidence_ids: Sequence[str],
    ) -> ThemeLabel: ...


class ThemeRelevanceStage(Protocol):
    """Thematic-only relevance/rerank port. Not a public V1 contract."""

    async def score(
        self,
        query: str,
        candidates: Sequence[Candidate],
    ) -> Sequence[Candidate]: ...


class ReleaseSnapshotProvider(Protocol):
    async def snapshot_for(self, scope: SearchScope) -> ReleaseInfo: ...


class OverviewProvider(Protocol):
    async def build(self, evidence: Sequence[Evidence]) -> SearchOverview: ...
