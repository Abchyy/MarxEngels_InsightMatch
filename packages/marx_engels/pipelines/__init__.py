"""Four independent search pipeline slots."""

from marx_engels.pipelines.exact import ExactPipeline
from marx_engels.pipelines.registry import PipelineRegistry

__all__ = ["ExactPipeline", "PipelineRegistry"]
