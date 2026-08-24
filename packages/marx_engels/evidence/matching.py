"""Internal exact-match helpers computed from SQLite verified_text."""


def non_overlapping_match_offsets(text: str, query: str) -> list[int]:
    """Return start offsets of non-overlapping occurrences of ``query`` in ``text``."""

    if not query:
        return []
    offsets: list[int] = []
    start = 0
    while True:
        index = text.find(query, start)
        if index < 0:
            return offsets
        offsets.append(index)
        start = index + len(query)
