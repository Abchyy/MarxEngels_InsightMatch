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
make init-local-corpus
make export-cloud-ingest
```

Split threshold is 180 MB or 180 pages, below the live MinerU precision-API limits of 200 MB / 200 pages. `assemble` writes versioned Raw pages / Clean pages / structure candidates and never marks passages Verified.

`ingest-sqlite` writes the Clean snapshot into local SQLite as `unverified` / `draft` for display and FTS search. `passage_fts.search_text` is retrieval aid only, not a formal quotation. The command does not enqueue `index_outbox` or create a published data release.

## Local Canonical SQLite asset

`corpora/marx_engels_collected_works_cn/sqlite/corpus.db` is a Git-ignored local seed. Tracked companions are `sqlite/local_asset.yaml` and `sqlite/corpus.sha256`. Copy it to a runtime database and apply source-derived trusted publication with `make init-local-corpus`. Do not write the seed. `corpus.sha256` binds the main SQLite file only: verify, init, and export open it as an immutable snapshot, reject a non-empty `-wal` sidecar, and must not create `-wal` or `-shm` in the seed directory. Other SQLite files, PDFs, OCR, MinerU archives, LanceDB data, secrets, cloud-export artifacts, and `runtime-data/` remain excluded.

`make export-cloud-ingest` writes retrieval units for a later cloud knowledge-base upload. It does not upload and does not read API keys. Cloud `search_text` is not a quotation; restore wording from SQLite `evidence_id`.
