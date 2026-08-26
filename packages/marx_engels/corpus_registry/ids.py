"""Stable identifiers for the Marx–Engels collected-works corpus package."""

from __future__ import annotations

CORPUS_ID = "marx_engels_collected_works_cn"
EDITION_ID = "people_press_2009_cn"
EXPECTED_VOLUME_COUNT = 10
VOLUME_ID_PREFIX = "mecw_cn_2009_v"

CHINESE_NUMERALS: dict[int, str] = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}

NUMERAL_TO_VOLUME: dict[str, int] = {value: key for key, value in CHINESE_NUMERALS.items()}

FILENAME_TEMPLATE = "马克思恩格斯文集第{numeral}卷.pdf"


def volume_id(volume_number: int) -> str:
    if volume_number < 1 or volume_number > EXPECTED_VOLUME_COUNT:
        raise ValueError(f"volume_number must be 1-{EXPECTED_VOLUME_COUNT}, got {volume_number}")
    return f"{VOLUME_ID_PREFIX}{volume_number:02d}"


def source_uri(volume_number: int) -> str:
    return f"internal://corpus/mecw/v{volume_number:02d}"


def expected_filename(volume_number: int) -> str:
    return FILENAME_TEMPLATE.format(numeral=CHINESE_NUMERALS[volume_number])


def source_record_id(volume: str, sha256: str) -> str:
    return f"src_{volume}_{sha256[:16]}"


def chunk_id(volume_number: int, start_page: int, end_page: int, source_sha256: str) -> str:
    return f"chunk_v{volume_number:02d}_{start_page:04d}_{end_page:04d}_{source_sha256[:12]}"
