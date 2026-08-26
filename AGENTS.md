# Repository instructions

- Treat the six technical specification documents as the product baseline.
- Public V1 contracts in `packages/marx_engels/contracts/` are frozen. Propose breaking changes through an ADR before editing them.
- SQLite is authoritative. Never return LanceDB `search_text` as a formal quotation.
- Only `EvidenceService` may construct a public `Evidence` object.
- Keep the four pipelines independent behind `SearchPipeline`.
- Do not commit PDFs, OCR output, SQLite files, LanceDB directories, secrets or generated runtime data.
- Single exception: `corpora/marx_engels_collected_works_cn/sqlite/corpus.db` is a versioned unverified/draft local demo asset. Do not extend this exception to any other database or runtime file.
- Use the English `make` commands documented in `README.md`.
- Add or update tests for every behavior change.
- Do not create worktrees unless the project owner explicitly asks.
