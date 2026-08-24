"""Deterministic reciprocal-rank fusion helper."""

from collections.abc import Mapping, Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, rank_constant: int = 60
) -> dict[str, float]:
    if rank_constant <= 0:
        raise ValueError("rank_constant must be positive")
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, document_id in enumerate(ranking, start=1):
            scores[document_id] = scores.get(document_id, 0.0) + 1.0 / (rank_constant + rank)
    return scores


def stable_score_order(scores: Mapping[str, float]) -> list[str]:
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [document_id for document_id, _ in ranked]
