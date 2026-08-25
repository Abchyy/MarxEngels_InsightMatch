from marx_engels.corpus_registry.ids import (
    CHINESE_NUMERALS,
    EXPECTED_VOLUME_COUNT,
    expected_filename,
)


def test_golden_volume_filenames_are_unique_and_complete() -> None:
    names = [expected_filename(number) for number in range(1, EXPECTED_VOLUME_COUNT + 1)]
    assert len(names) == 10
    assert len(set(names)) == 10
    assert names[0] == "马克思恩格斯文集第一卷.pdf"
    assert names[-1] == "马克思恩格斯文集第十卷.pdf"
    assert CHINESE_NUMERALS[5] == "五"
