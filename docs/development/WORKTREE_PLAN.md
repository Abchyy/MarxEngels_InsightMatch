# Planned parallel development

No worktree is created by the baseline setup.

## Branches and ownership

| Order | Branch | Owner | Primary paths |
|---|---|---|---|
| 1 | `feature/corpus-pipeline` | Collaborator | `corpus_registry`, `ingestion`, `corpora` |
| 2 | `feature/storage-indexing` | Project owner | `storage`, `indexing`, `migrations` |
| 3 | `feature/retrieval-evidence` | Project owner | `retrieval_core`, `pipelines`, `evidence`, `model_adapters` |
| 4 | `feature/api-frontend` | Project owner | `api`, `apps/api`, `apps/web` |
| 5 | `feature/quality-operations` | Project owner | `evaluation`, `tests`, `ci`, `deploy` |

## Preconditions

1. Clone or update the public baseline.
2. Run `make setup` and `make verify`.
3. Confirm `contracts/CONTRACT_VERSION` is `v1`.
4. Create worktrees from the same baseline commit.

## Integration rule

Feature branches consume contracts; they do not redefine them. Any breaking contract or migration change requires an ADR and must land on `main` before dependent implementation changes.
