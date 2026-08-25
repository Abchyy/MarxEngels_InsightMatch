"""Corpus-pipeline runtime settings. Token values are never logged."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CorpusSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pdf_asset_root: Path = Path("runtime-data/assets/pdf")
    corpus_data_root: Path = Path("runtime-data/corpus")
    mineru_api_token: SecretStr | None = None
    mineru_base_url: str = "https://mineru.net/api/v4"
    mineru_concurrency: int = Field(default=2, ge=1, le=2)

    def token_configured(self) -> bool:
        token = self.mineru_api_token
        return token is not None and bool(token.get_secret_value().strip())
