"""Four independent search pipeline slots."""

from marx_engels.pipelines.claim import ClaimPipeline
from marx_engels.pipelines.exact import ExactPipeline
from marx_engels.pipelines.registry import PipelineRegistry
from marx_engels.pipelines.thematic import ThematicPipeline
from marx_engels.pipelines.timeline import TimelinePipeline

__all__ = [
    "ClaimPipeline",
    "ExactPipeline",
    "PipelineRegistry",
    "ThematicPipeline",
    "TimelinePipeline",
]
