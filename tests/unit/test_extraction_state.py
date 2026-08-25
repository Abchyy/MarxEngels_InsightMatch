from pathlib import Path

from pydantic import SecretStr

from marx_engels.ingestion.atomic import atomic_write_json
from marx_engels.ingestion.fingerprint import extraction_fingerprint
from marx_engels.ingestion.models import ExtractOptions
from marx_engels.ingestion.providers.errors import AuthenticationError
from marx_engels.ingestion.providers.mineru import MinerUClient
from marx_engels.ingestion.secrets import redact_secrets


def test_fingerprint_changes_with_model_or_hash() -> None:
    options = ExtractOptions()
    first = extraction_fingerprint(
        source_sha256="a" * 64,
        chunk_sha256="b" * 64,
        provider="mineru",
        provider_version="1.0.0",
        options=options,
    )
    second = extraction_fingerprint(
        source_sha256="a" * 64,
        chunk_sha256="c" * 64,
        provider="mineru",
        provider_version="1.0.0",
        options=options,
    )
    ocr = extraction_fingerprint(
        source_sha256="a" * 64,
        chunk_sha256="b" * 64,
        provider="mineru",
        provider_version="1.0.0",
        options=ExtractOptions(is_ocr=True),
    )
    assert first != second
    assert first != ocr


def test_atomic_write_replaces_destination(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    atomic_write_json(path, {"ok": True})
    atomic_write_json(path, {"ok": False, "count": 2})
    assert path.read_text(encoding="utf-8").find('"count": 2') >= 0
    assert not list(tmp_path.glob("*.tmp"))


def test_token_never_appears_in_repr_or_errors() -> None:
    secret = "super-secret-mineru-token-value"
    client = MinerUClient(SecretStr(secret), sleeper=lambda _delay: None)
    error = AuthenticationError(f"Bearer {secret} rejected")
    assert secret not in repr(client)
    assert secret not in str(error)
    assert secret not in redact_secrets(f"Authorization: Bearer {secret}")
    client.close()
