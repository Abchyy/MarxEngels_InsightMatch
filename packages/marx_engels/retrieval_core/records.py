"""Non-public, non-display records loaded from the SQLite authority."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthoritativeEvidenceRecord:
    """SQLite-backed passage used by EvidenceService to build public Evidence.

    This record is not a display object. It must not carry LanceDB ``search_text``
    or any other retrieval-auxiliary quotation field.
    """

    evidence_id: str
    verified_text: str
    text_hash: str
    verification_status: str
    release_status: str
    content_type: str
    author_code: str
    author: str
    work_title: str
    corpus_id: str
    corpus_name: str
    edition_id: str
    edition_label: str
    volume_id: str
    volume_no: int
    work_id: str
    work_date_start: str | None
    work_date_end: str | None
    date_precision: str
    corpus_release_status: str
    edition_release_status: str
    volume_release_status: str
    work_release_status: str
    work_verification_status: str
    section_verification_status: str
    printed_pages: tuple[str, ...]
    pdf_pages: tuple[int, ...]
    page_mapping_statuses: tuple[str, ...]
    prev_evidence_id: str | None
    next_evidence_id: str | None
    prev_is_released: bool
    next_is_released: bool
