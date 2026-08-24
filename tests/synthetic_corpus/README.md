# Synthetic integration corpus

This fixture is a deterministic, entirely invented corpus for integration tests.
It is not Marx–Engels source material and must never be presented as a formal
quotation. Every passage starts with `【合成数据，非原典】`, and all display
metadata marks the edition as synthetic and forbidden for citation.

The fixture provides:

- two corpora so scope leakage can be detected;
- published, unpublished, and unverified passages;
- exact-search hits with deterministic occurrence counts;
- direct, contextual, and counter-evidence examples;
- known, approximate, disputed, and unknown work dates;
- a passage mapped across two printed/PDF pages;
- deterministic four-dimensional vector records for future LanceDB tests;
- synthetic JSONL cases for all four pipelines and the Evidence gate.

`builder.py` migrates a caller-provided temporary SQLite path and inserts the
fixture. Integration tests send the exact-search cases through the production
`SQLiteExactSearchIndex` adapter, and validate all synthetic JSONL cases through
the shared Golden Dataset structure validator. The builder never writes a
database into the repository. Generated SQLite files, LanceDB directories, PDFs,
and other runtime artifacts must remain untracked.

The JSONL files under `cases/` are synthetic integration expectations, not the
human-reviewed release Golden Dataset under `tests/golden/`.
