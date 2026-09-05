# ADR 0002: Local Canonical corpus, source-derived trust, and cloud-ready retrieval boundary

- Status: Accepted
- Date: 2026-09-03

## Context

The repository already contains a ten-volume SQLite snapshot of 《马克思恩格斯文集》 with stable `evidence_id`, `text_hash`, and `prev_id`/`next_id` values. That snapshot was previously Git-tracked as an unverified/draft demo asset. The product now needs a real, non-synthetic Exact vertical slice on the ordinary local app path, without human review, PDF jump, or any Bailian upload.

A parallel Canonical Corpus, a TypeScript `SearchResult` type, or a new public V1 contract would break the frozen evidence boundary.

## Decision

1. **SQLite is a local data asset, not a Git object.**
   The Canonical seed remains at `corpora/marx_engels_collected_works_cn/sqlite/corpus.db` on disk. Git keeps only the manifest, expected SHA-256, configuration example, and initialization docs. History is not rewritten. Runtime state lives in Git-ignored `runtime-data/`. `corpus.sha256` covers that main file only. Verify, init-local-corpus, and export-cloud-ingest open it as an immutable single-file snapshot, fail closed on a non-empty `-wal` sidecar, and must not create `-wal` or `-shm` beside the seed.

2. **Skip human review in this phase.**
   No review workflow, no page-mapping confirmation, and no claim that the text has been collated by a person.

3. **Source-derived trusted is an explicit local publication policy.**
   Passages whose bytes were extracted from the source, split deterministically, and hashed so they can be re-checked may be marked `verified`/`published` on the **runtime copy only**. The policy name is `source_derived_trusted`. It is not human review. Unknown draft rows still cannot pass `EvidenceService`. Publication fails closed when the seed is missing, the SHA-256 does not match, integrity or counts fail, or initialization is incomplete.

4. **Reuse the existing Canonical identity.**
   `evidence_id` is the Canonical Evidence ID. Cloud retrieval units reuse the existing `ru_{evidence_id}_{n}` scheme. The stable mapping is `retrieval_unit_id → evidence_id → SQLite verified_text`. Do not invent a second corpus.

5. **Page mapping is not an Evidence release gate in this phase.**
   Public `printed_pages` / `pdf_pages` may be empty or echo currently stored values. They are not described as human-confirmed pages. PDF viewer, PDF jump, and in-page highlight are out of scope.

6. **Cloud retrieval is a later provider behind a local boundary.**
   Exact continues to use `ExactSearchIndex`. `LexicalIndex` and `VectorIndex` remain. A provider-neutral `Retriever` port is added because `VectorIndex` requires the caller to supply embeddings, which would leak a cloud SDK, knowledge-base ID, or response shape into pipelines. `Candidate` is the only retrieval object. Cloud `search_text` is never a quotation. Final display text is always hydrated by `EvidenceService` from SQLite.

7. **Cloud export is local and deterministic.**
   Export writes Git-ignored artifacts that a future upload step can consume. This phase does not upload files, call cloud APIs, or read API keys.

## Consequences

- Ordinary `make run-api` / `make run-web` read a Git-ignored runtime copy initialized from the Canonical seed.
- Missing local database, hash mismatch, a non-empty Canonical `-wal` sidecar, or incomplete init fails closed. The app does not create an empty corpus and does not fall back to synthetic data.
- Semantic modes keep reporting `PIPELINE_NOT_IMPLEMENTED`.
- Collaborators must obtain the local SQLite asset out of band; a clone no longer contains `corpus.db`.
- Future Bailian integration implements `Retriever` without changing frozen V1 contracts.
