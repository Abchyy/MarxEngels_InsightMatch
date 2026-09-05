"""Transport-independent domain errors."""

from __future__ import annotations


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = retryable


class PipelineNotImplementedError(DomainError):
    def __init__(self, mode: str) -> None:
        super().__init__(
            "PIPELINE_NOT_IMPLEMENTED",
            (
                f"The {mode} pipeline is not available in this runtime. "
                "Semantic retrieval is not connected and will not fall back to synthetic data."
            ),
            details={"mode": mode},
        )
