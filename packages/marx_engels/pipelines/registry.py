"""Pipeline registration prevents invisible mode switching."""

from marx_engels.contracts import SearchMode
from marx_engels.retrieval_core import SearchPipeline


class PipelineRegistry:
    def __init__(self, pipelines: dict[SearchMode, SearchPipeline]) -> None:
        missing = set(SearchMode) - set(pipelines)
        if missing:
            missing_values = ", ".join(sorted(mode.value for mode in missing))
            raise ValueError(f"missing pipelines: {missing_values}")
        self._pipelines = dict(pipelines)

    def get(self, mode: SearchMode) -> SearchPipeline:
        return self._pipelines[mode]
