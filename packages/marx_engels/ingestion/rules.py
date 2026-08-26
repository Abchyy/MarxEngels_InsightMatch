"""Load corpus-package rules without baking edition specifics into generic code."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RULES_DIR = Path("corpora/marx_engels_collected_works_cn/rules")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"rule file {path} must contain a mapping")
    return payload


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(item) for item in patterns]


@dataclass(frozen=True)
class CorpusRules:
    normalization_version: str = "nfc-v1"
    join_confidence_threshold: float = 0.6
    garbled_replacement_min: int = 2
    low_text_char_threshold: int = 8
    header_repeat_min_pages: int = 3
    retrieval_unit_char_limit: int = 1800
    poetry_max_line_chars: int = 16
    poetry_min_short_lines: int = 3
    sentence_terminators: tuple[str, ...] = ("。", "！", "？", "；", "…", ".", "!", "?")
    list_prefixes: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    paragraph_indent_prefixes: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    header_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    footer_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    page_number_pattern: re.Pattern[str] = re.compile(r"^(?:第)?(?:[ivxlcdmIVXLCDM]+|\d+)(?:页)?$")
    toc_heading_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    work_title_markers: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    author_line_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    work_end_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    editor_note_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    index_heading_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    section_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)
    footnote_markers: tuple[re.Pattern[str], ...] = field(default_factory=tuple)

    @classmethod
    def load(cls, rules_dir: Path | None = None) -> CorpusRules:
        directory = rules_dir or DEFAULT_RULES_DIR
        cleaning = _load_yaml(directory / "cleaning.yaml")
        headers = _load_yaml(directory / "headers.yaml")
        structure = _load_yaml(directory / "structure.yaml")
        page_number = str(headers.get("page_number_pattern") or cls.page_number_pattern.pattern)
        return cls(
            normalization_version=str(cleaning.get("normalization_version") or "nfc-v1"),
            join_confidence_threshold=float(cleaning.get("join_confidence_threshold") or 0.6),
            garbled_replacement_min=int(cleaning.get("garbled_replacement_min") or 2),
            low_text_char_threshold=int(cleaning.get("low_text_char_threshold") or 8),
            header_repeat_min_pages=int(cleaning.get("header_repeat_min_pages") or 3),
            retrieval_unit_char_limit=int(cleaning.get("retrieval_unit_char_limit") or 1800),
            poetry_max_line_chars=int(cleaning.get("poetry_max_line_chars") or 16),
            poetry_min_short_lines=int(cleaning.get("poetry_min_short_lines") or 3),
            sentence_terminators=tuple(
                str(item)
                for item in cleaning.get("sentence_terminators") or cls.sentence_terminators
            ),
            list_prefixes=tuple(_compile(list(cleaning.get("list_prefixes") or []))),
            paragraph_indent_prefixes=tuple(
                _compile(list(cleaning.get("paragraph_indent_prefixes") or []))
            ),
            header_patterns=tuple(_compile(list(headers.get("header_patterns") or []))),
            footer_patterns=tuple(_compile(list(headers.get("footer_patterns") or []))),
            page_number_pattern=re.compile(page_number),
            toc_heading_patterns=tuple(_compile(list(structure.get("toc_heading_patterns") or []))),
            work_title_markers=tuple(_compile(list(structure.get("work_title_markers") or []))),
            author_line_patterns=tuple(_compile(list(structure.get("author_line_patterns") or []))),
            work_end_patterns=tuple(_compile(list(structure.get("work_end_patterns") or []))),
            editor_note_patterns=tuple(_compile(list(structure.get("editor_note_patterns") or []))),
            index_heading_patterns=tuple(
                _compile(list(structure.get("index_heading_patterns") or []))
            ),
            section_patterns=tuple(_compile(list(structure.get("section_patterns") or []))),
            footnote_markers=tuple(_compile(list(structure.get("footnote_markers") or []))),
        )

    def matches(self, patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
        stripped = text.strip()
        return any(pattern.search(stripped) for pattern in patterns)
