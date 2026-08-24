"""Closed vocabularies that form part of contract V1."""

from enum import StrEnum


class SearchMode(StrEnum):
    EXACT = "exact"
    CLAIM = "claim"
    TIMELINE = "timeline"
    THEMATIC = "thematic"


class ContentType(StrEnum):
    MAIN_TEXT = "main_text"
    AUTHOR_NOTE = "author_note"
    EDITOR_NOTE = "editor_note"
    FOOTNOTE = "footnote"


class AuthorCode(StrEnum):
    MARX = "marx"
    ENGELS = "engels"
    COAUTHORED = "coauthored"
    ATTRIBUTED = "attributed"
    UNKNOWN = "unknown"


class DatePrecision(StrEnum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    RANGE = "range"
    APPROXIMATE = "approximate"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


class SupportLabel(StrEnum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    COUNTER = "counter"
    CONTEXT_ONLY = "context_only"
    IRRELEVANT = "irrelevant"
