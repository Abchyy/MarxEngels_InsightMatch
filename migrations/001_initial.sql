PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE corpus (
    corpus_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    language TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    rights_status TEXT NOT NULL,
    release_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE edition (
    edition_id TEXT PRIMARY KEY,
    corpus_id TEXT NOT NULL REFERENCES corpus(corpus_id),
    publisher TEXT,
    publish_year INTEGER,
    isbn TEXT,
    edition_label TEXT,
    rights_status TEXT NOT NULL,
    release_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE asset (
    asset_id TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    mime_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE volume (
    volume_id TEXT PRIMARY KEY,
    edition_id TEXT NOT NULL REFERENCES edition(edition_id),
    volume_no INTEGER NOT NULL CHECK (volume_no >= 1),
    title TEXT NOT NULL,
    pdf_asset_id TEXT NOT NULL REFERENCES asset(asset_id),
    release_status TEXT NOT NULL,
    UNIQUE (edition_id, volume_no)
);

CREATE TABLE work (
    work_id TEXT PRIMARY KEY,
    volume_id TEXT NOT NULL REFERENCES volume(volume_id),
    title TEXT NOT NULL,
    author_code TEXT NOT NULL,
    work_date_start TEXT,
    work_date_end TEXT,
    date_precision TEXT NOT NULL,
    date_source TEXT,
    first_publication_date TEXT,
    order_no INTEGER NOT NULL CHECK (order_no >= 1),
    verification_status TEXT NOT NULL,
    release_status TEXT NOT NULL,
    UNIQUE (volume_id, order_no)
);

CREATE TABLE section (
    section_id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES work(work_id),
    parent_id TEXT REFERENCES section(section_id),
    title TEXT,
    level INTEGER NOT NULL CHECK (level >= 0),
    order_no INTEGER NOT NULL CHECK (order_no >= 1),
    verification_status TEXT NOT NULL,
    UNIQUE (work_id, parent_id, order_no)
);

CREATE TABLE page_map (
    page_id TEXT PRIMARY KEY,
    volume_id TEXT NOT NULL REFERENCES volume(volume_id),
    pdf_page INTEGER NOT NULL CHECK (pdf_page >= 1),
    printed_page_label TEXT,
    printed_page_number INTEGER,
    page_type TEXT NOT NULL,
    mapping_status TEXT NOT NULL,
    UNIQUE (volume_id, pdf_page)
);

CREATE TABLE passage (
    evidence_id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL REFERENCES section(section_id),
    content_type TEXT NOT NULL,
    verified_text TEXT NOT NULL CHECK (length(verified_text) > 0),
    text_hash TEXT NOT NULL,
    prev_id TEXT REFERENCES passage(evidence_id),
    next_id TEXT REFERENCES passage(evidence_id),
    order_no INTEGER NOT NULL CHECK (order_no >= 1),
    verification_status TEXT NOT NULL,
    release_status TEXT NOT NULL,
    revision_no INTEGER NOT NULL DEFAULT 1 CHECK (revision_no >= 1),
    supersedes_id TEXT REFERENCES passage(evidence_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (section_id, order_no)
);

CREATE TABLE passage_page (
    evidence_id TEXT NOT NULL REFERENCES passage(evidence_id),
    page_id TEXT NOT NULL REFERENCES page_map(page_id),
    order_no INTEGER NOT NULL CHECK (order_no >= 1),
    start_offset INTEGER,
    end_offset INTEGER,
    PRIMARY KEY (evidence_id, page_id)
);

CREATE TABLE verification_event (
    verification_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    field_name TEXT,
    before_hash TEXT,
    after_hash TEXT,
    reason_code TEXT NOT NULL,
    comment TEXT,
    operator_id TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE data_release (
    data_version TEXT PRIMARY KEY,
    corpus_id TEXT NOT NULL REFERENCES corpus(corpus_id),
    passage_count INTEGER NOT NULL CHECK (passage_count >= 0),
    manifest_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE index_outbox (
    event_id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL REFERENCES passage(evidence_id),
    operation TEXT NOT NULL,
    data_version TEXT NOT NULL REFERENCES data_release(data_version),
    text_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error TEXT,
    created_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE index_release (
    index_version TEXT PRIMARY KEY,
    data_version TEXT NOT NULL REFERENCES data_release(data_version),
    embedding_provider TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension > 0),
    config_hash TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count >= 0),
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE search_audit (
    request_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    query_text TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    data_version TEXT NOT NULL,
    index_version TEXT,
    model_versions_json TEXT NOT NULL,
    candidate_trace_json TEXT,
    result_ids_json TEXT NOT NULL,
    warning_codes_json TEXT NOT NULL,
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE feedback (
    feedback_id TEXT PRIMARY KEY,
    request_id TEXT,
    evidence_id TEXT REFERENCES passage(evidence_id),
    category TEXT NOT NULL,
    comment TEXT NOT NULL,
    client_context_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE passage_fts USING fts5(
    evidence_id UNINDEXED,
    search_text
);

CREATE INDEX idx_edition_corpus ON edition(corpus_id);
CREATE INDEX idx_volume_edition ON volume(edition_id, volume_no);
CREATE INDEX idx_work_volume_order ON work(volume_id, order_no);
CREATE INDEX idx_work_date ON work(work_date_start, work_date_end);
CREATE INDEX idx_section_work_order ON section(work_id, order_no);
CREATE INDEX idx_passage_section_order ON passage(section_id, order_no);
CREATE INDEX idx_passage_release ON passage(release_status, verification_status);
CREATE INDEX idx_page_volume_pdf ON page_map(volume_id, pdf_page);
CREATE INDEX idx_outbox_pending ON index_outbox(status, created_at);
CREATE INDEX idx_release_status ON index_release(status, published_at);
