"""Synthetic PDF/ZIP fixtures for corpus-pipeline tests."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(page_texts: list[str], *, junk_per_page: int = 0) -> bytes:
    if not page_texts:
        raise ValueError("build_pdf requires at least one page")
    n = len(page_texts)
    font_id = 3
    page_ids = [4 + i * 2 for i in range(n)]
    content_ids = [5 + i * 2 for i in range(n)]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Count {n} /Kids [{kids}] >>".encode("latin-1")
    for index, text in enumerate(page_texts):
        content = f"BT /F1 12 Tf 72 700 Td ({_escape(text)}) Tj ET"
        if junk_per_page:
            content += " " + " ".join(["0"] * max(1, junk_per_page // 2))
        stream = content.encode("latin-1")
        content_id = content_ids[index]
        page_id = page_ids[index]
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"
        )
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("latin-1")

    max_id = max(objects)
    out = bytearray(b"%PDF-1.4\n")
    offsets = {0: 0}
    for obj_id in range(1, max_id + 1):
        offsets[obj_id] = len(out)
        out.extend(f"{obj_id} 0 obj\n".encode("latin-1"))
        out.extend(objects[obj_id])
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {max_id + 1}\n".encode("latin-1"))
    out.extend(b"0000000000 65535 f \n")
    for obj_id in range(1, max_id + 1):
        out.extend(f"{offsets[obj_id]:010d} 00000 n \n".encode("latin-1"))
    out.extend(
        f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return bytes(out)


def write_content_list(path: Path, pages: list[list[dict[str, object]]]) -> Path:
    items: list[dict[str, object]] = []
    for page_idx, blocks in enumerate(pages):
        for block in blocks:
            payload = dict(block)
            payload.setdefault("page_idx", page_idx)
            items.append(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return path


def seed_completed_all_run(
    data_root: Path,
    *,
    volume_pages: dict[int, list[list[dict[str, object]]]],
    chunk_size: int = 3,
    run_id: str = "run_test_all",
    source_sha256: str = "a" * 64,
) -> str:
    """Write a completed ALL extraction layout that assemble can read without MinerU."""
    from datetime import UTC, datetime

    from marx_engels.corpus_registry.ids import expected_filename, volume_id
    from marx_engels.ingestion.atomic import atomic_write_json, atomic_write_yaml
    from marx_engels.ingestion.mapping import mapping_from_range
    from marx_engels.ingestion.paths import CorpusLayout

    layout = CorpusLayout(data_root)
    layout.ensure()
    now = datetime.now(UTC).isoformat()
    chunks: list[dict[str, object]] = []
    volumes_state: dict[str, object] = {}
    for volume_number, pages in sorted(volume_pages.items()):
        vid = volume_id(volume_number)
        atomic_write_yaml(
            layout.source_record_path(vid),
            {
                "source_record_id": f"src_{vid}_test",
                "corpus_id": "marx_engels_collected_works_cn",
                "edition_id": "people_press_2009_cn",
                "volume_id": vid,
                "volume_number": volume_number,
                "file_name": expected_filename(volume_number),
                "source_uri": f"internal://corpus/mecw/v{volume_number:02d}",
                "file_size_bytes": 1,
                "sha256": source_sha256,
                "pdf_page_count": len(pages),
                "registered_at": now,
                "status": "extracted",
                "rights_note": "待版权台账确认",
            },
        )
        volumes_state[str(volume_number)] = {
            "file_name": expected_filename(volume_number),
            "status": "extracted",
            "pdf_page_count": len(pages),
            "sha256": source_sha256,
        }
        start = 1
        while start <= len(pages):
            end = min(len(pages), start + chunk_size - 1)
            chunk_pages = pages[start - 1 : end]
            chunk_id = f"chunk_v{volume_number:02d}_{start:04d}_{end:04d}_{source_sha256[:12]}"
            mapping = mapping_from_range(
                chunk_id=chunk_id,
                volume_number=volume_number,
                source_sha256=source_sha256,
                chunk_sha256="b" * 64,
                start_page=start,
                end_page=end,
            )
            result_dir = layout.result_dir(run_id, volume_number, chunk_id)
            write_content_list(result_dir / "content_list.json", chunk_pages)
            atomic_write_json(
                result_dir / "page_mapping.json", json.loads(mapping.model_dump_json())
            )
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "volume_number": volume_number,
                    "source_sha256": source_sha256,
                    "chunk_sha256": "b" * 64,
                    "original_start_page": start,
                    "original_end_page": end,
                    "chunk_page_count": end - start + 1,
                    "offset": start - 1,
                    "file_name": f"{chunk_id}.pdf",
                    "status": "completed",
                    "fingerprint": "fp",
                    "batch_id": "batch",
                    "data_id": chunk_id,
                    "error": None,
                    "layer": "raw",
                }
            )
            start = end + 1
    atomic_write_json(
        layout.pipeline_state_path(),
        {
            "schema_version": 1,
            "corpus_id": "marx_engels_collected_works_cn",
            "active_run_id": run_id,
            "volumes": volumes_state,
            "runs": {
                run_id: {
                    "run_id": run_id,
                    "mode": "all",
                    "status": "completed",
                    "created_at": now,
                    "updated_at": now,
                    "provider": "fake",
                    "provider_version": "1.0.0",
                    "options": {
                        "model_version": "vlm",
                        "language": "ch",
                        "enable_table": True,
                        "enable_formula": True,
                        "is_ocr": False,
                    },
                    "chunks": chunks,
                    "notes": "test",
                }
            },
        },
    )
    return run_id


def write_pdf(path: Path, page_texts: list[str], *, junk_per_page: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_pdf(page_texts, junk_per_page=junk_per_page))
    return path


def build_result_zip(*, markdown: str = "# raw\n", content_list: str = "[]\n") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("full.md", markdown)
        archive.writestr("content_list.json", content_list)
        archive.writestr("middle.json", "{}\n")
        archive.writestr("model.json", "{}\n")
    return buffer.getvalue()
