"""Evidence gate and the only production constructor of public Evidence."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from marx_engels.contracts import Candidate, ContentType, DatePrecision, Evidence, SearchScope
from marx_engels.evidence.matching import non_overlapping_match_offsets
from marx_engels.retrieval_core import AuthoritativeEvidenceRecord, EvidenceRepository

_VERIFIED = "verified"
_PUBLISHED = "published"


class EvidenceExclusionReason(StrEnum):
    ID_NOT_FOUND = "ID_NOT_FOUND"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    TEXT_HASH_MISMATCH = "TEXT_HASH_MISMATCH"
    PAGES_UNAVAILABLE = "PAGES_UNAVAILABLE"
    METADATA_UNAVAILABLE = "METADATA_UNAVAILABLE"
    MODEL_UNAUTHORIZED_ID = "MODEL_UNAUTHORIZED_ID"
    EXACT_QUERY_REQUIRED = "EXACT_QUERY_REQUIRED"
    EXACT_QUERY_EMPTY = "EXACT_QUERY_EMPTY"
    NO_EXACT_MATCH = "NO_EXACT_MATCH"


@dataclass(frozen=True, slots=True)
class ExactMatchQuery:
    """Internal exact-mode input; not part of the frozen Candidate or Evidence contracts."""

    query: str


@dataclass(frozen=True, slots=True)
class EvidenceGateExclusion:
    evidence_id: str
    reason: EvidenceExclusionReason


@dataclass(frozen=True, slots=True)
class EvidenceHydrationResult:
    evidence: tuple[Evidence, ...]
    exclusions: tuple[EvidenceGateExclusion, ...]
    accepted_records: tuple[AuthoritativeEvidenceRecord, ...] = ()


class EvidenceService:
    """The only service allowed to produce public Evidence objects."""

    def __init__(self, repository: EvidenceRepository) -> None:
        self._repository = repository

    async def hydrate(
        self,
        candidates: Sequence[Candidate],
        scope: SearchScope,
        *,
        exact_query: ExactMatchQuery | None = None,
        allowed_evidence_ids: Iterable[str] | None = None,
    ) -> EvidenceHydrationResult:
        ordered = _unique_candidates(candidates)
        allowed_pool = None if allowed_evidence_ids is None else set(allowed_evidence_ids)
        records = await self._repository.get_by_ids(
            [candidate.evidence_id for candidate in ordered]
        )

        evidence: list[Evidence] = []
        accepted_records: list[AuthoritativeEvidenceRecord] = []
        exclusions: list[EvidenceGateExclusion] = []
        for candidate in ordered:
            reason = _first_gate_failure(
                candidate, records, scope, allowed_pool, exact_query
            )
            if reason is not None:
                exclusions.append(
                    EvidenceGateExclusion(evidence_id=candidate.evidence_id, reason=reason)
                )
                continue
            record = records[candidate.evidence_id]
            evidence.append(_to_public_evidence(candidate, record, exact_query))
            accepted_records.append(record)
        return EvidenceHydrationResult(
            evidence=tuple(evidence),
            exclusions=tuple(exclusions),
            accepted_records=tuple(accepted_records),
        )


def _unique_candidates(candidates: Sequence[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    ordered: list[Candidate] = []
    for candidate in candidates:
        if candidate.evidence_id in seen:
            continue
        seen.add(candidate.evidence_id)
        ordered.append(candidate)
    return ordered


def _first_gate_failure(
    candidate: Candidate,
    records: Mapping[str, AuthoritativeEvidenceRecord],
    scope: SearchScope,
    allowed_pool: set[str] | None,
    exact_query: ExactMatchQuery | None,
) -> EvidenceExclusionReason | None:
    evidence_id = candidate.evidence_id
    record = records.get(evidence_id)
    if record is None:
        return EvidenceExclusionReason.ID_NOT_FOUND
    if allowed_pool is not None and evidence_id not in allowed_pool:
        return EvidenceExclusionReason.MODEL_UNAUTHORIZED_ID
    if record.verification_status != _VERIFIED:
        return EvidenceExclusionReason.NOT_VERIFIED
    if record.release_status != _PUBLISHED:
        return EvidenceExclusionReason.NOT_PUBLISHED
    if not _in_scope(record, scope):
        return EvidenceExclusionReason.OUT_OF_SCOPE
    if _is_vector_candidate(candidate) and candidate.text_hash != record.text_hash:
        return EvidenceExclusionReason.TEXT_HASH_MISMATCH
    if not _metadata_available(record):
        return EvidenceExclusionReason.METADATA_UNAVAILABLE
    return _exact_gate_failure(candidate, record, exact_query)


def _in_scope(record: AuthoritativeEvidenceRecord, scope: SearchScope) -> bool:
    if record.corpus_id not in scope.corpus_ids:
        return False
    if scope.edition_ids and record.edition_id not in scope.edition_ids:
        return False
    if scope.volume_ids and record.volume_id not in scope.volume_ids:
        return False
    if scope.work_ids and record.work_id not in scope.work_ids:
        return False
    if scope.authors and record.author_code not in {author.value for author in scope.authors}:
        return False
    allowed_content_types = {content_type.value for content_type in scope.content_types}
    return not scope.content_types or record.content_type in allowed_content_types


def _is_exact_candidate(candidate: Candidate) -> bool:
    return "exact" in candidate.channels


def _is_vector_candidate(candidate: Candidate) -> bool:
    return (
        "vector" in candidate.channels
        or candidate.vector_rank is not None
        or candidate.vector_score is not None
    )


def _metadata_available(record: AuthoritativeEvidenceRecord) -> bool:
    if record.corpus_release_status != _PUBLISHED:
        return False
    if record.edition_release_status != _PUBLISHED:
        return False
    if record.volume_release_status != _PUBLISHED:
        return False
    if record.work_release_status != _PUBLISHED:
        return False
    if record.work_verification_status != _VERIFIED:
        return False
    if record.section_verification_status != _VERIFIED:
        return False
    if not record.verified_text.strip():
        return False
    if not record.author.strip():
        return False
    if not record.work_title.strip():
        return False
    if not record.corpus_name.strip():
        return False
    if not record.edition_label.strip():
        return False
    if record.volume_no < 1:
        return False
    try:
        ContentType(record.content_type)
        DatePrecision(record.date_precision)
    except ValueError:
        return False
    return True


def _exact_gate_failure(
    candidate: Candidate,
    record: AuthoritativeEvidenceRecord,
    exact_query: ExactMatchQuery | None,
) -> EvidenceExclusionReason | None:
    if not _is_exact_candidate(candidate):
        return None
    if exact_query is None:
        return EvidenceExclusionReason.EXACT_QUERY_REQUIRED
    query = exact_query.query.strip()
    if not query:
        return EvidenceExclusionReason.EXACT_QUERY_EMPTY
    if not non_overlapping_match_offsets(record.verified_text, query):
        return EvidenceExclusionReason.NO_EXACT_MATCH
    return None


def _to_public_evidence(
    candidate: Candidate,
    record: AuthoritativeEvidenceRecord,
    exact_query: ExactMatchQuery | None,
) -> Evidence:
    offsets: list[int] = []
    match_count: int | None = None
    if _is_exact_candidate(candidate) and exact_query is not None:
        offsets = non_overlapping_match_offsets(record.verified_text, exact_query.query.strip())
        match_count = len(offsets)
    # Page fields echo stored values and are not human-confirmed in this phase.
    return Evidence(
        evidence_id=record.evidence_id,
        verified_text=record.verified_text,
        content_type=ContentType(record.content_type),
        author=record.author,
        work_title=record.work_title,
        corpus_name=record.corpus_name,
        edition_label=record.edition_label,
        volume_no=record.volume_no,
        work_date_start=record.work_date_start,
        work_date_end=record.work_date_end,
        date_precision=DatePrecision(record.date_precision),
        printed_pages=list(record.printed_pages),
        pdf_pages=list(record.pdf_pages),
        prev_evidence_id=record.prev_evidence_id if record.prev_is_released else None,
        next_evidence_id=record.next_evidence_id if record.next_is_released else None,
        match_type=_match_type(candidate),
        support_label=candidate.support_label,
        rank_reasons=list(candidate.rank_reasons),
        exact_match_count=match_count,
        match_offsets=offsets,
    )


def _match_type(candidate: Candidate) -> str:
    channels = candidate.channels
    if "exact" in channels:
        return "exact"
    has_lexical = "lexical" in channels
    has_vector = "vector" in channels
    if has_lexical and has_vector:
        return "hybrid"
    if has_vector:
        return "semantic"
    if has_lexical:
        return "lexical"
    return channels[0] if channels else "unknown"
