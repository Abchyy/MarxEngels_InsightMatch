from marx_engels.retrieval_core.units import retrieval_unit_id, retrieval_units_for_passage


def test_short_passage_emits_one_stable_unit() -> None:
    units = retrieval_units_for_passage("ev_1", "短文本")
    assert len(units) == 1
    assert units[0].retrieval_unit_id == "ru_ev_1_1"
    assert units[0].evidence_id == "ev_1"
    assert units[0].search_text == "短文本"
    assert units[0].search_text_hash != units[0].search_text


def test_long_passage_split_is_deterministic() -> None:
    text = ("这是一句完整的话。" * 80) + "结尾。"
    first = retrieval_units_for_passage("ev_long", text, char_limit=80)
    second = retrieval_units_for_passage("ev_long", text, char_limit=80)
    assert len(first) > 1
    assert [item.retrieval_unit_id for item in first] == [
        retrieval_unit_id("ev_long", index) for index in range(1, len(first) + 1)
    ]
    assert first == second
    assert "".join(item.search_text for item in first) == text
