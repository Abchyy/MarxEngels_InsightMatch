"""Internal TimelinePipeline ports; not part of the frozen public contracts."""

from collections.abc import Sequence
from typing import Protocol

from marx_engels.contracts import Evidence, ReleaseInfo, SearchOverview, SearchScope


class TimelineReleaseProvider(Protocol):
    """Resolves the published data/index identity for a frozen request scope."""

    def release_for(self, scope: SearchScope) -> ReleaseInfo: ...


class TimelineOverviewProvider(Protocol):
    """Counts works and volumes from authoritative identities, not display titles."""

    def overview(self, evidence: Sequence[Evidence]) -> SearchOverview: ...


class TimelineSummaryProvider(Protocol):
    """Optional machine stage summary; must not invent evidence IDs."""

    async def summarize_group(
        self, query: str, group_id: str, evidence: Sequence[Evidence]
    ) -> str | None: ...
