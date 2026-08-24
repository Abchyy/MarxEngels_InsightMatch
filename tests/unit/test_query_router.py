from marx_engels.contracts import SearchMode
from marx_engels.pipelines.query_router import suggest_mode


def test_short_term_suggests_exact() -> None:
    result = suggest_mode("舆论")
    assert result.suggested_mode is SearchMode.EXACT
    assert result.requires_user_selection is False


def test_question_requires_explicit_organization_choice() -> None:
    result = suggest_mode("马克思恩格斯如何看待舆论？")
    assert result.suggested_mode is None
    assert result.requires_user_selection is True
    assert result.allowed_modes == [SearchMode.TIMELINE, SearchMode.THEMATIC]
