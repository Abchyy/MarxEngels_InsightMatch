"""Corpus package and scope registry boundaries."""

from marx_engels.corpus_registry.ids import (
    CORPUS_ID,
    EDITION_ID,
    EXPECTED_VOLUME_COUNT,
    expected_filename,
    volume_id,
)
from marx_engels.corpus_registry.inventory import InventoryError, discover_volumes, register_sources
from marx_engels.corpus_registry.manifest import CorpusManifest
from marx_engels.corpus_registry.models import SourceRecord, SourceStatus

__all__ = [
    "CORPUS_ID",
    "EDITION_ID",
    "EXPECTED_VOLUME_COUNT",
    "CorpusManifest",
    "InventoryError",
    "SourceRecord",
    "SourceStatus",
    "discover_volumes",
    "expected_filename",
    "register_sources",
    "volume_id",
]
