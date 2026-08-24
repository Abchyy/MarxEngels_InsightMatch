# Contributing

## Before coding

1. Read the parent technical design and the specification for the module you own.
2. Run `make verify` on the baseline.
3. Do not change frozen V1 contracts, SQLite migration history or public error semantics without an approved ADR.
4. Keep corpus files and runtime databases outside Git.

## Pull requests

- One functional concern per branch.
- Include tests for changed behavior.
- State affected contract, schema, data, index and model versions.
- Run `make verify` before requesting review.
- Contract changes require regenerated snapshots via `make freeze-contracts` and explicit review.

## Commit style

Use English Conventional Commit messages:

```text
feat(corpus): add page extraction adapter
feat(storage): implement SQLite scope repository
test(retrieval): add exact short-query regression
docs(architecture): record contract change process
```
