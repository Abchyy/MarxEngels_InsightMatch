"""Redact secrets from logs, exceptions, and diagnostic strings."""

from __future__ import annotations

import re

_BEARER = re.compile(r"(?i)(bearer\s+)\S+")
_AUTH_HEADER = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+")


def redact_secrets(text: str) -> str:
    redacted = _AUTH_HEADER.sub(r"\1[redacted]", text)
    return _BEARER.sub(r"\1[redacted]", redacted)
