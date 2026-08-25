"""Work / section / passage candidates with dual-signal work boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from marx_engels.ingestion.cleaning import text_hash
from marx_engels.ingestion.id_registry import IdRegistry
from marx_engels.ingestion.layer_models import (
    CleanPageRecord,
    ContentKind,
    ContentSpan,
    PageKind,
    PassageCandidate,
    PassageLifecycle,
    RetrievalUnit,
    ReviewIssue,
    SectionCandidate,
    WorkCandidate,
)
from marx_engels.ingestion.rules import CorpusRules


@dataclass
class _Line:
    page: CleanPageRecord
    span: ContentSpan
    text: str


@dataclass
class StructureBundle:
    works: list[WorkCandidate]
    sections: list[SectionCandidate]
    passages: list[PassageCandidate]
    issues: list[ReviewIssue]


def recognize_structure(
    pages: list[CleanPageRecord],
    rules: CorpusRules,
    registry: IdRegistry,
) -> StructureBundle:
    ordered = sorted(pages, key=lambda item: item.pdf_page)
    if not ordered:
        return StructureBundle([], [], [], [])
    volume_id = ordered[0].volume_id
    lines = [
        _Line(page, span, span.text.strip())
        for page in ordered
        for span in page.spans
        if span.text.strip()
    ]
    toc_titles = _toc_titles(lines, rules)
    works, work_issues = _detect_works(lines, toc_titles, rules, registry, volume_id)
    issues = list(work_issues)
    sections: list[SectionCandidate] = []
    passages: list[PassageCandidate] = []
    for work in works:
        work_pages = [
            page for page in ordered if work.pdf_page_start <= page.pdf_page <= work.pdf_page_end
        ]
        work_sections = _sections_for_work(work, work_pages, rules, registry)
        sections.extend(work_sections)
        work_passages = _passages_for_work(work, work_sections, work_pages, rules, registry)
        _link_prev_next(work_passages)
        assert_prev_next_consistent(work_passages)
        passages.extend(work_passages)
    return StructureBundle(works=works, sections=sections, passages=passages, issues=issues)


def _toc_titles(lines: list[_Line], rules: CorpusRules) -> list[str]:
    titles: list[str] = []
    in_toc = False
    for line in lines:
        if line.span.content_type is ContentKind.TOC or rules.matches(
            rules.toc_heading_patterns, line.text
        ):
            in_toc = True
            continue
        if in_toc and line.span.content_type in {ContentKind.MAIN_TEXT, ContentKind.TOC}:
            if rules.matches(rules.author_line_patterns, line.text) or len(line.text) > 80:
                in_toc = False
                continue
            compact = _compact(line.text)
            if compact:
                titles.append(compact)
        elif in_toc and line.span.content_type not in {
            ContentKind.HEADER,
            ContentKind.FOOTER,
            ContentKind.TOC,
        }:
            in_toc = False
    return titles


def _detect_works(
    lines: list[_Line],
    toc_titles: list[str],
    rules: CorpusRules,
    registry: IdRegistry,
    volume_id: str,
) -> tuple[list[WorkCandidate], list[ReviewIssue]]:
    works: list[WorkCandidate] = []
    issues: list[ReviewIssue] = []
    pending_end = False
    last_author_page: int | None = None
    first_page = lines[0].page.pdf_page if lines else 1
    last_page = lines[-1].page.pdf_page if lines else 1
    front_key = f"{volume_id}|front"
    works.append(
        WorkCandidate(
            work_id=registry.work_id(front_key),
            volume_id=volume_id,
            title="unassigned_front",
            pdf_page_start=first_page,
            pdf_page_end=first_page,
            signals=["volume_front"],
            confidence=0.2,
            accepted=False,
            warnings=["catch_all_front_matter"],
            manual_required=True,
        )
    )
    for line in lines:
        if rules.matches(rules.author_line_patterns, line.text):
            last_author_page = line.page.pdf_page
        if rules.matches(rules.work_end_patterns, line.text):
            pending_end = True
        if not _looks_like_work_title(line, rules):
            continue
        signals: list[str] = ["body_title"]
        if last_author_page is not None and abs(line.page.pdf_page - last_author_page) <= 1:
            signals.append("author_line")
        if pending_end:
            signals.append("previous_end")
        if _toc_hit(line.text, toc_titles):
            signals.append("toc_entry")
        unique = list(dict.fromkeys(signals))
        accepted = len(unique) >= 2
        if not accepted:
            issues.append(
                ReviewIssue(
                    issue_id=f"issue_{volume_id}_{line.page.pdf_page}_weak_work",
                    code="weak_work_boundary",
                    volume_id=volume_id,
                    pdf_pages=[line.page.pdf_page],
                    message="Work title lacks a second independent signal",
                    rule_version="structure-v1",
                )
            )
            continue
        key = f"{volume_id}|{line.page.pdf_page}"
        works.append(
            WorkCandidate(
                work_id=registry.work_id(key),
                volume_id=volume_id,
                title=line.text,
                pdf_page_start=line.page.pdf_page,
                pdf_page_end=line.page.pdf_page,
                signals=unique,
                confidence=0.85,
                accepted=True,
                warnings=[],
                manual_required=False,
            )
        )
        pending_end = False
        last_author_page = None
    _close_work_ranges(works, last_page)
    if (
        works
        and works[0].title == "unassigned_front"
        and works[0].pdf_page_end < works[0].pdf_page_start
    ):
        works.pop(0)
    return works, issues


def _close_work_ranges(works: list[WorkCandidate], last_page: int) -> None:
    if not works:
        return
    accepted = [item for item in works if item.accepted]
    for index, work in enumerate(works):
        following = next(
            (item.pdf_page_start for item in works[index + 1 :] if item.accepted), None
        )
        if work.accepted:
            work.pdf_page_end = (following - 1) if following else last_page
        elif work.title == "unassigned_front":
            first_accepted = accepted[0].pdf_page_start if accepted else last_page + 1
            work.pdf_page_end = first_accepted - 1
        else:
            work.pdf_page_end = work.pdf_page_start


def _looks_like_work_title(line: _Line, rules: CorpusRules) -> bool:
    if line.page.page_type is PageKind.TOC:
        return False
    if line.span.content_type in {
        ContentKind.HEADER,
        ContentKind.FOOTER,
        ContentKind.TOC,
        ContentKind.INDEX,
    }:
        return False
    if rules.matches(rules.section_patterns, line.text):
        return False
    if rules.matches(rules.editor_note_patterns, line.text):
        return False
    if "title_block" in line.span.signals:
        return len(line.text) <= 80
    return rules.matches(rules.work_title_markers, line.text) and len(line.text) <= 40


def _toc_hit(title: str, toc_titles: list[str]) -> bool:
    compact = _compact(title)
    if len(compact) < 4:
        return False
    return any(compact in item or item in compact for item in toc_titles if len(item) >= 4)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text.replace("《", "").replace("》", "").replace("·", ""))


def _sections_for_work(
    work: WorkCandidate,
    pages: list[CleanPageRecord],
    rules: CorpusRules,
    registry: IdRegistry,
) -> list[SectionCandidate]:
    root_key = f"{work.work_id}|root"
    root = SectionCandidate(
        section_id=registry.section_id(root_key),
        work_id=work.work_id,
        parent_id=None,
        title=work.title or "root",
        pdf_page_start=work.pdf_page_start,
        pdf_page_end=work.pdf_page_end,
        signals=["work_root"],
        confidence=1.0 if work.accepted else 0.3,
        manual_required=work.manual_required,
    )
    sections = [root]
    parent_id = root.section_id
    for page in pages:
        for span in page.spans:
            if not rules.matches(rules.section_patterns, span.text):
                continue
            nested = bool(re.match(r"^[一二三四五六七八九十]+[、．.]", span.text.strip()))
            key = f"{work.work_id}|{page.pdf_page}|{span.text[:40]}"
            section = SectionCandidate(
                section_id=registry.section_id(key),
                work_id=work.work_id,
                parent_id=parent_id if nested else root.section_id,
                title=span.text.strip(),
                pdf_page_start=page.pdf_page,
                pdf_page_end=work.pdf_page_end,
                signals=["section_heading"],
                confidence=0.7,
            )
            sections.append(section)
            if not nested:
                parent_id = section.section_id
    for index, section in enumerate(sections):
        if index == 0:
            continue
        following = next(
            (
                item.pdf_page_start
                for item in sections[index + 1 :]
                if item.parent_id == section.parent_id
            ),
            None,
        )
        section.pdf_page_end = (following - 1) if following else work.pdf_page_end
    return sections


def _passages_for_work(
    work: WorkCandidate,
    sections: list[SectionCandidate],
    pages: list[CleanPageRecord],
    rules: CorpusRules,
    registry: IdRegistry,
) -> list[PassageCandidate]:
    root_id = sections[0].section_id
    current_section = root_id
    open_passage: _OpenPassage | None = None
    built: list[_OpenPassage] = []
    for page in pages:
        for span in page.spans:
            if span.content_type in {ContentKind.HEADER, ContentKind.FOOTER}:
                continue
            matching = next((item for item in sections if item.title == span.text.strip()), None)
            if matching is not None:
                current_section = matching.section_id
            if (
                open_passage is not None
                and open_passage.content_type is ContentKind.MAIN_TEXT
                and span.content_type is ContentKind.MAIN_TEXT
                and span.joinable
                and open_passage.joinable
                and not _starts_new_paragraph(span.text, rules)
            ):
                open_passage.append(page.pdf_page, span.text)
                continue
            if open_passage is not None:
                built.append(open_passage)
            open_passage = _OpenPassage(
                work_id=work.work_id,
                section_id=current_section,
                volume_id=work.volume_id,
                content_type=span.content_type,
                joinable=span.joinable and span.content_type is ContentKind.MAIN_TEXT,
                signals=list(span.signals),
            )
            open_passage.append(page.pdf_page, span.text)
    if open_passage is not None:
        built.append(open_passage)
    passages: list[PassageCandidate] = []
    for order, item in enumerate(built, start=1):
        key = f"{work.work_id}|{item.pdf_start}|{order}"
        evidence_id = registry.evidence_id(key)
        record = registry.passages[key]
        text = item.text
        passages.append(
            PassageCandidate(
                evidence_id=evidence_id,
                work_id=work.work_id,
                section_id=item.section_id,
                volume_id=work.volume_id,
                content_type=item.content_type,
                text=text,
                text_hash=text_hash(text),
                pdf_page_start=item.pdf_start,
                pdf_page_end=item.pdf_end,
                lifecycle=PassageLifecycle(str(record["status"])),
                supersedes_id=list(record.get("supersedes_id") or []),
                superseded_by=list(record.get("superseded_by") or []),
                signals=item.signals
                + (["dual_signal_work"] if work.accepted else ["unassigned_or_weak_work"]),
                confidence=0.8 if work.accepted else 0.3,
                warnings=[] if work.accepted else ["work_not_dual_signal"],
                manual_required=work.manual_required or item.content_type is ContentKind.TOC,
                retrieval_units=_retrieval_units(evidence_id, text, rules),
            )
        )
    return passages


def _starts_new_paragraph(text: str, rules: CorpusRules) -> bool:
    return (
        rules.matches(rules.paragraph_indent_prefixes, text)
        or rules.matches(rules.list_prefixes, text)
        or rules.matches(rules.section_patterns, text)
        or rules.matches(rules.work_title_markers, text)
        or rules.matches(rules.footnote_markers, text)
    )


def _retrieval_units(evidence_id: str, text: str, rules: CorpusRules) -> list[RetrievalUnit]:
    limit = rules.retrieval_unit_char_limit
    if len(text) <= limit:
        return []
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        cut = max(window.rfind("。"), window.rfind("！"), window.rfind("？"), window.rfind("\n"))
        if cut < limit // 3:
            cut = limit
        else:
            cut += 1
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    units: list[RetrievalUnit] = []
    for index, chunk in enumerate(chunks, start=1):
        units.append(
            RetrievalUnit(
                retrieval_unit_id=f"ru_{evidence_id}_{index}",
                evidence_id=evidence_id,
                order_no=index,
                text=chunk,
                text_hash=text_hash(chunk),
            )
        )
    return units


def _link_prev_next(passages: list[PassageCandidate]) -> None:
    active = [item for item in passages if item.lifecycle is PassageLifecycle.ACTIVE]
    for index, passage in enumerate(active):
        passage.prev_id = active[index - 1].evidence_id if index else None
        passage.next_id = active[index + 1].evidence_id if index + 1 < len(active) else None


def assert_prev_next_consistent(passages: list[PassageCandidate]) -> None:
    active = [item for item in passages if item.lifecycle is PassageLifecycle.ACTIVE]
    by_id = {item.evidence_id: item for item in active}
    if not active:
        return
    starts = [item for item in active if item.prev_id is None]
    if len(starts) != 1:
        raise ValueError("prev/next chain must have exactly one start")
    seen: set[str] = set()
    current: PassageCandidate | None = starts[0]
    while current is not None:
        if current.evidence_id in seen:
            raise ValueError("prev/next chain contains a cycle")
        seen.add(current.evidence_id)
        if current.next_id is None:
            break
        nxt = by_id.get(current.next_id)
        if nxt is None:
            raise ValueError("next_id points outside the work")
        if nxt.prev_id != current.evidence_id:
            raise ValueError("prev/next pointers are not bidirectional")
        if nxt.work_id != current.work_id:
            raise ValueError("prev/next crossed a work boundary")
        current = nxt
    if seen != set(by_id):
        raise ValueError("prev/next chain does not visit every active passage")


@dataclass
class _OpenPassage:
    work_id: str
    section_id: str
    volume_id: str
    content_type: ContentKind
    joinable: bool
    signals: list[str] = field(default_factory=list)
    fragments: list[tuple[int, str]] = field(default_factory=list)

    def append(self, pdf_page: int, text: str) -> None:
        self.fragments.append((pdf_page, text))

    @property
    def text(self) -> str:
        return "".join(fragment for _, fragment in self.fragments)

    @property
    def pdf_start(self) -> int:
        return self.fragments[0][0]

    @property
    def pdf_end(self) -> int:
        return self.fragments[-1][0]
