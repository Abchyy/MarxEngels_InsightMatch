from pydantic import ValidationError

from marx_engels.contracts import SearchMode, SearchRequest, SearchScope


def scope() -> SearchScope:
    return SearchScope(corpus_ids=["marx_engels_collected_works_cn"])


def test_contract_models_are_frozen_and_closed() -> None:
    request = SearchRequest(query="舆论", mode=SearchMode.EXACT, scope=scope())
    try:
        request.query = "changed"  # type: ignore[misc]
    except ValidationError:
        pass
    else:
        raise AssertionError("frozen contract accepted mutation")

    try:
        SearchRequest.model_validate(
            {
                "query": "舆论",
                "mode": "exact",
                "scope": {"corpus_ids": ["marx_engels_collected_works_cn"]},
                "unexpected": True,
            }
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("closed contract accepted an extra field")


def test_scope_rejects_duplicates() -> None:
    try:
        SearchScope(corpus_ids=["same", "same"])
    except ValidationError:
        pass
    else:
        raise AssertionError("duplicate scope values were accepted")


def test_document_order_is_limited_to_supported_modes() -> None:
    try:
        SearchRequest(
            query="一个观点",
            mode=SearchMode.CLAIM,
            scope=scope(),
            sort="document_order",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("claim accepted document_order")
