# Database

PostgreSQL is the **authoritative transactional database** for all application
and domain state.

- Migrations: `migrations/versions`, managed by Alembic (`cd backend && uv run alembic upgrade head`).
- Schemas: `app` (domain state), `platform` (operational bookkeeping).
- Package 1 contains only the foundation migration (extensions, schemas,
  bootstrap record). The complete domain schema arrives in Package 2, and no
  speculative tables are created ahead of it.
- Large genomic files are never stored here — they live in S3-compatible object
  storage, with large analytical result sets in Parquet queried via DuckDB.
