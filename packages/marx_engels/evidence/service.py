"""Evidence service façade; storage hydration is implemented in its worktree."""

from collections.abc import Sequence

from marx_engels.contracts import Candidate, Evidence, SearchScope
from marx_engels.retrieval_core import EvidenceHydrator


class EvidenceService:
    """The only service allowed to produce public Evidence objects."""

    def __init__(self, hydrator: EvidenceHydrator) -> None:
        self._hydrator = hydrator

    async def hydrate(
        self, candidates: Sequence[Candidate], scope: SearchScope
    ) -> list[Evidence]:
        return await self._hydrator.hydrate(candidates, scope)
