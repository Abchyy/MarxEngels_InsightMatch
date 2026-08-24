"""Deterministic baseline mode suggestion, replaceable behind the same contract."""

from marx_engels.contracts import ModeSuggestionResponse, SearchMode

QUESTION_MARKERS = ("如何", "怎样", "为什么", "是什么", "怎么看", "何以", "吗", "？", "?")


def suggest_mode(query: str) -> ModeSuggestionResponse:
    stripped = query.strip()
    if any(marker in stripped for marker in QUESTION_MARKERS):
        return ModeSuggestionResponse(
            suggested_mode=None,
            confidence=0.9,
            requires_user_selection=True,
            allowed_modes=[SearchMode.TIMELINE, SearchMode.THEMATIC],
            reason_code="QUESTION_OR_DOMAIN",
        )
    if len(stripped) <= 12 and not any(mark in stripped for mark in ("，", "。", ",", ".")):
        return ModeSuggestionResponse(
            suggested_mode=SearchMode.EXACT,
            confidence=0.75,
            requires_user_selection=False,
            allowed_modes=[SearchMode.EXACT, SearchMode.CLAIM],
            reason_code="SHORT_TERM",
        )
    return ModeSuggestionResponse(
        suggested_mode=SearchMode.CLAIM,
        confidence=0.65,
        requires_user_selection=False,
        allowed_modes=[SearchMode.CLAIM, SearchMode.EXACT],
        reason_code="PROPOSITION_OR_LONG_TEXT",
    )
