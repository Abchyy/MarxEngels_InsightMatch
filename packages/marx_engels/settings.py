"""Validated runtime settings with no production path defaults."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "staging", "production"] = "local"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    sqlite_database_path: Path = Path("runtime-data/sqlite/corpus.db")
    sqlite_busy_timeout_ms: int = Field(default=5000, ge=0, le=60000)
    lancedb_uri: Path = Path("runtime-data/lancedb/current")
    pdf_asset_root: Path = Path("runtime-data/assets/pdf")
    active_data_version: str | None = None
    active_index_version: str | None = None
    embedding_provider: str = "not_configured"
    embedding_model: str = "not_configured"
    embedding_dimension: int = Field(default=1024, gt=0)
    query_log_policy: Literal["full", "hash", "disabled"] = "hash"
