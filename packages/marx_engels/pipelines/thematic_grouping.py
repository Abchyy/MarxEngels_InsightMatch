"""Exclusive thematic grouping and label fallback helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from marx_engels.contracts import Candidate, ResultGroup, SupportLabel
from marx_engels.pipelines.thematic_types import (
    OTHER_RELATED_GROUP_ID,
    OTHER_RELATED_GROUP_TYPE,
    OTHER_RELATED_LABEL,
    THEME_GROUP_TYPE,
    ClusterAssignment,
    SanitizedGrouping,
    ThemeLabel,
)


def fallback_theme_label(index: int) -> str:
    return f"主题 {index}"


def is_irrelevant(support_label: SupportLabel | None) -> bool:
    return support_label is SupportLabel.IRRELEVANT


def fails_relevance_gate(
    support_label: SupportLabel | None,
    rerank_score: float | None,
    *,
    min_rerank_score: float,
    require_judgment: bool,
) -> bool:
    if is_irrelevant(support_label):
        return True
    if rerank_score is not None and rerank_score < min_rerank_score:
        return True
    return require_judgment and support_label is None and rerank_score is None


def cited_evidence_ids_are_valid(claimed: Sequence[str], cluster_ids: set[str]) -> bool:
    if not claimed:
        return False
    seen: set[str] = set()
    for evidence_id in claimed:
        if not evidence_id or evidence_id.strip() != evidence_id:
            return False
        if evidence_id not in cluster_ids or evidence_id in seen:
            return False
        seen.add(evidence_id)
    return True


def apply_relevance_judgments(
    pool: Sequence[Candidate],
    scored: Sequence[Candidate],
) -> list[Candidate]:
    """Keep reranker order, but only original pool IDs. Drop unknown and duplicates."""

    pool_by_id = {candidate.evidence_id: candidate for candidate in pool}
    seen: set[str] = set()
    judged: list[Candidate] = []
    for judgment in scored:
        evidence_id = judgment.evidence_id
        original = pool_by_id.get(evidence_id)
        if original is None or evidence_id in seen:
            continue
        seen.add(evidence_id)
        judged.append(
            original.model_copy(
                update={
                    "support_label": judgment.support_label,
                    "rerank_score": judgment.rerank_score,
                    "rank_reasons": list(
                        dict.fromkeys([*original.rank_reasons, "rerank"])
                    ),
                }
            )
        )
    return judged


def assign_exclusively(
    assignments: Sequence[ClusterAssignment],
    allowed_ids: Sequence[str],
) -> SanitizedGrouping:
    """Keep first membership only and drop IDs outside the hydrated evidence pool."""

    allowed = list(dict.fromkeys(allowed_ids))
    allowed_set = set(allowed)
    claimed: set[str] = set()
    themes: list[ClusterAssignment] = []
    seen_cluster_ids: set[str] = set()

    for assignment in assignments:
        cluster_id = assignment.cluster_id.strip()
        members = _unique_keep_order(assignment.evidence_ids)
        if not cluster_id or cluster_id == OTHER_RELATED_GROUP_ID:
            continue
        if cluster_id in seen_cluster_ids:
            cluster_id = _dedupe_cluster_id(cluster_id, seen_cluster_ids)
        valid: list[str] = []
        for evidence_id in members:
            if evidence_id not in allowed_set or evidence_id in claimed:
                continue
            claimed.add(evidence_id)
            valid.append(evidence_id)
        if not valid:
            continue
        seen_cluster_ids.add(cluster_id)
        themes.append(ClusterAssignment(cluster_id=cluster_id, evidence_ids=tuple(valid)))

    leftover = tuple(evidence_id for evidence_id in allowed if evidence_id not in claimed)
    return SanitizedGrouping(themes=tuple(themes), other_related_ids=leftover)


def sort_theme_clusters(
    themes: Sequence[ClusterAssignment],
    scores: Mapping[str, float],
) -> tuple[ClusterAssignment, ...]:
    def sort_key(cluster: ClusterAssignment) -> tuple[float, float, int, str]:
        member_scores = [scores.get(evidence_id, 0.0) for evidence_id in cluster.evidence_ids]
        maximum = max(member_scores) if member_scores else 0.0
        mean = sum(member_scores) / len(member_scores) if member_scores else 0.0
        return (-maximum, -mean, -len(cluster.evidence_ids), cluster.cluster_id)

    return tuple(sorted(themes, key=sort_key))


def order_group_members(evidence_ids: Sequence[str], scores: Mapping[str, float]) -> list[str]:
    return sorted(
        evidence_ids, key=lambda evidence_id: (-scores.get(evidence_id, 0.0), evidence_id)
    )


def resolve_theme_presentation(
    label: ThemeLabel | None,
    cluster: ClusterAssignment,
    *,
    include_generated_summaries: bool,
    fallback_label: str,
) -> tuple[str, str | None, float | None, bool]:
    """Return display label, safe summary, confidence, and whether fallback was used."""

    if not include_generated_summaries or label is None:
        return fallback_label, None, None, True

    claimed_ids = label.evidence_ids
    cluster_ids = set(cluster.evidence_ids)
    display = label.label.strip()
    ids_valid = cited_evidence_ids_are_valid(claimed_ids, cluster_ids)
    used_fallback = not display or _looks_like_quotation(display) or not ids_valid
    if used_fallback:
        return fallback_label, None, None, True

    summary = None
    if label.summary and label.summary.strip() and claimed_ids and ids_valid:
        summary = label.summary.strip()
    confidence = label.confidence
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        confidence = None
    return display, summary, confidence, False


def theme_result_group(
    cluster: ClusterAssignment,
    *,
    label: str,
    summary: str | None,
    confidence: float | None,
    scores: Mapping[str, float],
) -> ResultGroup:
    return ResultGroup(
        group_id=cluster.cluster_id,
        label=label,
        group_type=THEME_GROUP_TYPE,
        evidence_ids=order_group_members(cluster.evidence_ids, scores),
        summary=summary,
        confidence=confidence,
    )


def other_related_group(
    evidence_ids: Sequence[str], scores: Mapping[str, float]
) -> ResultGroup | None:
    if not evidence_ids:
        return None
    return ResultGroup(
        group_id=OTHER_RELATED_GROUP_ID,
        label=OTHER_RELATED_LABEL,
        group_type=OTHER_RELATED_GROUP_TYPE,
        evidence_ids=order_group_members(evidence_ids, scores),
        summary=None,
        confidence=None,
    )


def _unique_keep_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _dedupe_cluster_id(cluster_id: str, seen: set[str]) -> str:
    suffix = 2
    candidate = f"{cluster_id}_{suffix}"
    while candidate in seen:
        suffix += 1
        candidate = f"{cluster_id}_{suffix}"
    return candidate


def _looks_like_quotation(label: str) -> bool:
    stripped = label.strip()
    quotes = {'"', "“", "「"}
    closers = {'"', "”", "」"}
    return len(stripped) >= 2 and stripped[0] in quotes and stripped[-1] in closers
