"""MinerU precision-API adapter. HTTP is injectable so tests never touch the network."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from marx_engels.ingestion.cancel import CancellationToken
from marx_engels.ingestion.constants import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    CHUNK_POLL_DEADLINE_SECONDS,
    DOWNLOAD_TIMEOUT_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    INITIAL_BACKOFF_SECONDS,
    MAX_BACKOFF_SECONDS,
    MAX_RETRIES,
    POLL_INTERVAL_SECONDS,
    UPLOAD_TIMEOUT_SECONDS,
)
from marx_engels.ingestion.models import ExtractOptions, ProviderTask
from marx_engels.ingestion.providers.errors import (
    AuthenticationError,
    PermanentProviderError,
    PollTimeoutError,
    ProviderError,
    QuotaExceededError,
    RateLimitError,
    TransientProviderError,
)
from marx_engels.ingestion.secrets import redact_secrets

LOGGER = logging.getLogger(__name__)
_TERMINAL_STATES = {"done", "failed"}
_AUTH_CODES = {"A0202", "A0211"}
_QUOTA_CODES = {"-60018", "-60019"}
_TRANSIENT_CODES = {
    "-10001",
    "-60001",
    "-60007",
    "-60008",
    "-60009",
    "-60010",
    "-60020",
    "-60021",
    "-60022",
}


def _as_code(value: object) -> str:
    return str(value)


class MinerUClient:
    def __init__(
        self,
        token: SecretStr,
        *,
        base_url: str = "https://mineru.net/api/v4",
        api_transport: httpx.BaseTransport | None = None,
        blob_transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._sleeper = sleeper or __import__("time").sleep
        self._monotonic = monotonic or __import__("time").monotonic
        self._max_retries = max_retries
        timeout = httpx.Timeout(
            HTTP_TIMEOUT_SECONDS, write=UPLOAD_TIMEOUT_SECONDS, read=DOWNLOAD_TIMEOUT_SECONDS
        )
        secret = token.get_secret_value()
        self._api = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
                "Accept": "*/*",
            },
            timeout=timeout,
            transport=api_transport,
            follow_redirects=True,
        )
        self._blob = httpx.Client(
            timeout=timeout,
            transport=blob_transport,
            follow_redirects=True,
        )

    @property
    def name(self) -> str:
        return ADAPTER_NAME

    @property
    def version(self) -> str:
        return ADAPTER_VERSION

    def __repr__(self) -> str:
        return f"MinerUClient(base_url={self._base_url!r}, token=**********)"

    def close(self) -> None:
        self._api.close()
        self._blob.close()

    def submit_file(
        self,
        file_path: Path,
        *,
        data_id: str,
        file_name: str,
        options: ExtractOptions,
        cancel: CancellationToken,
    ) -> str:
        cancel.raise_if_cancelled()
        payload = {
            "files": [
                {
                    "name": file_name,
                    "data_id": data_id,
                    "is_ocr": options.is_ocr,
                }
            ],
            "model_version": options.model_version,
            "language": options.language,
            "enable_table": options.enable_table,
            "enable_formula": options.enable_formula,
        }
        body = self._api_json("POST", "/file-urls/batch", json=payload, cancel=cancel)
        data = _require_dict(body.get("data"), "batch create response")
        batch_id = str(data.get("batch_id") or "")
        urls = data.get("file_urls")
        if not batch_id or not isinstance(urls, list) or not urls:
            raise PermanentProviderError("MinerU batch response missing batch_id or file_urls")
        self._put_file(str(urls[0]), file_path, cancel=cancel)
        return batch_id

    def poll_batch(
        self,
        batch_id: str,
        *,
        data_id: str,
        cancel: CancellationToken,
        deadline_monotonic: float,
    ) -> ProviderTask:
        while True:
            cancel.raise_if_cancelled()
            if self._monotonic() >= deadline_monotonic:
                raise PollTimeoutError(f"polling deadline reached for batch {batch_id}")
            body = self._api_json("GET", f"/extract-results/batch/{batch_id}", cancel=cancel)
            data = _require_dict(body.get("data"), "batch poll response")
            task = _select_result(data.get("extract_result"), data_id=data_id)
            LOGGER.info("MinerU batch %s state=%s", batch_id, task.state)
            if task.state in _TERMINAL_STATES:
                if task.state == "failed":
                    raise PermanentProviderError(task.err_msg or "MinerU extract failed")
                if not task.full_zip_url:
                    raise PermanentProviderError("MinerU done response missing full_zip_url")
                return task
            remaining = deadline_monotonic - self._monotonic()
            self._sleeper(min(POLL_INTERVAL_SECONDS, max(0.0, remaining)))

    def download_archive(self, url: str, dest: Path, *, cancel: CancellationToken) -> Path:
        cancel.raise_if_cancelled()
        dest.parent.mkdir(parents=True, exist_ok=True)
        response = self._send_blob("GET", url, cancel=cancel)
        if response.status_code >= 400:
            raise TransientProviderError(
                f"archive download failed with HTTP {response.status_code}"
            )
        dest.write_bytes(response.content)
        return dest

    def _put_file(self, url: str, file_path: Path, *, cancel: CancellationToken) -> None:
        cancel.raise_if_cancelled()
        size = file_path.stat().st_size
        with file_path.open("rb") as handle:
            request = self._blob.build_request(
                "PUT",
                url,
                content=handle,
                headers={"content-length": str(size)},
            )
            request.headers.pop("content-type", None)
            try:
                response = self._blob.send(request)
            except httpx.HTTPError as exc:
                raise TransientProviderError(_safe_http_error(exc)) from None
        if response.status_code not in {200, 201}:
            raise TransientProviderError(f"signed upload failed with HTTP {response.status_code}")

    def _api_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        cancel: CancellationToken,
    ) -> dict[str, Any]:
        delay = INITIAL_BACKOFF_SECONDS
        last_error: ProviderError | None = None
        for attempt in range(1, self._max_retries + 1):
            cancel.raise_if_cancelled()
            try:
                response = self._api.request(method, path, json=json)
            except httpx.HTTPError as exc:
                last_error = TransientProviderError(_safe_http_error(exc))
            else:
                last_error = self._map_response(response)
                if last_error is None:
                    payload = _parse_json(response)
                    return payload
                if isinstance(
                    last_error, AuthenticationError | QuotaExceededError | PermanentProviderError
                ):
                    raise last_error
            if attempt == self._max_retries:
                break
            wait = delay
            if isinstance(last_error, RateLimitError) and last_error.retry_after is not None:
                wait = last_error.retry_after
            LOGGER.warning("MinerU request retry %s/%s after error", attempt, self._max_retries)
            self._sleeper(wait)
            delay = min(MAX_BACKOFF_SECONDS, delay * 2)
        assert last_error is not None
        raise last_error

    def _map_response(self, response: httpx.Response) -> ProviderError | None:
        if response.status_code == 429:
            retry_after = _retry_after(response)
            return RateLimitError("MinerU returned HTTP 429", retry_after=retry_after)
        if response.status_code in {401, 403}:
            return AuthenticationError("MinerU rejected the configured token")
        if response.status_code >= 500:
            return TransientProviderError(f"MinerU returned HTTP {response.status_code}")
        if response.status_code >= 400:
            return PermanentProviderError(f"MinerU returned HTTP {response.status_code}")
        payload = _parse_json(response)
        code = _as_code(payload.get("code"))
        if code in {"0", "0.0"}:
            return None
        message = redact_secrets(str(payload.get("msg") or f"MinerU code {code}"))
        if code in _AUTH_CODES:
            return AuthenticationError("MinerU token is invalid or expired")
        if code in _QUOTA_CODES:
            return QuotaExceededError(message)
        if code in _TRANSIENT_CODES:
            return TransientProviderError(message)
        return PermanentProviderError(message)

    def _send_blob(self, method: str, url: str, *, cancel: CancellationToken) -> httpx.Response:
        cancel.raise_if_cancelled()
        try:
            return self._blob.request(method, url)
        except httpx.HTTPError as exc:
            raise TransientProviderError(_safe_http_error(exc)) from None


def _parse_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise TransientProviderError("MinerU returned non-JSON body") from exc
    if not isinstance(payload, dict):
        raise PermanentProviderError("MinerU JSON root is not an object")
    return payload


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PermanentProviderError(f"{label} is not an object")
    return value


def _select_result(extract_result: object, *, data_id: str) -> ProviderTask:
    rows: list[object]
    if isinstance(extract_result, list):
        rows = extract_result
    elif isinstance(extract_result, dict):
        rows = [extract_result]
    else:
        rows = []
    chosen: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("data_id") or "") == data_id:
            chosen = row
            break
        if chosen is None:
            chosen = row
    if chosen is None:
        return ProviderTask(batch_id="", data_id=data_id, file_name="", state="pending")
    progress = (
        chosen.get("extract_progress") if isinstance(chosen.get("extract_progress"), dict) else {}
    )
    return ProviderTask(
        batch_id=str(chosen.get("batch_id") or ""),
        data_id=str(chosen.get("data_id") or data_id),
        file_name=str(chosen.get("file_name") or ""),
        state=str(chosen.get("state") or "pending"),
        full_zip_url=str(chosen.get("full_zip_url") or "") or None,
        err_msg=str(chosen.get("err_msg") or "") or None,
        extracted_pages=_optional_int(
            progress.get("extracted_pages") if isinstance(progress, dict) else None
        ),
        total_pages=_optional_int(
            progress.get("total_pages") if isinstance(progress, dict) else None
        ),
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _safe_http_error(exc: Exception) -> str:
    return redact_secrets(f"{type(exc).__name__}: network error")


def default_poll_deadline(
    monotonic: Callable[[], float], *, seconds: float = CHUNK_POLL_DEADLINE_SECONDS
) -> float:
    return monotonic() + seconds
