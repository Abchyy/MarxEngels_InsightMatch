# Module ownership

| Path | Primary owner | Notes |
|---|---|---|
| `packages/marx_engels/contracts/`, `contracts/`, `migrations/` | Project owner | Cross-team review required |
| `packages/marx_engels/ingestion/`, `packages/marx_engels/corpus_registry/`, `corpora/` | Collaborator | Planned `feature/corpus-pipeline` |
| `packages/marx_engels/storage/`, `packages/marx_engels/indexing/` | Project owner | Planned `feature/storage-indexing` |
| `packages/marx_engels/retrieval_core/`, `packages/marx_engels/pipelines/`, `packages/marx_engels/evidence/`, `packages/marx_engels/model_adapters/` | Project owner | Planned `feature/retrieval-evidence` |
| `apps/api/`, `apps/web/`, `packages/marx_engels/api/` | Project owner | Planned `feature/api-frontend` |
| `tests/`, `packages/marx_engels/evaluation/`, `ci/`, `deploy/` | Project owner | Planned `feature/quality-operations` |

The collaborator owns only the first planned worktree. The project owner owns the remaining four. Ownership does not bypass review for frozen contracts or schema migrations.
