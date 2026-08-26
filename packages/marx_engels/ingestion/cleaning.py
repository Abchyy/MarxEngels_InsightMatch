"""Deterministic Clean-layer transforms with per-change audit records."""

from __future__ import annotations

import json
import unicodedata
from collections import Counter

from marx_engels.ingestion.atomic import atomic_write_json
from marx_engels.ingestion.hashing import sha256_bytes
from marx_engels.ingestion.id_registry import IdRegistry
from marx_engels.ingestion.layer_models import (
    CleanPageRecord,
    ContentKind,
    ContentSpan,
    PageKind,
    RawBlock,
    RawPageRecord,
    TransformationRecord,
)
from marx_engels.ingestion.page_merge import load_merged_pages
from marx_engels.ingestion.paths import CorpusLayout
from marx_engels.ingestion.pipeline import new_run_id
from marx_engels.ingestion.rules import CorpusRules


def text_hash(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def clean_merged_pages(
    layout: CorpusLayout,
    merge_run_id: str,
    *,
    rules: CorpusRules | None = None,
    registry: IdRegistry | None = None,
    clean_run_id: str | None = None,
) -> dict[str, object]:
    layout.ensure()
    ruleset = rules or CorpusRules.load()
    id_registry = registry or IdRegistry.load(layout)
    clean_id = clean_run_id or f"clean_{new_run_id().removeprefix('run_')}"
    merge_root = layout.merge_dir(merge_run_id)
    volume_dirs = sorted(path for path in merge_root.iterdir() if path.is_dir())
    page_count = 0
    transform_count = 0
    anomaly_count = 0
    volume_summaries: dict[str, object] = {}
    for volume_dir in volume_dirs:
        volume_id = volume_dir.name
        pages = load_merged_pages(layout, merge_run_id, volume_id)
        headers = _repeated_headers(pages, ruleset)
        cleaned: list[CleanPageRecord] = []
        transformations: list[dict[str, object]] = []
        for raw in pages:
            page, records = clean_page(raw, ruleset, id_registry, repeated_headers=headers)
            cleaned.append(page)
            transformations.extend(json.loads(item.model_dump_json()) for item in records)
            _write_clean_page(layout, clean_id, page)
        _write_transformations(layout, clean_id, volume_id, transformations)
        page_count += len(cleaned)
        transform_count += len(transformations)
        anomalies = [page.pdf_page for page in cleaned if page.manual_required]
        anomaly_count += len(anomalies)
        volume_summaries[volume_id] = {
            "pages": len(cleaned),
            "transformations": len(transformations),
            "manual_required_pages": anomalies,
        }
    id_registry.save(layout)
    report = {
        "clean_run_id": clean_id,
        "merge_run_id": merge_run_id,
        "normalization_version": ruleset.normalization_version,
        "pages": page_count,
        "transformations": transform_count,
        "anomalies": anomaly_count,
        "volumes": volume_summaries,
    }
    atomic_write_json(layout.cleaning_report_path(clean_id), report)
    atomic_write_json(layout.clean_pages / "latest.json", {"clean_run_id": clean_id})
    return report


def clean_page(
    raw: RawPageRecord,
    rules: CorpusRules,
    registry: IdRegistry,
    *,
    repeated_headers: set[str] | None = None,
) -> tuple[CleanPageRecord, list[TransformationRecord]]:
    records: list[TransformationRecord] = []
    headers = repeated_headers or set()
    page_id = registry.page_id(raw.volume_id, raw.pdf_page)
    location = f"{raw.volume_id}:pdf_page:{raw.pdf_page}"
    nfc_text, nfc_record = _apply_nfc(raw.raw_text, location, rules)
    if nfc_record is not None:
        records.append(nfc_record)
    whitespace, ws_record = _normalize_whitespace(nfc_text, location)
    if ws_record is not None:
        records.append(ws_record)
    spans, printed_label, printed_number, classify_records = _classify_blocks(
        raw, whitespace, rules, headers, location
    )
    records.extend(classify_records)
    joined, join_records = _join_spans(spans, rules, location)
    records.extend(join_records)
    quality_warnings, quality_manual = _quality_flags(raw, joined, rules)
    warnings = list(raw.warnings) + quality_warnings
    if any(span.content_type is ContentKind.TOC for span in joined):
        page_type = PageKind.TOC
    elif not joined and (raw.missing or not raw.raw_text.strip()):
        page_type = PageKind.BLANK
    elif raw.pdf_page <= 2:
        page_type = PageKind.COVER
    else:
        page_type = PageKind.MAIN
    clean_text = "\n".join(
        span.text for span in joined if span.content_type is ContentKind.MAIN_TEXT
    )
    if not clean_text:
        clean_text = "\n".join(
            span.text
            for span in joined
            if span.content_type not in {ContentKind.HEADER, ContentKind.FOOTER}
        )
    page = CleanPageRecord(
        page_id=page_id,
        volume_id=raw.volume_id,
        volume_number=raw.volume_number,
        pdf_page=raw.pdf_page,
        clean_text=clean_text,
        text_hash=text_hash(clean_text),
        spans=joined,
        printed_page_label=printed_label,
        printed_page_number=printed_number,
        page_type=page_type,
        warnings=warnings,
        manual_required=raw.manual_required or quality_manual,
        normalization_version=rules.normalization_version,
        transformation_count=len(records),
    )
    return page, records


def load_clean_pages(
    layout: CorpusLayout, clean_run_id: str, volume_id: str
) -> list[CleanPageRecord]:
    directory = layout.clean_page_dir(clean_run_id) / volume_id
    pages = [
        CleanPageRecord.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("page_*.json"))
    ]
    return sorted(pages, key=lambda item: item.pdf_page)


def _write_clean_page(layout: CorpusLayout, clean_run_id: str, page: CleanPageRecord) -> None:
    path = layout.volume_page_file(
        layout.clean_page_dir(clean_run_id), page.volume_id, page.pdf_page
    )
    atomic_write_json(path, json.loads(page.model_dump_json()))


def _write_transformations(
    layout: CorpusLayout, clean_run_id: str, volume_id: str, records: list[dict[str, object]]
) -> None:
    path = layout.transformation_dir(clean_run_id) / volume_id / "transformations.json"
    atomic_write_json(path, records)


def _apply_nfc(
    text: str, location: str, rules: CorpusRules
) -> tuple[str, TransformationRecord | None]:
    normalized = unicodedata.normalize("NFC", text)
    if normalized == text:
        return text, None
    return normalized, _record(
        "unicode_nfc", rules.normalization_version, location, text, normalized, 1.0
    )


def _normalize_whitespace(text: str, location: str) -> tuple[str, TransformationRecord | None]:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    collapsed = [" ".join(line.split()) if line.strip() else "" for line in lines]
    while collapsed and collapsed[0] == "":
        collapsed.pop(0)
    while collapsed and collapsed[-1] == "":
        collapsed.pop()
    rebuilt: list[str] = []
    blank = False
    for line in collapsed:
        if line == "":
            if not blank:
                rebuilt.append("")
            blank = True
            continue
        blank = False
        rebuilt.append(line)
    result = "\n".join(rebuilt)
    if result == text:
        return text, None
    return result, _record("whitespace_normalize", "v1", location, text, result, 0.9)


def _classify_blocks(
    raw: RawPageRecord,
    fallback_text: str,
    rules: CorpusRules,
    repeated_headers: set[str],
    location: str,
) -> tuple[list[ContentSpan], str | None, int | None, list[TransformationRecord]]:
    records: list[TransformationRecord] = []
    spans: list[ContentSpan] = []
    printed_label: str | None = None
    printed_number: int | None = None
    blocks = raw.blocks or [
        RawBlock(source_type="text", kind="text", text=line)
        for line in fallback_text.split("\n")
        if line.strip()
    ]
    for block in blocks:
        text = unicodedata.normalize("NFC", block.text).strip()
        if not text:
            continue
        content_type, signals, joinable = _kind_for_block(block, text, rules, repeated_headers)
        if (
            content_type is ContentKind.HEADER
            and text == raw.raw_text.strip()
            and not rules.matches(rules.header_patterns, text)
            and text not in repeated_headers
        ):
            content_type = ContentKind.MAIN_TEXT
        if content_type is ContentKind.FOOTER or content_type is ContentKind.HEADER:
            records.append(
                _record(
                    "header_footer_candidate",
                    "v1",
                    location,
                    text,
                    "",
                    0.8,
                    warnings=[f"candidate:{content_type.value}"],
                )
            )
        if block.kind == "page_number" or rules.page_number_pattern.fullmatch(text):
            label, number = parse_printed_label(text)
            if label:
                printed_label = label
                printed_number = number
                records.append(_record("page_number_candidate", "v1", location, text, label, 0.75))
            content_type = (
                ContentKind.FOOTER if content_type is ContentKind.MAIN_TEXT else content_type
            )
        spans.append(
            ContentSpan(content_type=content_type, text=text, joinable=joinable, signals=signals)
        )
    return spans, printed_label, printed_number, records


def _kind_for_block(
    block: RawBlock, text: str, rules: CorpusRules, repeated_headers: set[str]
) -> tuple[ContentKind, list[str], bool]:
    signals: list[str] = [f"source:{block.source_type}"]
    if (
        block.kind == "header"
        or text in repeated_headers
        or rules.matches(rules.header_patterns, text)
    ):
        signals.append("header_rule")
        return ContentKind.HEADER, signals, False
    if block.kind == "footer" or rules.matches(rules.footer_patterns, text):
        signals.append("footer_rule")
        return ContentKind.FOOTER, signals, False
    if block.kind in {"footnote"} or rules.matches(rules.footnote_markers, text):
        editor = rules.matches(rules.editor_note_patterns, text)
        kind = ContentKind.EDITOR_NOTE if editor else ContentKind.FOOTNOTE
        signals.append("footnote_marker")
        return kind, signals, False
    if rules.matches(rules.toc_heading_patterns, text):
        return ContentKind.TOC, [*signals, "toc_heading"], False
    if rules.matches(rules.index_heading_patterns, text):
        return ContentKind.INDEX, [*signals, "index_heading"], False
    if rules.matches(rules.editor_note_patterns, text):
        return ContentKind.EDITOR_NOTE, [*signals, "editor_note"], False
    if rules.matches(rules.author_line_patterns, text):
        return ContentKind.MAIN_TEXT, [*signals, "author_line"], False
    if block.kind == "title" or block.text_level:
        return ContentKind.MAIN_TEXT, [*signals, "title_block"], False
    if _is_poetry_or_list(text, rules):
        return ContentKind.MAIN_TEXT, [*signals, "structure_preserve"], False
    return ContentKind.MAIN_TEXT, signals, True


def _join_spans(
    spans: list[ContentSpan], rules: CorpusRules, location: str
) -> tuple[list[ContentSpan], list[TransformationRecord]]:
    if not spans:
        return [], []
    records: list[TransformationRecord] = []
    joined: list[ContentSpan] = [spans[0]]
    for span in spans[1:]:
        previous = joined[-1]
        if (
            previous.joinable
            and span.joinable
            and previous.content_type is ContentKind.MAIN_TEXT
            and span.content_type is ContentKind.MAIN_TEXT
            and len(previous.text) > rules.poetry_max_line_chars
            and len(span.text) > rules.poetry_max_line_chars
            and _can_join(previous.text, span.text, rules)
        ):
            before = previous.text
            after = f"{previous.text}{span.text}"
            joined[-1] = previous.model_copy(update={"text": after})
            records.append(
                _record(
                    "cross_line_join",
                    "v1",
                    location,
                    before,
                    after,
                    0.7,
                )
            )
        else:
            joined.append(span)
    return joined, records


def _can_join(previous: str, current: str, rules: CorpusRules) -> bool:
    if not previous or not current:
        return False
    if previous[-1] in rules.sentence_terminators:
        return False
    if rules.matches(rules.list_prefixes, current):
        return False
    if rules.matches(rules.paragraph_indent_prefixes, current):
        return False
    if rules.matches(rules.section_patterns, current) or rules.matches(
        rules.work_title_markers, current
    ):
        return False
    return not rules.matches(rules.footnote_markers, current)


def _is_poetry_or_list(text: str, rules: CorpusRules) -> bool:
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) >= rules.poetry_min_short_lines and all(
        len(line) <= rules.poetry_max_line_chars for line in lines
    ):
        return True
    return any(rules.matches(rules.list_prefixes, line) for line in lines)


def _quality_flags(
    raw: RawPageRecord, spans: list[ContentSpan], rules: CorpusRules
) -> tuple[list[str], bool]:
    warnings: list[str] = []
    manual = False
    text = "\n".join(span.text for span in spans)
    replacements = text.count("\ufffd") + text.count("□") + text.count("?")
    if replacements >= rules.garbled_replacement_min and len(text) < 40:
        warnings.append("garbled_characters")
        manual = True
    if (
        len(text.strip()) < rules.low_text_char_threshold
        and not raw.missing
        and any(block.kind == "image" for block in raw.blocks)
    ):
        warnings.append("low_text_image_page")
        manual = True
    if raw.duplicate:
        warnings.append("duplicate_page")
        manual = True
    unusual = sum(
        1 for char in text if unicodedata.category(char).startswith("C") and char not in "\n\t"
    )
    if unusual:
        warnings.append("control_characters")
        manual = True
    return warnings, manual


def _repeated_headers(pages: list[RawPageRecord], rules: CorpusRules) -> set[str]:
    counter: Counter[str] = Counter()
    for page in pages:
        seen: set[str] = set()
        for block in page.blocks:
            text = block.text.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            if block.kind == "header" or rules.matches(rules.header_patterns, text):
                counter[text] += 1
    return {text for text, count in counter.items() if count >= rules.header_repeat_min_pages}


def parse_printed_label(text: str) -> tuple[str | None, int | None]:
    stripped = text.strip().replace("页", "").replace("第", "")
    if not stripped:
        return None, None
    if stripped.isdigit():
        return stripped, int(stripped)
    roman = _roman_to_int(stripped)
    if roman is not None:
        return stripped, roman
    return stripped, None


def _roman_to_int(value: str) -> int | None:
    glyphs = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    upper = value.upper()
    if not upper or any(char not in glyphs for char in upper):
        return None
    total = 0
    previous = 0
    for char in reversed(upper):
        current = glyphs[char]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total


def _record(
    name: str,
    version: str,
    location: str,
    before: str,
    after: str,
    confidence: float,
    warnings: list[str] | None = None,
) -> TransformationRecord:
    return TransformationRecord(
        rule_name=name,
        rule_version=version,
        input_location=location,
        before_hash=text_hash(before),
        after_hash=text_hash(after),
        confidence=confidence,
        warnings=list(warnings or []),
    )
