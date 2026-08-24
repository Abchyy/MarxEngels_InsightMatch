"""ASGI entrypoint for tools that expect an app under apps/api."""

from marx_engels.api.app import app

__all__ = ["app"]
