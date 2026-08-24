from pathlib import Path

import pytest

from marx_engels.contracts import Candidate, Evidence
from marx_engels.storage.lancedb_adapter import VECTOR_TABLE_FIELDS, passage_vector_schema


@pytest.mark.contract
def test_candidate_cannot_carry_formal_quotation() -> None:
    assert "verified_text" not in Candidate.model_fields
    assert "work_title" not in Candidate.model_fields


@pytest.mark.contract
def test_evidence_contains_authoritative_display_fields() -> None:
    required = {
        "evidence_id",
        "verified_text",
        "author",
        "work_title",
        "corpus_name",
        "edition_label",
        "volume_no",
        "printed_pages",
        "pdf_pages",
    }
    assert required <= set(Evidence.model_fields)


@pytest.mark.contract
def test_lancedb_schema_matches_frozen_field_order() -> None:
    schema = passage_vector_schema(8)
    assert tuple(schema.names) == VECTOR_TABLE_FIELDS
    assert schema.field("vector").type.list_size == 8


@pytest.mark.contract
def test_contract_version_is_v1() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "contracts" / "CONTRACT_VERSION").read_text().strip() == "v1"
