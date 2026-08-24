"""Version-isolated LanceDB schema and connection adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa

VECTOR_TABLE_FIELDS = (
    "retrieval_unit_id",
    "evidence_id",
    "corpus_id",
    "edition_id",
    "volume_id",
    "work_id",
    "content_type",
    "search_text",
    "vector",
    "text_hash",
    "embedding_provider",
    "embedding_model",
    "data_version",
    "index_version",
    "release_status",
)


def passage_vector_schema(dimension: int) -> pa.Schema:
    if dimension <= 0:
        raise ValueError("embedding dimension must be positive")
    return pa.schema(
        [
            pa.field("retrieval_unit_id", pa.string(), nullable=False),
            pa.field("evidence_id", pa.string(), nullable=False),
            pa.field("corpus_id", pa.string(), nullable=False),
            pa.field("edition_id", pa.string(), nullable=False),
            pa.field("volume_id", pa.string(), nullable=False),
            pa.field("work_id", pa.string(), nullable=False),
            pa.field("content_type", pa.string(), nullable=False),
            pa.field("search_text", pa.string(), nullable=False),
            pa.field("vector", pa.list_(pa.float32(), dimension), nullable=False),
            pa.field("text_hash", pa.string(), nullable=False),
            pa.field("embedding_provider", pa.string(), nullable=False),
            pa.field("embedding_model", pa.string(), nullable=False),
            pa.field("data_version", pa.string(), nullable=False),
            pa.field("index_version", pa.string(), nullable=False),
            pa.field("release_status", pa.string(), nullable=False),
        ]
    )


class LanceDatabase:
    """Keep LanceDB-specific APIs behind this adapter."""

    def __init__(self, uri: Path) -> None:
        self.uri = uri

    def connect(self) -> Any:
        import lancedb

        return lancedb.connect(str(self.uri))

    def ensure_table(self, table_name: str, *, dimension: int) -> Any:
        database = self.connect()
        if table_name in database.table_names():
            return database.open_table(table_name)
        return database.create_table(table_name, schema=passage_vector_schema(dimension))
