# Marx–Engels Collected Works corpus package

This directory contains the manifest template, versioned processing rules, and the Unverified/Draft SQLite snapshot at `sqlite/corpus.db`. Do not commit the ten source PDFs, derived chunks, MinerU ZIP archives, Markdown, JSON extracts, or quality reports.

## Rules

- Original PDFs under `PDF_ASSET_ROOT` are read-only. Never overwrite, rename, or write beside them.
- Derived data belongs in `CORPUS_DATA_ROOT`:
  - `source_records/` registered volume hashes
  - `raw/chunks/` split PDFs and page mappings
  - `raw/mineru/` requests, archives, and unpacked Raw results
  - `raw/pages/` provider-neutral merged PDF pages (versioned run dirs)
  - `clean/pages/`, `clean/transformations/`, `clean/structures/`, `clean/passages/`
  - `reports/` preflight, extraction, cleaning, and structure reports
  - `review/issues/` automatic assemble flags
  - `reports/publication/` local SQLite handoff reports
  - `state/` resumable pipeline state and ID registry
- MinerU output is the Raw layer only. Clean structure is unverified/draft. Neither is a formal quotation.
- `ingest-sqlite` writes a local Unverified/Draft snapshot for display and FTS search. It does not mark passages Verified or enqueue a published index.

## Filename convention

Source PDFs are expected to be named `马克思恩格斯文集第{chinese_numeral}卷.pdf` for volumes 1-10.

Planned implementation outputs must follow specification 01 and hand verified release events to the SQLite/indexing boundary without changing V1 contract identifiers.
