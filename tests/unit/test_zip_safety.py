import io
import zipfile
from pathlib import Path

import pytest
from tests.helpers import build_result_zip

from marx_engels.ingestion.results import classify_artifact, extract_and_register
from marx_engels.ingestion.zipsafe import ZipSlipError, safe_extract


def test_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.md", "nope")
    zip_path = tmp_path / "bad.zip"
    zip_path.write_bytes(buffer.getvalue())
    with pytest.raises(ZipSlipError):
        safe_extract(zip_path, tmp_path / "out")


def test_safe_extract_rejects_absolute_path(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("/tmp/evil.md", "nope")
    zip_path = tmp_path / "abs.zip"
    zip_path.write_bytes(buffer.getvalue())
    with pytest.raises(ZipSlipError):
        safe_extract(zip_path, tmp_path / "out")


def test_register_discovers_known_and_unknown_names(tmp_path: Path) -> None:
    archive = tmp_path / "result.zip"
    archive.write_bytes(build_result_zip())
    artifacts = extract_and_register(archive, tmp_path / "unpacked")
    kinds = {item.kind for item in artifacts}
    assert "full_markdown" in kinds
    assert "content_list" in kinds
    assert "middle" in kinds
    assert "model" in kinds
    assert all(item.layer.value == "raw" for item in artifacts)
    assert classify_artifact("nested/layout.json") == "middle"
