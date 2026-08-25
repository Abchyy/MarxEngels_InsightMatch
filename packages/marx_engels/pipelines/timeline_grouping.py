"""Organize authoritative Evidence into stable timeline groups."""

from collections.abc import Sequence

from marx_engels.contracts import DatePrecision, Evidence, ResultGroup

_KNOWN_PRECISIONS = frozenset(
    {
        DatePrecision.DAY,
        DatePrecision.MONTH,
        DatePrecision.YEAR,
        DatePrecision.RANGE,
        DatePrecision.APPROXIMATE,
    }
)
_DISPUTED = "disputed"
_UNKNOWN = "unknown"
_CALENDAR = "calendar_bucket"


def organize_timeline(
    evidence: Sequence[Evidence],
) -> tuple[list[ResultGroup], tuple[Evidence, ...]]:
    """Group by calendar decade, then disputed, then unknown. IDs stay unique."""

    unique = _unique_evidence(evidence)
    buckets: dict[tuple[str, int | None], list[Evidence]] = {}
    for item in unique:
        key = _bucket_key(item)
        buckets.setdefault(key, []).append(item)

    groups: list[ResultGroup] = []
    ordered_evidence: list[Evidence] = []
    for key in _sorted_bucket_keys(buckets):
        members = _sort_within_bucket(buckets[key])
        groups.append(_to_group(key, members))
        ordered_evidence.extend(members)
    return groups, tuple(ordered_evidence)


def _unique_evidence(evidence: Sequence[Evidence]) -> list[Evidence]:
    seen: set[str] = set()
    unique: list[Evidence] = []
    for item in evidence:
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        unique.append(item)
    return unique


def _bucket_key(evidence: Evidence) -> tuple[str, int | None]:
    if evidence.date_precision is DatePrecision.DISPUTED:
        return (_DISPUTED, None)
    if evidence.date_precision is DatePrecision.UNKNOWN:
        return (_UNKNOWN, None)
    if evidence.date_precision not in _KNOWN_PRECISIONS:
        return (_UNKNOWN, None)
    year = _parse_year(evidence.work_date_start) or _parse_year(evidence.work_date_end)
    if year is None:
        return (_UNKNOWN, None)
    return (_CALENDAR, (year // 10) * 10)


def _parse_year(value: str | None) -> int | None:
    if value is None:
        return None
    digits = value.strip()[:4]
    if len(digits) != 4 or not digits.isdigit():
        return None
    year = int(digits)
    if year < 1:
        return None
    return year


def _sorted_bucket_keys(
    buckets: dict[tuple[str, int | None], list[Evidence]],
) -> list[tuple[str, int | None]]:
    calendar = sorted(
        (key for key in buckets if key[0] == _CALENDAR),
        key=lambda key: key[1] or 0,
    )
    ordered = list(calendar)
    if (_DISPUTED, None) in buckets:
        ordered.append((_DISPUTED, None))
    if (_UNKNOWN, None) in buckets:
        ordered.append((_UNKNOWN, None))
    return ordered


def _sort_within_bucket(members: list[Evidence]) -> list[Evidence]:
    return sorted(
        members,
        key=lambda item: (
            item.work_date_start is None,
            item.work_date_start or "",
            item.work_date_end is None,
            item.work_date_end or "",
            item.volume_no,
            item.evidence_id,
        ),
    )


def _to_group(key: tuple[str, int | None], members: Sequence[Evidence]) -> ResultGroup:
    kind, decade = key
    evidence_ids = [item.evidence_id for item in members]
    if kind == _CALENDAR and decade is not None:
        approximate = any(
            item.date_precision is DatePrecision.APPROXIMATE for item in members
        )
        label = f"约{decade}年代" if approximate else f"{decade}年代"
        precision = DatePrecision.APPROXIMATE if all(
            item.date_precision is DatePrecision.APPROXIMATE for item in members
        ) else DatePrecision.YEAR
        return ResultGroup(
            group_id=f"decade_{decade}",
            label=label,
            group_type=_CALENDAR,
            evidence_ids=evidence_ids,
            date_start=f"{decade:04d}",
            date_end=f"{decade + 9:04d}",
            date_precision=precision,
        )
    if kind == _DISPUTED:
        return ResultGroup(
            group_id=_DISPUTED,
            label="年代争议",
            group_type=_DISPUTED,
            evidence_ids=evidence_ids,
            date_start=None,
            date_end=None,
            date_precision=DatePrecision.DISPUTED,
        )
    return ResultGroup(
        group_id=_UNKNOWN,
        label="时间待考",
        group_type=_UNKNOWN,
        evidence_ids=evidence_ids,
        date_start=None,
        date_end=None,
        date_precision=DatePrecision.UNKNOWN,
    )
