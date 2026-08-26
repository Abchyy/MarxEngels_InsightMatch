from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from tests.helpers import write_pdf

from marx_engels.ingestion.cancel import CancellationToken
from marx_engels.ingestion.models import ExtractOptions
from marx_engels.ingestion.providers.errors import (
    AuthenticationError,
    RateLimitError,
    TransientProviderError,
)
from marx_engels.ingestion.providers.mineru import MinerUClient

TOKEN = "super-secret-mineru-token-value"


class ScriptedTransport(httpx.BaseTransport):
    def __init__(self, script: list[httpx.Response | Exception]) -> None:
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(api: ScriptedTransport, blob: ScriptedTransport | None = None) -> MinerUClient:
    return MinerUClient(
        SecretStr(TOKEN),
        api_transport=api,
        blob_transport=blob or api,
        sleeper=lambda _delay: None,
        monotonic=lambda: 0.0,
        max_retries=4,
    )


def test_batch_upload_put_omits_content_type(tmp_path: Path) -> None:
    pdf = write_pdf(tmp_path / "demo.pdf", ["page"])
    api = ScriptedTransport(
        [
            httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"batch_id": "batch-1", "file_urls": ["https://oss.test/upload"]},
                },
            )
        ]
    )
    blob = ScriptedTransport([httpx.Response(200)])
    client = _client(api, blob)
    batch_id = client.submit_file(
        pdf,
        data_id="chunk-1",
        file_name="demo.pdf",
        options=ExtractOptions(is_ocr=False),
        cancel=CancellationToken(),
    )
    assert batch_id == "batch-1"
    put = blob.requests[0]
    assert put.method == "PUT"
    assert "content-type" not in put.headers
    assert "authorization" not in put.headers


def test_poll_reaches_done_and_download_uses_blob_client(tmp_path: Path) -> None:
    api = ScriptedTransport(
        [
            httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "extract_result": [{"data_id": "chunk-1", "state": "running"}],
                    },
                },
            ),
            httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "data_id": "chunk-1",
                                "state": "done",
                                "full_zip_url": "https://cdn.test/result.zip",
                            }
                        ]
                    },
                },
            ),
        ]
    )
    blob = ScriptedTransport([httpx.Response(200, content=b"zip-bytes")])
    clock = {"t": 0.0}

    def monotonic() -> float:
        return clock["t"]

    def sleeper(_delay: float) -> None:
        clock["t"] += 1

    client = MinerUClient(
        SecretStr(TOKEN),
        api_transport=api,
        blob_transport=blob,
        sleeper=sleeper,
        monotonic=monotonic,
    )
    task = client.poll_batch(
        "batch-1", data_id="chunk-1", cancel=CancellationToken(), deadline_monotonic=30
    )
    dest = tmp_path / "out.zip"
    client.download_archive(task.full_zip_url or "", dest, cancel=CancellationToken())
    assert dest.read_bytes() == b"zip-bytes"
    assert blob.requests[0].url.host == "cdn.test"
    assert "authorization" not in blob.requests[0].headers


def test_retries_429_and_5xx_then_auth_does_not_retry() -> None:
    api = ScriptedTransport(
        [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(503),
            httpx.Response(200, json={"code": "A0202", "msg": "Invalid Token"}),
        ]
    )
    client = _client(api)
    with pytest.raises(AuthenticationError) as exc:
        client._api_json("GET", "/extract-results/batch/x", cancel=CancellationToken())
    assert TOKEN not in str(exc.value)
    assert TOKEN not in repr(client)


def test_rate_limit_error_is_retryable() -> None:
    error = RateLimitError("MinerU returned HTTP 429", retry_after=2)
    assert error.retryable is True
    transient = TransientProviderError("MinerU returned HTTP 500")
    assert transient.retryable is True
