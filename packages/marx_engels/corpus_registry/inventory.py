"""Discover and validate the ten collected-works PDF volumes."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from marx_engels.corpus_registry.hashing import sha256_file
from marx_engels.corpus_registry.ids import (
    CORPUS_ID,
    EDITION_ID,
    EXPECTED_VOLUME_COUNT,
    NUMERAL_TO_VOLUME,
    expected_filename,
    source_record_id,
    source_uri,
    volume_id,
)
from marx_engels.corpus_registry.models import InventoryIssue, SourceRecord, SourceStatus

_VOLUME_IN_NAME = re.compile(r"第([一二三四五六七八九十]+)卷")
_LATIN_VOLUME = re.compile(
    r"(?:^|[_\-\s])v(?:ol(?:ume)?)?0*([1-9]|10)(?:[_\-\s.]|$)", re.IGNORECASE
)


class InventoryError(Exception):
    def __init__(self, issues: list[InventoryIssue]) -> None:
        self.issues = issues
        summary = "; ".join(issue.message for issue in issues) or "inventory failed"
        super().__init__(summary)


@dataclass(frozen=True)
class DiscoveredVolume:
    volume_number: int
    path: Path
    file_name: str
    file_size_bytes: int
    sha256: str


def parse_volume_number(file_name: str) -> int | None:
    match = _VOLUME_IN_NAME.search(file_name)
    if match:
        numeral = match.group(1)
        if numeral in NUMERAL_TO_VOLUME:
            return NUMERAL_TO_VOLUME[numeral]
        return None
    latin = _LATIN_VOLUME.search(file_name)
    if latin:
        return int(latin.group(1))
    return None


def list_pdfs(asset_root: Path) -> list[Path]:
    if not asset_root.exists():
        raise InventoryError(
            [
                InventoryIssue(
                    code="missing_asset_root",
                    message="PDF_ASSET_ROOT does not exist.",
                )
            ]
        )
    files = [
        path for path in asset_root.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"
    ]
    return sorted(files, key=lambda item: item.name)


def discover_volumes(asset_root: Path) -> tuple[list[DiscoveredVolume], list[InventoryIssue]]:
    issues: list[InventoryIssue] = []
    grouped: dict[int, list[Path]] = defaultdict(list)
    try:
        pdfs = list_pdfs(asset_root)
    except InventoryError as exc:
        return [], list(exc.issues)

    for path in pdfs:
        volume_number = parse_volume_number(path.name)
        if volume_number is None:
            issues.append(
                InventoryIssue(
                    code="unparseable_filename",
                    message=f"Cannot determine volume number from filename {path.name}.",
                    file_name=path.name,
                )
            )
            continue
        grouped[volume_number].append(path)

    for volume_number in range(1, EXPECTED_VOLUME_COUNT + 1):
        matches = grouped.get(volume_number, [])
        if not matches:
            issues.append(
                InventoryIssue(
                    code="missing_volume",
                    message=f"Missing volume {volume_number} ({expected_filename(volume_number)}).",
                    volume_number=volume_number,
                )
            )
        elif len(matches) > 1:
            names = ", ".join(path.name for path in matches)
            issues.append(
                InventoryIssue(
                    code="duplicate_volume",
                    message=f"Volume {volume_number} is duplicated: {names}.",
                    volume_number=volume_number,
                )
            )

    unexpected = [number for number in grouped if number < 1 or number > EXPECTED_VOLUME_COUNT]
    for volume_number in sorted(unexpected):
        for path in grouped[volume_number]:
            issues.append(
                InventoryIssue(
                    code="unexpected_volume",
                    message=f"Unexpected volume number {volume_number} in {path.name}.",
                    file_name=path.name,
                    volume_number=volume_number,
                )
            )

    discovered: list[DiscoveredVolume] = []
    for volume_number in range(1, EXPECTED_VOLUME_COUNT + 1):
        matches = grouped.get(volume_number, [])
        if len(matches) != 1:
            continue
        path = matches[0]
        size = path.stat().st_size
        if size <= 0:
            issues.append(
                InventoryIssue(
                    code="empty_file",
                    message=f"Volume {volume_number} file {path.name} is empty.",
                    file_name=path.name,
                    volume_number=volume_number,
                )
            )
            continue
        discovered.append(
            DiscoveredVolume(
                volume_number=volume_number,
                path=path,
                file_name=path.name,
                file_size_bytes=size,
                sha256=sha256_file(path),
            )
        )
    return discovered, issues


def register_sources(
    asset_root: Path, *, registered_at: datetime | None = None
) -> list[SourceRecord]:
    discovered, issues = discover_volumes(asset_root)
    if issues:
        raise InventoryError(issues)
    stamp = registered_at or datetime.now(UTC)
    return [
        SourceRecord(
            source_record_id=source_record_id(volume_id(item.volume_number), item.sha256),
            corpus_id=CORPUS_ID,
            edition_id=EDITION_ID,
            volume_id=volume_id(item.volume_number),
            volume_number=item.volume_number,
            file_name=item.file_name,
            source_uri=source_uri(item.volume_number),
            file_size_bytes=item.file_size_bytes,
            sha256=item.sha256,
            registered_at=stamp,
            status=SourceStatus.REGISTERED,
        )
        for item in discovered
    ]
