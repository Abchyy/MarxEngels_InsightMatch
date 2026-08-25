"""Run merge → clean → structure → IDs → page mapping without calling MinerU."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from marx_engels.ingestion.atomic import atomic_write_json, atomic_write_text
from marx_engels.ingestion.cleaning import clean_merged_pages, load_clean_pages
from marx_engels.ingestion.id_registry import IdRegistry
from marx_engels.ingestion.layer_models import PassageCandidate, ReviewIssue
from marx_engels.ingestion.page_merge import merge_raw_pages
from marx_engels.ingestion.paths import CorpusLayout
from marx_engels.ingestion.pipeline import new_run_id
from marx_engels.ingestion.printed_pages import build_page_maps, build_passage_pages
from marx_engels.ingestion.rules import CorpusRules
from marx_engels.ingestion.structure import recognize_structure

LOGGER = logging.getLogger(__name__)


def assemble_corpus(
    layout: CorpusLayout,
    *,
    extraction_run_id: str | None = None,
    rules_dir: Path | None = None,
    merge_run_id: str | None = None,
) -> dict[str, Any]:
    layout.ensure()
    rules = CorpusRules.load(rules_dir)
    merge_manifest = merge_raw_pages(
        layout, extraction_run_id=extraction_run_id, merge_run_id=merge_run_id
    )
    merge_id = str(merge_manifest["merge_run_id"])
    registry = IdRegistry.load(layout)
    clean_report = clean_merged_pages(layout, merge_id, rules=rules, registry=registry)
    clean_id = str(clean_report["clean_run_id"])
    assemble_id = f"struct_{new_run_id().removeprefix('run_')}"
    all_works: list[dict[str, Any]] = []
    all_sections: list[dict[str, Any]] = []
    all_passages: list[PassageCandidate] = []
    all_maps: list[dict[str, Any]] = []
    all_links: list[dict[str, Any]] = []
    all_issues: list[ReviewIssue] = []
    merge_root = layout.merge_dir(merge_id)
    volume_ids = sorted(path.name for path in merge_root.iterdir() if path.is_dir())
    for volume_id in volume_ids:
        try:
            pages = load_clean_pages(layout, clean_id, volume_id)
            bundle = recognize_structure(pages, rules, registry)
            page_maps = build_page_maps(pages)
            links = build_passage_pages(bundle.passages, pages, page_maps)
            all_works.extend(json.loads(item.model_dump_json()) for item in bundle.works)
            all_sections.extend(json.loads(item.model_dump_json()) for item in bundle.sections)
            all_passages.extend(bundle.passages)
            all_maps.extend(json.loads(item.model_dump_json()) for item in page_maps)
            all_links.extend(json.loads(item.model_dump_json()) for item in links)
            all_issues.extend(bundle.issues)
            all_issues.extend(
                ReviewIssue(
                    issue_id=f"issue_{volume_id}_{page.pdf_page}_manual",
                    code="manual_required_page",
                    volume_id=volume_id,
                    pdf_pages=[page.pdf_page],
                    target_id=page.page_id,
                    message=";".join(page.warnings) or "manual_required",
                    rule_version="clean-v1",
                )
                for page in pages
                if page.manual_required
            )
            atomic_write_json(
                layout.passage_dir(assemble_id) / f"{volume_id}.json",
                [json.loads(item.model_dump_json()) for item in bundle.passages],
            )
        except Exception as exc:
            LOGGER.exception("structure failed for volume %s", volume_id)
            all_issues.append(
                ReviewIssue(
                    issue_id=f"issue_{volume_id}_structure_failed",
                    code="structure_failed",
                    volume_id=volume_id,
                    pdf_pages=[],
                    message=str(exc),
                    rule_version="structure-v1",
                )
            )
    registry.save(layout)
    atomic_write_json(layout.structure_dir(assemble_id) / "works.json", all_works)
    atomic_write_json(layout.structure_dir(assemble_id) / "sections.json", all_sections)
    atomic_write_json(layout.structure_dir(assemble_id) / "page_maps.json", all_maps)
    atomic_write_json(layout.structure_dir(assemble_id) / "passage_pages.json", all_links)
    _write_issues(layout.review_issue_path(assemble_id), all_issues)
    unverified = all(
        item.verification_status.value == "unverified" and item.release_status.value == "draft"
        for item in all_passages
    )
    report = {
        "assemble_run_id": assemble_id,
        "extraction_run_id": merge_manifest["extraction_run_id"],
        "merge_run_id": merge_id,
        "clean_run_id": clean_id,
        "chunks": merge_manifest.get("chunk_count"),
        "recovered_pages": merge_manifest.get("recovered_pages"),
        "clean_pages": clean_report.get("pages"),
        "transformations": clean_report.get("transformations"),
        "clean_anomalies": clean_report.get("anomalies"),
        "works": len(all_works),
        "sections": len(all_sections),
        "passages": len(all_passages),
        "evidence_ids": len({item.evidence_id for item in all_passages}),
        "page_maps": len(all_maps),
        "passage_pages": len(all_links),
        "manual_required_passages": sum(1 for item in all_passages if item.manual_required),
        "review_issues": len(all_issues),
        "all_passages_unverified_draft": unverified,
        "volumes": merge_manifest.get("volumes"),
    }
    atomic_write_json(layout.structure_report_path(assemble_id), report)
    atomic_write_json(layout.clean_structures / "latest.json", {"assemble_run_id": assemble_id})
    return report


def _write_issues(path: Path, issues: list[ReviewIssue]) -> None:
    lines = [item.model_dump_json() for item in issues]
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
