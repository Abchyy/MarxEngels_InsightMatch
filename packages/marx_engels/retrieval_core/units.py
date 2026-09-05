"""Deterministic retrieval-unit splitting. IDs are stable; text is not a quotation."""

from __future__ import annotations

from dataclasses import dataclass

from marx_engels.corpus_registry.hashing import sha256_bytes


def _text_hash(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))

DEFAULT_RETRIEVAL_UNIT_CHAR_LIMIT = 1800


@dataclass(frozen=True, slots=True)
class RetrievalUnitSpec:
    retrieval_unit_id: str
    evidence_id: str
    order_no: int
    search_text: str
    search_text_hash: str


def retrieval_unit_id(evidence_id: str, order_no: int) -> str:
    return f"ru_{evidence_id}_{order_no}"


def split_retrieval_unit_texts(
    text: str, *, char_limit: int = DEFAULT_RETRIEVAL_UNIT_CHAR_LIMIT
) -> tuple[str, ...]:
    if not text:
        return ()
    if char_limit < 1:
        raise ValueError("char_limit must be >= 1")
    if len(text) <= char_limit:
        return (text,)
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= char_limit:
            chunks.append(remaining)
            break
        window = remaining[:char_limit]
        cut = max(window.rfind("。"), window.rfind("！"), window.rfind("？"), window.rfind("\n"))
        if cut < char_limit // 3:
            cut = char_limit
        else:
            cut += 1
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    return tuple(chunks)


def retrieval_units_for_passage(
    evidence_id: str,
    text: str,
    *,
    char_limit: int = DEFAULT_RETRIEVAL_UNIT_CHAR_LIMIT,
) -> tuple[RetrievalUnitSpec, ...]:
    chunks = split_retrieval_unit_texts(text, char_limit=char_limit)
    return tuple(
        RetrievalUnitSpec(
            retrieval_unit_id=retrieval_unit_id(evidence_id, index),
            evidence_id=evidence_id,
            order_no=index,
            search_text=chunk,
            search_text_hash=_text_hash(chunk),
        )
        for index, chunk in enumerate(chunks, start=1)
    )
