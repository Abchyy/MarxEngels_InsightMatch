"""Cancellation signal for polling loops."""

from __future__ import annotations


class ExtractionCancelled(Exception):
    """Raised when an in-flight poll or upload is cancelled."""


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise ExtractionCancelled("extraction cancelled")
