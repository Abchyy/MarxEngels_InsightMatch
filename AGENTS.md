# Repository instructions

- Treat the six technical specification documents as the product baseline.
- Public V1 contracts in `packages/marx_engels/contracts/` are frozen. Propose breaking changes through an ADR before editing them.
- SQLite is authoritative. Never return LanceDB `search_text` as a formal quotation.
- Only `EvidenceService` may construct a public `Evidence` object.
- Keep the four pipelines independent behind `SearchPipeline`.
- Do not commit PDFs, OCR output, SQLite files, LanceDB directories, secrets or generated runtime data.
- Canonical SQLite is a Git-ignored local asset. Track only the manifest, expected SHA-256, and init docs. Never write the Canonical seed at runtime.
- Use the English `make` commands documented in `README.md`.
- Add or update tests for every behavior change.
- Do not create worktrees unless the project owner explicitly asks.
