# Marx–Engels InsightMatch

面向《马克思恩格斯文集》十卷的可核验原典检索助手。当前仓库已具备模块边界、公共契约、数据库迁移、API、前端检索工作流、四条检索管线、离线语料处理管线，以及一份 Git 忽略的十卷 Canonical SQLite 本地资产。普通运行时的 Exact 模式从该资产的 runtime 副本检索，并由 `EvidenceService` 回填 SQLite 原文。该发布策略是 source-derived trusted，不是人工校勘。

## Architecture baseline

- SQLite 是正式文本、元数据、页码、发布状态与审计的权威真源。
- LanceDB 是可从 SQLite 重建的派生向量索引。
- `EvidenceService` 是唯一可以组装正式引文响应的模块。
- 四条管线独立实现：`exact`、`claim`、`timeline`、`thematic`。
- 公共契约位于 `packages/marx_engels/contracts/`，V1 冻结快照位于 `contracts/`。
- 业务模块只依赖 Protocol，不直接依赖其他模块的具体存储连接。

## Repository layout

```text
apps/
  api/                 FastAPI entrypoint
  web/                 React + TypeScript + Vite shell
packages/marx_engels/
  contracts/           frozen V1 domain and HTTP contracts
  corpus_registry/     corpus manifest and scope boundary
  storage/             SQLite and LanceDB adapters
  retrieval_core/      retrieval ports and shared algorithms
  pipelines/           exact/claim/timeline/thematic boundaries
  evidence/            evidence gate and hydration boundary
  model_adapters/      embedding/reranker/LLM ports
  ingestion/           offline corpus workflow boundary
  indexing/            FTS/vector indexing boundary
  evaluation/          golden-dataset and metric boundary
config/                versioned runtime defaults
contracts/             generated JSON Schema and OpenAPI snapshots
migrations/            ordered SQLite migrations
tests/                 unit, contract and integration tests
```

## Quick start

Prerequisites: Python 3.12, `uv`, Node.js 22+, `pnpm`, and `make`.

```bash
make setup
cp .env.example .env
make init-local-corpus
make verify
make run-api
```

In another terminal:

```bash
make run-web
```

API documentation is available at `http://127.0.0.1:8000/docs` after startup.

## Stable commands

```bash
make setup
make lint
make typecheck
make test
make test-unit
make test-contract
make test-integration
make migrate
make verify-corpus
make init-local-corpus
make export-cloud-ingest
make build-index
make verify-index
make run-api
make run-web
make run-demo-api
make run-demo-web
make export-openapi
make verify-contracts
make verify
```

Corpus ingestion (read-only `PDF_ASSET_ROOT`, derived data in `CORPUS_DATA_ROOT`):

```bash
uv run python -m marx_engels.ingestion.cli inventory
uv run python -m marx_engels.ingestion.cli preflight
uv run python -m marx_engels.ingestion.cli extract --pilot
uv run python -m marx_engels.ingestion.cli extract --all
uv run python -m marx_engels.ingestion.cli resume
uv run python -m marx_engels.ingestion.cli status
uv run python -m marx_engels.ingestion.cli assemble
uv run python -m marx_engels.ingestion.cli ingest-sqlite --replace
make verify-corpus
```

`MINERU_API_TOKEN` stays in local `.env` and must never be printed or committed. MinerU Markdown is Raw extraction, not a verified quotation.

Commands must not access production implicitly. Corpus PDFs, OCR/MinerU output, SQLite databases, LanceDB data, cloud-export artifacts, and model credentials remain excluded from Git.

## Local Canonical SQLite asset

The ten-volume Canonical seed is a Git-ignored local file:

`corpora/marx_engels_collected_works_cn/sqlite/corpus.db`

Git tracks the expected SHA-256, catalog counts, and init docs only:

- `corpora/marx_engels_collected_works_cn/sqlite/local_asset.yaml`
- `corpora/marx_engels_collected_works_cn/sqlite/corpus.sha256`

Obtain the seed out of band, then:

```bash
make init-local-corpus
```

This copies the seed to `runtime-data/sqlite/corpus.db` and applies the source-derived trusted local publication. The Canonical seed is never written at runtime. Missing files, hash mismatch, a non-empty seed `-wal` sidecar, or incomplete init fail closed; the app does not create an empty corpus and does not fall back to synthetic data. Read-only seed checks use the hashed main file only and do not create `-wal` or `-shm`.

This publication does **not** mean the text has been collated by a person. Final quotations always come from SQLite `verified_text` via `EvidenceService`. Cloud or FTS `search_text` is retrieval aid only.

`make export-cloud-ingest` writes deterministic retrieval-unit files under `runtime-data/cloud-export/` for a later upload step. It does not call any cloud API.

See `docs/adr/0002-local-canonical-corpus-and-cloud-ready-baseline.md`, `corpora/marx_engels_collected_works_cn/README.md`, and `docs/development/CORPUS_PIPELINE.md`.

## Planned worktree ownership

No worktree is created in this baseline.

| Planned branch | Owner | Scope |
|---|---|---|
| `feature/corpus-pipeline` | Collaborator | corpus processing and construction |
| `feature/storage-indexing` | Project owner | SQLite, FTS5, LanceDB and index publication |
| `feature/retrieval-evidence` | Project owner | four pipelines and EvidenceService |
| `feature/api-frontend` | Project owner | FastAPI and React integration |
| `feature/quality-operations` | Project owner | tests, evaluation, deployment and operations |

See `docs/development/WORKTREE_PLAN.md` and `OWNERS.md` before starting parallel work.

## Continuous integration template

`ci/github-actions-ci.yml` contains the complete backend/frontend quality gate. It is kept as a template because the GitHub CLI token used for the first public push cannot update workflow files. After granting the CLI `workflow` scope, enable it with:

```bash
mkdir -p .github/workflows
cp ci/github-actions-ci.yml .github/workflows/ci.yml
git add .github/workflows/ci.yml
git commit -m "ci: enable GitHub Actions"
git push
```

Until then, `make verify` runs the same essential checks locally.

## Synthetic browser demo

This path is explicitly isolated from production, staging, and ordinary local
runtime. It does not call the default `ApplicationContainer`, does not load
production models, and does not present synthetic text as Marx–Engels source.

Use two terminals:

```bash
make run-demo-api
```

```bash
make run-demo-web
```

Then open `http://127.0.0.1:5173`. The page banner always reads
「合成数据演示，不是马克思恩格斯原典」. Four existing synthetic queries can be
clicked into the form:

| Mode | Query |
|---|---|
| exact | 劳动 |
| claim | 协作劳动会改变群体关系 |
| timeline | 公共讨论如何变化 |
| thematic | 生产关系与制度安排 |

`make run-api` and `make run-web` use the ordinary composition root and the
real ten-volume runtime SQLite after `make init-local-corpus`. Unimplemented
semantic modes report `PIPELINE_NOT_IMPLEMENTED` and never switch to synthetic
data. Do not commit runtime SQLite, demo SQLite, or cloud-export artifacts.

## Design documents

- `Marx_Engels_Text_Retrieval_Assistant_Technical_Design_V1.1.md`
- `01_Corpus_Processing_and_Construction_Specification_V1.0.md`
- `02_Data_Storage_and_Indexing_Specification_V1.0.md`
- `03_Retrieval_Pipelines_and_Evidence_Service_Specification_V1.0.md`
- `04_API_and_Frontend_Integration_Specification_V1.0.md`
- `05_Testing_Deployment_and_Operations_Specification_V1.0.md`

## License

No open-source license has been selected yet. Public visibility does not grant reuse rights; add a license only after the project owners agree.
