"""Explicit baseline placeholder; never silently fabricates search results."""

from marx_engels.contracts import SearchMode, SearchRequest, SearchResponse
from marx_engels.errors import PipelineNotImplementedError


class UnimplementedPipeline:
    def __init__(self, mode: SearchMode) -> None:
        self.mode = mode

    async def execute(self, request: SearchRequest, request_id: str) -> SearchResponse:
        del request, request_id
        raise PipelineNotImplementedError(self.mode.value)
