"""Typed errors for extraction providers. Messages are redacted of secrets."""

from __future__ import annotations

from marx_engels.ingestion.secrets import redact_secrets


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, code: str | None = None) -> None:
        super().__init__(redact_secrets(message))
        self.retryable = retryable
        self.code = code

    def __str__(self) -> str:
        return redact_secrets(super().__str__())


class AuthenticationError(ProviderError):
    def __init__(self, message: str = "provider authentication failed") -> None:
        super().__init__(message, retryable=False, code="auth")


class RateLimitError(ProviderError):
    def __init__(
        self, message: str = "provider rate-limited", *, retry_after: float | None = None
    ) -> None:
        super().__init__(message, retryable=True, code="rate_limit")
        self.retry_after = retry_after


class TransientProviderError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True, code="transient")


class QuotaExceededError(ProviderError):
    def __init__(self, message: str = "provider quota exceeded") -> None:
        super().__init__(message, retryable=False, code="quota")


class PermanentProviderError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False, code="permanent")


class PollTimeoutError(ProviderError):
    def __init__(self, message: str = "polling deadline reached") -> None:
        super().__init__(message, retryable=True, code="poll_timeout")
