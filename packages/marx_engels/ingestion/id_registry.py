"""Persistent UUID registry. Keys are structural; IDs are never hashed from titles."""

from __future__ import annotations

import uuid
from typing import Any

from marx_engels.ingestion.atomic import atomic_write_json
from marx_engels.ingestion.layer_models import PassageLifecycle
from marx_engels.ingestion.paths import CorpusLayout
from marx_engels.ingestion.state import load_json


def _new_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"


class IdRegistry:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        data = payload or {}
        self.pages: dict[str, str] = dict(data.get("pages") or {})
        self.works: dict[str, str] = dict(data.get("works") or {})
        self.sections: dict[str, str] = dict(data.get("sections") or {})
        raw_passages = data.get("passages") or {}
        self.passages: dict[str, dict[str, Any]] = {
            str(key): dict(value) for key, value in raw_passages.items()
        }

    @classmethod
    def load(cls, layout: CorpusLayout) -> IdRegistry:
        return cls(load_json(layout.id_registry_path()))

    def save(self, layout: CorpusLayout) -> None:
        atomic_write_json(
            layout.id_registry_path(),
            {
                "schema_version": 1,
                "pages": dict(sorted(self.pages.items())),
                "works": dict(sorted(self.works.items())),
                "sections": dict(sorted(self.sections.items())),
                "passages": dict(sorted(self.passages.items())),
            },
        )

    def page_id(self, volume_id: str, pdf_page: int) -> str:
        key = f"{volume_id}|{pdf_page}"
        if key not in self.pages:
            self.pages[key] = _new_prefixed_id("page")
        return self.pages[key]

    def work_id(self, key: str) -> str:
        if key not in self.works:
            self.works[key] = _new_prefixed_id("work")
        return self.works[key]

    def section_id(self, key: str) -> str:
        if key not in self.sections:
            self.sections[key] = _new_prefixed_id("sec")
        return self.sections[key]

    def evidence_id(self, key: str, *, supersedes: list[str] | None = None) -> str:
        record = self.passages.get(key)
        if record and record.get("status") == PassageLifecycle.ACTIVE.value:
            return str(record["id"])
        evidence_id = _new_prefixed_id("ev")
        self.passages[key] = {
            "id": evidence_id,
            "status": PassageLifecycle.ACTIVE.value,
            "supersedes_id": list(supersedes or []),
            "superseded_by": [],
        }
        return evidence_id

    def lookup_passage_key(self, evidence_id: str) -> str | None:
        for key, record in self.passages.items():
            if record.get("id") == evidence_id:
                return key
        return None

    def split_passage(self, evidence_id: str, part_keys: list[str]) -> list[str]:
        source_key = self.lookup_passage_key(evidence_id)
        if source_key is None:
            raise KeyError(evidence_id)
        source = self.passages[source_key]
        new_ids = [self.evidence_id(key, supersedes=[evidence_id]) for key in part_keys]
        source["status"] = PassageLifecycle.SUPERSEDED.value
        source["superseded_by"] = list(new_ids)
        return new_ids

    def merge_passages(self, evidence_ids: list[str], new_key: str) -> str:
        merged = self.evidence_id(new_key, supersedes=list(evidence_ids))
        for evidence_id in evidence_ids:
            key = self.lookup_passage_key(evidence_id)
            if key is None or key == new_key:
                continue
            record = self.passages[key]
            record["status"] = PassageLifecycle.SUPERSEDED.value
            record["superseded_by"] = [merged]
        return merged

    def reject_passage(self, evidence_id: str) -> None:
        key = self.lookup_passage_key(evidence_id)
        if key is None:
            raise KeyError(evidence_id)
        self.passages[key]["status"] = PassageLifecycle.REJECTED.value
