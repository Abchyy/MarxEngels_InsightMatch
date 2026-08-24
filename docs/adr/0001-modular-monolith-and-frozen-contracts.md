# ADR 0001: Modular monolith and frozen V1 contracts

- Status: Accepted
- Date: 2026-08-24

## Context

The project must support parallel development while keeping deployment simple and preserving strict evidence boundaries.

## Decision

Use one deployable Python backend with explicit internal modules and Protocol-based ports. Keep the React frontend separate. Freeze V1 domain and HTTP contracts before creating feature worktrees. SQLite remains authoritative; LanceDB remains a replaceable derived index.

## Consequences

- Modules can be developed with fakes before infrastructure is complete.
- Contract or schema changes require explicit review and regenerated snapshots.
- A future service split can preserve the same ports and HTTP contracts.
