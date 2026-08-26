from pathlib import Path

import pytest
from tests.helpers import write_pdf

from marx_engels.corpus_registry.hashing import sha256_file
from marx_engels.corpus_registry.ids import expected_filename, volume_id
from marx_engels.corpus_registry.inventory import (
    InventoryError,
    discover_volumes,
    parse_volume_number,
    register_sources,
)


def _seed_volumes(
    root: Path, *, volumes: range | list[int] | None = None, empty: set[int] | None = None
) -> None:
    empty = empty or set()
    for number in volumes or range(1, 11):
        path = root / expected_filename(number)
        if number in empty:
            path.write_bytes(b"")
        else:
            write_pdf(path, [f"volume {number} page {page}" for page in range(1, 4)])


def test_filename_and_volume_id_are_stable() -> None:
    assert parse_volume_number("马克思恩格斯文集第五卷.pdf") == 5
    assert parse_volume_number("马克思恩格斯文集第十卷.pdf") == 10
    assert volume_id(1) == "mecw_cn_2009_v01"
    names = [expected_filename(number) for number in range(1, 11)]
    assert len(set(names)) == 10


def test_inventory_registers_ten_unique_volumes(tmp_path: Path) -> None:
    _seed_volumes(tmp_path)
    records = register_sources(tmp_path)
    assert [record.volume_number for record in records] == list(range(1, 11))
    assert len({record.sha256 for record in records}) == 10
    assert all(record.source_uri.startswith("internal://") for record in records)
    assert all("Users" not in record.model_dump_json() for record in records)


def test_inventory_detects_missing_duplicate_and_empty(tmp_path: Path) -> None:
    _seed_volumes(tmp_path, volumes=range(1, 10), empty={9})
    (tmp_path / expected_filename(3)).write_bytes((tmp_path / expected_filename(2)).read_bytes())
    (tmp_path / "马克思恩格斯文集第三卷-副本.pdf").write_bytes(
        (tmp_path / expected_filename(2)).read_bytes()
    )
    _discovered, issues = discover_volumes(tmp_path)
    codes = {issue.code for issue in issues}
    assert "missing_volume" in codes
    assert "duplicate_volume" in codes
    assert "empty_file" in codes


def test_hash_is_stable(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / expected_filename(1), ["same text"])
    assert sha256_file(path) == sha256_file(path)


def test_register_sources_raises_on_incomplete_set(tmp_path: Path) -> None:
    write_pdf(tmp_path / expected_filename(1), ["only one"])
    with pytest.raises(InventoryError):
        register_sources(tmp_path)
