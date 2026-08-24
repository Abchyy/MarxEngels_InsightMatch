"""Request ID propagation."""

from uuid import uuid4

from fastapi import Request


def request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str):
        return existing
    generated = f"req_{uuid4().hex}"
    request.state.request_id = generated
    return generated
