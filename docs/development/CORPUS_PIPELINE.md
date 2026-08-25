# Corpus pipeline (feature/corpus-pipeline)

Offline workflow: register the ten 《马克思恩格斯文集》 PDFs, extract Raw MinerU output, then merge, clean, and structure without calling MinerU again.

## Why these libraries

- `pypdf`: maintained BSD-licensed PDF library used to read page counts, sample the text layer, and copy pages into derived chunks without modifying the original files.
- `httpx`: already used in this repository; the MinerU adapter injects transports so unit tests never open the network.

## Data roots

| Variable | Role |
|---|---|
| `PDF_ASSET_ROOT` | Read-only original PDFs |
| `CORPUS_DATA_ROOT` | Source records, Raw/Clean artifacts, reports, ID registry |
| `MINERU_API_TOKEN` | Local secret; never print, log, or commit |

## Commands

```bash
uv run python -m marx_engels.ingestion.cli inventory
uv run python -m marx_engels.ingestion.cli preflight
uv run python -m marx_engels.ingestion.cli extract --pilot
uv run python -m marx_engels.ingestion.cli extract --all
uv run python -m marx_engels.ingestion.cli resume
uv run python -m marx_engels.ingestion.cli status
uv run python -m marx_engels.ingestion.cli merge-pages
uv run python -m marx_engels.ingestion.cli clean-pages
uv run python -m marx_engels.ingestion.cli assemble
uv run python -m marx_engels.ingestion.cli ingest-sqlite --replace
make verify-corpus
```

Split threshold is 180 MB or 180 pages, below the live MinerU precision-API limits of 200 MB / 200 pages. `assemble` writes versioned Raw pages / Clean pages / structure candidates and never marks passages Verified.

`ingest-sqlite` writes the Clean snapshot into local SQLite as `unverified` / `draft` for display and FTS search. `passage_fts.search_text` is retrieval aid only, not a formal quotation. The command does not enqueue `index_outbox` or create a published data release.
