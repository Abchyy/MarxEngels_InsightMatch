from marx_engels.ingestion.id_registry import IdRegistry
from marx_engels.ingestion.layer_models import PassageLifecycle


def test_registry_reuses_ids_and_records_split_merge_reject() -> None:
    registry = IdRegistry()
    first = registry.evidence_id("work|1|1")
    again = registry.evidence_id("work|1|1")
    assert first == again
    page_a = registry.page_id("mecw_cn_2009_v01", 4)
    page_b = registry.page_id("mecw_cn_2009_v01", 4)
    assert page_a == page_b
    parts = registry.split_passage(first, ["work|1|1a", "work|1|1b"])
    assert len(parts) == 2
    assert registry.passages["work|1|1"]["status"] == PassageLifecycle.SUPERSEDED.value
    assert parts[0] != first
    merged = registry.merge_passages(parts, "work|1|merged")
    assert merged not in parts
    registry.reject_passage(merged)
    assert registry.passages["work|1|merged"]["status"] == PassageLifecycle.REJECTED.value
    # rejected records remain in the registry
    assert "work|1|1" in registry.passages
