import ast
import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from marx_engels.contracts import (
    AuthorCode,
    Candidate,
    ContentType,
    Evidence,
    SearchScope,
    SupportLabel,
)
from marx_engels.evidence import (
    EvidenceExclusionReason,
    EvidenceHydrationResult,
    EvidenceService,
    ExactMatchQuery,
)
from marx_engels.retrieval_core import AuthoritativeEvidenceRecord

CORPUS_ID = "marx_engels_collected_works_cn"
LANCEDB_SEARCH_TEXT = "著作题名 人人平等 检索辅助上下文"


class FakeEvidenceRepository:
    """In-memory repository used only by this test module."""

    def __init__(self, records: Mapping[str, AuthoritativeEvidenceRecord] | None = None) -> None:
        self.records = dict(records or {})
        self.search_text_by_id: dict[str, str] = {}
        self.calls: list[tuple[str, ...]] = []

    async def get_by_ids(
        self, evidence_ids: Sequence[str]
    ) -> dict[str, AuthoritativeEvidenceRecord]:
        self.calls.append(tuple(evidence_ids))
        return {
            evidence_id: self.records[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in self.records
        }


def make_record(evidence_id: str = "ev_ok", **overrides: object) -> AuthoritativeEvidenceRecord:
    record = AuthoritativeEvidenceRecord(
        evidence_id=evidence_id,
        verified_text="人人平等",
        text_hash="hash_ok",
        verification_status="verified",
        release_status="published",
        content_type=ContentType.MAIN_TEXT.value,
        author_code=AuthorCode.MARX.value,
        author="马克思",
        work_title="关于费尔巴哈的提纲",
        corpus_id=CORPUS_ID,
        corpus_name="马克思恩格斯文集",
        edition_id="people_press_2009_cn",
        edition_label="人民出版社2009年版",
        volume_id="vol_1",
        volume_no=1,
        work_id="work_1",
        work_date_start="1845",
        work_date_end="1845",
        date_precision="year",
        corpus_release_status="published",
        edition_release_status="published",
        volume_release_status="published",
        work_release_status="published",
        work_verification_status="verified",
        section_verification_status="verified",
        printed_pages=("123",),
        pdf_pages=(145,),
        page_mapping_statuses=("verified",),
        prev_evidence_id="ev_prev",
        next_evidence_id="ev_next",
        prev_is_released=True,
        next_is_released=True,
    )
    return replace(record, **overrides)  # type: ignore[arg-type]


def make_candidate(evidence_id: str = "ev_ok", **overrides: object) -> Candidate:
    payload: dict[str, object] = {
        "evidence_id": evidence_id,
        "channels": ["lexical"],
        "support_label": SupportLabel.DIRECT,
        "rank_reasons": ["fts"],
    }
    payload.update(overrides)
    return Candidate.model_validate(payload)


def make_scope(**overrides: object) -> SearchScope:
    payload: dict[str, object] = {"corpus_ids": [CORPUS_ID]}
    payload.update(overrides)
    return SearchScope.model_validate(payload)


def hydrate(
    repository: FakeEvidenceRepository,
    candidates: Sequence[Candidate],
    scope: SearchScope | None = None,
    **kwargs: object,
) -> EvidenceHydrationResult:
    service = EvidenceService(repository)

    async def run() -> EvidenceHydrationResult:
        return await service.hydrate(candidates, scope or make_scope(), **kwargs)  # type: ignore[arg-type]

    return asyncio.run(run())


def exclusion_map(result: EvidenceHydrationResult) -> dict[str, EvidenceExclusionReason]:
    return {item.evidence_id: item.reason for item in result.exclusions}


def test_authoritative_record_rejects_search_text_bypass_field() -> None:
    try:
        make_record(search_text=LANCEDB_SEARCH_TEXT)
    except TypeError:
        pass
    else:
        raise AssertionError("authoritative record accepted search_text")
    assert "search_text" not in AuthoritativeEvidenceRecord.__dataclass_fields__


def test_scope_leak_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_ok": make_record(),
            "ev_leak": make_record(evidence_id="ev_leak", volume_id="vol_other"),
        }
    )
    result = hydrate(
        repository,
        [make_candidate(), make_candidate("ev_leak")],
        make_scope(volume_ids=["vol_1"]),
    )
    assert [item.evidence_id for item in result.evidence] == ["ev_ok"]
    assert exclusion_map(result) == {"ev_leak": EvidenceExclusionReason.OUT_OF_SCOPE}


def test_unpublished_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {"ev_draft": make_record(evidence_id="ev_draft", release_status="draft")}
    )
    result = hydrate(repository, [make_candidate("ev_draft")])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_draft": EvidenceExclusionReason.NOT_PUBLISHED}


def test_unverified_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_pending": make_record(
                evidence_id="ev_pending", verification_status="pending_review"
            )
        }
    )
    result = hydrate(repository, [make_candidate("ev_pending")])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_pending": EvidenceExclusionReason.NOT_VERIFIED}


def test_vector_hash_mismatch_is_excluded() -> None:
    repository = FakeEvidenceRepository({"ev_ok": make_record()})
    result = hydrate(
        repository,
        [
            make_candidate(
                channels=["vector"],
                vector_rank=1,
                vector_score=0.9,
                text_hash="stale_index_hash",
            )
        ],
    )
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.TEXT_HASH_MISMATCH}


def test_missing_pages_are_excluded() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_npage": make_record(
                evidence_id="ev_npage",
                printed_pages=(),
                pdf_pages=(),
                page_mapping_statuses=(),
            )
        }
    )
    result = hydrate(repository, [make_candidate("ev_npage")])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_npage": EvidenceExclusionReason.PAGES_UNAVAILABLE}


def test_model_unauthorized_id_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_ok": make_record(),
            "ev_injected": make_record(evidence_id="ev_injected"),
        }
    )
    result = hydrate(
        repository,
        [make_candidate(), make_candidate("ev_injected")],
        allowed_evidence_ids=["ev_ok"],
    )
    assert [item.evidence_id for item in result.evidence] == ["ev_ok"]
    assert exclusion_map(result) == {
        "ev_injected": EvidenceExclusionReason.MODEL_UNAUTHORIZED_ID
    }


def test_missing_id_is_excluded() -> None:
    repository = FakeEvidenceRepository({"ev_ok": make_record()})
    result = hydrate(repository, [make_candidate("ev_missing")])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_missing": EvidenceExclusionReason.ID_NOT_FOUND}


def test_batch_read_avoids_n_plus_one() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_a": make_record(evidence_id="ev_a"),
            "ev_b": make_record(evidence_id="ev_b", volume_id="vol_other"),
            "ev_c": make_record(evidence_id="ev_c", release_status="draft"),
        }
    )
    result = hydrate(
        repository,
        [make_candidate("ev_a"), make_candidate("ev_b"), make_candidate("ev_c")],
        make_scope(volume_ids=["vol_1"]),
    )
    assert repository.calls == [("ev_a", "ev_b", "ev_c")]
    assert [item.evidence_id for item in result.evidence] == ["ev_a"]
    assert exclusion_map(result) == {
        "ev_b": EvidenceExclusionReason.OUT_OF_SCOPE,
        "ev_c": EvidenceExclusionReason.NOT_PUBLISHED,
    }


def test_lancedb_search_text_cannot_enter_evidence() -> None:
    record = make_record()
    repository = FakeEvidenceRepository({"ev_ok": record})
    repository.search_text_by_id["ev_ok"] = LANCEDB_SEARCH_TEXT
    result = hydrate(repository, [make_candidate(channels=["vector"], text_hash="hash_ok")])
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.verified_text == "人人平等"
    assert evidence.verified_text != LANCEDB_SEARCH_TEXT
    assert "search_text" not in Evidence.model_fields
    assert "search_text" not in evidence.model_dump()
    dumped = " ".join(str(value) for value in evidence.model_dump().values())
    assert "检索辅助" not in dumped
    assert LANCEDB_SEARCH_TEXT not in dumped


def test_preserves_candidate_order_support_label_and_rank_reasons() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_b": make_record(evidence_id="ev_b"),
            "ev_a": make_record(evidence_id="ev_a"),
            "ev_c": make_record(evidence_id="ev_c", release_status="draft"),
        }
    )
    result = hydrate(
        repository,
        [
            make_candidate(
                "ev_b",
                support_label=SupportLabel.COUNTER,
                rank_reasons=["rerank", "counter"],
            ),
            make_candidate(
                "ev_c",
                support_label=SupportLabel.DIRECT,
                rank_reasons=["should-not-appear"],
            ),
            make_candidate(
                "ev_a",
                support_label=SupportLabel.INDIRECT,
                rank_reasons=["lexical"],
            ),
        ],
    )
    assert [item.evidence_id for item in result.evidence] == ["ev_b", "ev_a"]
    assert result.evidence[0].support_label is SupportLabel.COUNTER
    assert result.evidence[0].rank_reasons == ["rerank", "counter"]
    assert result.evidence[1].support_label is SupportLabel.INDIRECT
    assert result.evidence[1].rank_reasons == ["lexical"]


def test_exact_query_counts_are_computed_from_verified_text() -> None:
    repository = FakeEvidenceRepository({"ev_ok": make_record(verified_text="人人平等")})
    result = hydrate(
        repository,
        [
            make_candidate(
                channels=["exact"],
                exact_match_count=99,
                rank_reasons=["exact-count"],
            )
        ],
        exact_query=ExactMatchQuery(query="人"),
    )
    evidence = result.evidence[0]
    assert evidence.exact_match_count == 2
    assert evidence.match_offsets == [0, 1]
    assert evidence.verified_text == "人人平等"
    assert evidence.match_type == "exact"
    assert evidence.rank_reasons == ["exact-count"]
    assert result.exclusions == ()


def test_exact_candidate_without_query_is_excluded() -> None:
    repository = FakeEvidenceRepository({"ev_ok": make_record()})
    result = hydrate(
        repository,
        [
            make_candidate(
                channels=["exact"],
                exact_match_count=99,
            )
        ],
    )
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.EXACT_QUERY_REQUIRED}


def test_lexical_and_vector_without_exact_query_are_not_excluded() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_lex": make_record(evidence_id="ev_lex"),
            "ev_vec": make_record(evidence_id="ev_vec"),
        }
    )
    result = hydrate(
        repository,
        [
            make_candidate("ev_lex", channels=["lexical"]),
            make_candidate(
                "ev_vec",
                channels=["vector"],
                vector_rank=1,
                text_hash="hash_ok",
            ),
        ],
    )
    assert [item.evidence_id for item in result.evidence] == ["ev_lex", "ev_vec"]
    assert result.exclusions == ()
    assert result.evidence[0].exact_match_count is None
    assert result.evidence[0].match_offsets == []
    assert result.evidence[1].exact_match_count is None
    assert result.evidence[1].match_offsets == []


def test_exact_query_does_not_filter_non_exact_candidates() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_lex": make_record(evidence_id="ev_lex", verified_text="人人平等"),
            "ev_exact": make_record(evidence_id="ev_exact", verified_text="人人平等"),
        }
    )
    result = hydrate(
        repository,
        [
            make_candidate("ev_lex", channels=["lexical"], exact_match_count=3),
            make_candidate("ev_exact", channels=["exact"], exact_match_count=3),
        ],
        exact_query=ExactMatchQuery(query="舆论"),
    )
    assert [item.evidence_id for item in result.evidence] == ["ev_lex"]
    assert result.evidence[0].exact_match_count is None
    assert result.evidence[0].match_offsets == []
    assert exclusion_map(result) == {"ev_exact": EvidenceExclusionReason.NO_EXACT_MATCH}


def test_unpublished_neighbors_are_not_exposed() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_ok": make_record(
                prev_evidence_id="ev_prev_draft",
                next_evidence_id="ev_next_draft",
                prev_is_released=False,
                next_is_released=False,
            )
        }
    )
    result = hydrate(repository, [make_candidate()])
    evidence = result.evidence[0]
    assert evidence.prev_evidence_id is None
    assert evidence.next_evidence_id is None


def test_gate_stops_at_the_first_failure() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_multi": make_record(
                evidence_id="ev_multi",
                release_status="draft",
                volume_id="vol_other",
                printed_pages=(),
                pdf_pages=(),
            )
        }
    )
    result = hydrate(
        repository,
        [make_candidate("ev_multi")],
        make_scope(volume_ids=["vol_1"]),
    )
    assert exclusion_map(result) == {"ev_multi": EvidenceExclusionReason.NOT_PUBLISHED}


def test_content_type_outside_default_scope_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_note": make_record(
                evidence_id="ev_note",
                content_type=ContentType.EDITOR_NOTE.value,
            )
        }
    )
    result = hydrate(repository, [make_candidate("ev_note")])
    assert exclusion_map(result) == {"ev_note": EvidenceExclusionReason.OUT_OF_SCOPE}


def test_unknown_unauthorized_id_is_excluded_as_missing() -> None:
    repository = FakeEvidenceRepository({"ev_ok": make_record()})
    result = hydrate(
        repository,
        [make_candidate("ev_unknown")],
        allowed_evidence_ids=["ev_ok"],
    )
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_unknown": EvidenceExclusionReason.ID_NOT_FOUND}


def test_draft_corpus_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {"ev_ok": make_record(corpus_release_status="draft")}
    )
    result = hydrate(repository, [make_candidate()])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.METADATA_UNAVAILABLE}


def test_draft_edition_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {"ev_ok": make_record(edition_release_status="draft")}
    )
    result = hydrate(repository, [make_candidate()])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.METADATA_UNAVAILABLE}


def test_draft_volume_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {"ev_ok": make_record(volume_release_status="draft")}
    )
    result = hydrate(repository, [make_candidate()])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.METADATA_UNAVAILABLE}


def test_draft_work_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {"ev_ok": make_record(work_release_status="draft")}
    )
    result = hydrate(repository, [make_candidate()])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.METADATA_UNAVAILABLE}


def test_unverified_work_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {"ev_ok": make_record(work_verification_status="pending_review")}
    )
    result = hydrate(repository, [make_candidate()])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.METADATA_UNAVAILABLE}


def test_unverified_section_is_excluded() -> None:
    repository = FakeEvidenceRepository(
        {"ev_ok": make_record(section_verification_status="pending_review")}
    )
    result = hydrate(repository, [make_candidate()])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.METADATA_UNAVAILABLE}


def test_missing_display_metadata_is_excluded() -> None:
    repository = FakeEvidenceRepository({"ev_ok": make_record(author="")})
    result = hydrate(repository, [make_candidate()])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.METADATA_UNAVAILABLE}


def test_mixed_page_mapping_statuses_are_excluded() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_ok": make_record(
                printed_pages=("123", "124"),
                pdf_pages=(145, 146),
                page_mapping_statuses=("verified", "candidate"),
            )
        }
    )
    result = hydrate(repository, [make_candidate()])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.PAGES_UNAVAILABLE}


def test_mismatched_page_list_lengths_are_excluded() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_ok": make_record(
                printed_pages=("123", "124"),
                pdf_pages=(145,),
                page_mapping_statuses=("verified", "verified"),
            )
        }
    )
    result = hydrate(repository, [make_candidate()])
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.PAGES_UNAVAILABLE}


def test_empty_exact_query_does_not_construct_evidence() -> None:
    repository = FakeEvidenceRepository({"ev_ok": make_record()})
    result = hydrate(
        repository,
        [make_candidate(channels=["exact"])],
        exact_query=ExactMatchQuery(query="   "),
    )
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.EXACT_QUERY_EMPTY}


def test_exact_zero_hits_do_not_construct_evidence() -> None:
    repository = FakeEvidenceRepository({"ev_ok": make_record(verified_text="人人平等")})
    result = hydrate(
        repository,
        [make_candidate(channels=["exact"], exact_match_count=99)],
        exact_query=ExactMatchQuery(query="舆论"),
    )
    assert result.evidence == ()
    assert exclusion_map(result) == {"ev_ok": EvidenceExclusionReason.NO_EXACT_MATCH}


def test_production_code_constructs_evidence_only_in_service() -> None:
    root = Path(__file__).resolve().parents[2] / "packages" / "marx_engels"
    allowed = (root / "evidence" / "service.py").resolve()
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            constructed = isinstance(func, ast.Name) and func.id == "Evidence"
            constructed = constructed or (
                isinstance(func, ast.Attribute) and func.attr == "Evidence"
            )
            if constructed and path.resolve() != allowed:
                offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert offenders == []
